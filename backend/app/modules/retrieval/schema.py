"""DTOs of the retrieval module (PRD 0010): the invoice index, history, search, similarity."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ConflictError, NotFoundError
from app.modules.structured_extraction.schema import DocumentType, InvoiceData
from app.modules.validation.schema import ValidationIssue

CARD_VERSION = "retrieval.card.v1"
EMBEDDING_DIMENSIONS = 1536
# Results less similar than this are not shown (cosine similarity, PRD D7).
MIN_SIMILARITY = 0.30
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
# Most invoices one vendor history lists (the stats use all of them).
MAX_HISTORY_ITEMS = 50


class MatchRule(StrEnum):
    TAX_ID = "tax_id"
    NAME = "name"


class VendorKey(BaseModel):
    """How a document's vendor is matched (PRD D4)."""

    display: str | None
    name_key: str | None
    tax_key: str | None

    @property
    def known(self) -> bool:
        return self.name_key is not None or self.tax_key is not None


class IndexEntry(BaseModel):
    """One ``invoice_embeddings`` row, as other modules and the API see it."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    filename: str
    uploaded_at: datetime
    run_id: uuid.UUID | None
    document_type: DocumentType
    vendor: str | None
    vendor_tax_id: str | None
    invoice_number: str | None
    invoice_date: date | None
    currency: str | None
    total_amount: Decimal | None
    total_base: Decimal | None
    base_currency: str
    needs_review: bool | None
    embedded: bool


class InvoiceHit(IndexEntry):
    # Cosine similarity (1 = same direction), 3 decimals; null for filter / identifier hits.
    similarity: float | None = None


class PreparedEmbedding(BaseModel):
    """A document's card and vector, made during its run and stored at completion (D3)."""

    card: str
    card_hash: str
    vector: list[float] | None
    model: str | None
    reused: bool
    error_code: str | None = None


class IndexRequest(BaseModel):
    """What the agent hands over when a run completes."""

    document_id: uuid.UUID
    run_id: uuid.UUID | None
    data: InvoiceData
    needs_review: bool | None
    embedding: PreparedEmbedding | None


class HistoryStats(BaseModel):
    """Totals of a set of invoices in the base currency (code-computed, PRD D8)."""

    base_currency: str
    count: int
    with_total: int
    skipped_currencies: list[str]
    sum: Decimal | None = None
    min: Decimal | None = None
    max: Decimal | None = None
    mean: Decimal | None = None
    median: Decimal | None = None
    q1: Decimal | None = None
    q3: Decimal | None = None
    low_fence: Decimal | None = None
    high_fence: Decimal | None = None


class TargetPosition(BaseModel):
    """Where one invoice sits among its vendor's invoices."""

    document_id: uuid.UUID
    total_base: Decimal | None
    diff_vs_median: Decimal | None
    diff_pct: Decimal | None
    rank: int | None  # 1 = largest total
    position: Literal["below", "within", "above"] | None


class VendorHistory(BaseModel):
    """``GET /documents/{id}/vendor-history`` and the ``get_vendor_history`` tool."""

    document_id: uuid.UUID | None
    vendor: str | None
    match_rule: MatchRule | None
    base_currency: str
    invoices: list[IndexEntry]  # newest invoice date first, at most MAX_HISTORY_ITEMS
    earlier: int  # uploaded before the target document
    later: int
    stats: HistoryStats
    target: TargetPosition | None
    duplicates: list[IndexEntry]


class SimilarInvoices(BaseModel):
    document_id: uuid.UUID
    available: bool  # false when the document has no vector (embedding failed)
    items: list[InvoiceHit]


class SearchFilters(BaseModel):
    text: str | None = None
    vendor: str | None = None
    invoice_number: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    currency: str | None = None
    min_total: Decimal | None = None  # base currency
    max_total: Decimal | None = None
    document_type: DocumentType | None = None
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)


class SearchResult(BaseModel):
    items: list[InvoiceHit]
    total_matches: int
    # Over every filter match when there is no text; over the returned items otherwise.
    aggregates: HistoryStats | None
    vendor_candidates: list[str] = []
    note: str | None = None
    # Tokens of the question's embedding; for the query run's totals, never sent to the model.
    embedding_tokens: int = Field(default=0, exclude=True)


class HistoryCheck(BaseModel):
    """What ``check_vendor_history`` found for one document (PRD D5)."""

    skipped: bool
    reason: str | None = None
    vendor: str | None = None
    match_rule: MatchRule | None = None
    earlier_invoices: int = 0
    issues: list[ValidationIssue] = []


class BackfillReport(BaseModel):
    indexed: int = 0
    embedded: int = 0
    skipped: int = 0
    failed: int = 0


class RetrievalStats(BaseModel):
    documents_indexed: int
    documents_embedded: int
    documents_not_embedded: int


class NotIndexedError(ConflictError):
    def __init__(self) -> None:
        super().__init__(
            "This document is not indexed yet. Reprocess it or run the back-fill command.",
            code="not_indexed",
        )


class VendorNotFoundError(NotFoundError):
    """A vendor / invoice / document reference matched nothing; recoverable for the agent."""

    def __init__(self, message: str, candidates: list[str]) -> None:
        if candidates:
            message = f"{message} Known vendors with a similar name: {', '.join(candidates)}."
        super().__init__(message, code="vendor_not_found")
        self.candidates = candidates
