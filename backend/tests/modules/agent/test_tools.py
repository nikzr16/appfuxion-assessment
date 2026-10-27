"""Document Agent tools: guards, short results, conversion and the summary rules."""

import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.errors import LLMError
from app.core.llm import FakeLLM
from app.core.storage import LocalStorage
from app.modules.agent import prompts, tools
from app.modules.agent.runner import Tool, ToolError
from app.modules.agent.tools import (
    MAX_SUMMARY_CHARS,
    DocumentToolContext,
    build_document_tools,
    compose_summary,
    missing_issues,
)
from app.modules.guardrails import service as guardrails_service
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.validation.schema import (
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
    ValidationStatus,
)
from tests.modules.agent.conftest import (
    INVOICE_LINES,
    SUMMARY,
    MakeDocument,
    invoice,
    unknown_document,
)


def _context(
    db_session: Session, storage: LocalStorage, llm: FakeLLM, document_id: uuid.UUID, **kw: Any
) -> DocumentToolContext:
    return DocumentToolContext(
        db=db_session,
        llm=llm,
        storage=storage,
        document_id=document_id,
        base_currency="MYR",
        **kw,
    )


def _fake(ctx: DocumentToolContext) -> FakeLLM:
    assert isinstance(ctx.llm, FakeLLM)
    return ctx.llm


def _tools(ctx: DocumentToolContext) -> dict[str, Tool]:
    return {tool.name: tool for tool in build_document_tools(ctx)}


def _call(ctx: DocumentToolContext, name: str, **arguments: Any) -> dict[str, Any]:
    return _tools(ctx)[name].handler(arguments)


def _error(ctx: DocumentToolContext, name: str, **arguments: Any) -> ToolError:
    with pytest.raises(ToolError) as caught:
        _call(ctx, name, **arguments)
    return caught.value


