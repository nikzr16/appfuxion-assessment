import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadedFile(BaseModel):
    """Internal DTO: what the router read from the multipart upload."""

    filename: str | None
    content_type: str | None
    data: bytes


class DocumentUploadResponse(BaseModel):
    """Body of ``POST /api/documents``."""

    document_id: uuid.UUID
    status: DocumentStatus


class DocumentRead(BaseModel):
    """One document's metadata and status. ``storage_path`` is never exposed."""

    model_config = ConfigDict(from_attributes=True)

    # The ORM column is ``id``; the API field is always ``document_id``.
    document_id: uuid.UUID = Field(validation_alias=AliasChoices("document_id", "id"))
    filename: str
    version: int
    content_type: str
    size_bytes: int
    status: DocumentStatus
    error: str | None
    created_at: datetime
    updated_at: datetime


class DocumentSource(BaseModel):
    """Internal DTO for other modules: where a document's file is stored and its status.

    Not returned by any route, so ``storage_key`` never leaves the backend.
    """

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID = Field(validation_alias=AliasChoices("document_id", "id"))
    content_type: str
    # The ORM column is ``storage_path``; it is the key ``Storage`` reads.
    storage_key: str = Field(validation_alias=AliasChoices("storage_key", "storage_path"))
    status: DocumentStatus
    error: str | None


class DocumentList(BaseModel):
    items: list[DocumentRead]
    total: int
    limit: int
    offset: int
