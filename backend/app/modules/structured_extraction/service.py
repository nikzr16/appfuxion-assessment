import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ConflictError, LLMOutputError
from app.core.llm import LLMClient, Message, Purpose, TokenUsage
from app.core.logging import bind_document_id, bind_trace
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.structured_extraction import crud, prompts
from app.modules.structured_extraction.model import Extraction
from app.modules.structured_extraction.schema import ExtractionRead, InvoiceData
from app.modules.text_extraction import service as text_extraction_service

logger = logging.getLogger(__name__)

# One retry with the validation errors fed back (PRD D5).
MAX_ATTEMPTS = 2
# Longer text is cut to its head (vendor, number, dates) and tail (totals) (PRD D8).
MAX_INPUT_CHARS = 60_000
HEAD_CHARS = 45_000
TAIL_CHARS = 15_000
# Bounds on the error list fed back to the model.
MAX_FEEDBACK_ERRORS = 20
MAX_FEEDBACK_INPUT_CHARS = 80


class StructuredExtractionError(AppError):
    """The model gave no usable structured reply (``invalid_llm_output`` / ``llm_refused``)."""

    status_code = 502
    code = "invalid_llm_output"


@dataclass(frozen=True)
class _Outcome:
    data: InvoiceData
    model: str
    attempts: int
    usage: TokenUsage


def _to_read(row: Extraction) -> ExtractionRead:
    return ExtractionRead.model_validate(row)


# -- Pure helpers ---------------------------------------------------------------------


def _fit_text(text: str) -> str:
    """The text as is, or its head and tail with an omission marker when it is too long."""
    if len(text) <= MAX_INPUT_CHARS:
        return text
    omitted = len(text) - HEAD_CHARS - TAIL_CHARS
    logger.warning(
        "document text truncated",
        extra={"chars_total": len(text), "chars_sent": HEAD_CHARS + TAIL_CHARS},
    )
    return f"{text[:HEAD_CHARS]}\n\n[... {omitted} characters omitted ...]\n\n{text[-TAIL_CHARS:]}"


def _format_errors(errors: Sequence[Mapping[str, Any]]) -> list[str]:
    """``line_items.0.amount: <message> (got: <value>)`` lines for the retry prompt."""
    lines: list[str] = []
    for error in errors[:MAX_FEEDBACK_ERRORS]:
        path = ".".join(str(part) for part in error.get("loc", ())) or "reply"
        line = f"{path}: {error.get('msg', 'invalid value')}"
        if "input" in error:
            got = repr(error["input"])
            if len(got) > MAX_FEEDBACK_INPUT_CHARS:
                got = got[: MAX_FEEDBACK_INPUT_CHARS - 3] + "..."
            line = f"{line} (got: {got})"
        lines.append(line)
    return lines


# -- LLM call -------------------------------------------------------------------------


@bind_trace(purpose=Purpose.STRUCTURED_EXTRACTION, prompt_version=prompts.PROMPT_VERSION)
def _extract_with_retry(llm: LLMClient, text: str) -> _Outcome:
    """Ask for ``InvoiceData``; on an invalid reply retry once with the errors fed back.

    API failures (``LLMError``) are not retried here (the SDK already retries them) and a
    refusal is final: neither is likely to change by asking again.
    """
    base: list[Message] = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        {"role": "user", "content": prompts.document_prompt(text)},
    ]
    messages = base
    usage = TokenUsage()
    errors: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = llm.complete(messages, response_format=InvoiceData, temperature=0)
        except LLMOutputError as exc:
            errors = _format_errors(exc.errors)
        else:
            usage = usage + response.usage
            if response.refusal:
                raise StructuredExtractionError(
                    f"The model refused to extract the document: {response.refusal}",
                    code="llm_refused",
                )
            if isinstance(response.parsed, InvoiceData):
                return _Outcome(response.parsed, response.model, attempt, usage)
            errors = ["reply: the reply contained no structured object"]
        logger.warning(
            "structured extraction reply rejected",
            extra={"attempt": attempt, "errors": len(errors)},
        )
        messages = [*base, {"role": "user", "content": prompts.retry_prompt(errors)}]
    raise StructuredExtractionError(
        f"The model returned no valid structured data after {MAX_ATTEMPTS} attempts: "
        + "; ".join(errors[:3])
    )


# -- Use cases ------------------------------------------------------------------------


def extract_structured_data(
    db: Session, llm: LLMClient, document_id: uuid.UUID, *, force: bool = False
) -> ExtractionRead:
    """Turn the document's saved text into ``InvoiceData`` and save it; the 0005 agent tool.

    Idempotent: an existing row is returned without any LLM call unless ``force`` replaces
    it in place. The text must have been extracted first (``text_not_extracted`` otherwise).

    This commits its own row, so the result survives a later pipeline failure, and it
    commits ``db`` first so no transaction stays open during the LLM call: call it at a
    point where the session has nothing else pending. It never changes the document's
    status; on failure it raises and the caller marks the document ``failed``.
    """
    documents_service.get_document_source(db, document_id)  # 404 when unknown
    with bind_document_id(str(document_id)):
        if not force:
            existing = crud.get_by_document(db, document_id)
            if existing is not None:
                logger.debug("structured data already extracted; reusing it")
                return _to_read(existing)
        text = text_extraction_service.find_text(db, document_id)
        if text is None:
            raise ConflictError(
                "No text has been extracted for this document; run text extraction first.",
                code="text_not_extracted",
            )
        db.commit()  # end the read transaction before the LLM call

        started = time.perf_counter()
        document = _fit_text(text.raw_text)
        outcome = _extract_with_retry(llm, document)

        row = crud.upsert(
            db,
            values={
                "document_id": document_id,
                "data": outcome.data.model_dump(mode="json"),
                "model": outcome.model,
                "prompt_version": prompts.PROMPT_VERSION,
                "attempts": outcome.attempts,
                "prompt_tokens": outcome.usage.prompt_tokens,
                "completion_tokens": outcome.usage.completion_tokens,
            },
            overwrite=force,
        )
        db.commit()
        logger.info(
            "structured data extracted",
            extra={
                "document_type": outcome.data.document_type.value,
                "line_items": len(outcome.data.line_items),
                "attempts": outcome.attempts,
                "prompt_tokens": outcome.usage.prompt_tokens,
                "completion_tokens": outcome.usage.completion_tokens,
                "chars_sent": len(document),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return _to_read(row)


def get_extraction(db: Session, document_id: uuid.UUID) -> ExtractionRead:
    """The saved extraction; never extracts. Explains why there is none (409) or 404."""
    row = crud.get_by_document(db, document_id)
    if row is not None:
        return _to_read(row)
    source = documents_service.get_document_source(db, document_id)
    if source.status == DocumentStatus.PROCESSING:
        raise ConflictError(
            "The document is still processing; its structured data is not ready yet.",
            code="extraction_not_ready",
        )
    message = "No structured data is available for this document."
    if source.error:
        message = f"{message} Processing failed: {source.error}"
    raise ConflictError(message, code="extraction_unavailable")
