import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LlmCall(Base):
    """One LLM call (PRD 0007 D3): labels, counts and timings only, never message text."""

    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint("kind IN ('chat', 'embedding')", name="kind_valid"),
        CheckConstraint("status IN ('ok', 'error')", name="status_valid"),
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_non_negative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_non_negative"),
        CheckConstraint("cost_usd >= 0", name="cost_usd_non_negative"),
        CheckConstraint("latency_ms >= 0", name="latency_ms_non_negative"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        Index("ix_llm_calls_document_id_started_at", "document_id", "started_at"),
        Index("ix_llm_calls_run_id", "run_id"),
        Index("ix_llm_calls_started_at", "started_at"),
        Index("ix_llm_calls_query_run_id", "query_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # String references: this module never imports another module's ``model``.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True
    )
    step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent: Mapped[str | None] = mapped_column(String(30), nullable=True)
    purpose: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Estimated at write time from the dated price table; NULL for an unpriced model.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10))
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 1 = first try; 2+ = transient-error retries of the same call (feature 0008).
    attempt: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Set for the Query Agent's calls (feature 0010).
    query_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("query_runs.id", ondelete="CASCADE"), nullable=True
    )
