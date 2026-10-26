"""The single entry point for LLM access.

Every OpenAI call in the project goes through an ``LLMClient``. Feature modules depend
on the ``LLMClient`` protocol (via the ``get_llm_client`` dependency), never on the
OpenAI SDK, so tests swap in ``FakeLLM`` and never touch the network.

Feature 0000 only fixes this seam: models come from config, token usage is captured on
every response, and every call is logged. Prompt versions, structured-output helpers
and agent loops are added by the features that need them.
"""

import hashlib
import logging
import math
import time
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import openai
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import LLMError

logger = logging.getLogger(__name__)

Message = Mapping[str, Any]


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


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list[list[float]]
    usage: TokenUsage
    model: str


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
    ) -> LLMResponse:
        """Run a chat completion.

        ``model`` defaults to ``OPENAI_MODEL`` (or ``OPENAI_VISION_MODEL`` when
        ``vision=True``). ``response_format`` requests structured output parsed into the
        given Pydantic model (available as ``LLMResponse.parsed``).
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
                max_retries=self._settings.openai_max_retries,
            )
        self._client = client

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        vision: bool = False,
        response_format: type[BaseModel] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        chosen = model or (
            self._settings.openai_vision_model if vision else self._settings.openai_model
        )
        kwargs: dict[str, Any] = {"model": chosen, "messages": [dict(m) for m in messages]}
        if tools:
            kwargs["tools"] = [dict(t) for t in tools]
        if temperature is not None:
            kwargs["temperature"] = temperature

        started = time.perf_counter()
        try:
            if response_format is not None:
                completion = self._client.chat.completions.parse(
                    response_format=response_format, **kwargs
                )
            else:
                completion = self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as exc:
            logger.error("llm.complete failed", extra={"model": chosen, "error": str(exc)})
            raise LLMError(f"OpenAI request failed: {exc}") from exc

        message = completion.choices[0].message
        usage = _usage_from(completion.usage)
        tool_calls = tuple(
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments)
            for tc in (getattr(message, "tool_calls", None) or [])
        )
        logger.info(
            "llm.complete",
            extra={
                "model": chosen,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return LLMResponse(
            content=message.content,
            usage=usage,
            model=getattr(completion, "model", chosen),
            tool_calls=tool_calls,
            parsed=getattr(message, "parsed", None),
        )

    def embed(self, texts: Sequence[str], *, model: str | None = None) -> EmbeddingResponse:
        chosen = model or self._settings.openai_embedding_model
        started = time.perf_counter()
        try:
            result = self._client.embeddings.create(model=chosen, input=list(texts))
        except openai.OpenAIError as exc:
            logger.error("llm.embed failed", extra={"model": chosen, "error": str(exc)})
            raise LLMError(f"OpenAI embedding request failed: {exc}") from exc

        usage = _usage_from(result.usage)
        logger.info(
            "llm.embed",
            extra={
                "model": chosen,
                "prompt_tokens": usage.prompt_tokens,
                "inputs": len(texts),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return EmbeddingResponse(
            vectors=[list(item.embedding) for item in result.data],
            usage=usage,
            model=getattr(result, "model", chosen),
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


class FakeLLM:
    """Scripted ``LLMClient`` for tests: replays queued replies in order, records calls.

    Replies may be a string (content), a Pydantic model (structured output), a ready-made
    ``LLMResponse`` (e.g. with tool calls) or an exception instance, which is raised.
    """

    def __init__(
        self,
        replies: Iterable[FakeReply] = (),
        *,
        usage: TokenUsage | None = None,
        model: str = "fake-model",
        embedding_dimensions: int = 1536,
    ) -> None:
        self.replies: deque[FakeReply] = deque(replies)
        self.usage = usage or TokenUsage(prompt_tokens=10, completion_tokens=5)
        self.model = model
        self.embedding_dimensions = embedding_dimensions
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
    ) -> LLMResponse:
        self.calls.append(
            LLMCall(
                messages=[dict(m) for m in messages],
                model=model,
                vision=vision,
                response_format=response_format,
                tools=[dict(t) for t in tools] if tools else None,
                temperature=temperature,
            )
        )
        if not self.replies:
            raise AssertionError("FakeLLM has no scripted replies left for this call.")
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, LLMResponse):
            response = reply
        elif isinstance(reply, BaseModel):
            response = LLMResponse(
                content=reply.model_dump_json(),
                usage=self.usage,
                model=self.model,
                parsed=reply,
            )
        else:
            parsed = response_format.model_validate_json(reply) if response_format else None
            response = LLMResponse(content=reply, usage=self.usage, model=self.model, parsed=parsed)
        self.total_usage = self.total_usage + response.usage
        return response

    def embed(self, texts: Sequence[str], *, model: str | None = None) -> EmbeddingResponse:
        self.embed_calls.append(list(texts))
        usage = TokenUsage(prompt_tokens=sum(len(t.split()) for t in texts))
        self.total_usage = self.total_usage + usage
        return EmbeddingResponse(
            vectors=[_fake_vector(t, self.embedding_dimensions) for t in texts],
            usage=usage,
            model=model or self.model,
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
