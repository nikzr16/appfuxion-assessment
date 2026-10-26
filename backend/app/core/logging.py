"""Structured JSON logging with a ``document_id`` context variable.

Anything logged while a document is being processed carries its id automatically:

    with bind_document_id("doc_123"):
        logger.info("extracting text")   # -> {"...", "document_id": "doc_123"}
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

document_id_var: ContextVar[str | None] = ContextVar("document_id", default=None)

# Attributes every LogRecord has; anything else was passed via ``extra=`` and is emitted.
_RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


@contextmanager
def bind_document_id(document_id: str) -> Iterator[None]:
    token = document_id_var.set(document_id)
    try:
        yield
    finally:
        document_id_var.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        document_id = document_id_var.get()
        if document_id is not None:
            payload["document_id"] = document_id
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
