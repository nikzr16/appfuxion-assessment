import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError, ConflictError, LLMOutputError
from app.core.llm import LLMClient, Message, Purpose, TokenUsage
from app.core.logging import bind_document_id, bind_trace
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.guardrails import service as guardrails_service
from app.modules.guardrails.schema import ExtractionGrounding, GroundingAttempt, GroundingReport
from app.modules.structured_extraction import crud, prompts
from app.modules.structured_extraction.model import Extraction
from app.modules.structured_extraction.schema import ExtractionRead, GroundingStats, InvoiceData
from app.modules.text_extraction import service as text_extraction_service
from app.modules.text_extraction.schema import DocumentTextRead

logger = logging.getLogger(__name__)

# One retry with the validation errors fed back (PRD D5).
MAX_ATTEMPTS = 2
# Extraction calls per extraction in total, schema and grounding retries together (0008 D3).
EXTRACTION_BUDGET = 3
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


@dataclass(frozen=True)
class _Grounded:
    data: InvoiceData
    grounding: ExtractionGrounding
    calls: int
    usage: TokenUsage
    model: str | None


def _history(used: int, report: GroundingReport) -> list[GroundingAttempt]:
    """The calls ``extract_structured_data`` made: only its last reply was schema-valid."""
    return [
        GroundingAttempt(
            attempt=attempt,
            reason="initial" if attempt == 1 else "schema",
            valid=attempt == used,
            ungrounded=[f.path for f in report.ungrounded_fields()] if attempt == used else [],
        )
        for attempt in range(1, used + 1)
    ]


@bind_trace(purpose=Purpose.GROUNDING_RETRY, prompt_version=prompts.PROMPT_VERSION)
def _ground_with_retry(
    llm: LLMClient, text: DocumentTextRead, data: InvoiceData, used: int
) -> _Grounded:
    """Check grounding; re-ask with the ungrounded values while the budget lasts (PRD D3).

    Every re-ask counts against ``EXTRACTION_BUDGET`` (shared with the schema retries already
    spent). A schema-invalid or refused reply is discarded. The kept attempt is the one with
    the fewest ungrounded values (ties: the latest); the rest are flagged, never nulled.
    """
    report = guardrails_service.check_grounding(data, text.raw_text, text.method)
    history = _history(used, report)
    base: list[Message] = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        {"role": "user", "content": prompts.document_prompt(_fit_text(text.raw_text))},
    ]
    best, best_report, kept = data, report, used
    current, current_report = data, report
    calls, retries = used, 0
    usage = TokenUsage()
    model: str | None = None
    while current_report.ungrounded and calls < EXTRACTION_BUDGET:
        calls += 1
        retries += 1
        items = [(f.path, f.value) for f in current_report.ungrounded_fields()]
        messages = [
            *base,
            {"role": "assistant", "content": current.model_dump_json()},
            {"role": "user", "content": prompts.grounding_retry_prompt(items)},
        ]
        try:
            response = llm.complete(messages, response_format=InvoiceData, temperature=0)
        except LLMOutputError:
            history.append(
                GroundingAttempt(attempt=calls, reason="grounding", valid=False, ungrounded=[])
            )
            continue
        usage = usage + response.usage
        model = response.model
        if response.refusal or not isinstance(response.parsed, InvoiceData):
            history.append(
                GroundingAttempt(attempt=calls, reason="grounding", valid=False, ungrounded=[])
            )
            continue
        current = response.parsed
        current_report = guardrails_service.check_grounding(current, text.raw_text, text.method)
        history.append(
            GroundingAttempt(
                attempt=calls,
                reason="grounding",
                valid=True,
                ungrounded=[f.path for f in current_report.ungrounded_fields()],
            )
        )
        if current_report.ungrounded <= best_report.ungrounded:
            best, best_report, kept = current, current_report, calls
    grounding = ExtractionGrounding(
        report=best_report,
        kept_attempt=kept,
        grounding_retries=retries,
        attempts=history,
        checked_at=datetime.now(UTC),
    )
    return _Grounded(best, grounding, calls, usage, model)


def ground_extraction(db: Session, llm: LLMClient, document_id: uuid.UUID) -> ExtractionRead:
    """Check the saved extraction against the text and re-extract what is ungrounded (0008).

    The agent's ``check_grounding`` tool. Idempotent: a row that already has a grounding
    report is returned without any work. Like ``extract_structured_data`` it commits ``db``
    before any LLM call and commits its own update; it never changes the document's status.
    """
    documents_service.get_document_source(db, document_id)  # 404 when unknown
    with bind_document_id(str(document_id)):
        row = crud.get_by_document(db, document_id)
        if row is None:
            raise ConflictError(
                "No structured data has been extracted; run extract_structured_data first.",
                code="structured_data_missing",
            )
        extraction = _to_read(row)
        if extraction.grounding is not None:
            logger.debug("grounding already checked; reusing it")
            return extraction
        text = text_extraction_service.find_text(db, document_id)
        if text is None:
            raise ConflictError(
                "No text has been extracted for this document; run text extraction first.",
                code="text_not_extracted",
            )
        db.commit()  # end the read transaction before any LLM call

        started = time.perf_counter()
        outcome = _ground_with_retry(llm, text, extraction.data, extraction.attempts)
        values: dict[str, Any] = {
            "grounding": outcome.grounding.model_dump(mode="json"),
            "attempts": outcome.calls,
            "prompt_tokens": extraction.prompt_tokens + outcome.usage.prompt_tokens,
            "completion_tokens": extraction.completion_tokens + outcome.usage.completion_tokens,
        }
        if outcome.grounding.grounding_retries:
            values["data"] = outcome.data.model_dump(mode="json")
            values["prompt_version"] = prompts.PROMPT_VERSION
            if outcome.model:
                values["model"] = outcome.model
        row = crud.update_grounding(db, document_id, values=values)
        db.commit()
        report = outcome.grounding.report
        logger.info(
            "grounding checked",
            extra={
                "checked": report.checked,
                "grounded": report.grounded,
                "weak": report.weak,
                "inferred": report.inferred,
                "ungrounded": report.ungrounded,
                "grounding_retries": outcome.grounding.grounding_retries,
                "kept_attempt": outcome.grounding.kept_attempt,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return _to_read(row)


def grounding_stats(db: Session, *, since: datetime | None = None) -> GroundingStats:
    """Grounding totals over extractions updated since ``since`` (feature 0008 metrics)."""
    extractions, checked, grounded, retried = crud.grounding_totals(db, since=since)
    return GroundingStats(
        extractions=extractions,
        values_checked=checked,
        values_grounded=grounded,
        grounding_retry_extractions=retried,
    )


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
