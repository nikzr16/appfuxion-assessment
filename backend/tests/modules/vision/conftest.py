"""Fixtures shared by the vision service and router tests."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from app.core.storage import LocalStorage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import UploadedFile

_EXTENSIONS = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}

MakeDocument = Callable[[str, bytes], uuid.UUID]


@pytest.fixture
def make_document(db_session: Session, storage: LocalStorage) -> MakeDocument:
    """Upload ``data`` through ``documents.service`` (real row + stored file); returns its id."""

    def make(content_type: str, data: bytes) -> uuid.UUID:
        upload = UploadedFile(
            filename=f"invoice.{_EXTENSIONS[content_type]}", content_type=content_type, data=data
        )
        return documents_service.create_document(db_session, storage, upload).document_id

    return make
