"""Deterministic invoice validation and static-rate currency conversion (brief Part 5).

Pure functions: no database, no network, no LLM. ``validate_invoice`` turns every problem
into an issue and never raises; ``convert_currency`` raises ``CurrencyConversionError`` when
it cannot convert. The 0005 agent tools wrap both.
"""

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

import pycountry

from app.modules.structured_extraction.schema import DocumentType, InvoiceData
from app.modules.validation.currencies import (
    DEFAULT_MINOR_UNITS,
    EXCLUDED_CODES,
    MINOR_UNITS,
    RATES_AS_OF,
    RATES_PER_USD,
    RATES_SOURCE,
)
from app.modules.validation.schema import (
    ConversionResult,
    CurrencyConversionError,
    IssueCode,
    Severity,
    ValidationIssue,
    ValidationReport,
    ValidationStatus,
)

_CURRENCY_CODE = re.compile(r"[A-Z]{3}")
FUTURE_SLACK = timedelta(days=1)  # time zones: "today" may already be tomorrow elsewhere
TOO_OLD_YEARS = 10
RATE_DIGITS = 10  # significant digits of the reported conversion rate

_LABELS = {
    "vendor": "Vendor",
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "due_date": "Due date",
    "currency": "Currency",
    "total_amount": "Total amount",
}
_MISSING_HINTS = {
    "invoice_date": " (it may have been printed in an ambiguous day/month format)",
    "due_date": " (it may have been printed in an ambiguous day/month format)",
    "currency": " (the symbol may be ambiguous, e.g. a bare $)",
}

# PRD D3: severity of a missing field per document type; absent means "not required".
_REQUIRED: dict[DocumentType, dict[str, Severity]] = {
    DocumentType.INVOICE: {
        "vendor": Severity.ERROR,
        "invoice_number": Severity.WARNING,
        "invoice_date": Severity.WARNING,
        "due_date": Severity.INFO,
        "currency": Severity.WARNING,
        "total_amount": Severity.ERROR,
        "line_items": Severity.INFO,
    },
    DocumentType.RECEIPT: {
        "vendor": Severity.ERROR,
        "invoice_date": Severity.WARNING,
        "currency": Severity.WARNING,
        "total_amount": Severity.ERROR,
        "line_items": Severity.INFO,
    },
}


def is_iso_currency(code: str) -> bool:
    """True for an ISO 4217 currency; precious metals, IMF units and test codes are not."""
    code = code.strip().upper()
    if not _CURRENCY_CODE.fullmatch(code) or code in EXCLUDED_CODES:
        return False
    return pycountry.currencies.get(alpha_3=code) is not None


def minor_units(code: str | None) -> int:
    """Decimal places of a currency (JPY 0, MYR 2, KWD 3); 2 when unknown or ``None``."""
    if code is None:
        return DEFAULT_MINOR_UNITS
    return MINOR_UNITS.get(code.strip().upper(), DEFAULT_MINOR_UNITS)


def expected_fields(document_type: DocumentType) -> list[str]:
    """Fields a document of this type should have (the required-field table, PRD D3).

    Used by 0008 guardrails to score completeness; ``unknown`` documents expect nothing.
    """
    return list(_REQUIRED.get(document_type, {}))


def validate_invoice(data: InvoiceData, *, today: date | None = None) -> ValidationReport:
    """Check one document against itself and report every problem as an issue.

    ``today`` (default ``date.today()``) is only used by the future / too-old date checks.
    The issue order is fixed (required fields, currency, dates, negatives, totals, line
    items), so the same input always gives the same report.
    """
    if data.document_type is DocumentType.UNKNOWN:
        issue = ValidationIssue(
            field="document_type",
            code=IssueCode.NOT_FINANCIAL_DOCUMENT,
            severity=Severity.WARNING,
            message=(
                "The document was classified as neither an invoice nor a receipt, "
                "so no other checks were run."
            ),
        )
        return ValidationReport(status=ValidationStatus.WARN, issues=[issue])

    currency = data.currency if data.currency and is_iso_currency(data.currency) else None
    money = _MoneyFormat(currency)
    issues = [
        *_required_fields(data),
        *_currency(data),
        *_dates(data, today or date.today()),
        *_negatives(data, money),
        *_totals(data, money),
        *_line_items(data, money),
    ]
    return ValidationReport(status=_roll_up(issues), issues=issues)


