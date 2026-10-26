from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.modules.structured_extraction.schema import DocumentType, InvoiceData

NULLABLE_NUMBER = {"anyOf": [{"type": "number"}, {"type": "null"}]}
NULLABLE_DATE = {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]}


def _strict_schema() -> dict[str, Any]:
    """The JSON schema the OpenAI SDK sends for ``response_format=InvoiceData``."""
    return to_strict_json_schema(InvoiceData)


def _without_descriptions(node: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in node.items() if k not in ("description", "title")}


def _invoice(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "document_type": "invoice",
        "vendor": "ACME Sdn Bhd",
        "vendor_address": None,
        "vendor_tax_id": None,
        "customer_name": None,
        "customer_address": None,
        "invoice_number": "INV-001",
        "invoice_date": "2025-03-04",
        "due_date": None,
        "payment_terms": None,
        "currency": "MYR",
        "subtotal": None,
        "tax": None,
        "total_amount": 123.45,
        "line_items": [],
    }
    data.update(overrides)
    return data


# -- Strict structured-output schema --------------------------------------------------


def test_every_property_is_required_and_no_extra_keys_are_allowed() -> None:
    schema = _strict_schema()
    line_item = schema["$defs"]["LineItem"]

    for node in (schema, line_item):
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
    assert set(line_item["properties"]) == {"description", "quantity", "unit_price", "amount"}
    assert len(schema["properties"]) == 15


def test_money_and_quantities_are_plain_json_numbers() -> None:
    schema = _strict_schema()
    line_item = schema["$defs"]["LineItem"]["properties"]

    for name in ("subtotal", "tax", "total_amount"):
        assert _without_descriptions(schema["properties"][name]) == NULLABLE_NUMBER
    for name in ("quantity", "unit_price", "amount"):
        assert _without_descriptions(line_item[name]) == NULLABLE_NUMBER


def test_dates_are_iso_date_strings_and_document_type_is_an_enum() -> None:
    properties = _strict_schema()["properties"]

    assert _without_descriptions(properties["invoice_date"]) == NULLABLE_DATE
    assert _without_descriptions(properties["due_date"]) == NULLABLE_DATE
    assert properties["document_type"]["enum"] == ["invoice", "receipt", "unknown"]
    assert properties["line_items"]["type"] == "array"


# -- Validation ------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["0.1", "1234567.89", "12.3456", "-5.00"])
def test_money_round_trips_exactly(raw: str) -> None:
    parsed = InvoiceData.model_validate_json(
        f'{{"document_type": "invoice", "vendor": null, "vendor_address": null, '
        f'"vendor_tax_id": null, "customer_name": null, "customer_address": null, '
        f'"invoice_number": null, "invoice_date": null, "due_date": null, '
        f'"payment_terms": null, "currency": null, "subtotal": null, "tax": null, '
        f'"total_amount": {raw}, "line_items": []}}'
    )
    assert parsed.total_amount == Decimal(raw)

    dumped = parsed.model_dump(mode="json")
    # A decimal string, never a float; the value is exact (trailing zeros may be dropped).
    assert isinstance(dumped["total_amount"], str)
    assert Decimal(dumped["total_amount"]) == Decimal(raw)
    assert InvoiceData.model_validate(dumped).total_amount == Decimal(raw)


def test_values_are_typed() -> None:
    parsed = InvoiceData.model_validate(_invoice())

    assert parsed.document_type is DocumentType.INVOICE
    assert parsed.invoice_date == date(2025, 3, 4)
    assert isinstance(parsed.total_amount, Decimal)


def test_currency_is_upper_cased() -> None:
    assert InvoiceData.model_validate(_invoice(currency=" myr ")).currency == "MYR"


@pytest.mark.parametrize("currency", ["RM", "US$", "MYRR", "M1R"])
def test_currency_must_be_a_three_letter_code(currency: str) -> None:
    with pytest.raises(ValidationError) as caught:
        InvoiceData.model_validate(_invoice(currency=currency))
    assert caught.value.errors()[0]["loc"] == ("currency",)


def test_blank_text_becomes_null() -> None:
    parsed = InvoiceData.model_validate(_invoice(vendor="   ", currency=""))

    assert parsed.vendor is None
    assert parsed.currency is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"invoice_date": "2025-02-30"},
        {"extra_field": "x"},
        {"total_amount": "NaN"},
        {"document_type": "statement"},
    ],
)
def test_malformed_values_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        InvoiceData.model_validate(_invoice(**overrides))
