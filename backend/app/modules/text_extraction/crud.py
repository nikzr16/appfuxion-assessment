import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.text_extraction.model import DocumentText


def get_by_document(db: Session, document_id: uuid.UUID) -> DocumentText | None:
    return db.execute(
        select(DocumentText).where(DocumentText.document_id == document_id)
    ).scalar_one_or_none()


def upsert(db: Session, *, values: Mapping[str, Any], overwrite: bool) -> DocumentText:
    """Insert the document's text row; the caller commits.

    On a ``document_id`` conflict the existing row is replaced in place when ``overwrite``
    is set (same ``id``, ``updated_at`` bumped) and returned untouched otherwise, so two
    concurrent extractions end with one row.
    """
    statement = insert(DocumentText).values(**values)
    if overwrite:
        statement = statement.on_conflict_do_update(
            index_elements=[DocumentText.document_id],
            set_={
                "raw_text": statement.excluded.raw_text,
                "method": statement.excluded.method,
                "page_count": statement.excluded.page_count,
                "model": statement.excluded.model,
                "prompt_version": statement.excluded.prompt_version,
                "updated_at": func.now(),
            },
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=[DocumentText.document_id])
    row = db.execute(
        statement.returning(DocumentText), execution_options={"populate_existing": True}
    ).scalar_one_or_none()
    if row is None:  # DO NOTHING: a concurrent call won the race, return its row
        row = get_by_document(db, values["document_id"])
    assert row is not None
    return row
