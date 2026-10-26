from types import SimpleNamespace
from typing import Any

import openai
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import LLMError, LLMOutputError
from app.core.llm import (
    FakeLLM,
    LLMResponse,
    OpenAILLMClient,
    TokenUsage,
    ToolCall,
)


class Answer(BaseModel):
    vendor: str | None
    total: str | None


# -- FakeLLM -------------------------------------------------------------------------


def test_fake_llm_replays_scripted_replies_in_order_and_records_calls() -> None:
    fake = FakeLLM(["first", "second"])
    messages = [{"role": "user", "content": "hi"}]

    one = fake.complete(messages, temperature=0.0)
    two = fake.complete(messages, vision=True)

    assert (one.content, two.content) == ("first", "second")
    assert len(fake.calls) == 2
    assert fake.calls[0].messages == messages
    assert fake.calls[0].temperature == 0.0
    assert fake.calls[1].vision is True


def test_fake_llm_captures_token_usage() -> None:
    fake = FakeLLM(["a", "b"], usage=TokenUsage(prompt_tokens=100, completion_tokens=20))
    fake.complete([{"role": "user", "content": "x"}])
    fake.complete([{"role": "user", "content": "y"}])
    assert fake.total_usage == TokenUsage(prompt_tokens=200, completion_tokens=40)
    assert fake.total_usage.total_tokens == 240


def test_fake_llm_structured_output_from_model_and_json_string() -> None:
    fake = FakeLLM([Answer(vendor="ACME", total="10.00"), '{"vendor": null, "total": "5.00"}'])

    first = fake.complete([], response_format=Answer)
    second = fake.complete([], response_format=Answer)

    assert first.parsed == Answer(vendor="ACME", total="10.00")
    assert second.parsed == Answer(vendor=None, total="5.00")


def test_fake_llm_invalid_structured_reply_raises_llm_output_error() -> None:
    fake = FakeLLM(['{"vendor": "ACME"}'])

    with pytest.raises(LLMOutputError) as caught:
        fake.complete([], response_format=Answer)

    assert caught.value.code == "llm_invalid_output"
    assert caught.value.status_code == 502
    assert [e["loc"] for e in caught.value.errors] == [("total",)]
    assert len(fake.calls) == 1  # the call is still recorded


def test_fake_llm_can_script_a_refusal() -> None:
    refusal = LLMResponse(content=None, usage=TokenUsage(), model="m", refusal="I can't help.")
    reply = FakeLLM([refusal]).complete([], response_format=Answer)

    assert reply.parsed is None
    assert reply.refusal == "I can't help."


def test_fake_llm_can_return_tool_calls_and_raise_errors() -> None:
    call = ToolCall(id="call_1", name="validate_invoice", arguments="{}")
    fake = FakeLLM(
        [
            LLMResponse(content=None, usage=TokenUsage(1, 1), model="m", tool_calls=(call,)),
            LLMError("boom"),
        ]
    )

    assert fake.complete([]).tool_calls == (call,)
    with pytest.raises(LLMError, match="boom"):
        fake.complete([])


def test_fake_llm_fails_loudly_when_script_is_exhausted() -> None:
    with pytest.raises(AssertionError, match="no scripted replies"):
        FakeLLM().complete([])


def test_fake_llm_embeddings_are_deterministic_and_normalised() -> None:
    fake = FakeLLM(embedding_dimensions=8)
    a1, a2, b = fake.embed(["alpha", "alpha", "beta"]).vectors
    assert a1 == a2
    assert a1 != b
    assert len(a1) == 8
    assert sum(v * v for v in a1) == pytest.approx(1.0)
    assert fake.embed_calls == [["alpha", "alpha", "beta"]]


# -- OpenAILLMClient (SDK stubbed; no network) -----------------------------------------


def stub_sdk(*, create: Any = None, parse: Any = None, embed: Any = None) -> Any:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create, parse=parse)),
        embeddings=SimpleNamespace(create=embed),
    )


