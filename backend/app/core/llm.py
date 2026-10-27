"""The single entry point for LLM access.

Every OpenAI call in the project goes through an ``LLMClient``. Feature modules depend
on the ``LLMClient`` protocol (via the ``get_llm_client`` dependency), never on the
OpenAI SDK, so tests swap in ``FakeLLM`` and never touch the network.

Feature 0000 only fixes this seam: models come from config, token usage is captured on
every response, and every call is logged. Prompt versions, structured-output helpers
and agent loops are added by the features that need them.

Feature 0007 measures every call here, in one place: each ``complete`` / ``embed`` call of
every client (``FakeLLM`` included) logs one ``llm.call`` line and hands an
``LLMCallRecord`` to the recorder registered with ``register_llm_recorder`` (the
observability module's token ledger). Callers only label their calls with
``app.core.logging.bind_trace(purpose=...)``.

Feature 0008 retries transient failures here instead of in the SDK (``max_retries=0``):
rate limits, timeouts, connection errors and 5xx are retried with exponential backoff and
full jitter (honouring ``Retry-After``), and every attempt is measured separately, so each
one is its own ``llm.call`` line and ledger row with an ``attempt`` number.
"""

import hashlib
import logging
import math
import random
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Any, Literal, Protocol

import openai
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import AppError, LLMError, LLMOutputError
from app.core.logging import TraceLabels, trace_labels

logger = logging.getLogger(__name__)

Message = Mapping[str, Any]
# ``required`` forces a tool call on every turn (feature 0010, Query Agent).
ToolChoice = Literal["auto", "required"]


class Purpose(StrEnum):
    """What an LLM call is for (the ``purpose`` trace label, PRD 0007 D2)."""

    VISION_TRANSCRIPTION = "vision_transcription"
    STRUCTURED_EXTRACTION = "structured_extraction"
    MULTIMODAL_EXTRACTION = "multimodal_extraction"
    GROUNDING_RETRY = "grounding_retry"
    AGENT_LOOP = "agent_loop"
    SUMMARY = "summary"
    EMBEDDING = "embedding"
    QUERY_EMBEDDING = "query_embedding"
    UNKNOWN = "unknown"


class Agent(StrEnum):
    """Which agent made an LLM call (the ``agent`` trace label). B4 adds more."""

    DOCUMENT = "document"
    QUERY = "query"


@dataclass(frozen=True)
class TokenUsage:
    """Tokens consumed by one or more LLM calls."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the model (``arguments`` is a JSON string)."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    usage: TokenUsage
    model: str
    tool_calls: tuple[ToolCall, ...] = ()
    parsed: BaseModel | None = None
    # Set when the model declined a structured-output request (``parsed`` is then None).
    refusal: str | None = None


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list[list[float]]
    usage: TokenUsage
    model: str


# -- Recording (feature 0007) -----------------------------------------------------------

CallKind = Literal["chat", "embedding"]


@dataclass(frozen=True)
class LLMCallRecord:
    """One measured LLM call, success or failure. Never holds prompts or replies."""

    kind: CallKind
    model: str
    usage: TokenUsage
    latency_ms: int
    status: Literal["ok", "error"]
    error_code: str | None
    started_at: datetime
    labels: TraceLabels
    # 1 for the first try of a call, 2+ for transient-error retries (feature 0008).
    attempt: int = 1


LLMRecorder = Callable[[LLMCallRecord], None]

_recorder: LLMRecorder | None = None


def register_llm_recorder(recorder: LLMRecorder | None) -> None:
    """Install the function that stores each call record (``None`` stops recording)."""
    global _recorder
    _recorder = recorder


class _Meter:
    """Filled in by the measured block with what the response reported."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.usage = TokenUsage()


@contextmanager
def _observe(kind: CallKind, model: str, *, attempt: int = 1) -> Iterator[_Meter]:
    """Time one call; on exit log ``llm.call`` and hand the record to the recorder.

    Exceptions from the call are re-raised unchanged. Exceptions from the recorder are
    logged and dropped: observability must never break a document run (PRD 0007 D5).
    """
    labels = trace_labels()
    if labels.purpose is None:
        if kind == "embedding":
            labels = replace(labels, purpose=Purpose.EMBEDDING.value)
        else:
            labels = replace(labels, purpose=Purpose.UNKNOWN.value)
            logger.warning("llm.call without purpose", extra={"purpose": labels.purpose})
    meter = _Meter(model)
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    error: BaseException | None = None
    try:
        yield meter
    except BaseException as exc:
        error = exc
        raise
    finally:
        error_code = None
        if error is not None:
            error_code = error.code if isinstance(error, AppError) else "internal_error"
        record = LLMCallRecord(
            kind=kind,
            model=meter.model,
            usage=meter.usage,
            latency_ms=round((time.perf_counter() - started) * 1000),
            status="ok" if error is None else "error",
            error_code=error_code,
            started_at=started_at,
            labels=labels,
            attempt=attempt,
        )
        _log_call(record, error)
        _record(record)


