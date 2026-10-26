"""The currency data and the two small lookups built on it."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.validation.currencies import (
    EXCLUDED_CODES,
    MINOR_UNITS,
    RATES_AS_OF,
    RATES_PER_USD,
)
from app.modules.validation.service import is_iso_currency, minor_units

# The 25 currencies 0003's prompt can produce from a symbol (PRD 0004 D11).
PRD_RATE_CODES = {
    *("MYR", "SGD", "IDR", "THB", "PHP", "VND", "BND", "KHR", "LAK", "MMK", "USD"),
    *("EUR", "GBP", "INR", "KRW", "HKD", "TWD", "AUD", "NZD", "CAD", "CNY", "JPY"),
    *("CHF", "AED", "SAR"),
}


def test_rate_table_covers_the_prd_currencies() -> None:
    assert set(RATES_PER_USD) == PRD_RATE_CODES
    assert RATES_PER_USD["USD"] == Decimal(1)
    assert isinstance(RATES_AS_OF, date)


@pytest.mark.parametrize("code", sorted(PRD_RATE_CODES))
def test_every_rate_is_a_positive_decimal_for_a_real_currency(code: str) -> None:
    rate = RATES_PER_USD[code]
    assert isinstance(rate, Decimal) and rate.is_finite() and rate > 0
    assert is_iso_currency(code)


@pytest.mark.parametrize(
    ("code", "valid"),
    [
        ("MYR", True),
        ("myr", True),
        ("XAF", True),
        ("XCD", True),
        ("CLF", True),
        ("ABC", False),
        ("RM", False),
        ("MYRR", False),
        ("", False),
        *[(code, False) for code in sorted(EXCLUDED_CODES)],
    ],
)
def test_is_iso_currency(code: str, valid: bool) -> None:
    assert is_iso_currency(code) is valid


def test_minor_unit_exceptions_are_real_currencies() -> None:
    assert all(is_iso_currency(code) for code in MINOR_UNITS)


@pytest.mark.parametrize(
    ("code", "places"),
    [("JPY", 0), ("VND", 0), ("MYR", 2), ("USD", 2), ("KWD", 3), ("CLF", 4), ("jpy", 0), (None, 2)],
)
def test_minor_units(code: str | None, places: int) -> None:
    assert minor_units(code) == places
