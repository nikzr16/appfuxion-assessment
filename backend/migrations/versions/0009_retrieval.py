"""retrieval: invoice_embeddings, query_conversations, query_runs, llm_calls.query_run_id

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Schema only: earlier documents are indexed by the back-fill command (PRD 0010 D12).
    op.create_table(
        "invoice_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document_type", sa.String(length=20), nullable=False),
        sa.Column("vendor", sa.Text(), nullable=True),
        sa.Column("vendor_tax_id", sa.String(length=100), nullable=True),
        sa.Column("vendor_name_key", sa.String(length=255), nullable=True),
        sa.Column("vendor_tax_key", sa.String(length=100), nullable=True),
        sa.Column("invoice_number", sa.String(length=100), nullable=True),
        sa.Column("invoice_number_key", sa.String(length=100), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("total_base", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=True),
        sa.Column("card", sa.Text(), nullable=False),
        sa.Column("card_hash", sa.String(length=64), nullable=False),
        sa.Column("card_version", sa.String(length=50), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "document_type IN ('invoice', 'receipt')",
            name=op.f("ck_invoice_embeddings_document_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_invoice_embeddings_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_invoice_embeddings_run_id_agent_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_embeddings")),
        sa.UniqueConstraint("document_id", name=op.f("uq_invoice_embeddings_document_id")),
    )
    for column in ("vendor_name_key", "vendor_tax_key", "invoice_number_key", "invoice_date"):
        op.create_index(f"ix_invoice_embeddings_{column}", "invoice_embeddings", [column])
    op.create_index(
        "ix_invoice_embeddings_embedding_hnsw",
        "invoice_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "query_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_conversations")),
    )
    op.create_table(
        "query_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answerable", sa.Boolean(), nullable=True),
        sa.Column("numbers_verified", sa.Boolean(), nullable=True),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("embedding_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name=op.f("ck_query_runs_status_valid")
        ),
        sa.CheckConstraint("turn >= 1", name=op.f("ck_query_runs_turn_positive")),
        sa.CheckConstraint(
            "prompt_tokens >= 0", name=op.f("ck_query_runs_prompt_tokens_non_negative")
        ),
        sa.CheckConstraint(
            "completion_tokens >= 0", name=op.f("ck_query_runs_completion_tokens_non_negative")
        ),
        sa.CheckConstraint(
            "embedding_tokens >= 0", name=op.f("ck_query_runs_embedding_tokens_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["query_conversations.id"],
            name=op.f("fk_query_runs_conversation_id_query_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_query_runs_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_runs")),
        sa.UniqueConstraint("conversation_id", "turn", name="uq_query_runs_conversation_turn"),
    )
    op.create_index("ix_query_runs_started_at", "query_runs", ["started_at"])

    op.add_column("llm_calls", sa.Column("query_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_llm_calls_query_run_id_query_runs"),
        "llm_calls",
        "query_runs",
        ["query_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_llm_calls_query_run_id", "llm_calls", ["query_run_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_query_run_id", table_name="llm_calls")
    op.drop_constraint(
        op.f("fk_llm_calls_query_run_id_query_runs"), "llm_calls", type_="foreignkey"
    )
    op.drop_column("llm_calls", "query_run_id")
    op.drop_index("ix_query_runs_started_at", table_name="query_runs")
    op.drop_table("query_runs")
    op.drop_table("query_conversations")
    op.drop_index("ix_invoice_embeddings_embedding_hnsw", table_name="invoice_embeddings")
    for column in ("vendor_name_key", "vendor_tax_key", "invoice_number_key", "invoice_date"):
        op.drop_index(f"ix_invoice_embeddings_{column}", table_name="invoice_embeddings")
    op.drop_table("invoice_embeddings")