def _log_call(record: LLMCallRecord, error: BaseException | None) -> None:
    """One line per call with the ledger's fields; never message contents (PRD 0007 D9)."""
    fields: dict[str, Any] = {
        "kind": record.kind,
        "purpose": record.labels.purpose,  # the bound label wins when one is set
        "model": record.model,
        "prompt_tokens": record.usage.prompt_tokens,
        "completion_tokens": record.usage.completion_tokens,
        "latency_ms": record.latency_ms,
        "status": record.status,
        "attempt": record.attempt,
    }
    if error is None:
        logger.info("llm.call", extra=fields)
    else:
        logger.error(
            "llm.call", extra={**fields, "error_code": record.error_code, "error": str(error)}
        )


def _record(record: LLMCallRecord) -> None:
    recorder = _recorder
    if recorder is None:
        return
    try:
        recorder(record)
    except Exception:
        logger.warning("llm.call not recorded", exc_info=True)


# -- Transient-error retries (feature 0008) ------------------------------------------------

BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 20.0
RETRY_AFTER_CAP_SECONDS = 60.0

# Replaced in tests so backoff never waits.
_sleep: Callable[[float], None] = time.sleep


def _backoff(attempt: int, retry_after: float | None) -> float:
    """Seconds to wait after failed ``attempt``: the server's hint, else full jitter."""
    if retry_after is not None:
        return min(max(retry_after, 0.0), RETRY_AFTER_CAP_SECONDS)
    ceiling = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
    return random.uniform(0, ceiling)


def _with_retries[T](
    kind: CallKind, model: str, max_attempts: int, call: Callable[[_Meter], T]
) -> T:
    """Run ``call`` (one measured attempt each) until it succeeds or cannot be retried.

    Only an ``LLMError`` with ``retryable=True`` is retried; anything else, and the last
    attempt's error, propagates unchanged.
    """
    attempts = max(max_attempts, 1)
    for attempt in range(1, attempts + 1):
        try:
            with _observe(kind, model, attempt=attempt) as meter:
                return call(meter)
        except LLMError as exc:
            if not exc.retryable or attempt == attempts:
                raise
            wait = _backoff(attempt, exc.retry_after)
            logger.warning(
                "llm.call retrying",
                extra={"attempt": attempt, "error_code": exc.code, "wait_ms": round(wait * 1000)},
            )
            _sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


def _retry_after(response: Any) -> float | None:
    """Seconds from ``retry-after-ms`` / ``retry-after`` (seconds form only), if present."""
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            return float(raw) * scale
        except ValueError:
            continue  # an HTTP date: fall back to jittered backoff
    return None


def _classify(exc: openai.OpenAIError, prefix: str = "OpenAI request failed") -> LLMError:
    """Map an SDK error to an ``LLMError`` with a specific code and retryability (D5)."""
    message = f"{prefix}: {exc}"
    if isinstance(exc, openai.APITimeoutError):
        return LLMError(message, code="llm_timeout", retryable=True)
    if isinstance(exc, openai.APIConnectionError):
        return LLMError(message, code="llm_unavailable", retryable=True)
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        retry_after = _retry_after(exc.response)
        if status == 429:
            if getattr(exc, "code", None) == "insufficient_quota":
                return LLMError(message, code="llm_quota_exceeded")
            return LLMError(
                message, code="llm_rate_limited", retryable=True, retry_after=retry_after
            )
        if status == 408:
            return LLMError(message, code="llm_timeout", retryable=True, retry_after=retry_after)
        if status == 409 or status >= 500:
            return LLMError(
                message, code="llm_unavailable", retryable=True, retry_after=retry_after
            )
    return LLMError(message)


