"""Builders shared by the validation tests (pure functions: no DB rows, no LLM)."""

from datetime import date
from typing import Any

from app.modules.structured_extraction.schema import InvoiceData

TODAY = date(2026, 10, 26)


def line(quantity: str | None, unit_price: str | None, amount: str | None) -> dict[str, Any]:
    return {
        "description": "Item",
        "quantity": quantity,
        "unit_price": unit_price,
        "amount": amount,
    }


def make_invoice(**overrides: Any) -> InvoiceData:
    """A complete, consistent MYR invoice; ``lines=[...]`` replaces the line items."""
    data: dict[str, Any] = {
        "document_type": "invoice",
        "vendor": "ACME Supplies Sdn Bhd",
        "vendor_address": None,
        "vendor_tax_id": None,
        "customer_name": None,
        "customer_address": None,
        "invoice_number": "INV-001",
        "invoice_date": "2026-10-01",
        "due_date": "2026-10-31",
        "payment_terms": None,
        "currency": "MYR",
        "subtotal": "100.00",
        "tax": "6.00",
        "total_amount": "106.00",
        "line_items": [line("2", "25.00", "50.00"), line("1", "50.00", "50.00")],
    }
    if "lines" in overrides:
        overrides["line_items"] = overrides.pop("lines")
    data.update(overrides)
    return InvoiceData.model_validate(data)
