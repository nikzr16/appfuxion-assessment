"""Structured JSON logging with trace context variables.

Anything logged while a document is being processed carries its id automatically:

    with bind_document_id("7f3e2b1a-4c5d-4e6f-8a9b-0c1d2e3f4a5b"):
        logger.info("extracting text")   # -> {"...", "document_id": "7f3e2b1a-4c5d-..."}

Feature 0007 adds the other trace labels (``run_id``, ``agent``, ``purpose``,
``prompt_version``, ``step_index``), bound with ``bind_trace``. They label log lines and
every LLM call recorded in the token ledger.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

document_id_var: ContextVar[str | None] = ContextVar("document_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
agent_var: ContextVar[str | None] = ContextVar("agent", default=None)
purpose_var: ContextVar[str | None] = ContextVar("purpose", default=None)
prompt_version_var: ContextVar[str | None] = ContextVar("prompt_version", default=None)
step_index_var: ContextVar[int | None] = ContextVar("step_index", default=None)
query_run_id_var: ContextVar[str | None] = ContextVar("query_run_id", default=None)

# Context fields added to every log line when set, in this order.
_CONTEXT_FIELDS: tuple[tuple[str, ContextVar[Any]], ...] = (
    ("document_id", document_id_var),
    ("run_id", run_id_var),
    ("agent", agent_var),
    ("purpose", purpose_var),
    ("prompt_version", prompt_version_var),
    ("step_index", step_index_var),
    ("query_run_id", query_run_id_var),
)

# Attributes every LogRecord has; anything else was passed via ``extra=`` and is emitted.
_RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


@contextmanager
def bind_document_id(document_id: str) -> Iterator[None]:
    token = document_id_var.set(document_id)
    try:
        yield
    finally:
        document_id_var.reset(token)


class _Unset:
    """Sentinel: ``bind_trace`` leaves a label as it is unless it is passed."""


_UNSET: Any = _Unset()


@contextmanager
def bind_trace(
    *,
    run_id: str | None = _UNSET,
    agent: str | None = _UNSET,
    purpose: str | None = _UNSET,
    prompt_version: str | None = _UNSET,
    step_index: int | None = _UNSET,
    query_run_id: str | None = _UNSET,
) -> Iterator[None]:
    """Bind the given trace labels for the block; labels not passed keep their value."""
    values = {
        run_id_var: run_id,
        agent_var: agent,
        purpose_var: purpose,
        prompt_version_var: prompt_version,
        step_index_var: step_index,
        query_run_id_var: query_run_id,
    }
    tokens: list[tuple[ContextVar[Any], Token[Any]]] = [
        (var, var.set(value)) for var, value in values.items() if value is not _UNSET
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


@dataclass(frozen=True)
class TraceLabels:
    """A snapshot of the trace context at one moment (e.g. when an LLM call starts)."""

    document_id: str | None = None
    run_id: str | None = None
    agent: str | None = None
    purpose: str | None = None
    prompt_version: str | None = None
    step_index: int | None = None
    query_run_id: str | None = None


def trace_labels() -> TraceLabels:
    return TraceLabels(
        document_id=document_id_var.get(),
        run_id=run_id_var.get(),
        agent=agent_var.get(),
        purpose=purpose_var.get(),
        prompt_version=prompt_version_var.get(),
        step_index=step_index_var.get(),
        query_run_id=query_run_id_var.get(),
    )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, var in _CONTEXT_FIELDS:
            value = var.get()
            if value is not None:
                payload[name] = value
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _JsonHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Marker subclass so ``configure_logging`` can stay idempotent."""


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in root.handlers:
        if isinstance(handler, _JsonHandler):
            handler.setLevel(level.upper())
            return
    handler = _JsonHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
