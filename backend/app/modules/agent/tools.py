"""The Document Agent's tools: the 0002-0004 services, bound to one document.

Every tool reads and writes through the owning module's ``service``; the model never passes
a document ID, a number or ``InvoiceData`` (PRD 0005 D1). Guards keep the order: each tool
needs its predecessor to have succeeded *in this run* (D2), so a reprocess never summarises
stale data. What a tool returns is exactly what the model sees, kept short: never the raw
document text.
"""

import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.llm import LLMClient, Message, Purpose, TokenUsage
from app.core.logging import bind_trace
from app.core.storage import Storage
from app.modules.agent import prompts
from app.modules.agent.runner import NO_ARGUMENTS, Tool, ToolError, ToolHandler
from app.modules.guardrails import service as guardrails_service
from app.modules.guardrails.schema import ConfidenceReport, GroundingReport
from app.modules.retrieval import service as retrieval_service
from app.modules.retrieval.schema import HistoryCheck, PreparedEmbedding, SimilarInvoices
from app.modules.structured_extraction import service as structured_extraction_service
from app.modules.structured_extraction.schema import DocumentType, InvoiceData
from app.modules.text_extraction import service as text_extraction_service
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.validation import service as validation_service
from app.modules.validation.schema import (
    ConversionResult,
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
)
from app.modules.vision import service as vision_service

# Errors the model can act on; every other ``AppError`` code ends the run (PRD D6).
RECOVERABLE_CODES = frozenset(
    {
        "text_not_extracted",
        "tables_required",
        "structured_data_missing",
        "grounding_required",
        "validation_required",
        "history_check_required",
        "similar_search_required",
        "conversion_not_needed",
        "unsupported_currency",
        "invalid_amount",
        "invalid_arguments",
        "unknown_tool",
    }
)

MAX_SUMMARY_CHARS = 1500
# Fields the summary must ask the reader to verify, key fields first (PRD 0008 D8).
MAX_REVIEW_FIELDS = 6
# Earlier similar invoices handed to the summary (PRD 0010 D6).
SUMMARY_SIMILAR = 3


@dataclass
class DocumentToolContext:
    """Everything one run's tools share, including what they produced so far."""

    db: Session
    llm: LLMClient
    storage: Storage
    document_id: uuid.UUID
    base_currency: str
    force: bool = False
    today: date | None = None
    summary_usage: TokenUsage = field(default_factory=TokenUsage)
    text_done: bool = False
    text_method: ExtractionMethod | None = None
    tables_done: bool = False
    structured: InvoiceData | None = None
    grounding: GroundingReport | None = None
    confidence: ConfidenceReport | None = None
    validation: ValidationReport | None = None
    conversion: ConversionResult | None = None
    # Vendor history and similar invoices (feature 0010); reset with the validation.
    history: HistoryCheck | None = None
    similar: SimilarInvoices | None = None
    embedding: PreparedEmbedding | None = None
    summary: str | None = None
    _text_forced: bool = False
    _tables_forced: bool = False
    _structured_forced: bool = False


