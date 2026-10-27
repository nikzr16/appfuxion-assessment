import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema, field_validator

from app.modules.guardrails.schema import ExtractionGrounding

_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


def _blank_to_none(value: Any) -> Any:
    """Strip text; an empty string means the value is absent."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# Money and quantities are exact decimals in code. The model is shown a plain JSON number
# (Pydantic's default schema would also allow a string such as "RM 12.30").
Money = Annotated[Decimal, Field(allow_inf_nan=False), WithJsonSchema({"type": "number"})]
Text = Annotated[str | None, BeforeValidator(_blank_to_none)]


# Where ``line_items`` came from (feature 0009): copied by code from a table, or the model.
LineItemsSource = Literal["table", "model"]


class LineItemSourceStats(BaseModel):
    """Line items of extractions in a window, by where they came from (feature 0009)."""

    from_table: int
    from_model: int


class DocumentType(StrEnum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    UNKNOWN = "unknown"


class LineItem(BaseModel):
    """One printed item row. Every field is required but nullable (strict output)."""

    model_config = ConfigDict(extra="forbid")

    description: Text = Field(description="The item text as printed.")
    quantity: Money | None = Field(description="Quantity as printed; null if not shown.")
    unit_price: Money | None = Field(description="Price per unit as printed; null if not shown.")
    amount: Money | None = Field(description="Line total as printed; null if not shown.")


class InvoiceData(BaseModel):
    """Structured fields of one financial document.

    This is both the OpenAI strict structured-output schema (every field required and
    nullable, no defaults) and the typed DTO that 0004 validation consumes. A value that is
    not in the document is ``None``; nothing is computed or guessed.
    """

    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType = Field(
        description="invoice (requests payment), receipt (proof of payment) or unknown."
    )
    vendor: Text = Field(description="Seller / issuer name.")
    vendor_address: Text = Field(description="Seller address on one line.")
    vendor_tax_id: Text = Field(
        description="Seller tax or registration number as printed (SST, GST, VAT, TIN ...)."
    )
    customer_name: Text = Field(description="Bill-to / sold-to name.")
    customer_address: Text = Field(description="Bill-to / sold-to address on one line.")
    invoice_number: Text = Field(description="Invoice or receipt number as printed.")
    invoice_date: date | None = Field(description="Issue date, YYYY-MM-DD.")
    due_date: date | None = Field(description="Payment due date, YYYY-MM-DD.")
    payment_terms: Text = Field(description="Payment terms as printed, e.g. Net 30.")
    currency: Text = Field(description="ISO 4217 code, e.g. MYR; null if unclear.")
    subtotal: Money | None = Field(description="Subtotal before tax as printed.")
    tax: Money | None = Field(description="Total tax amount as printed.")
    total_amount: Money | None = Field(description="Grand total as printed.")
    line_items: list[LineItem] = Field(description="Printed item rows; [] when there are none.")

    @field_validator("currency")
    @classmethod
    def _iso_currency_shape(cls, value: str | None) -> str | None:
        """Shape only (three letters); whether the code exists is checked in 0004."""
        if value is None:
            return None
        code = value.upper()
        if not _CURRENCY_CODE.fullmatch(code):
            raise ValueError("must be a 3-letter ISO 4217 code such as MYR, or null")
        return code


class ExtractionRead(BaseModel):
    """Internal DTO: one ``extractions`` row, all columns."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    data: InvoiceData
    model: str
    prompt_version: str
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    grounding: ExtractionGrounding | None = None
    line_items_source: LineItemsSource | None = None
    created_at: datetime
    updated_at: datetime


class ExtractionResponse(BaseModel):
    """Body of ``GET /api/documents/{document_id}/extraction``."""

    document_id: uuid.UUID
    structured_data: InvoiceData
    model: str
    prompt_version: str
    attempts: int
    # The grounding report and attempt history (feature 0008); null before it ran.
    grounding: ExtractionGrounding | None = None
    # ``table`` when code copied the line items from the document's table (feature 0009).
    line_items_source: LineItemsSource | None = None


class GroundingStats(BaseModel):
    """Grounded extractions in a window (feature 0008 metrics)."""

    extractions: int
    values_checked: int
    values_grounded: int
    grounding_retry_extractions: int
