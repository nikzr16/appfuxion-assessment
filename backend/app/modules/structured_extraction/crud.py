import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
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