def build_document_tools(ctx: DocumentToolContext) -> list[Tool]:
    return [
        Tool(
            name="extract_text",
            description=(
                "Read the document's text (PDF text layer or vision). Call it first. Returns "
                "the method, page count and number of characters, not the text itself."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _extract_text(ctx)),
        ),
        Tool(
            name="extract_tables",
            description=(
                "Find the document's tables and layout blocks (header, bill-to, line items, "
                "totals, ...). Always call it after extract_text, even when there may be no "
                "table; extract_structured_data refuses to run before it. Returns counts, "
                "table kinds and column roles, not the cell text."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _extract_tables(ctx)),
        ),
        Tool(
            name="extract_structured_data",
            description=(
                "Extract the invoice fields from the document's text and tables and return "
                "them as JSON. Requires extract_tables."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _extract_structured_data(ctx)),
        ),
        Tool(
            name="check_grounding",
            description=(
                "Check that every extracted value appears in the document's text, and "
                "re-extract values that do not (deterministic check, bounded retries). "
                "Returns counts and the values that could not be found. Requires "
                "extract_structured_data; validate_invoice refuses to run before it."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _check_grounding(ctx)),
        ),
        Tool(
            name="validate_invoice",
            description=(
                "Check the extracted fields with deterministic code (required fields, "
                "totals, dates, currency). Returns a status and a list of issues. Requires "
                "check_grounding."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _validate_invoice(ctx)),
        ),
        Tool(
            name="check_vendor_history",
            description=(
                "Compare the invoice with the earlier invoices from the same vendor "
                "(deterministic code): duplicate invoice number, an amount far outside the "
                "vendor's usual range, or a first invoice from this vendor. Adds any findings "
                "to the validation report. Requires validate_invoice; always call it."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _check_vendor_history(ctx)),
        ),
        Tool(
            name="convert_currency",
            description=(
                "Convert the extracted total to another currency with a static, dated rate "
                "table. Only call it when the document's currency is set and differs from "
                f"{ctx.base_currency}. Requires extract_structured_data."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "to_currency": {
                        "type": "string",
                        "description": "ISO 4217 code to convert the total to.",
                    }
                },
                "required": ["to_currency"],
                "additionalProperties": False,
            },
            handler=_guarded(lambda args: _convert_currency(ctx, args)),
        ),
        Tool(
            name="search_similar_invoices",
            description=(
                "Find the earlier invoices most similar to this one (vector search). "
                "Requires check_vendor_history; always call it before generate_summary."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _search_similar_invoices(ctx)),
        ),
        Tool(
            name="generate_summary",
            description=(
                "Write the final plain-text summary from the extracted fields, the "
                "validation report and the similar invoices. Requires validate_invoice, "
                "check_vendor_history and search_similar_invoices. Call it last."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _generate_summary(ctx)),
        ),
    ]


