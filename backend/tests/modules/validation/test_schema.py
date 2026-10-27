"""The report and conversion DTOs are plain JSON for the 0005 tool results and JSONB."""

from decimal import Decimal

from app.modules.validation.schema import (
    ConversionResult,
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
    ValidationStatus,
)
from app.modules.validation.service import convert_currency


def test_report_json_shape() -> None:
    report = ValidationReport(
        status=ValidationStatus.WARN,
        issues=[
            ValidationIssue(
                field="total_amount",
                code=IssueCode.SUBTOTAL_TAX_MISMATCH,
                severity=Severity.WARNING,
                message="...",
                expected=Decimal("106.00"),
                actual=Decimal("108.00"),
            ),
            ValidationIssue(
                field="vendor",
                code=IssueCode.MISSING_FIELD,
                severity=Severity.ERROR,
                message="Vendor is missing.",
            ),
        ],
    )
    body = report.model_dump(mode="json")
    assert body["status"] == "warn"
    assert body["issues"][0] == {
        "field": "total_amount",
        "code": "subtotal_tax_mismatch",
        "severity": "warning",
        "message": "...",
        "expected": "106.00",
        "actual": "108.00",
    }
    assert body["issues"][1]["expected"] is None
    assert ValidationReport.model_validate(body) == report


def test_conversion_result_round_trips() -> None:
    result = convert_currency(Decimal("100"), "USD", "MYR")
    body = result.model_dump(mode="json")
    assert set(body) == {
        "original_amount",
        "from_currency",
        "to_currency",
        "rate",
        "converted_amount",
        "rate_date",
        "source",
    }
    assert ConversionResult.model_validate(body) == result


def test_enum_values_match_the_prd() -> None:
    assert [s.value for s in ValidationStatus] == ["pass", "warn", "fail"]
    assert [s.value for s in Severity] == ["error", "warning", "info"]
    assert [c.value for c in IssueCode] == [
        "missing_field",
        "not_financial_document",
        "invalid_currency",
        "subtotal_tax_mismatch",
        "tax_included",
        "line_items_sum_mismatch",
        "line_items_incomplete",
        "line_amount_mismatch",
        "negative_amount",
        "due_before_invoice",
        "date_in_future",
        "date_too_old",
        "duplicate_invoice_number",
        "amount_outlier",
        "new_vendor",
    ]
