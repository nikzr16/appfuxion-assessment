import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.documents.model import Document
from app.modules.documents.schema import DocumentStatus


def create(
    db: Session,
    *,
    document_id: uuid.UUID,
    filename: str,
    version: int,
    storage_path: str,
    content_type: str,
    size_bytes: int,
) -> Document:
    """Insert a ``processing`` document and flush; the caller commits."""
    document = Document(
        id=document_id,
        filename=filename,
        version=version,
        storage_path=storage_path,
        content_type=content_type,
        size_bytes=size_bytes,
        status=DocumentStatus.PROCESSING.value,
    )
    db.add(document)
    db.flush()
    return document


def get(db: Session, document_id: uuid.UUID) -> Document | None:
    return db.get(Document, document_id)


def max_version(db: Session, filename: str) -> int:
    """Highest version stored for exactly this filename (case-sensitive); 0 if none."""
    result = db.execute(
        select(func.max(Document.version)).where(Document.filename == filename)
    ).scalar()
    return result or 0


def list_(
    db: Session, *, limit: int, offset: int, status: DocumentStatus | None = None
) -> tuple[Sequence[Document], int]:
    """Newest first (``created_at DESC, id DESC``) plus the total matching row count."""
    count_query = select(func.count()).select_from(Document)
    rows_query = select(Document)
    if status is not None:
        count_query = count_query.where(Document.status == status.value)
        rows_query = rows_query.where(Document.status == status.value)
    total = db.execute(count_query).scalar_one()
    rows = (
        db.execute(
            rows_query.order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return rows, total


def update_status(
    db: Session, document_id: uuid.UUID, status: DocumentStatus, error: str | None = None
) -> Document | None:
    """Set status (and error) and flush; ``None`` if the document does not exist.

    The caller commits, so a pipeline can complete a document in the same transaction as
    its results.
    """
    document = db.get(Document, document_id)
    if document is None:
        return None
    document.status = status.value
    document.error = error
    db.flush()
    return document


def restart_processing(db: Session, document_id: uuid.UUID) -> bool:
    """Set a document that is not ``processing`` back to ``processing`` (clearing its error)
    and flush; ``False`` when it is unknown or already processing. The caller commits.

    One conditional ``UPDATE``, so two concurrent reprocess requests cannot both win.
    """
    result = db.execute(
        update(Document)
        .where(Document.id == document_id, Document.status != DocumentStatus.PROCESSING.value)
        .values(status=DocumentStatus.PROCESSING.value, error=None, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    db.flush()
    return result.rowcount == 1


def count_by_status(db: Session, *, since: datetime | None = None) -> dict[str, int]:
    """Documents per status, optionally only those created since ``since``."""
    query = select(Document.status, func.count()).group_by(Document.status)
    if since is not None:
        query = query.where(Document.created_at >= since)
    return dict(db.execute(query).all())