class LLMClient(Protocol):
    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        vision: bool = False,
        response_format: type[BaseModel] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        temperature: float | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> LLMResponse:
        """Run a chat completion.

        ``model`` defaults to ``OPENAI_MODEL`` (or ``OPENAI_VISION_MODEL`` when
        ``vision=True``). ``response_format`` requests structured output parsed into the
        given Pydantic model (available as ``LLMResponse.parsed``); a reply that fails
        that model's validation raises ``LLMOutputError``.
        """
        ...

    def embed(self, texts: Sequence[str], *, model: str | None = None) -> EmbeddingResponse:
        """Embed texts with ``OPENAI_EMBEDDING_MODEL`` unless ``model`` is given."""
        ...


class OpenAILLMClient:
    """``LLMClient`` backed by the official OpenAI SDK."""

    def __init__(self, settings: Settings | None = None, *, client: Any = None) -> None:
        self._settings = settings or get_settings()
        if client is None:
            if not self._settings.openai_configured:
                raise LLMError("OPENAI_API_KEY is not set.", code="llm_not_configured")
            client = openai.OpenAI(
                api_key=self._settings.openai_api_key.get_secret_value(),
                timeout=self._settings.openai_timeout_seconds,
                max_retries=0,  # retried by ``_with_retries`` so each attempt is visible
            )
        self._client = client
        self._max_attempts = 1 + self._settings.openai_max_retries

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        vision: bool = False,
        response_format: type[BaseModel] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        temperature: float | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> LLMResponse:
        chosen = model or (
            self._settings.openai_vision_model if vision else self._settings.openai_model
        )
        kwargs: dict[str, Any] = {"model": chosen, "messages": [dict(m) for m in messages]}
        if tools:
            kwargs["tools"] = [dict(t) for t in tools]
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        if temperature is not None:
            kwargs["temperature"] = temperature

        def attempt(meter: _Meter) -> Any:
            try:
                if response_format is not None:
                    completion = self._client.chat.completions.parse(
                        response_format=response_format, **kwargs
                    )
                else:
                    completion = self._client.chat.completions.create(**kwargs)
            except openai.OpenAIError as exc:
                raise _classify(exc) from exc
            except ValidationError as exc:  # the SDK parses structured replies with Pydantic
                raise _output_error(exc) from exc
            meter.model = getattr(completion, "model", chosen)
            meter.usage = _usage_from(completion.usage)
            return completion

        completion = _with_retries("chat", chosen, self._max_attempts, attempt)
        usage = _usage_from(completion.usage)

        message = completion.choices[0].message
        tool_calls = tuple(
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
            for tc in (getattr(message, "tool_calls", None) or [])
        )
        return LLMResponse(
            content=message.content,
            usage=usage,
            model=getattr(completion, "model", chosen),
            tool_calls=tool_calls,
            parsed=getattr(message, "parsed", None),
            refusal=getattr(message, "refusal", None),
        )

    def embed(self, texts: Sequence[str], *, model: str | None = None) -> EmbeddingResponse:
        chosen = model or self._settings.openai_embedding_model

        def attempt(meter: _Meter) -> Any:
            try:
                result = self._client.embeddings.create(model=chosen, input=list(texts))
            except openai.OpenAIError as exc:
                raise _classify(exc, "OpenAI embedding request failed") from exc
            meter.model = getattr(result, "model", chosen)
            meter.usage = _usage_from(result.usage)
            return result

        result = _with_retries("embedding", chosen, self._max_attempts, attempt)
        usage = _usage_from(result.usage)

        return EmbeddingResponse(
            vectors=[list(item.embedding) for item in result.data],
            usage=usage,
            model=getattr(result, "model", chosen),
        )


def _output_error(exc: ValidationError) -> LLMOutputError:
    return LLMOutputError(
        f"The model's structured reply did not match {exc.title}.",
        errors=[dict(e) for e in exc.errors(include_url=False, include_context=False)],
    )


def _usage_from(usage: Any) -> TokenUsage:
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )


# -- Test double ---------------------------------------------------------------------

FakeReply = str | BaseModel | LLMResponse | Exception


@dataclass(frozen=True)
class LLMCall:
    """One recorded ``FakeLLM.complete`` invocation."""

    messages: list[dict[str, Any]]
    model: str | None
    vision: bool
    response_format: type[BaseModel] | None
    tools: list[dict[str, Any]] | None
    temperature: float | None
    tool_choice: ToolChoice | None = None


