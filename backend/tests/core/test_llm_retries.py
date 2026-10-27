"""Transient-error retries in the LLM seam (feature 0008, PRD D5)."""

import random
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from app.core import llm as llm_module
from app.core.config import Settings
from app.core.errors import LLMError, LLMOutputError
from app.core.llm import (
    BACKOFF_CAP_SECONDS,
    RETRY_AFTER_CAP_SECONDS,
    FakeLLM,
    LLMCallRecord,
    OpenAILLMClient,
    register_llm_recorder,
)
from app.core.logging import bind_trace

REQUEST = httpx.Request("POST", "https://api.openai.test/v1/chat/completions")


def status_error(status: int, *, headers: dict[str, str] | None = None, code: str | None = None):
    response = httpx.Response(status, headers=headers or {}, request=REQUEST)
    body = {"code": code} if code else None
    cls = {429: openai.RateLimitError, 500: openai.InternalServerError}.get(
        status, openai.APIStatusError
    )
    return cls(f"status {status}", response=response, body=body)


def settings(max_retries: int = 2) -> Settings:
    return Settings(_env_file=None, openai_max_retries=max_retries)  # type: ignore[call-arg]


def ok_completion() -> Any:
    return SimpleNamespace(
        model="gpt-test",
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None, parsed=None, refusal=None)
            )
        ],
    )


def sdk_failing(*errors: Exception) -> tuple[Any, list[int]]:
    """An SDK stub raising ``errors`` in turn, then answering; counts the calls."""
    queue = list(errors)
    calls: list[int] = []

    def create(**kwargs: Any) -> Any:
        calls.append(1)
        if queue:
            raise queue.pop(0)
        return ok_completion()

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return sdk, calls


@pytest.fixture
def records() -> Iterator[list[LLMCallRecord]]:
    seen: list[LLMCallRecord] = []
    register_llm_recorder(seen.append)
    yield seen
    register_llm_recorder(None)


# -- Classification -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (openai.APITimeoutError(request=REQUEST), "llm_timeout", True),
        (openai.APIConnectionError(request=REQUEST), "llm_unavailable", True),
        (status_error(429), "llm_rate_limited", True),
        (status_error(429, code="insufficient_quota"), "llm_quota_exceeded", False),
        (status_error(408), "llm_timeout", True),
        (status_error(409), "llm_unavailable", True),
        (status_error(500), "llm_unavailable", True),
        (status_error(503), "llm_unavailable", True),
        (status_error(400), "llm_error", False),
        (status_error(401), "llm_error", False),
        (status_error(404), "llm_error", False),
        (openai.OpenAIError("anything else"), "llm_error", False),
    ],
)
def test_sdk_errors_are_classified(error: Exception, code: str, retryable: bool) -> None:
    classified = llm_module._classify(error)  # type: ignore[arg-type]
    assert (classified.code, classified.retryable) == (code, retryable)


