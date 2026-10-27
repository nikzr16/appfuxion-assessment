from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.storage import Storage, get_storage
from app.modules.vision import service
from app.modules.vision.schema import LayoutResponse

router = APIRouter(prefix="/documents", tags=["vision"])

# Rendered pages never change for a stored file, but documents may be reprocessed or deleted.
PAGE_CACHE_CONTROL = "private, max-age=3600"


@router.get("/{document_id}/layout", response_model=LayoutResponse)
def get_document_layout(document_id: UUID, db: Session = Depends(get_db)) -> LayoutResponse:
    """The newest tables and layout analysis plus earlier ones. Read-only: never analyses."""
    return service.get_layout(db, document_id)


@router.get(
    "/{document_id}/pages/{page}/image",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}},
)
def get_page_image(
    document_id: UUID,
    page: int = Path(ge=1),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """A JPEG preview of one page (images have only page 1), rendered on request."""
    content = service.render_page_image(db, storage, document_id, page)
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={"Cache-Control": PAGE_CACHE_CONTROL},
    )
