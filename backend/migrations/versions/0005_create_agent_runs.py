"""create agent_runs

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("agent_prompt_version", sa.String(length=50), nullable=False),
        sa.Column("summary_prompt_version", sa.String(length=50), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode IN ('single', 'multi')", name=op.f("ck_agent_runs_mode_valid")),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=op.f("ck_agent_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "trigger IN ('upload', 'reprocess')", name=op.f("ck_agent_runs_trigger_valid")
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0",
            name=op.f("ck_agent_runs_completion_tokens_non_negative"),
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0", name=op.f("ck_agent_runs_prompt_tokens_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_agent_runs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index(
        "ix_agent_runs_document_id_started_at",
        "agent_runs",
        ["document_id", sa.literal_column("started_at DESC")],
        unique=False,
    )
    # At most one running run per document.
    op.create_index(
        "uq_agent_runs_document_running",
        "agent_runs",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_document_running", table_name="agent_runs")
    op.drop_index("ix_agent_runs_document_id_started_at", table_name="agent_runs")
    op.drop_table("agent_runs")
