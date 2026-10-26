import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.documents.schema import DocumentStatus


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("filename", "version", name="uq_documents_filename_version"),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="status_valid",
        ),
        Index("ix_documents_created_at", "created_at"),
    )

    # The API exposes this as ``document_id`` (see ``DocumentRead``).
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default=DocumentStatus.PROCESSING.value)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
