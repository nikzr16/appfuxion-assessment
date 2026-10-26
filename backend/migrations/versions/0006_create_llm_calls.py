"""create llm_calls

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=True),
        sa.Column("agent", sa.String(length=30), nullable=True),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('chat', 'embedding')", name=op.f("ck_llm_calls_kind_valid")),
        sa.CheckConstraint("status IN ('ok', 'error')", name=op.f("ck_llm_calls_status_valid")),
        sa.CheckConstraint(
            "completion_tokens >= 0", name=op.f("ck_llm_calls_completion_tokens_non_negative")
        ),
        sa.CheckConstraint("cost_usd >= 0", name=op.f("ck_llm_calls_cost_usd_non_negative")),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_llm_calls_latency_ms_non_negative")),
        sa.CheckConstraint(
            "prompt_tokens >= 0", name=op.f("ck_llm_calls_prompt_tokens_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_llm_calls_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_llm_calls_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index(
        "ix_llm_calls_document_id_started_at",
        "llm_calls",
        ["document_id", "started_at"],
        unique=False,
    )
    op.create_index("ix_llm_calls_run_id", "llm_calls", ["run_id"], unique=False)
    op.create_index("ix_llm_calls_started_at", "llm_calls", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_llm_calls_started_at", table_name="llm_calls")
    op.drop_index("ix_llm_calls_run_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_document_id_started_at", table_name="llm_calls")
    op.drop_table("llm_calls")