def _guarded(handler: Callable[[dict[str, Any]], dict[str, Any]]) -> ToolHandler:
    """Turn a service's ``AppError`` into a recoverable or fatal ``ToolError``."""

    def run(arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return handler(arguments)
        except ToolError:
            raise
        except AppError as exc:
            raise ToolError(exc.code, exc.message, fatal=exc.code not in RECOVERABLE_CODES) from exc

    return run


# -- Tools ----------------------------------------------------------------------------


def _extract_text(ctx: DocumentToolContext) -> dict[str, Any]:
    force = ctx.force and not ctx._text_forced
    text = text_extraction_service.extract_text(
        ctx.db, ctx.storage, ctx.llm, ctx.document_id, force=force
    )
    ctx._text_forced = ctx._text_forced or force
    ctx.text_done = True
    ctx.text_method = text.method
    # New text needs its tables found again (PRD 0009 D7).
    ctx.tables_done = False
    return {
        "method": text.method.value,
        "page_count": text.page_count,
        "characters": len(text.raw_text),
    }


def _extract_tables(ctx: DocumentToolContext) -> dict[str, Any]:
    if not ctx.text_done or ctx.text_method is None:
        raise ToolError("text_not_extracted", "Call extract_text before extract_tables.")
    force = ctx.force and not ctx._tables_forced
    summary = vision_service.extract_tables(
        ctx.db, ctx.storage, ctx.document_id, method=ctx.text_method, force=force
    )
    ctx._tables_forced = ctx._tables_forced or force
    ctx.tables_done = True
    return summary.model_dump(mode="json")


def _extract_structured_data(ctx: DocumentToolContext) -> dict[str, Any]:
    if not ctx.text_done:
        raise ToolError("text_not_extracted", "Call extract_text before extract_structured_data.")
    if not ctx.tables_done:
        raise ToolError("tables_required", "Call extract_tables before extract_structured_data.")
    force = ctx.force and not ctx._structured_forced
    extraction = structured_extraction_service.extract_structured_data(
        ctx.db, ctx.llm, ctx.document_id, force=force, storage=ctx.storage
    )
    ctx._structured_forced = ctx._structured_forced or force
    ctx.structured = extraction.data
    # A new extraction must be grounded (and validated) again (PRD 0008 D1).
    ctx.grounding = None
    ctx.confidence = None
    _reset_validation(ctx)
    return extraction.data.model_dump(mode="json")


def _check_grounding(ctx: DocumentToolContext) -> dict[str, Any]:
    before = _require_structured(ctx, "check_grounding").model_dump(mode="json")
    extraction = structured_extraction_service.ground_extraction(
        ctx.db, ctx.llm, ctx.document_id, storage=ctx.storage
    )
    assert extraction.grounding is not None
    report = extraction.grounding.report
    ctx.structured = extraction.data
    ctx.grounding = report
    after = extraction.data.model_dump(mode="json")
    return {
        "checked": report.checked,
        "grounded": report.grounded,
        "weak": report.weak,
        "inferred": report.inferred,
        "ungrounded": report.ungrounded,
        "retries": extraction.grounding.grounding_retries,
        "ungrounded_values": [
            {"field": f.path, "value": f.value} for f in report.ungrounded_fields()
        ],
        "changed_fields": [name for name, value in before.items() if after[name] != value],
    }


def _validate_invoice(ctx: DocumentToolContext) -> dict[str, Any]:
    data = _require_structured(ctx, "validate_invoice")
    if ctx.grounding is None:
        raise ToolError("grounding_required", "Call check_grounding before validate_invoice.")
    _reset_validation(ctx)
    ctx.validation = validation_service.validate_invoice(data, today=ctx.today)
    ctx.confidence = guardrails_service.score_confidence(data, ctx.grounding, ctx.validation)
    result = ctx.validation.model_dump(mode="json")
    if ctx.confidence is not None:
        result["needs_review"] = ctx.confidence.needs_review
        result["review_fields"] = ctx.confidence.review_fields
    return result


def _reset_validation(ctx: DocumentToolContext) -> None:
    """A new validation report needs the vendor history and similar invoices again."""
    ctx.validation = None
    ctx.history = None
    ctx.similar = None
    ctx.embedding = None


def _check_vendor_history(ctx: DocumentToolContext) -> dict[str, Any]:
    data = _require_structured(ctx, "check_vendor_history")
    if ctx.validation is None or ctx.grounding is None:
        raise ToolError("validation_required", "Call validate_invoice before check_vendor_history.")
    check = retrieval_service.check_vendor_history(
        ctx.db, ctx.document_id, data, base_currency=ctx.base_currency
    )
    ctx.validation = retrieval_service.merge_report(ctx.validation, check)
    ctx.confidence = guardrails_service.score_confidence(data, ctx.grounding, ctx.validation)
    ctx.history = check
    ctx.similar = None
    result = check.model_dump(mode="json")
    result["status"] = ctx.validation.status.value
    if ctx.confidence is not None:
        result["needs_review"] = ctx.confidence.needs_review
        result["review_fields"] = ctx.confidence.review_fields
    return result


def _search_similar_invoices(ctx: DocumentToolContext) -> dict[str, Any]:
    data = _require_structured(ctx, "search_similar_invoices")
    if ctx.history is None:
        raise ToolError(
            "history_check_required",
            "Call check_vendor_history before search_similar_invoices.",
        )
    if data.document_type is DocumentType.UNKNOWN:
        ctx.similar = SimilarInvoices(document_id=ctx.document_id, available=False, items=[])
        return {"skipped": True, "reason": "The document is not an invoice or receipt."}
    ctx.embedding = retrieval_service.prepare_embedding(ctx.db, ctx.llm, ctx.document_id, data)
    ctx.similar = retrieval_service.similar_to(
        ctx.db, ctx.document_id, ctx.embedding.vector, k=SUMMARY_SIMILAR, earlier_only=True
    )
    return {
        "available": ctx.similar.available,
        "reused_embedding": ctx.embedding.reused,
        "items": _similar_items(ctx.similar),
    }


def _similar_items(similar: SimilarInvoices | None) -> list[dict[str, Any]]:
    if similar is None:
        return []
    return [
        {
            "vendor": item.vendor,
            "invoice_number": item.invoice_number,
            "invoice_date": item.invoice_date.isoformat() if item.invoice_date else None,
            "total_amount": str(item.total_amount) if item.total_amount is not None else None,
            "currency": item.currency,
            "similarity": item.similarity,
        }
        for item in similar.items
    ]


def _convert_currency(ctx: DocumentToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    target = arguments.get("to_currency")
    if not isinstance(target, str) or not target.strip():
        raise ToolError("invalid_arguments", "to_currency must be an ISO 4217 code such as MYR.")
    target = target.strip().upper()
    data = _require_structured(ctx, "convert_currency")
    if data.currency is None or data.total_amount is None:
        raise ToolError(
            "conversion_not_needed",
            "The document has no currency or no total, so there is nothing to convert.",
        )
    if data.currency in (target, ctx.base_currency):
        raise ToolError(
            "conversion_not_needed",
            f"The total is already in {data.currency}; do not convert it.",
        )
    ctx.conversion = validation_service.convert_currency(data.total_amount, data.currency, target)
    return ctx.conversion.model_dump(mode="json")


def _generate_summary(ctx: DocumentToolContext) -> dict[str, Any]:
    if ctx.validation is None or ctx.structured is None:
        raise ToolError("validation_required", "Call validate_invoice before generate_summary.")
    if ctx.history is None:
        raise ToolError(
            "history_check_required", "Call check_vendor_history before generate_summary."
        )
    if ctx.similar is None:
        raise ToolError(
            "similar_search_required", "Call search_similar_invoices before generate_summary."
        )
    if ctx.structured.document_type is DocumentType.UNKNOWN:
        ctx.summary = prompts.UNKNOWN_SUMMARY  # PRD D5: nothing to summarise, no LLM call
        return {"summary": ctx.summary}
    review = ctx.confidence.review_fields[:MAX_REVIEW_FIELDS] if ctx.confidence else []

    payload = {
        "document_type": ctx.structured.document_type.value,
        "structured_data": ctx.structured.model_dump(mode="json"),
        "validation": ctx.validation.model_dump(mode="json"),
        "conversion": ctx.conversion.model_dump(mode="json") if ctx.conversion else None,
        "base_currency": ctx.base_currency,
        "similar_invoices": _similar_items(ctx.similar),
        "review": [
            {"field": field_name(path), "reason": _review_reason(ctx.confidence, path)}
            for path in review
        ],
    }
    messages: list[Message] = [
        {"role": "system", "content": prompts.SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload)},
    ]
    text = _complete(ctx, messages)
    missing = missing_issues(text, ctx.validation)
    unverified = missing_review(text, review)
    if not text or missing or unverified:
        feedback = (
            prompts.summary_retry_prompt(
                [issue.message for issue in missing], [field_name(p) for p in unverified]
            )
            if text
            else "Your reply was empty. Write the summary, following the same rules."
        )
        messages = [
            *messages,
            {"role": "assistant", "content": text},
            {"role": "user", "content": feedback},
        ]
        text = _complete(ctx, messages)
        if not text:
            raise ToolError(
                "invalid_llm_output", "The model returned an empty summary.", fatal=True
            )
        missing = missing_issues(text, ctx.validation)
        unverified = missing_review(text, review)
    extra = [prompts.review_sentence([field_name(p) for p in unverified])] if unverified else []
    ctx.summary = compose_summary(text, missing, extra)
    return {"summary": ctx.summary}


def _require_structured(ctx: DocumentToolContext, tool: str) -> InvoiceData:
    if ctx.structured is None:
        raise ToolError("structured_data_missing", f"Call extract_structured_data before {tool}.")
    return ctx.structured


@bind_trace(purpose=Purpose.SUMMARY, prompt_version=prompts.SUMMARY_PROMPT_VERSION)
def _complete(ctx: DocumentToolContext, messages: list[Message]) -> str:
    response = ctx.llm.complete(messages, temperature=0)
    ctx.summary_usage = ctx.summary_usage + response.usage
    return (response.content or "").strip()


# -- Summary coverage (PRD D3) ---------------------------------------------------------

_FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vendor": ("vendor", "supplier", "seller", "issuer"),
    "total_amount": ("total",),
    "subtotal": ("subtotal", "sub-total"),
    "tax": ("tax",),
    "invoice_number": ("invoice number", "number"),
    "invoice_date": ("date",),
    "due_date": ("due",),
    "currency": ("currency",),
    "line_items": ("line item", "line items", "items"),
}
_CODE_KEYWORDS: dict[IssueCode, tuple[str, ...]] = {
    IssueCode.INVALID_CURRENCY: ("currency",),
    IssueCode.SUBTOTAL_TAX_MISMATCH: ("subtotal", "sub-total", "tax"),
    IssueCode.LINE_ITEMS_SUM_MISMATCH: ("line item", "line items", "items"),
    IssueCode.NEGATIVE_AMOUNT: ("negative", "credit", "refund"),
    IssueCode.DUE_BEFORE_INVOICE: ("due",),
    IssueCode.DATE_IN_FUTURE: ("future",),
    IssueCode.DUPLICATE_INVOICE_NUMBER: ("duplicate", "already", "same invoice number"),
    IssueCode.AMOUNT_OUTLIER: (
        "unusual",
        "usual",
        "range",
        "higher",
        "lower",
        "above",
        "below",
        "outlier",
    ),
}
_LINE_FIELD = re.compile(r"line_items\[(\d+)\]")