def completion(
    content: str | None, *, tool_calls: Any = None, parsed: Any = None, refusal: Any = None
) -> Any:
    return SimpleNamespace(
        model="gpt-test-2026",
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content, tool_calls=tool_calls, parsed=parsed, refusal=refusal
                )
            )
        ],
    )


def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        openai_model="text-model",
        openai_vision_model="vision-model",
        openai_embedding_model="embed-model",
    )


def test_openai_client_uses_configured_models_and_captures_usage() -> None:
    seen: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return completion("hello")

    client = OpenAILLMClient(settings(), client=stub_sdk(create=create))
    text_reply = client.complete([{"role": "user", "content": "hi"}])
    vision_reply = client.complete([{"role": "user", "content": "img"}], vision=True)

    assert [call["model"] for call in seen] == ["text-model", "vision-model"]
    assert text_reply.content == "hello"
    assert text_reply.usage == TokenUsage(prompt_tokens=11, completion_tokens=7)
    assert vision_reply.model == "gpt-test-2026"


def test_openai_client_structured_output_and_tool_calls() -> None:
    parsed = Answer(vendor="ACME", total="1.00")
    tool_call = SimpleNamespace(
        id="call_9", function=SimpleNamespace(name="convert_currency", arguments='{"a": 1}')
    )
    sdk = stub_sdk(
        parse=lambda **kw: completion('{"vendor": "ACME"}', parsed=parsed),
        create=lambda **kw: completion(None, tool_calls=[tool_call]),
    )
    client = OpenAILLMClient(settings(), client=sdk)

    structured = client.complete([], response_format=Answer)
    tooled = client.complete([], tools=[{"type": "function", "function": {"name": "x"}}])

    assert structured.parsed == parsed
    assert tooled.tool_calls == (
        ToolCall(id="call_9", name="convert_currency", arguments='{"a": 1}'),
    )


def test_openai_client_embeddings() -> None:
    result = SimpleNamespace(
        model="embed-model",
        usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
        data=[SimpleNamespace(embedding=[0.1, 0.2]), SimpleNamespace(embedding=[0.3, 0.4])],
    )
    client = OpenAILLMClient(settings(), client=stub_sdk(embed=lambda **kw: result))

    response = client.embed(["a", "b"])

    assert response.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert response.usage == TokenUsage(prompt_tokens=4, completion_tokens=0)


def test_openai_sdk_errors_become_llm_error() -> None:
    def create(**kwargs: Any) -> Any:
        raise openai.OpenAIError("rate limited")

    client = OpenAILLMClient(settings(), client=stub_sdk(create=create))
    with pytest.raises(LLMError, match="rate limited"):
        client.complete([])


def test_openai_structured_validation_failure_becomes_llm_output_error() -> None:
    def parse(**kwargs: Any) -> Any:
        Answer.model_validate_json('{"vendor": 1, "total": null}')  # what the SDK does

    client = OpenAILLMClient(settings(), client=stub_sdk(parse=parse))
    with pytest.raises(LLMOutputError) as caught:
        client.complete([], response_format=Answer)

    assert isinstance(caught.value, LLMError)
    assert caught.value.errors[0]["loc"] == ("vendor",)
    assert caught.value.errors[0]["input"] == 1
    assert "url" not in caught.value.errors[0]


def test_openai_client_surfaces_a_refusal() -> None:
    sdk = stub_sdk(parse=lambda **kw: completion(None, refusal="I can't help with that."))
    reply = OpenAILLMClient(settings(), client=sdk).complete([], response_format=Answer)

    assert reply.parsed is None
    assert reply.refusal == "I can't help with that."


def test_real_client_requires_api_key_but_construction_is_lazy() -> None:
    with pytest.raises(LLMError) as excinfo:
        OpenAILLMClient(settings())  # no OPENAI_API_KEY and no injected SDK client
    assert excinfo.value.code == "llm_not_configured"
