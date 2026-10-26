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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.llm import LLMClient, Message, TokenUsage
from app.core.storage import Storage
from app.modules.agent import prompts
from app.modules.agent.runner import NO_ARGUMENTS, Tool, ToolError, ToolHandler
from app.modules.structured_extraction import service as structured_extraction_service
from app.modules.structured_extraction.schema import DocumentType, InvoiceData
from app.modules.text_extraction import service as text_extraction_service
from app.modules.validation import service as validation_service
from app.modules.validation.schema import (
    ConversionResult,
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
)

# Errors the model can act on; every other ``AppError`` code ends the run (PRD D6).
RECOVERABLE_CODES = frozenset(
    {
        "text_not_extracted",
        "structured_data_missing",
        "validation_required",
        "conversion_not_needed",
        "unsupported_currency",
        "invalid_amount",
        "invalid_arguments",
        "unknown_tool",
    }
)

MAX_SUMMARY_CHARS = 1500


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
    structured: InvoiceData | None = None
    validation: ValidationReport | None = None
    conversion: ConversionResult | None = None
    summary: str | None = None
    _text_forced: bool = False
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
            name="extract_structured_data",
            description=(
                "Extract the invoice fields from the document's text and return them as "
                "JSON. Requires extract_text."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _extract_structured_data(ctx)),
        ),
        Tool(
            name="validate_invoice",
            description=(
                "Check the extracted fields with deterministic code (required fields, "
                "totals, dates, currency). Returns a status and a list of issues. Requires "
                "extract_structured_data."
            ),
            parameters=NO_ARGUMENTS,
            handler=_guarded(lambda _args: _validate_invoice(ctx)),
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
            name="generate_summary",
            description=(
                "Write the final plain-text summary from the extracted fields and the "
                "validation report. Requires validate_invoice. Call it last."
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
    return {
        "method": text.method.value,
        "page_count": text.page_count,
        "characters": len(text.raw_text),
    }


def _extract_structured_data(ctx: DocumentToolContext) -> dict[str, Any]:
    if not ctx.text_done:
        raise ToolError("text_not_extracted", "Call extract_text before extract_structured_data.")
    force = ctx.force and not ctx._structured_forced
    extraction = structured_extraction_service.extract_structured_data(
        ctx.db, ctx.llm, ctx.document_id, force=force
    )
    ctx._structured_forced = ctx._structured_forced or force
    ctx.structured = extraction.data
    return extraction.data.model_dump(mode="json")


def _validate_invoice(ctx: DocumentToolContext) -> dict[str, Any]:
    data = _require_structured(ctx, "validate_invoice")
    ctx.validation = validation_service.validate_invoice(data, today=ctx.today)
    return ctx.validation.model_dump(mode="json")


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
    if ctx.structured.document_type is DocumentType.UNKNOWN:
        ctx.summary = prompts.UNKNOWN_SUMMARY  # PRD D5: nothing to summarise, no LLM call
        return {"summary": ctx.summary}

    payload = {
        "document_type": ctx.structured.document_type.value,
        "structured_data": ctx.structured.model_dump(mode="json"),
        "validation": ctx.validation.model_dump(mode="json"),
        "conversion": ctx.conversion.model_dump(mode="json") if ctx.conversion else None,
        "base_currency": ctx.base_currency,
    }
    messages: list[Message] = [
        {"role": "system", "content": prompts.SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload)},
    ]
    text = _complete(ctx, messages)
    missing = missing_issues(text, ctx.validation)
    if not text or missing:
        feedback = (
            prompts.summary_retry_prompt([issue.message for issue in missing])
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
    ctx.summary = compose_summary(text, missing)
    return {"summary": ctx.summary}


def _require_structured(ctx: DocumentToolContext, tool: str) -> InvoiceData:
    if ctx.structured is None:
        raise ToolError("structured_data_missing", f"Call extract_structured_data before {tool}.")
    return ctx.structured


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


def compose_summary(text: str, missing: list[ValidationIssue]) -> str:
    """The model's text plus one sentence per issue it still missed, capped in length.

    The appended issue messages are never cut; the model's text is shortened instead.
    """
    text = " ".join(text.split())
    appendix = " ".join(issue.message for issue in missing)
    room = MAX_SUMMARY_CHARS - (len(appendix) + 1 if appendix else 0)
    if len(text) > room:
        cut = text[: max(room - 1, 0)]
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
        text = f"{cut}…" if cut else ""
    return " ".join(part for part in (text, appendix) if part)
