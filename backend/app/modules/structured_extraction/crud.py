import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, Row, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.structured_extraction.model import Extraction


def get_by_document(db: Session, document_id: uuid.UUID) -> Extraction | None:
    return db.execute(
        select(Extraction).where(Extraction.document_id == document_id)
    ).scalar_one_or_none()


def upsert(db: Session, *, values: Mapping[str, Any], overwrite: bool) -> Extraction:
    """Insert the document's extraction row; the caller commits.

    On a ``document_id`` conflict the existing row is replaced in place when ``overwrite``
    is set (same ``id``, ``updated_at`` bumped) and returned untouched otherwise, so two
    concurrent extractions end with one row.
    """
    statement = insert(Extraction).values(**values)
    if overwrite:
        statement = statement.on_conflict_do_update(
            index_elements=[Extraction.document_id],
            set_={
                "data": statement.excluded.data,
                "model": statement.excluded.model,
                "prompt_version": statement.excluded.prompt_version,
                "attempts": statement.excluded.attempts,
                "prompt_tokens": statement.excluded.prompt_tokens,
                "completion_tokens": statement.excluded.completion_tokens,
                "line_items_source": statement.excluded.line_items_source,
                "grounding": None,  # a new extraction is never shown with an old report
                "updated_at": func.now(),
            },
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=[Extraction.document_id])
    row = db.execute(
        statement.returning(Extraction), execution_options={"populate_existing": True}
    ).scalar_one_or_none()
    if row is None:  # DO NOTHING: a concurrent call won the race, return its row
        row = get_by_document(db, values["document_id"])
    assert row is not None
    return row


def update_grounding(
    db: Session, document_id: uuid.UUID, *, values: Mapping[str, Any]
) -> Extraction:
    """Save a grounding result (and the kept data / counters); the caller commits."""
    statement = (
        update(Extraction)
        .where(Extraction.document_id == document_id)
        .values(**values, updated_at=func.now())
        .returning(Extraction)
    )
    row = db.execute(statement, execution_options={"populate_existing": True}).scalar_one()
    return row


def grounding_totals(db: Session, *, since: datetime | None = None) -> Row[Any]:
    """Grounded extractions, values checked / grounded, and how many needed a retry."""
    report = Extraction.grounding["report"]
    query = select(
        func.count(Extraction.id),
        func.coalesce(func.sum(report["checked"].astext.cast(Integer)), 0),
        func.coalesce(func.sum(report["grounded"].astext.cast(Integer)), 0),
        func.count(Extraction.id).filter(
            Extraction.grounding["grounding_retries"].astext.cast(Integer) > 0
        ),
    ).where(Extraction.grounding.is_not(None))
    if since is not None:
        query = query.where(Extraction.updated_at >= since)
    return db.execute(query).one()


def line_item_totals(db: Session, *, since: datetime | None = None) -> Row[Any]:
    """Line items (``from_table``, ``from_model``) of extractions updated since ``since``."""
    items = func.jsonb_array_length(Extraction.data["line_items"])

    def total(source: str) -> Any:
        return func.coalesce(func.sum(items).filter(Extraction.line_items_source == source), 0)

    query = select(total("table").label("from_table"), total("model").label("from_model"))
    if since is not None:
        query = query.where(Extraction.updated_at >= since)
    return db.execute(query).one()
