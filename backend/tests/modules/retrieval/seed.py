"""Seeded invoices for the retrieval tests: real documents plus index rows with known
fields, upload times and (optionally) designed vectors."""

import math
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.storage import LocalStorage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import UploadedFile
from app.modules.retrieval import crud, rules
from app.modules.retrieval import service as retrieval_service
from app.modules.retrieval.schema import EMBEDDING_DIMENSIONS, IndexRequest, PreparedEmbedding
from app.modules.structured_extraction.schema import InvoiceData
from tests.modules.agent.conftest import invoice_pdf

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


def unit(*weights: tuple[int, float]) -> list[float]:
    """A unit vector with the given (dimension, weight) components."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for dimension, weight in weights:
        vector[dimension] = weight
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def invoice_data(**overrides: Any) -> InvoiceData:
    data: dict[str, Any] = {
        "document_type": "invoice",
        "vendor": "ABC Supplies Sdn Bhd",
        "vendor_address": None,
        "vendor_tax_id": None,
        "customer_name": None,
        "customer_address": None,
        "invoice_number": "INV-1001",
        "invoice_date": "2026-01-15",
        "due_date": None,
        "payment_terms": None,
        "currency": "MYR",
        "subtotal": None,
        "tax": None,
        "total_amount": "1000.00",
        "line_items": [
            {"description": "Printer toner", "quantity": None, "unit_price": None, "amount": None}
        ],
    }
    data.update(overrides)
    return InvoiceData.model_validate(data)


def make_document(
    db: Session,
    storage: LocalStorage,
    *,
    uploaded_at: datetime,
    filename: str = "invoice.pdf",
    completed: bool = True,
) -> uuid.UUID:
    upload = UploadedFile(filename=filename, content_type="application/pdf", data=invoice_pdf())
    document_id = documents_service.create_document(db, storage, upload).document_id
    if completed:
        documents_service.mark_completed(db, document_id)
    db.execute(
        text("UPDATE documents SET created_at = :at WHERE id = :id"),
        {"at": uploaded_at, "id": document_id},
    )
    db.commit()
    return document_id


def seed_invoice(
    db: Session,
    storage: LocalStorage,
    *,
    index: int = 0,
    vector: Sequence[float] | None = None,
    needs_review: bool | None = False,
    filename: str | None = None,
    **fields: Any,
) -> uuid.UUID:
    """One completed, indexed invoice uploaded ``index`` days after ``T0``."""
    data = invoice_data(**fields)
    document_id = make_document(
        db,
        storage,
        uploaded_at=T0 + timedelta(days=index),
        filename=filename or f"invoice-{index}.pdf",
    )
    card = rules.build_card(data)
    retrieval_service.index_document(
        db,
        IndexRequest(
            document_id=document_id,
            run_id=None,
            data=data,
            needs_review=needs_review,
            embedding=PreparedEmbedding(
                card=card,
                card_hash=rules.card_hash(card, "text-embedding-3-small"),
                vector=list(vector) if vector is not None else None,
                model="text-embedding-3-small" if vector is not None else None,
                reused=False,
            ),
        ),
    )
    db.commit()
    return document_id


def set_vector(db: Session, document_id: uuid.UUID, vector: Sequence[float]) -> None:
    crud.set_embedding(db, document_id, vector=vector, model="fake", card_hash="x" * 64)
    db.commit()
