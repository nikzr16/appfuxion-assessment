"""convert_currency: expected values are computed from the rate table, so a refresh of the
snapshot does not break these tests."""

from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.modules.validation.currencies import RATES_AS_OF, RATES_PER_USD, RATES_SOURCE
from app.modules.validation.schema import CurrencyConversionError
from app.modules.validation.service import convert_currency

CENT = Decimal("0.01")


@pytest.mark.parametrize(
    ("amount", "source", "target", "places"),
    [
        ("100", "USD", "MYR", 2),
        ("123.45", "MYR", "SGD", 2),
        ("1000", "MYR", "JPY", 0),
        ("250000", "IDR", "EUR", 2),
        ("-50.00", "MYR", "USD", 2),  # credit notes convert too
    ],
)
def test_converts_through_usd(amount: str, source: str, target: str, places: int) -> None:
    result = convert_currency(Decimal(amount), source, target)
    exact = RATES_PER_USD[target] / RATES_PER_USD[source]
    expected = (Decimal(amount) * exact).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    assert result.converted_amount == expected
    assert result.converted_amount.as_tuple().exponent == -places
    assert (result.from_currency, result.to_currency) == (source, target)
    assert result.original_amount == Decimal(amount)
    assert (result.rate_date, result.source) == (RATES_AS_OF, RATES_SOURCE)


def test_usd_to_myr_uses_the_published_rate() -> None:
    result = convert_currency(Decimal("1"), "USD", "MYR")
    assert result.rate == RATES_PER_USD["MYR"]


def test_rate_is_shown_to_ten_significant_digits() -> None:
    result = convert_currency(Decimal("1"), "MYR", "JPY")
    assert len(result.rate.as_tuple().digits) <= 10
    assert abs(result.rate - RATES_PER_USD["JPY"] / RATES_PER_USD["MYR"]) < Decimal("1E-7")


def test_rounds_half_up() -> None:
    # 0.005 USD -> 0.01 USD (half-even would give 0.00)
    assert convert_currency(Decimal("0.005"), "USD", "USD").converted_amount == CENT
    assert convert_currency(Decimal("0.015"), "USD", "USD").converted_amount == Decimal("0.02")


def test_same_currency_has_rate_one() -> None:
    result = convert_currency(Decimal("12.3456"), "MYR", "MYR")
    assert result.rate == Decimal(1)
    assert result.converted_amount == Decimal("12.35")


def test_codes_are_normalised() -> None:
    result = convert_currency(Decimal("10"), " myr ", "usd")
    assert (result.from_currency, result.to_currency) == ("MYR", "USD")


def test_result_serialises_to_strings() -> None:
    body = convert_currency(Decimal("100"), "USD", "MYR").model_dump(mode="json")
    assert body["converted_amount"] == str(
        (Decimal(100) * RATES_PER_USD["MYR"]).quantize(CENT, ROUND_HALF_UP)
    )
    assert body["rate_date"] == RATES_AS_OF.isoformat()
    assert isinstance(body["rate"], str)


@pytest.mark.parametrize(("source", "target"), [("ABC", "MYR"), ("MYR", "KWD"), ("", "USD")])
def test_unsupported_currency(source: str, target: str) -> None:
    with pytest.raises(CurrencyConversionError) as caught:
        convert_currency(Decimal("1"), source, target)
    assert caught.value.code == "unsupported_currency"
    assert caught.value.status_code == 422
    assert "MYR" in caught.value.message  # lists what is supported


@pytest.mark.parametrize(
    "amount", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), 1.5, 10, "10"]
)
def test_invalid_amount(amount: object) -> None:
    with pytest.raises(CurrencyConversionError) as caught:
        convert_currency(amount, "USD", "MYR")  # type: ignore[arg-type]
    assert caught.value.code == "invalid_amount"


def test_amount_too_large_is_invalid() -> None:
    with pytest.raises(CurrencyConversionError) as caught:
        convert_currency(Decimal("1E+30"), "USD", "IDR")
    assert caught.value.code == "invalid_amount"