def convert_currency(amount: Decimal, from_currency: str, to_currency: str) -> ConversionResult:
    """Convert ``amount`` with the static rate table (cross rate through USD).

    The converted amount uses the exact cross rate and is rounded half-up to the target's
    minor units; the reported ``rate`` is rounded to 10 significant digits for display.
    Raises ``CurrencyConversionError`` (``invalid_amount`` / ``unsupported_currency``).
    """
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise CurrencyConversionError(
            "Amount must be a finite decimal number.", code="invalid_amount"
        )
    source, target = from_currency.strip().upper(), to_currency.strip().upper()
    for code in (source, target):
        if code not in RATES_PER_USD:
            raise CurrencyConversionError(
                f"{code!r} is not in the rate table (rates as of {RATES_AS_OF.isoformat()}). "
                f"Supported: {', '.join(sorted(RATES_PER_USD))}."
            )
    exact = Decimal(1) if source == target else RATES_PER_USD[target] / RATES_PER_USD[source]
    try:
        converted = (amount * exact).quantize(_unit(minor_units(target)), ROUND_HALF_UP)
    except InvalidOperation as exc:  # result needs more than the 28 significant digits
        raise CurrencyConversionError(
            "Amount is too large to convert.", code="invalid_amount"
        ) from exc
    with localcontext() as ctx:
        ctx.prec = RATE_DIGITS
        rate = +exact
    return ConversionResult(
        original_amount=amount,
        from_currency=source,
        to_currency=target,
        rate=rate,
        converted_amount=converted,
        rate_date=RATES_AS_OF,
        source=RATES_SOURCE,
    )


# --- checks (one per PRD decision, in report order) ---------------------------------------


def merge_issues(report: ValidationReport, issues: list[ValidationIssue]) -> ValidationReport:
    """Append findings made outside this module (vendor history, feature 0010) after the
    report's own issues and recompute the status with the same rule."""
    if not issues:
        return report
    merged = [*report.issues, *issues]
    return ValidationReport(status=_roll_up(merged), issues=merged)


def _required_fields(data: InvoiceData) -> list[ValidationIssue]:
    """PRD D3: missing fields, severity by document type."""
    issues = []
    for field, severity in _REQUIRED[data.document_type].items():
        if field == "line_items":
            if not data.line_items:
                issues.append(
                    _issue(field, IssueCode.MISSING_FIELD, severity, "No line items were found.")
                )
        elif getattr(data, field) is None:
            message = f"{_LABELS[field]} is missing{_MISSING_HINTS.get(field, '')}."
            issues.append(_issue(field, IssueCode.MISSING_FIELD, severity, message))
    return issues


def _currency(data: InvoiceData) -> list[ValidationIssue]:
    """PRD D8: a currency that is set must be a real ISO 4217 code."""
    if data.currency is None or is_iso_currency(data.currency):
        return []
    message = f"Currency {data.currency!r} is not a valid ISO 4217 currency code."
    return [_issue("currency", IssueCode.INVALID_CURRENCY, Severity.ERROR, message)]


def _dates(data: InvoiceData, today: date) -> list[ValidationIssue]:
    """PRD D7: due before invoice; invoice date in the future or more than 10 years old."""
    issues = []
    invoice_date, due_date = data.invoice_date, data.due_date
    if invoice_date and due_date and due_date < invoice_date:
        message = (
            f"The due date {due_date.isoformat()} is before the invoice date "
            f"{invoice_date.isoformat()}."
        )
        issues.append(_issue("due_date", IssueCode.DUE_BEFORE_INVOICE, Severity.ERROR, message))
    if invoice_date and invoice_date > today + FUTURE_SLACK:
        message = (
            f"The invoice date {invoice_date.isoformat()} is in the future (today is "
            f"{today.isoformat()}); the year may have been misread."
        )
        issues.append(_issue("invoice_date", IssueCode.DATE_IN_FUTURE, Severity.WARNING, message))
    if invoice_date and invoice_date < _years_before(today, TOO_OLD_YEARS):
        message = (
            f"The invoice date {invoice_date.isoformat()} is more than {TOO_OLD_YEARS} years ago."
        )
        issues.append(_issue("invoice_date", IssueCode.DATE_TOO_OLD, Severity.INFO, message))
    return issues


def _negatives(data: InvoiceData, money: "_MoneyFormat") -> list[ValidationIssue]:
    """PRD D6: only headline amounts are flagged; negative lines are discounts / returns."""
    issues = []
    for field, label in (("subtotal", "subtotal"), ("tax", "tax"), ("total_amount", "total")):
        value = getattr(data, field)
        if value is not None and value < 0:
            message = (
                f"The {label} is negative ({money(value)}); this looks like a credit note "
                "or refund."
            )
            issues.append(
                _issue(field, IssueCode.NEGATIVE_AMOUNT, Severity.WARNING, message, actual=value)
            )
    return issues


def _totals(data: InvoiceData, money: "_MoneyFormat") -> list[ValidationIssue]:
    """PRD D5 (a): subtotal + tax ≈ total, accepting tax-inclusive layouts."""
    subtotal, tax, total = data.subtotal, data.tax, data.total_amount
    if subtotal is None or total is None:
        return []
    if tax is None:
        if money.close(subtotal, total):
            return []
        message = (
            f"Subtotal {money(subtotal)} does not match the total {money(total)} "
            f"(difference {money(abs(total - subtotal))})."
        )
        expected = subtotal
    else:
        expected = subtotal + tax
        if money.close(expected, total):
            return []
        if money.close(subtotal, total):
            message = (
                f"Subtotal {money(subtotal)} already equals the total, so the tax "
                f"{money(tax)} is treated as included in the prices."
            )
            return [_issue("total_amount", IssueCode.TAX_INCLUDED, Severity.INFO, message)]
        message = (
            f"Subtotal {money(subtotal, code=False)} + tax {money(tax, code=False)} = "
            f"{money(expected)}, but the total is {money(total)} "
            f"(difference {money(abs(total - expected))})."
        )
    return [
        _issue(
            "total_amount",
            IssueCode.SUBTOTAL_TAX_MISMATCH,
            Severity.WARNING,
            message,
            expected=expected,
            actual=total,
        )
    ]


