import uuid
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, false, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.retrieval.model import InvoiceEmbedding as Row


@dataclass(frozen=True)
class Filters:
    """SQL filters over the index; ``None`` means "no filter"."""

    vendor_name_key: str | None = None
    vendor_tax_key: str | None = None
    vendor: bool = False  # filter by the vendor keys above (PRD D4 rule)
    invoice_number_key: str | None = None
    invoice_number_prefix: bool = False
    date_from: date | None = None
    date_to: date | None = None
    currency: str | None = None
    min_total_base: Decimal | None = None
    max_total_base: Decimal | None = None
    document_type: str | None = None
    uploaded_before: datetime | None = None
    exclude_document_id: uuid.UUID | None = None


def vendor_condition(name_key: str | None, tax_key: str | None) -> ColumnElement[bool]:
    """Same tax ID, or same normalised name unless both tax IDs are set and differ."""
    conditions: list[ColumnElement[bool]] = []
    if tax_key:
        conditions.append(Row.vendor_tax_key == tax_key)
    if name_key:
        by_name = Row.vendor_name_key == name_key
        if tax_key:
            by_name = and_(
                by_name, or_(Row.vendor_tax_key.is_(None), Row.vendor_tax_key == tax_key)
            )
        conditions.append(by_name)
    return or_(*conditions) if conditions else false()


def _where(filters: Filters) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = []
    if filters.vendor:
        where.append(vendor_condition(filters.vendor_name_key, filters.vendor_tax_key))
    if filters.invoice_number_key:
        if filters.invoice_number_prefix:
            where.append(Row.invoice_number_key.startswith(filters.invoice_number_key))
        else:
            where.append(Row.invoice_number_key == filters.invoice_number_key)
    if filters.date_from:
        where.append(Row.invoice_date >= filters.date_from)
    if filters.date_to:
        where.append(Row.invoice_date <= filters.date_to)
    if filters.currency:
        where.append(Row.currency == filters.currency)
    if filters.min_total_base is not None:
        where.append(Row.total_base >= filters.min_total_base)
    if filters.max_total_base is not None:
        where.append(Row.total_base <= filters.max_total_base)
    if filters.document_type:
        where.append(Row.document_type == filters.document_type)
    if filters.uploaded_before is not None:
        where.append(Row.uploaded_at < filters.uploaded_before)
    if filters.exclude_document_id is not None:
        where.append(Row.document_id != filters.exclude_document_id)
    return where or [true()]


_NEWEST = (Row.invoice_date.desc().nulls_last(), Row.uploaded_at.desc(), Row.document_id)


def get_by_document(db: Session, document_id: uuid.UUID) -> Row | None:
    return db.execute(select(Row).where(Row.document_id == document_id)).scalar_one_or_none()


def upsert(db: Session, values: dict[str, Any]) -> Row:
    """Insert or replace the document's row (one per document); flushes, never commits."""
    update = {k: v for k, v in values.items() if k not in ("id", "document_id")}
    update["updated_at"] = func.now()
    statement = (
        insert(Row)
        .values(id=uuid.uuid4(), **values)
        .on_conflict_do_update(index_elements=[Row.document_id], set_=update)
    )
    db.execute(statement)
    db.flush()
    row = get_by_document(db, values["document_id"])
    assert row is not None
    db.refresh(row)
    return row


def set_embedding(
    db: Session,
    document_id: uuid.UUID,
    *,
    vector: Sequence[float],
    model: str | None,
    card_hash: str,
) -> None:
    db.execute(
        update(Row)
        .where(Row.document_id == document_id)
        .values(embedding=list(vector), embedding_model=model, card_hash=card_hash)
    )
    db.flush()


def delete_by_document(db: Session, document_id: uuid.UUID) -> None:
    db.execute(delete(Row).where(Row.document_id == document_id))
    db.flush()


def find(db: Session, filters: Filters, *, limit: int | None = None) -> Sequence[Row]:
    """Matching rows, newest invoice date first."""
    statement = select(Row).where(*_where(filters)).order_by(*_NEWEST)
    if limit is not None:
        statement = statement.limit(limit)
    return db.execute(statement).scalars().all()


def count(db: Session, filters: Filters) -> int:
    return db.execute(select(func.count()).select_from(Row).where(*_where(filters))).scalar_one()


def nearest(
    db: Session, vector: Sequence[float], filters: Filters, *, k: int, max_distance: float
) -> list[tuple[Row, float]]:
    """Rows with a vector, closest first (cosine distance), within ``max_distance``."""
    distance = Row.embedding.cosine_distance(list(vector)).label("distance")
    statement = (
        select(Row, distance)
        .where(Row.embedding.is_not(None), distance <= max_distance, *_where(filters))
        .order_by(distance, Row.document_id)
        .limit(k)
    )
    return [(row, float(dist)) for row, dist in db.execute(statement).all()]


def identifier_matches(db: Session, key: str, raw: str, *, limit: int) -> Sequence[Row]:
    """Rows whose invoice number, filename or document ID equals / starts with an identifier."""
    conditions: list[ColumnElement[bool]] = [
        Row.invoice_number_key.startswith(key),
        func.lower(Row.filename).startswith(raw.lower()),
    ]
    with suppress(ValueError):
        conditions.append(Row.document_id == uuid.UUID(raw))
    statement = select(Row).where(or_(*conditions)).order_by(*_NEWEST).limit(limit)
    return db.execute(statement).scalars().all()


def vendor_names_like(db: Session, text: str, *, limit: int) -> list[str]:
    """Distinct vendor names containing ``text`` (case-insensitive), most invoices first."""
    statement = (
        select(Row.vendor)
        .where(Row.vendor.is_not(None), Row.vendor.ilike(f"%{text}%"))
        .group_by(Row.vendor)
        .order_by(func.count().desc(), Row.vendor)
        .limit(limit)
    )
    return [name for name in db.execute(statement).scalars().all() if name]


def top_vendors(db: Session, *, limit: int) -> list[tuple[str, int]]:
    """Vendors with the most indexed invoices (by normalised key, newest display name)."""
    statement = (
        select(func.max(Row.vendor), func.count())
        .where(Row.vendor_name_key.is_not(None))
        .group_by(Row.vendor_name_key)
        .order_by(func.count().desc(), func.max(Row.vendor))
        .limit(limit)
    )
    return [(name, total) for name, total in db.execute(statement).all() if name]


def missing_embeddings(db: Session) -> Sequence[Row]:
    return (
        db.execute(select(Row).where(Row.embedding.is_(None)).order_by(Row.uploaded_at))
        .scalars()
        .all()
    )


def indexed_document_ids(db: Session) -> set[uuid.UUID]:
    return set(db.execute(select(Row.document_id)).scalars().all())


def stats(db: Session) -> tuple[int, int]:
    """(rows, rows with a vector)."""
    total, embedded = db.execute(select(func.count(), func.count(Row.embedding))).one()
    return int(total), int(embedded)
