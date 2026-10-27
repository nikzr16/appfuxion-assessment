import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Row, func, literal_column, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.modules.vision.model import DocumentLayout


def insert(db: Session, **values: Any) -> DocumentLayout:
    """Add one analysis row and flush; the caller commits. Rows are never updated."""
    row = DocumentLayout(**values)
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def list_by_document(db: Session, document_id: uuid.UUID) -> Sequence[DocumentLayout]:
    """Every analysis of the document, newest first."""
    return (
        db.execute(
            select(DocumentLayout)
            .where(DocumentLayout.document_id == document_id)
            .order_by(DocumentLayout.created_at.desc(), DocumentLayout.id)
        )
        .scalars()
        .all()
    )


def latest_by_document(
    db: Session, document_id: uuid.UUID, *, source: str | None = None
) -> DocumentLayout | None:
    query = select(DocumentLayout).where(DocumentLayout.document_id == document_id)
    if source is not None:
        query = query.where(DocumentLayout.source == source)
    return db.execute(query.order_by(DocumentLayout.created_at.desc()).limit(1)).scalars().first()


_LINE_ITEM_TABLE = literal_column("""'$[*] ? (@.kind == "line_items")'::jsonpath""")


def stats(db: Session, *, since: datetime | None = None) -> Row[Any]:
    """One row over the newest analysis per document made since ``since``: layouts,
    documents_with_line_item_table, tables_found."""
    newest = (
        select(DocumentLayout.tables)
        .ext(distinct_on(DocumentLayout.document_id))
        .order_by(DocumentLayout.document_id, DocumentLayout.created_at.desc())
    )
    if since is not None:
        newest = newest.where(DocumentLayout.created_at >= since)
    latest = newest.subquery()
    return db.execute(
        select(
            func.count().label("layouts"),
            func.count()
            .filter(func.jsonb_path_exists(latest.c.tables, _LINE_ITEM_TABLE))
            .label("documents_with_line_item_table"),
            func.coalesce(func.sum(func.jsonb_array_length(latest.c.tables)), 0).label(
                "tables_found"
            ),
        ).select_from(latest)
    ).one()
