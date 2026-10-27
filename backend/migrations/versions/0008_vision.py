"""vision: document_layouts table and extractions.line_items_source

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Schema only: documents from before 0009 have no layout until reprocessed (PRD D13).
    op.create_table(
        "document_layouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("layout_version", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("pages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tables", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("blocks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('pdf_parser', 'vision')", name=op.f("ck_document_layouts_source_valid")
        ),
        sa.CheckConstraint("page_count >= 1", name=op.f("ck_document_layouts_page_count_positive")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_layouts_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_document_layouts_run_id_agent_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_layouts")),
    )
    op.create_index(
        "ix_document_layouts_document_created",
        "document_layouts",
        ["document_id", "created_at"],
        unique=False,
    )
    op.add_column(
        "extractions", sa.Column("line_items_source", sa.String(length=10), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_extractions_line_items_source_valid"),
        "extractions",
        "line_items_source IN ('table', 'model')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_extractions_line_items_source_valid"), "extractions", type_="check")
    op.drop_column("extractions", "line_items_source")
    op.drop_index("ix_document_layouts_document_created", table_name="document_layouts")
    op.drop_table("document_layouts")
