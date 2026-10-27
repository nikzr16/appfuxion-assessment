"""guardrails: grounding, confidence and retry attempt columns

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Schema only: rows from before 0008 keep NULL grounding / confidence (PRD D11).
    op.add_column(
        "extractions",
        sa.Column("grounding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("overall_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
    )
    op.add_column("agent_runs", sa.Column("needs_review", sa.Boolean(), nullable=True))
    op.create_check_constraint(
        op.f("ck_agent_runs_overall_confidence_range"),
        "agent_runs",
        "overall_confidence BETWEEN 0 AND 1",
    )
    op.add_column(
        "llm_calls", sa.Column("attempt", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_check_constraint(op.f("ck_llm_calls_attempt_positive"), "llm_calls", "attempt >= 1")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_llm_calls_attempt_positive"), "llm_calls", type_="check")
    op.drop_column("llm_calls", "attempt")
    op.drop_constraint(op.f("ck_agent_runs_overall_confidence_range"), "agent_runs", type_="check")
    op.drop_column("agent_runs", "needs_review")
    op.drop_column("agent_runs", "overall_confidence")
    op.drop_column("extractions", "grounding")