def test_retry_after_headers_are_read() -> None:
    seconds = llm_module._classify(status_error(429, headers={"retry-after": "7"}))
    millis = llm_module._classify(status_error(429, headers={"retry-after-ms": "1500"}))
    date = llm_module._classify(
        status_error(503, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    )
    assert (seconds.retry_after, millis.retry_after, date.retry_after) == (7.0, 1.5, None)


# -- Backoff --------------------------------------------------------------------------


def test_backoff_is_full_jitter_under_a_growing_cap() -> None:
    random.seed(8)
    for attempt, ceiling in [(1, 1.0), (2, 2.0), (3, 4.0), (6, BACKOFF_CAP_SECONDS)]:
        waits = [llm_module._backoff(attempt, None) for _ in range(200)]
        assert all(0 <= wait <= ceiling for wait in waits)
        assert max(waits) > ceiling / 2  # really spread, not a constant


def test_backoff_honours_retry_after_up_to_a_cap() -> None:
    assert llm_module._backoff(1, 3.0) == 3.0
    assert llm_module._backoff(1, 600.0) == RETRY_AFTER_CAP_SECONDS


# -- Real client ------------------------------------------------------------------------


def test_sdk_retries_are_switched_off() -> None:
    client = OpenAILLMClient(Settings(_env_file=None, openai_api_key="sk-test"))  # type: ignore[call-arg]
    assert client._client.max_retries == 0
    assert client._max_attempts == 3


def test_transient_errors_are_retried_until_success(
    records: list[LLMCallRecord], retry_waits: list[float]
) -> None:
    sdk, calls = sdk_failing(status_error(429, headers={"retry-after": "2"}), status_error(503))
    with bind_trace(purpose="summary"):
        reply = OpenAILLMClient(settings(), client=sdk).complete([])

    assert reply.content == "ok"
    assert len(calls) == 3
    assert retry_waits[0] == 2.0 and 0 <= retry_waits[1] <= 2.0
    assert [(r.attempt, r.status, r.error_code) for r in records] == [
        (1, "error", "llm_rate_limited"),
        (2, "error", "llm_unavailable"),
        (3, "ok", None),
    ]
    assert all(r.labels.purpose == "summary" for r in records)


def test_gives_up_after_one_plus_max_retries(
    records: list[LLMCallRecord], retry_waits: list[float]
) -> None:
    sdk, calls = sdk_failing(*(status_error(500) for _ in range(5)))
    with pytest.raises(LLMError) as caught:
        OpenAILLMClient(settings(max_retries=1), client=sdk).complete([])

    assert caught.value.code == "llm_unavailable"
    assert len(calls) == 2 and len(retry_waits) == 1
    assert [r.attempt for r in records] == [1, 2]


def test_non_retryable_errors_raise_at_once(retry_waits: list[float]) -> None:
    sdk, calls = sdk_failing(status_error(400), status_error(500))
    with pytest.raises(LLMError) as caught:
        OpenAILLMClient(settings(), client=sdk).complete([])
    assert caught.value.code == "llm_error"
    assert len(calls) == 1 and retry_waits == []


def test_zero_retries_means_one_attempt() -> None:
    sdk, calls = sdk_failing(status_error(429))
    with pytest.raises(LLMError):
        OpenAILLMClient(settings(max_retries=0), client=sdk).complete([])
    assert len(calls) == 1


def test_embeddings_are_retried_too(records: list[LLMCallRecord]) -> None:
    errors = [openai.APITimeoutError(request=REQUEST)]

    def embed(**kwargs: Any) -> Any:
        if errors:
            raise errors.pop()
        return SimpleNamespace(
            model="embed",
            usage=SimpleNamespace(prompt_tokens=1),
            data=[SimpleNamespace(embedding=[0.1])],
        )

    sdk = SimpleNamespace(embeddings=SimpleNamespace(create=embed))
    result = OpenAILLMClient(settings(), client=sdk).embed(["a"])
    assert result.vectors == [[0.1]]
    assert [(r.kind, r.attempt, r.status) for r in records] == [
        ("embedding", 1, "error"),
        ("embedding", 2, "ok"),
    ]


# -- FakeLLM ----------------------------------------------------------------------------


def test_fake_llm_retries_scripted_transient_errors(records: list[LLMCallRecord]) -> None:
    fake = FakeLLM([LLMError("busy", code="llm_rate_limited", retryable=True), "done"])
    with bind_trace(purpose="summary"):
        assert fake.complete([]).content == "done"
    assert len(fake.calls) == 1  # one ``complete`` invocation, two attempts
    assert [(r.attempt, r.status) for r in records] == [(1, "error"), (2, "ok")]


def test_fake_llm_does_not_retry_invalid_output_or_plain_errors() -> None:
    with pytest.raises(LLMOutputError):
        FakeLLM(["{not json", "ignored"]).complete([], response_format=_Answer)
    fake = FakeLLM([LLMError("down"), "ignored"])
    with pytest.raises(LLMError):
        fake.complete([])
    assert list(fake.replies) == ["ignored"]


class _Answer(llm_module.BaseModel):
    value: str
