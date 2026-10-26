import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ExtractionMethod(StrEnum):
    PDF_PARSER = "pdf_parser"
    VISION = "vision"


class PageTranscription(BaseModel):
    """Structured output of one vision call. Every field is required (strict output)."""

    text: str = Field(description="The page's text, copied exactly as printed.")
    legible: bool = Field(description="False only when no text on the page can be read.")


class DocumentTextRead(BaseModel):
    """Internal DTO: one ``document_texts`` row, all columns."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    raw_text: str
    method: ExtractionMethod
    page_count: int
    model: str | None
    prompt_version: str | None
    created_at: datetime
    updated_at: datetime


class DocumentTextResponse(BaseModel):
    """Body of ``GET /api/documents/{document_id}/text``."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    raw_text: str
    method: ExtractionMethod
    page_count: int
