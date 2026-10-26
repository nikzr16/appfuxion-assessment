from functools import partial
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.llm import LLMClient, get_llm_client
from app.core.storage import Storage, get_storage
from app.modules.agent import service
from app.modules.agent.schema import AgentResult, AgentRunRead, RunTrigger
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentUploadResponse

router = APIRouter(prefix="/documents", tags=["agent"])


@router.get("/{document_id}/result", response_model=AgentResult)
def get_document_result(document_id: UUID, db: Session = Depends(get_db)) -> AgentResult:
    """``{document_id, structured_data, validation, conversion, summary}``. Read-only."""
    return service.get_result(db, document_id)


@router.post(
    "/{document_id}/reprocess",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reprocess_document(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
    storage: Storage = Depends(get_storage),
) -> DocumentUploadResponse:
    """Run the agent again with forced re-extraction, in the background."""
    response = service.start_reprocess(db, document_id)
    pipeline = partial(
        service.run_document_agent,
        llm=llm,
        storage=storage,
        trigger=RunTrigger.REPROCESS,
        force=True,
    )
    background_tasks.add_task(documents_service.run_pipeline, document_id, pipeline)
    return response


@router.get("/{document_id}/runs", response_model=list[AgentRunRead])
def list_document_runs(document_id: UUID, db: Session = Depends(get_db)) -> list[AgentRunRead]:
    """The document's agent runs, newest first, each with its tool-call log."""
    return service.list_runs(db, document_id)
