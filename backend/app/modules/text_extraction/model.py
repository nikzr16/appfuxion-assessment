import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.text_extraction.schema import ExtractionMethod


class DocumentText(Base):
    __tablename__ = "document_texts"
    __table_args__ = (
        CheckConstraint("method IN ('pdf_parser', 'vision')", name="method_valid"),
        CheckConstraint("page_count >= 1", name="page_count_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # A string reference: this module never imports ``documents.model``.
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    raw_text: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(20), default=ExtractionMethod.PDF_PARSER.value)
    page_count: Mapped[int] = mapped_column(Integer)
    # The vision model and prompt version; both are null for ``pdf_parser`` rows.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
