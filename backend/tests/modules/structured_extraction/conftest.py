"""Fixtures shared by the structured extraction service and router tests."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.storage import LocalStorage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import UploadedFile
from app.modules.structured_extraction.schema import InvoiceData
from app.modules.text_extraction import crud as text_crud

MakeDocument = Callable[..., uuid.UUID]

SAMPLE_TEXT = """\
ACME Supplies Sdn Bhd
SST No: W10-1808-32000123
INVOICE INV-2025-001
Date: 4 March 2025
Item | Qty | Unit price | Amount
Widget | 2 | 10.00 | 20.00
Gadget | 1 | 103.45 | 103.45
Total RM 123.45"""


@pytest.fixture
def make_document(db_session: Session, storage: LocalStorage) -> MakeDocument:
    """A real document row (+ stored file); with ``raw_text`` its text row is saved too.

    The text row goes through ``text_extraction.crud`` directly: a test-only shortcut so any
    text (e.g. 70,000 characters) can be set up without building a PDF.
    """

    def make(raw_text: str | None = SAMPLE_TEXT) -> uuid.UUID:
        upload = UploadedFile(
            filename="invoice.pdf", content_type="application/pdf", data=b"%PDF-1.4 test"
        )
        document_id = documents_service.create_document(db_session, storage, upload).document_id
        if raw_text is not None:
            text_crud.upsert(
                db_session,
                values={
                    "document_id": document_id,
                    "raw_text": raw_text,
                    "method": "pdf_parser",
                    "page_count": 1,
                },
                overwrite=False,
            )
            db_session.commit()
        return document_id

    return make


def invoice(**overrides: Any) -> InvoiceData:
    """A complete, valid structured reply for ``SAMPLE_TEXT``."""
    data: dict[str, Any] = {
        "document_type": "invoice",
        "vendor": "ACME Supplies Sdn Bhd",
        "vendor_address": None,
        "vendor_tax_id": "W10-1808-32000123",
        "customer_name": None,
        "customer_address": None,
        "invoice_number": "INV-2025-001",
        "invoice_date": "2025-03-04",
        "due_date": None,
        "payment_terms": None,
        "currency": "MYR",
        "subtotal": None,
        "tax": None,
        "total_amount": "123.45",
        "line_items": [
            {"description": "Widget", "quantity": "2", "unit_price": "10.00", "amount": "20.00"},
            {"description": "Gadget", "quantity": "1", "unit_price": "103.45", "amount": "103.45"},
        ],
    }
    data.update(overrides)
    return InvoiceData.model_validate(data)
