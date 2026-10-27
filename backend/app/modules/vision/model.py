import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DocumentLayout(Base):
    """One layout analysis of a document; append-only, the newest row is current (D9)."""

    __tablename__ = "document_layouts"
    __table_args__ = (
        CheckConstraint("source IN ('pdf_parser', 'vision')", name="source_valid"),
        CheckConstraint("page_count >= 1", name="page_count_positive"),
        Index("ix_document_layouts_document_created", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # String references: this module never imports ``documents.model`` or ``agent.model``.
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    # The agent run that made it; NULL outside a run.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20))
    layout_version: Mapped[str] = mapped_column(String(50))
    # The vision model for ``vision`` rows; NULL for ``pdf_parser``.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer)
    pages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
