from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.retrieval import service
from app.modules.retrieval.schema import DEFAULT_LIMIT, MAX_LIMIT, SimilarInvoices, VendorHistory

router = APIRouter(prefix="/documents", tags=["retrieval"])


@router.get("/{document_id}/similar", response_model=SimilarInvoices)
def get_similar_invoices(
    document_id: UUID,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: Session = Depends(get_db),
) -> SimilarInvoices:
    """Indexed invoices closest to this one (cosine similarity of their cards)."""
    return service.similar_invoices(db, document_id, k=limit)


@router.get("/{document_id}/vendor-history", response_model=VendorHistory)
def get_vendor_history(document_id: UUID, db: Session = Depends(get_db)) -> VendorHistory:
    """The document's vendor, its other invoices and where this one sits; computed live."""
    return service.vendor_history(db, document_id=document_id)