class FakeLLM:
    """Scripted ``LLMClient`` for tests: replays queued replies in order, records calls.

    Replies may be a string (content), a Pydantic model (structured output), a ready-made
    ``LLMResponse`` (e.g. with tool calls or a refusal) or an exception instance, which is
    raised. A string that fails ``response_format`` validation raises ``LLMOutputError``,
    as the real client does. Replies go through the same retry loop as the real client: a
    scripted ``LLMError(..., retryable=True)`` is retried with the next scripted reply.
    """

    def __init__(
        self,
        replies: Iterable[FakeReply] = (),
        *,
        usage: TokenUsage | None = None,
        model: str = "fake-model",
        embedding_dimensions: int = 1536,
        max_retries: int = 2,
        embedder: Callable[[str], list[float]] | None = None,
    ) -> None:
        self.replies: deque[FakeReply] = deque(replies)
        self.max_attempts = 1 + max_retries
        self.usage = usage or TokenUsage(prompt_tokens=10, completion_tokens=5)
        self.model = model
        self.embedding_dimensions = embedding_dimensions
        # Tests that need designed similarities supply vectors; ``embed_error`` (when set)
        # is raised by the next ``embed`` call (feature 0010).
        self.embedder = embedder
        self.embed_error: Exception | None = None
        self.calls: list[LLMCall] = []
        self.embed_calls: list[list[str]] = []
        self.total_usage = TokenUsage()

    def queue(self, *replies: FakeReply) -> "FakeLLM":
        self.replies.extend(replies)
        return self

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        vision: bool = False,
        response_format: type[BaseModel] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        temperature: float | None = None,
        tool_choice: ToolChoice | None = None,
    ) -> LLMResponse:
        self.calls.append(
            LLMCall(
                messages=[dict(m) for m in messages],
                model=model,
                vision=vision,
                response_format=response_format,
                tools=[dict(t) for t in tools] if tools else None,
                temperature=temperature,
                tool_choice=tool_choice,
            )
        )

        # Measured and retried like the real client, so tests exercise the ledger path (PRD
        # 0007 D1) and the transient-retry path (PRD 0008 D5).
        def attempt(meter: _Meter) -> LLMResponse:
            response = self._next_response(response_format)
            meter.model = response.model
            meter.usage = response.usage
            return response

        response = _with_retries("chat", model or self.model, self.max_attempts, attempt)
        self.total_usage = self.total_usage + response.usage
        return response

    def _next_response(self, response_format: type[BaseModel] | None) -> LLMResponse:
        if not self.replies:
            raise AssertionError("FakeLLM has no scripted replies left for this call.")
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, LLMResponse):
            return reply
        if isinstance(reply, BaseModel):
            return LLMResponse(
                content=reply.model_dump_json(),
                usage=self.usage,
                model=self.model,
                parsed=reply,
            )
        try:
            parsed = response_format.model_validate_json(reply) if response_format else None
        except ValidationError as exc:
            raise _output_error(exc) from exc
        return LLMResponse(content=reply, usage=self.usage, model=self.model, parsed=parsed)

    def embed(self, texts: Sequence[str], *, model: str | None = None) -> EmbeddingResponse:
        self.embed_calls.append(list(texts))
        chosen = model or self.model
        with _observe("embedding", chosen) as meter:
            if self.embed_error is not None:
                error, self.embed_error = self.embed_error, None
                raise error
            usage = TokenUsage(prompt_tokens=sum(len(t.split()) for t in texts))
            meter.usage = usage
        self.total_usage = self.total_usage + usage
        embed = self.embedder or (lambda t: _fake_vector(t, self.embedding_dimensions))
        return EmbeddingResponse(
            vectors=[embed(t) for t in texts],
            usage=usage,
            model=chosen,
        )


def _fake_vector(text: str, dimensions: int) -> list[float]:
    """Deterministic unit-length pseudo-embedding: same text -> same vector."""
    raw = bytearray()
    counter = 0
    while len(raw) < dimensions:
        raw.extend(hashlib.sha256(f"{counter}:{text}".encode()).digest())
        counter += 1
    values = [(b - 127.5) / 127.5 for b in raw[:dimensions]]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


# -- Dependency ----------------------------------------------------------------------


@lru_cache
def get_llm_client() -> LLMClient:
    """FastAPI dependency. Created lazily so the app starts without an API key.

    Tests override it: ``app.dependency_overrides[get_llm_client] = lambda: fake``.
    """
    return OpenAILLMClient()
