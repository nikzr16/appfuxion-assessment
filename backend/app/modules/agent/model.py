import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.agent.schema import RunStatus


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("mode IN ('single', 'multi')", name="mode_valid"),
        CheckConstraint("trigger IN ('upload', 'reprocess')", name="trigger_valid"),
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_non_negative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_non_negative"),
        CheckConstraint("overall_confidence BETWEEN 0 AND 1", name="overall_confidence_range"),
        Index("ix_agent_runs_document_id_started_at", "document_id", text("started_at DESC")),
        # At most one running run per document (PRD 0005 D12).
        Index(
            "uq_agent_runs_document_running",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # A string reference: this module never imports ``documents.model``.
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    mode: Mapped[str] = mapped_column(String(20))
    trigger: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.RUNNING.value)
    # ``ToolStep`` dicts in JSON mode; never raw document text.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # ``AgentPart`` dicts in JSON mode: one per agent that started (multi mode, 0011).
    agents: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # ``AgentResult`` in JSON mode once the run has completed.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_prompt_version: Mapped[str] = mapped_column(String(50))
    summary_prompt_version: Mapped[str] = mapped_column(String(50))
    # Agent-loop and summary calls of this run (extraction tokens stay on their own rows).
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Copies of the result's confidence for metrics queries (0008); NULL before / if unscored.
    overall_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    needs_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QueryConversation(Base):
    """One Ask AI chat (PRD 0010 D8): its turns are the memory of the Query Agent."""

    __tablename__ = "query_conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QueryRun(Base):
    """One question in a conversation and the Query Agent's answer (PRD 0010 D9)."""

    __tablename__ = "query_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
        CheckConstraint("turn >= 1", name="turn_positive"),
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_non_negative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_non_negative"),
        CheckConstraint("embedding_tokens >= 0", name="embedding_tokens_non_negative"),
        UniqueConstraint("conversation_id", "turn", name="uq_query_runs_conversation_turn"),
        Index("ix_query_runs_started_at", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("query_conversations.id", ondelete="CASCADE")
    )
    turn: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    # The document the user was looking at when asking (context only).
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.RUNNING.value)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answerable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    numbers_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(50))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
