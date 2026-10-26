from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.core.errors import AppError


class Severity(StrEnum):
    """How bad one issue is. ``info`` never changes the report status."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationStatus(StrEnum):
    """Roll-up of the issues: any error → fail; else any warning → warn; else pass."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class IssueCode(StrEnum):
    """Stable issue catalogue (PRD 0004 D10). Add codes freely; never rename one."""

    MISSING_FIELD = "missing_field"
    NOT_FINANCIAL_DOCUMENT = "not_financial_document"
    INVALID_CURRENCY = "invalid_currency"
    SUBTOTAL_TAX_MISMATCH = "subtotal_tax_mismatch"
    TAX_INCLUDED = "tax_included"
    LINE_ITEMS_SUM_MISMATCH = "line_items_sum_mismatch"
    LINE_ITEMS_INCOMPLETE = "line_items_incomplete"
    LINE_AMOUNT_MISMATCH = "line_amount_mismatch"
    NEGATIVE_AMOUNT = "negative_amount"
    DUE_BEFORE_INVOICE = "due_before_invoice"
    DATE_IN_FUTURE = "date_in_future"
    DATE_TOO_OLD = "date_too_old"


class ValidationIssue(BaseModel):
    """One finding. ``field`` is a JSON path into ``InvoiceData`` (``line_items[2].amount``).

    ``expected`` (computed by code) and ``actual`` (as printed) are exact values, set only on
    the numeric issues; the message already contains them, formatted for people.
    """

    model_config = ConfigDict(frozen=True)

    field: str
    code: IssueCode
    severity: Severity
    message: str
    expected: Decimal | None = None
    actual: Decimal | None = None


class ValidationReport(BaseModel):
    """Result of ``validate_invoice``; ``model_dump(mode="json")`` gives decimal strings."""

    model_config = ConfigDict(frozen=True)

    status: ValidationStatus
    issues: list[ValidationIssue]


class ConversionResult(BaseModel):
    """Result of ``convert_currency``: 1 ``from_currency`` = ``rate`` ``to_currency``.

    ``converted_amount`` is computed with the exact cross rate and rounded half-up to the
    target's minor units; ``rate`` is that cross rate shown to 10 significant digits.
    """

    model_config = ConfigDict(frozen=True)

    original_amount: Decimal
    from_currency: str
    to_currency: str
    rate: Decimal
    converted_amount: Decimal
    rate_date: date
    source: str


class CurrencyConversionError(AppError):
    """A conversion that cannot be done: ``unsupported_currency`` or ``invalid_amount``."""

    status_code = 422
    code = "unsupported_currency"
