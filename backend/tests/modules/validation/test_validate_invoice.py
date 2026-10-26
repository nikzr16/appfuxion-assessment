"""validate_invoice: one table per PRD decision (D2-D9). Pure calls, ``today`` injected."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.modules.validation.schema import (
    IssueCode,
    Severity,
    ValidationReport,
    ValidationStatus,
)
from app.modules.validation.service import validate_invoice
from tests.modules.validation.conftest import TODAY, line, make_invoice

ERROR, WARNING, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
Found = list[tuple[IssueCode, Severity, str]]


def check(**overrides: Any) -> ValidationReport:
    return validate_invoice(make_invoice(**overrides), today=TODAY)


def found(report: ValidationReport) -> Found:
    return [(issue.code, issue.severity, issue.field) for issue in report.issues]


def totals_case(currency: str | None, subtotal: str, total: str) -> dict[str, Any]:
    """Subtotal vs total with no tax; one line equal to the subtotal."""
    return {
        "currency": currency,
        "subtotal": subtotal,
        "tax": None,
        "total_amount": total,
        "lines": [line("1", subtotal, subtotal)],
    }


def test_clean_invoice_passes() -> None:
    report = check()
    assert report.status is ValidationStatus.PASS
    assert report.issues == []


# --- D3 required fields ------------------------------------------------------------------

MISSING = IssueCode.MISSING_FIELD


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"vendor": None}, [(MISSING, ERROR, "vendor")]),
        ({"invoice_number": None}, [(MISSING, WARNING, "invoice_number")]),
        ({"invoice_date": None}, [(MISSING, WARNING, "invoice_date")]),
        ({"due_date": None}, [(MISSING, INFO, "due_date")]),
        ({"currency": None}, [(MISSING, WARNING, "currency")]),
        ({"total_amount": None}, [(MISSING, ERROR, "total_amount")]),
        ({"lines": []}, [(MISSING, INFO, "line_items")]),
        # receipts never need a number or a due date
        ({"document_type": "receipt", "invoice_number": None, "due_date": None}, []),
        ({"document_type": "receipt", "vendor": None}, [(MISSING, ERROR, "vendor")]),
        ({"document_type": "receipt", "invoice_date": None}, [(MISSING, WARNING, "invoice_date")]),
        ({"document_type": "receipt", "currency": None}, [(MISSING, WARNING, "currency")]),
        ({"document_type": "receipt", "total_amount": None}, [(MISSING, ERROR, "total_amount")]),
        ({"document_type": "receipt", "lines": []}, [(MISSING, INFO, "line_items")]),
    ],
)
def test_required_fields(overrides: dict[str, Any], expected: Found) -> None:
    assert found(check(**overrides)) == expected


def test_unknown_document_gets_one_warning_and_no_other_checks() -> None:
    # Fields that would otherwise fail (missing vendor, bad total) are not checked.
    report = check(document_type="unknown", vendor=None, total_amount="999.00")
    assert found(report) == [(IssueCode.NOT_FINANCIAL_DOCUMENT, WARNING, "document_type")]
    assert report.status is ValidationStatus.WARN


def test_missing_date_and_currency_messages_explain_why() -> None:
    messages = {i.field: i.message for i in check(invoice_date=None, currency=None).issues}
    assert messages["invoice_date"] == (
        "Invoice date is missing (it may have been printed in an ambiguous day/month format)."
    )
    assert "ambiguous" in messages["currency"]


# --- D2 roll-up --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({}, ValidationStatus.PASS),
        ({"due_date": None}, ValidationStatus.PASS),  # info only
        ({"invoice_number": None}, ValidationStatus.WARN),
        ({"invoice_number": None, "due_date": None}, ValidationStatus.WARN),
        ({"vendor": None, "invoice_number": None}, ValidationStatus.FAIL),
    ],
)
def test_roll_up(overrides: dict[str, Any], status: ValidationStatus) -> None:
    assert check(**overrides).status is status


# --- D5 (a) totals -----------------------------------------------------------------------

TOTALS = IssueCode.SUBTOTAL_TAX_MISMATCH


def test_subtotal_plus_tax_mismatch_reports_numbers() -> None:
    report = check(total_amount="108.00")
    assert found(report) == [(TOTALS, WARNING, "total_amount")]
    issue = report.issues[0]
    assert (issue.expected, issue.actual) == (Decimal("106.00"), Decimal("108.00"))
    assert issue.message == (
        "Subtotal 100.00 + tax 6.00 = 106.00 MYR, but the total is 108.00 MYR "
        "(difference 2.00 MYR)."
    )
    assert report.status is ValidationStatus.WARN


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        # tax-inclusive layout: subtotal already equals the total
        (
            {"subtotal": "106.00", "total_amount": "106.00", "lines": [line("2", "53", "106")]},
            [(IssueCode.TAX_INCLUDED, INFO, "total_amount")],
        ),
        # no tax: subtotal must equal the total
        ({"tax": None, "total_amount": "100.00"}, []),
        ({"tax": None}, [(TOTALS, WARNING, "total_amount")]),
        # a missing input skips the check (already reported as missing)
        ({"subtotal": None, "tax": None, "total_amount": "100.00"}, []),
    ],
)
def test_totals(overrides: dict[str, Any], expected: Found) -> None:
    assert found(check(**overrides)) == expected


# --- D5 (b) line sum ---------------------------------------------------------------------

SUM = IssueCode.LINE_ITEMS_SUM_MISMATCH


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        # against the subtotal when there is one
        (
            {"lines": [line(None, None, "48.00"), line(None, None, "50.00")]},
            [(SUM, WARNING, "line_items")],
        ),
        # no subtotal: total - tax (tax exclusive) or the total (tax inclusive) both pass
        ({"subtotal": None}, []),
        ({"subtotal": None, "lines": [line(None, None, "106.00")]}, []),
        ({"subtotal": None, "lines": [line(None, None, "90.00")]}, [(SUM, WARNING, "line_items")]),
        # no subtotal and no total: nothing to compare with
        ({"subtotal": None, "total_amount": None}, [(MISSING, ERROR, "total_amount")]),
        # a line without an amount: one info, no sum check
        (
            {"lines": [line("1", "50.00", None), line(None, None, "10.00")]},
            [(IssueCode.LINE_ITEMS_INCOMPLETE, INFO, "line_items")],
        ),
    ],
)
def test_line_sum(overrides: dict[str, Any], expected: Found) -> None:
    assert found(check(**overrides)) == expected


def test_line_sum_mismatch_reports_numbers() -> None:
    report = check(lines=[line(None, None, "48.00"), line(None, None, "50.00")])
    issue = report.issues[0]
    assert (issue.expected, issue.actual) == (Decimal("98.00"), Decimal("100.00"))
    assert issue.message == (
        "The line items add up to 98.00 MYR, but the subtotal is 100.00 MYR (difference 2.00 MYR)."
    )


def test_incomplete_lines_message_counts_them() -> None:
    report = check(lines=[line("1", "50.00", None), line(None, None, "50.00")])
    assert report.issues[0].message == (
        "1 of 2 line items have no amount, so the line total was not checked."
    )


# --- D5 (c) per line ---------------------------------------------------------------------


def test_line_amount_mismatch() -> None:
    report = check(lines=[line("2", "25.00", "49.00"), line("1", "51.00", "51.00")])
    assert found(report) == [(IssueCode.LINE_AMOUNT_MISMATCH, WARNING, "line_items[0].amount")]
    issue = report.issues[0]
    assert (issue.expected, issue.actual) == (Decimal("50.00"), Decimal("49.00"))
    assert issue.message.startswith("Line 1: quantity 2 x unit price 25.00 = 50.00 MYR")


def test_line_with_four_decimal_unit_price_passes() -> None:
    # 3 x 3.3333 = 9.9999, printed as 10.00: within one minor unit
    assert check(lines=[line("3", "3.3333", "10.00"), line("1", "90.00", "90.00")]).issues == []


# --- D4 tolerance ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("currency", "subtotal", "total", "mismatch"),
    [
        ("MYR", "100.00", "100.01", False),
        ("MYR", "100.00", "100.02", True),
        ("JPY", "1000", "1001", False),
        ("JPY", "1000", "1002", True),
        ("KWD", "10.000", "10.001", False),
        ("KWD", "10.000", "10.002", True),
        (None, "100.00", "100.01", False),
        (None, "100.00", "100.02", True),
    ],
)
def test_tolerance_is_one_minor_unit(
    currency: str | None, subtotal: str, total: str, mismatch: bool
) -> None:
    codes = [issue.code for issue in check(**totals_case(currency, subtotal, total)).issues]
    assert (TOTALS in codes) is mismatch


def test_messages_use_the_currency_minor_units() -> None:
    report = check(**totals_case("JPY", "1000", "1500"))
    assert report.issues[0].message == (
        "Subtotal 1,000 JPY does not match the total 1,500 JPY (difference 500 JPY)."
    )


# --- D6 negatives ------------------------------------------------------------------------


def test_discount_line_is_allowed() -> None:
    lines = [line("1", "110.00", "110.00"), line("1", "-10.00", "-10.00")]
    assert check(lines=lines).issues == []


def test_negative_headline_amounts_warn() -> None:
    report = check(
        subtotal="-100.00",
        tax="-6.00",
        total_amount="-106.00",
        lines=[line("2", "-25.00", "-50.00"), line("1", "-50.00", "-50.00")],
    )
    negative = IssueCode.NEGATIVE_AMOUNT
    assert found(report) == [
        (negative, WARNING, "subtotal"),
        (negative, WARNING, "tax"),
        (negative, WARNING, "total_amount"),
    ]
    assert report.issues[2].actual == Decimal("-106.00")
    assert "credit note" in report.issues[2].message


# --- D7 dates ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"due_date": "2026-09-30"}, [(IssueCode.DUE_BEFORE_INVOICE, ERROR, "due_date")]),
        ({"due_date": "2026-10-01"}, []),  # same day is fine
        (
            {"invoice_date": "2026-10-28", "due_date": None},
            [(MISSING, INFO, "due_date"), (IssueCode.DATE_IN_FUTURE, WARNING, "invoice_date")],
        ),
        ({"invoice_date": "2026-10-27", "due_date": None}, [(MISSING, INFO, "due_date")]),
        (
            {"invoice_date": "2016-10-25", "due_date": None},
            [(MISSING, INFO, "due_date"), (IssueCode.DATE_TOO_OLD, INFO, "invoice_date")],
        ),
        ({"invoice_date": "2016-10-26", "due_date": None}, [(MISSING, INFO, "due_date")]),
    ],
)
def test_dates(overrides: dict[str, Any], expected: Found) -> None:
    assert found(check(**overrides)) == expected


def test_too_old_on_29_february() -> None:
    today = date(2028, 2, 29)
    old = validate_invoice(make_invoice(invoice_date="2018-02-27", due_date=None), today=today)
    edge = validate_invoice(make_invoice(invoice_date="2018-02-28", due_date=None), today=today)
    assert IssueCode.DATE_TOO_OLD in [i.code for i in old.issues]
    assert IssueCode.DATE_TOO_OLD not in [i.code for i in edge.issues]


def test_today_defaults_to_the_current_date() -> None:
    report = validate_invoice(make_invoice(invoice_date="2999-01-01", due_date=None))
    assert IssueCode.DATE_IN_FUTURE in [issue.code for issue in report.issues]


# --- D8 currency -------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["ABC", "XAU", "XTS", "XXX"])
def test_invalid_currency_fails(code: str) -> None:
    report = check(currency=code)
    assert found(report) == [(IssueCode.INVALID_CURRENCY, ERROR, "currency")]
    assert report.status is ValidationStatus.FAIL


def test_real_x_currency_is_valid() -> None:
    assert check(**totals_case("XAF", "1000", "1000")).issues == []


# --- D9 contract -------------------------------------------------------------------------


def test_issue_order_is_fixed() -> None:
    report = check(
        vendor=None,
        currency="ABC",
        due_date="2026-09-01",
        total_amount="108.00",
        lines=[line("2", "25.00", "49.00"), line(None, None, "51.00")],
    )
    assert [issue.code for issue in report.issues] == [
        IssueCode.MISSING_FIELD,
        IssueCode.INVALID_CURRENCY,
        IssueCode.DUE_BEFORE_INVOICE,
        IssueCode.SUBTOTAL_TAX_MISMATCH,
        IssueCode.LINE_AMOUNT_MISMATCH,
    ]
    assert report == check(
        vendor=None,
        currency="ABC",
        due_date="2026-09-01",
        total_amount="108.00",
        lines=[line("2", "25.00", "49.00"), line(None, None, "51.00")],
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "subtotal": "1E+20",
            "tax": "0",
            "total_amount": "1E+20",
            "lines": [line("1E+10", "1E+10", "1E+20")],
        },
        {"subtotal": "1E-10", "tax": "-0", "total_amount": "0", "lines": [line("0", "0", "-0")]},
        {"currency": None, "subtotal": None, "tax": None, "total_amount": None, "lines": []},
        {"currency": "KWD", "lines": [line("1E-20", "1E+20", "1")]},
    ],
)
def test_never_raises_and_round_trips(overrides: dict[str, Any]) -> None:
    report = check(**overrides)
    assert ValidationReport.model_validate(report.model_dump(mode="json")) == report
