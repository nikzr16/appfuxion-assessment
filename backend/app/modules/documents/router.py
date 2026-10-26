from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.storage import Storage, get_storage
from app.modules.documents import service
from app.modules.documents.pipeline import DocumentPipeline, get_document_pipeline
from app.modules.documents.schema import (
    DocumentList,
    DocumentRead,
    DocumentStatus,
    DocumentUploadResponse,
    UploadedFile,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    pipeline: DocumentPipeline = Depends(get_document_pipeline),
) -> DocumentUploadResponse:
    """Store an uploaded PDF/JPEG/PNG and process it in the background."""
    # One byte over the limit is enough for the service to see "too large".
    data = file.file.read(get_settings().max_upload_bytes + 1)
    document = service.create_document(
        db,
        storage,
        UploadedFile(filename=file.filename, content_type=file.content_type, data=data),
    )
    background_tasks.add_task(service.run_pipeline, document.document_id, pipeline)
    return DocumentUploadResponse(document_id=document.document_id, status=document.status)


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: UUID, db: Session = Depends(get_db)) -> DocumentRead:
    return service.get_document(db, document_id)


@router.get("", response_model=DocumentList)
def list_documents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: DocumentStatus | None = None,
    db: Session = Depends(get_db),
) -> DocumentList:
    return service.list_documents(db, limit=limit, offset=offset, status=status)