def issue_keywords(issue: ValidationIssue) -> tuple[str, ...]:
    """Words of which at least one must appear in a summary that mentions ``issue``."""
    if issue.code is IssueCode.LINE_AMOUNT_MISMATCH and (match := _LINE_FIELD.match(issue.field)):
        number = int(match.group(1)) + 1
        return (f"line {number}", f"item {number}")
    if issue.code is IssueCode.MISSING_FIELD:
        return _FIELD_KEYWORDS.get(issue.field, (issue.field.replace("_", " "),))
    return _CODE_KEYWORDS.get(issue.code, (issue.field.replace("_", " "),))


def missing_issues(summary: str, report: ValidationReport) -> list[ValidationIssue]:
    """Error and warning issues the summary does not mention (``info`` is optional)."""
    text = summary.lower()
    return [
        issue
        for issue in report.issues
        if issue.severity in (Severity.ERROR, Severity.WARNING)
        and not any(_contains(text, keyword) for keyword in issue_keywords(issue))
    ]


def _contains(text: str, keyword: str) -> bool:
    words = r"\s+".join(re.escape(word) for word in keyword.split())
    return re.search(rf"(?<![a-z0-9]){words}(?![a-z0-9])", text) is not None


def compose_summary(text: str, missing: list[ValidationIssue], extra: Sequence[str] = ()) -> str:
    """The model's text plus one sentence per issue (and ``extra`` sentence) it still missed.

    The appended sentences are never cut; the model's text is shortened instead.
    """
    text = " ".join(text.split())
    appendix = " ".join([*(issue.message for issue in missing), *extra])
    room = MAX_SUMMARY_CHARS - (len(appendix) + 1 if appendix else 0)
    if len(text) > room:
        cut = text[: max(room - 1, 0)]
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
        text = f"{cut}…" if cut else ""
    return " ".join(part for part in (text, appendix) if part)