def _line_items(data: InvoiceData, money: "_MoneyFormat") -> list[ValidationIssue]:
    """PRD D5 (c) quantity x unit price ≈ amount per line, then (b) the line sum."""
    issues = []
    for index, line in enumerate(data.line_items):
        quantity, unit_price, amount = line.quantity, line.unit_price, line.amount
        if quantity is None or unit_price is None or amount is None:
            continue
        expected = quantity * unit_price
        if not money.close(expected, amount):
            message = (
                f"Line {index + 1}: quantity {_plain(quantity)} x unit price "
                f"{money(unit_price, code=False)} = {money(expected)}, but the line amount is "
                f"{money(amount)} (difference {money(abs(amount - expected))})."
            )
            issues.append(
                _issue(
                    f"line_items[{index}].amount",
                    IssueCode.LINE_AMOUNT_MISMATCH,
                    Severity.WARNING,
                    message,
                    expected=expected,
                    actual=amount,
                )
            )
    issues += _line_sum(data, money)
    return issues


def _line_sum(data: InvoiceData, money: "_MoneyFormat") -> list[ValidationIssue]:
    """PRD D5 (b): Σ line amounts ≈ subtotal; without one, ≈ total or total - tax."""
    if not data.line_items:
        return []
    missing = sum(1 for line in data.line_items if line.amount is None)
    if missing:
        message = (
            f"{missing} of {len(data.line_items)} line items have no amount, so the line "
            "total was not checked."
        )
        return [_issue("line_items", IssueCode.LINE_ITEMS_INCOMPLETE, Severity.INFO, message)]
    lines_total = sum(
        (line.amount for line in data.line_items if line.amount is not None), Decimal(0)
    )
    subtotal, tax, total = data.subtotal, data.tax, data.total_amount
    if subtotal is not None:
        if money.close(lines_total, subtotal):
            return []
        actual, target = subtotal, f"the subtotal is {money(subtotal)}"
    elif total is not None:
        if money.close(lines_total, total) or (
            tax is not None and money.close(lines_total, total - tax)
        ):
            return []
        actual, target = total, f"the total is {money(total)}"
        if tax is not None:
            target += f" ({money(total - tax)} before tax)"
    else:
        return []
    message = (
        f"The line items add up to {money(lines_total)}, but {target} "
        f"(difference {money(abs(actual - lines_total))})."
    )
    return [
        _issue(
            "line_items",
            IssueCode.LINE_ITEMS_SUM_MISMATCH,
            Severity.WARNING,
            message,
            expected=lines_total,
            actual=actual,
        )
    ]


# --- helpers ------------------------------------------------------------------------------


class _MoneyFormat:
    """Tolerance and display for one document's currency (PRD D4)."""

    def __init__(self, currency: str | None) -> None:
        self.currency = currency
        self.places = minor_units(currency)
        self.tolerance = _unit(self.places)

    def close(self, a: Decimal, b: Decimal) -> bool:
        """Equal within one minor unit, compared exactly (no rounding)."""
        return abs(a - b) <= self.tolerance

    def __call__(self, value: Decimal, *, code: bool = True) -> str:
        """``1,234.50 MYR``: at least the minor units, more when the value has them."""
        exponent = value.normalize().as_tuple().exponent
        places = max(self.places, -exponent) if isinstance(exponent, int) else self.places
        text = f"{value:,.{places}f}"
        return f"{text} {self.currency}" if code and self.currency else text


def _issue(
    field: str,
    code: IssueCode,
    severity: Severity,
    message: str,
    *,
    expected: Decimal | None = None,
    actual: Decimal | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        field=field,
        code=code,
        severity=severity,
        message=message,
        expected=expected,
        actual=actual,
    )


def _roll_up(issues: list[ValidationIssue]) -> ValidationStatus:
    """PRD D2: any error → fail; else any warning → warn; else pass."""
    severities = {issue.severity for issue in issues}
    if Severity.ERROR in severities:
        return ValidationStatus.FAIL
    if Severity.WARNING in severities:
        return ValidationStatus.WARN
    return ValidationStatus.PASS


def _unit(places: int) -> Decimal:
    """One minor unit: 2 → 0.01, 0 → 1, 3 → 0.001."""
    return Decimal(1).scaleb(-places)


def _plain(value: Decimal) -> str:
    """A quantity as printed, without trailing zeros or exponent (``2``, ``1.5``)."""
    return f"{value.normalize():f}"


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February in a non-leap year
        return day.replace(year=day.year - years, day=28)
