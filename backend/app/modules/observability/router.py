from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.observability import service
from app.modules.observability.schema import DocumentTrace, MetricsSummary

router = APIRouter(tags=["observability"])


@router.get("/documents/{document_id}/trace", response_model=DocumentTrace)
def get_document_trace(
    document_id: UUID,
    run_id: UUID | None = Query(None, description="An earlier run; the latest when omitted."),
    db: Session = Depends(get_db),
) -> DocumentTrace:
    """The run's timeline of tool steps and LLM calls, with tokens, cost and timing."""
    return service.get_trace(db, document_id, run_id)


@router.get("/metrics/summary", response_model=MetricsSummary)
def get_metrics_summary(
    days: int | None = Query(None, ge=1, le=365, description="Window; all time when omitted."),
    db: Session = Depends(get_db),
) -> MetricsSummary:
    """Documents, runs, processing time, tokens and estimated cost."""
    return service.get_metrics(db, days=days)