# -- Fields to verify (PRD 0008 D8) ---------------------------------------------------------

_REVIEW_KEYWORDS: dict[str, tuple[str, ...]] = {
    **_FIELD_KEYWORDS,
    "invoice_number": ("invoice number",),
    "vendor_address": ("address",),
    "vendor_tax_id": ("tax id", "tax number", "registration"),
    "customer_name": ("customer",),
    "customer_address": ("address",),
    "payment_terms": ("terms",),
}
_VERIFY_WORDS = ("verify", "verified", "review", "check", "checked", "confirm", "confirmed")
_LINE_PATH = re.compile(r"line_items\[(\d+)\]\.(\w+)")


def field_name(path: str) -> str:
    """Readable name of a field path: ``line_items[1].amount`` -> ``line 2 amount``."""
    if match := _LINE_PATH.fullmatch(path):
        return f"line {int(match.group(1)) + 1} {match.group(2).replace('_', ' ')}"
    return path.replace("_", " ")


def _review_keywords(path: str) -> tuple[str, ...]:
    if match := _LINE_PATH.fullmatch(path):
        number = int(match.group(1)) + 1
        return (f"line {number}", f"item {number}")
    return _REVIEW_KEYWORDS.get(path, (field_name(path),))


def missing_review(summary: str, paths: Sequence[str]) -> list[str]:
    """Review fields the summary does not ask to verify (all of them without a verify word)."""
    if not paths:
        return []
    text = summary.lower()
    if not any(_contains(text, word) for word in _VERIFY_WORDS):
        return list(paths)
    return [p for p in paths if not any(_contains(text, k) for k in _review_keywords(p))]


def _review_reason(confidence: ConfidenceReport | None, path: str) -> str:
    if confidence is None or path not in confidence.fields:
        return "could not be confirmed"
    return confidence.fields[path].reasons[0]
