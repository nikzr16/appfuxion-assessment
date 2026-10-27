from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.structured_extraction import service
from app.modules.structured_extraction.schema import ExtractionResponse

router = APIRouter(prefix="/documents", tags=["structured_extraction"])


@router.get("/{document_id}/extraction", response_model=ExtractionResponse)
def get_document_extraction(document_id: UUID, db: Session = Depends(get_db)) -> ExtractionResponse:
    """The structured data. Read-only: it never starts an extraction or calls OpenAI."""
    extraction = service.get_extraction(db, document_id)
    return ExtractionResponse(
        document_id=extraction.document_id,
        structured_data=extraction.data,
        model=extraction.model,
        prompt_version=extraction.prompt_version,
        attempts=extraction.attempts,
        grounding=extraction.grounding,
        line_items_source=extraction.line_items_source,
    )
