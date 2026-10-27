import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.retrieval.schema import EMBEDDING_DIMENSIONS


class InvoiceEmbedding(Base):
    """One indexed document: its key fields, its invoice card and the card's vector.

    One row per document, replaced on reprocess (PRD 0010 D9). ``embedding`` is NULL when
    the embedding call failed; vendor history still works without it (D3).
    """

    __tablename__ = "invoice_embeddings"
    __table_args__ = (
        CheckConstraint("document_type IN ('invoice', 'receipt')", name="document_type_valid"),
        Index("ix_invoice_embeddings_vendor_name_key", "vendor_name_key"),
        Index("ix_invoice_embeddings_vendor_tax_key", "vendor_tax_key"),
        Index("ix_invoice_embeddings_invoice_number_key", "invoice_number_key"),
        Index("ix_invoice_embeddings_invoice_date", "invoice_date"),
        Index(
            "ix_invoice_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # String references: this module never imports another module's ``model``.
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), unique=True
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    # The document's upload time: "earlier invoices" means uploaded before this one.
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    document_type: Mapped[str] = mapped_column(String(20))
    vendor: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor_tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vendor_name_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_tax_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_number_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    # The total in ``base_currency`` (static rate table); NULL when it cannot be converted.
    total_base: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    base_currency: Mapped[str] = mapped_column(String(3))
    needs_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    card: Mapped[str] = mapped_column(Text)
    card_hash: Mapped[str] = mapped_column(String(64))
    card_version: Mapped[str] = mapped_column(String(50))
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
