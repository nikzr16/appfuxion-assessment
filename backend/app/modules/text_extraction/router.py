from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.modules.text_extraction import service
from app.modules.text_extraction.schema import DocumentTextResponse

router = APIRouter(prefix="/documents", tags=["text_extraction"])


@router.get("/{document_id}/text", response_model=DocumentTextResponse)
def get_document_text(document_id: UUID, db: Session = Depends(get_db)) -> DocumentTextResponse:
    """The extracted text. Read-only: it never starts an extraction or calls OpenAI."""
    return DocumentTextResponse.model_validate(service.get_text(db, document_id))