@pytest.fixture
def ctx(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> DocumentToolContext:
    return _context(db_session, storage, FakeLLM(), make_document())


def _with_invoice(ctx: DocumentToolContext, **overrides: Any) -> DocumentToolContext:
    """Skip the extraction and grounding tools: state as if they ran in this run."""
    ctx.text_done = True
    ctx.tables_done = True
    ctx.structured = invoice(**overrides)
    ctx.grounding = guardrails_service.check_grounding(
        ctx.structured, "\n".join(INVOICE_LINES), ExtractionMethod.PDF_PARSER
    )
    return ctx


def _issue(field: str, code: IssueCode, severity: Severity, message: str) -> ValidationIssue:
    return ValidationIssue(field=field, code=code, severity=severity, message=message)


def _report(*issues: ValidationIssue) -> ValidationReport:
    return ValidationReport(status=ValidationStatus.WARN, issues=list(issues))


TOTAL_WARNING = _issue(
    "total_amount",
    IssueCode.SUBTOTAL_TAX_MISMATCH,
    Severity.WARNING,
    "Subtotal 100.00 + tax 6.00 = 106.00 MYR, but the total is 108.00 MYR (difference 2.00).",
)
DUE_ERROR = _issue(
    "due_date",
    IssueCode.DUE_BEFORE_INVOICE,
    Severity.ERROR,
    "The due date 2025-03-01 is before the invoice date 2025-03-04.",
)


# -- Definitions ----------------------------------------------------------------------


def test_the_seven_tools_are_registered_with_strict_schemas(ctx: DocumentToolContext) -> None:
    definitions = [tool.definition() for tool in build_document_tools(ctx)]

    assert [d["function"]["name"] for d in definitions] == [
        "extract_text",
        "extract_tables",
        "extract_structured_data",
        "check_grounding",
        "validate_invoice",
        "convert_currency",
        "generate_summary",
    ]
    for definition in definitions:
        parameters = definition["function"]["parameters"]
        assert definition["function"]["strict"] is True
        assert parameters["additionalProperties"] is False
        assert parameters["required"] == list(parameters["properties"])
    assert "MYR" in definitions[5]["function"]["description"]


# -- Results and guards ----------------------------------------------------------------


def test_extract_text_returns_a_short_result_without_the_text(ctx: DocumentToolContext) -> None:
    result = _call(ctx, "extract_text")

    assert result == {"method": "pdf_parser", "page_count": 1, "characters": result["characters"]}
    assert result["characters"] > 0
    assert ctx.text_done


def test_structured_data_needs_text_from_this_run(ctx: DocumentToolContext) -> None:
    error = _error(ctx, "extract_structured_data")

    assert (error.code, error.fatal) == ("text_not_extracted", False)
    assert _fake(ctx).calls == []


def test_extract_tables_needs_text_from_this_run(ctx: DocumentToolContext) -> None:
    error = _error(ctx, "extract_tables")

    assert (error.code, error.fatal) == ("text_not_extracted", False)


def test_structured_data_needs_tables_from_this_run(ctx: DocumentToolContext) -> None:
    _call(ctx, "extract_text")

    error = _error(ctx, "extract_structured_data")

    assert (error.code, error.fatal) == ("tables_required", False)
    assert _fake(ctx).calls == []


def test_extract_tables_returns_counts_without_cell_text(ctx: DocumentToolContext) -> None:
    _call(ctx, "extract_text")

    result = _call(ctx, "extract_tables")

    assert result["available"] is True
    assert result["source"] == "pdf_parser"
    assert set(result) == {
        "source",
        "available",
        "pages",
        "tables",
        "line_item_table",
        "blocks",
        "reused",
    }
    assert ctx.tables_done


def test_a_new_extract_text_needs_tables_again(ctx: DocumentToolContext) -> None:
    _call(ctx, "extract_text")
    _call(ctx, "extract_tables")
    _call(ctx, "extract_text")

    assert _error(ctx, "extract_structured_data").code == "tables_required"


def test_structured_data_returns_the_invoice_json(ctx: DocumentToolContext) -> None:
    _fake(ctx).queue(invoice())
    _call(ctx, "extract_text")
    _call(ctx, "extract_tables")

    result = _call(ctx, "extract_structured_data")

    assert result == invoice().model_dump(mode="json")
    assert result["total_amount"] == "123.45"
    assert ctx.structured == invoice()


@pytest.mark.parametrize("tool", ["validate_invoice", "convert_currency"])
def test_tools_after_extraction_need_structured_data_from_this_run(
    ctx: DocumentToolContext, tool: str
) -> None:
    error = _error(ctx, tool, **({"to_currency": "MYR"} if tool == "convert_currency" else {}))

    assert (error.code, error.fatal) == ("structured_data_missing", False)


def test_validate_invoice_returns_the_report(ctx: DocumentToolContext) -> None:
    result = _call(_with_invoice(ctx), "validate_invoice")

    assert result["status"] == "pass"
    assert ctx.validation is not None
    assert ctx.confidence is not None and ctx.confidence.needs_review is False
    assert result == {
        **ctx.validation.model_dump(mode="json"),
        "needs_review": False,
        "review_fields": [],
    }


def test_generate_summary_refuses_until_validate_invoice_has_run(ctx: DocumentToolContext) -> None:
    error = _error(_with_invoice(ctx), "generate_summary")

    assert (error.code, error.fatal) == ("validation_required", False)
    assert ctx.summary is None


def test_reprocess_forces_only_the_first_extraction_calls(
    ctx: DocumentToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    forced: list[tuple[str, bool]] = []
    real_text = tools.text_extraction_service.extract_text
    real_structured = tools.structured_extraction_service.extract_structured_data
    real_tables = tools.vision_service.extract_tables

    def text_spy(*args: Any, force: bool) -> Any:
        forced.append(("text", force))
        return real_text(*args, force=force)

    def structured_spy(*args: Any, force: bool, **kwargs: Any) -> Any:
        forced.append(("structured", force))
        return real_structured(*args, force=force, **kwargs)

    def tables_spy(*args: Any, force: bool, **kwargs: Any) -> Any:
        forced.append(("tables", force))
        return real_tables(*args, force=force, **kwargs)

    monkeypatch.setattr(tools.text_extraction_service, "extract_text", text_spy)
    monkeypatch.setattr(
        tools.structured_extraction_service, "extract_structured_data", structured_spy
    )
    monkeypatch.setattr(tools.vision_service, "extract_tables", tables_spy)
    ctx.force = True
    _fake(ctx).queue(invoice(), invoice())

    for name in ("extract_text", "extract_text", "extract_tables", "extract_tables"):
        _call(ctx, name)
    _call(ctx, "extract_structured_data")
    _call(ctx, "extract_structured_data")

    assert forced == [
        ("text", True),
        ("text", False),
        ("tables", True),
        ("tables", False),
        ("structured", True),
        ("structured", False),
    ]


# -- convert_currency -----------------------------------------------------------------


def test_convert_currency_converts_the_saved_total(ctx: DocumentToolContext) -> None:
    result = _call(_with_invoice(ctx, currency="USD"), "convert_currency", to_currency="myr")

    assert result["original_amount"] == "123.45"
    assert (result["from_currency"], result["to_currency"]) == ("USD", "MYR")
    assert Decimal(result["converted_amount"]) > Decimal("123.45")
    assert result["rate_date"] and result["source"]
    assert ctx.conversion is not None


@pytest.mark.parametrize(
    ("overrides", "target"),
    [
        ({"currency": "MYR"}, "MYR"),  # already the base currency
        ({"currency": "MYR"}, "USD"),  # base currency: never converted away
        ({"currency": "SGD"}, "SGD"),  # same as the target
        ({"currency": None}, "MYR"),
        ({"currency": "USD", "total_amount": None}, "MYR"),
    ],
)
def test_convert_currency_refuses_when_nothing_needs_converting(
    ctx: DocumentToolContext, overrides: dict[str, Any], target: str
) -> None:
    error = _error(_with_invoice(ctx, **overrides), "convert_currency", to_currency=target)

    assert (error.code, error.fatal) == ("conversion_not_needed", False)
    assert ctx.conversion is None


def test_an_unsupported_currency_is_recoverable(ctx: DocumentToolContext) -> None:
    error = _error(_with_invoice(ctx, currency="XAF"), "convert_currency", to_currency="MYR")

    assert (error.code, error.fatal) == ("unsupported_currency", False)


@pytest.mark.parametrize("arguments", [{}, {"to_currency": ""}, {"to_currency": 5}])
def test_convert_currency_needs_a_target_code(
    ctx: DocumentToolContext, arguments: dict[str, Any]
) -> None:
    error = _error(_with_invoice(ctx, currency="USD"), "convert_currency", **arguments)

    assert error.code == "invalid_arguments"


# -- generate_summary ------------------------------------------------------------------


def _validated(ctx: DocumentToolContext, report: ValidationReport, **overrides: Any) -> None:
    _with_invoice(ctx, **overrides)
    ctx.validation = report


def test_the_summary_call_gets_the_data_and_report_but_no_raw_text(
    ctx: DocumentToolContext,
) -> None:
    _validated(ctx, _report(), currency="USD")
    _call(ctx, "convert_currency", to_currency="MYR")
    _fake(ctx).queue(SUMMARY)

    result = _call(ctx, "generate_summary")

    assert result == {"summary": SUMMARY}
    call = _fake(ctx).calls[-1]
    assert call.temperature == 0
    assert call.tools is None
    assert call.messages[0] == {"role": "system", "content": prompts.SUMMARY_SYSTEM_PROMPT}
    payload = json.loads(call.messages[1]["content"])
    assert set(payload) == {
        "document_type",
        "structured_data",
        "validation",
        "conversion",
        "base_currency",
        "review",
    }
    assert payload["review"] == []
    assert payload["structured_data"]["total_amount"] == "123.45"
    assert payload["conversion"]["to_currency"] == "MYR"
    assert all(line not in call.messages[1]["content"] for line in INVOICE_LINES[2:])


def test_a_summary_that_misses_an_issue_is_retried_once(ctx: DocumentToolContext) -> None:
    _validated(ctx, _report(TOTAL_WARNING))
    fixed = "The invoice failed its total check: subtotal plus tax is 106.00 but total 108.00."
    _fake(ctx).queue("A fine invoice.", fixed)

    result = _call(ctx, "generate_summary")

    assert result == {"summary": fixed}
    retry = _fake(ctx).calls[-1].messages
    assert retry[2] == {"role": "assistant", "content": "A fine invoice."}
    assert TOTAL_WARNING.message in retry[3]["content"]
    assert ctx.summary_usage.prompt_tokens == 20


def test_issues_still_missing_after_the_retry_are_appended_by_code(
    ctx: DocumentToolContext,
) -> None:
    _validated(ctx, _report(TOTAL_WARNING, DUE_ERROR))
    _fake(ctx).queue("A fine invoice.", "A fine invoice with a due date problem.")

    result = _call(ctx, "generate_summary")

    assert result["summary"] == f"A fine invoice with a due date problem. {TOTAL_WARNING.message}"


def test_an_empty_summary_is_retried_and_fatal_if_still_empty(ctx: DocumentToolContext) -> None:
    _validated(ctx, _report())
    _fake(ctx).queue("", "  ")

    error = _error(ctx, "generate_summary")

    assert (error.code, error.fatal) == ("invalid_llm_output", True)
    assert len(_fake(ctx).calls) == 2


def test_an_llm_failure_in_the_summary_is_fatal(ctx: DocumentToolContext) -> None:
    _validated(ctx, _report())
    _fake(ctx).queue(LLMError("down"))

    error = _error(ctx, "generate_summary")

    assert (error.code, error.fatal) == ("llm_error", True)


def test_an_unknown_document_gets_the_fixed_summary_without_an_llm_call(
    ctx: DocumentToolContext,
) -> None:
    ctx.text_done = True
    ctx.structured = unknown_document()
    ctx.validation = _report()

    result = _call(ctx, "generate_summary")

    assert result == {"summary": prompts.UNKNOWN_SUMMARY}
    assert _fake(ctx).calls == []


@pytest.mark.parametrize(
    ("issue", "mentioned", "not_mentioned"),
    [
        (TOTAL_WARNING, "The subtotal and tax do not add up.", "All good."),
        (DUE_ERROR, "It is due before it was issued.", "All good."),
        (
            _issue("vendor", IssueCode.MISSING_FIELD, Severity.ERROR, "Vendor is missing."),
            "The supplier is not named.",
            "All good.",
        ),
        (
            _issue(
                "line_items[2].amount",
                IssueCode.LINE_AMOUNT_MISMATCH,
                Severity.WARNING,
                "Line 3: quantity 2 x unit price 5.00 = 10.00 MYR, but the amount is 11.00.",
            ),
            "Line 3 has a wrong amount.",
            "Line 30 has a wrong amount.",
        ),
        (
            _issue(
                "line_items",
                IssueCode.LINE_ITEMS_SUM_MISMATCH,
                Severity.WARNING,
                "The line items add up to 10.00, but the subtotal is 12.00.",
            ),
            "The items do not add up.",
            "All good.",
        ),
        (
            _issue("total_amount", IssueCode.NEGATIVE_AMOUNT, Severity.WARNING, "Negative."),
            "It looks like a credit note.",
            "All good.",
        ),
        (
            _issue("invoice_date", IssueCode.DATE_IN_FUTURE, Severity.WARNING, "Future."),
            "The date is in the future.",
            "All good.",
        ),
        (
            _issue("currency", IssueCode.INVALID_CURRENCY, Severity.ERROR, "Bad currency."),
            "The currency is not valid.",
            "All good.",
        ),
    ],
)
def test_missing_issues_matches_keywords_per_issue(
    issue: ValidationIssue, mentioned: str, not_mentioned: str
) -> None:
    assert missing_issues(mentioned, _report(issue)) == []
    assert missing_issues(not_mentioned, _report(issue)) == [issue]


def test_info_issues_are_not_required() -> None:
    info = _issue("due_date", IssueCode.MISSING_FIELD, Severity.INFO, "Due date is missing.")

    assert missing_issues("All good.", _report(info)) == []


def test_compose_summary_caps_the_text_but_never_the_appended_issues() -> None:
    text = "word " * 400

    summary = compose_summary(text, [TOTAL_WARNING])

    assert len(summary) <= MAX_SUMMARY_CHARS
    assert summary.endswith(TOTAL_WARNING.message)
    assert "… " in summary


def test_compose_summary_normalises_whitespace() -> None:
    assert compose_summary("  Two\nlines  ", []) == "Two lines"
