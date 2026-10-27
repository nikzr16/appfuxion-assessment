"""multi-agent: agent_runs.agents

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One entry per agent that started in a multi-agent run (PRD 0011 D3); [] otherwise.
    op.add_column(
        "agent_runs",
        sa.Column(
            "agents",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "agents")
