import io
import logging
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import pdfplumber
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.llm import LLMClient
from app.core.logging import bind_document_id
from app.core.storage import Storage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.text_extraction import crud
from app.modules.text_extraction.model import DocumentText
from app.modules.text_extraction.schema import DocumentTextRead, ExtractionMethod
from app.modules.vision import service as vision_service
from app.modules.vision.schema import LayoutAnalysis

logger = logging.getLogger(__name__)

# A PDF page "has text" when at least this many characters remain after removing
# whitespace and pdfminer's ``(cid:N)`` glyph placeholders.
MIN_PAGE_CHARS = 20

_NO_TEXT_PLACEHOLDERS = re.compile(r"\(cid:\d+\)|\s")


class TextExtractionError(AppError):
    """The document cannot be turned into text (``unreadable_document`` / ``no_text_found``)."""

    status_code = 422
    code = "unreadable_document"


@dataclass(frozen=True)
class _Extraction:
    pages: list[str]
    method: ExtractionMethod
    page_count: int
    # The vision model that answered; ``None`` for ``pdf_parser``.
    model: str | None = None
    # Tables and blocks the vision pages returned (0009); ``None`` for ``pdf_parser``.
    layout: LayoutAnalysis | None = None


def _to_read(row: DocumentText) -> DocumentTextRead:
    return DocumentTextRead.model_validate(row)


# -- Pure helpers ---------------------------------------------------------------------


def _has_text(text: str) -> bool:
    return len(_NO_TEXT_PLACEHOLDERS.sub("", text)) >= MIN_PAGE_CHARS


def _join_pages(pages: Sequence[str], page_count: int) -> str:
    """One page keeps its text; several get a ``--- Page N ---`` marker (empty pages too)."""
    if page_count == 1:
        return pages[0]
    return "\n\n".join(f"--- Page {number} ---\n{text}" for number, text in enumerate(pages, 1))


def _read_text_layer(data: bytes) -> list[str]:
    """Text of every PDF page (empty string where there is none)."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            texts = [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:  # pdfminer raises many unrelated types on bad or locked files
        raise TextExtractionError(
            "The PDF could not be opened (it may be corrupt or password-protected)."
        ) from exc
    if not texts:
        raise TextExtractionError("The PDF has no pages.")
    return texts


# -- Vision ---------------------------------------------------------------------------


def _scan(llm: LLMClient, data: bytes, *, is_image: bool, page_count: int) -> _Extraction:
    """Vision pages (text + tables + blocks in one call per page, 0009 D2)."""
    max_pages = get_settings().vision_max_pages
    if not is_image and page_count > max_pages:
        logger.warning(
            "vision page cap applied", extra={"pages_total": page_count, "pages_sent": max_pages}
        )
    try:
        result = vision_service.analyse_scanned(
            llm, data, is_image=is_image, page_count=page_count, max_pages=max_pages
        )
    except vision_service.UnreadableImageError as exc:
        raise TextExtractionError(exc.message) from exc
    return _Extraction(
        result.texts, ExtractionMethod.VISION, page_count, result.model, result.analysis
    )


def _extract_image(data: bytes, llm: LLMClient) -> _Extraction:
    return _scan(llm, data, is_image=True, page_count=1)


def _extract_pdf(data: bytes, llm: LLMClient) -> _Extraction:
    texts = _read_text_layer(data)
    page_count = len(texts)
    if all(_has_text(text) for text in texts):
        return _Extraction([t.rstrip() for t in texts], ExtractionMethod.PDF_PARSER, page_count)

    # No text layer on at least one page: the whole document goes through vision.
    return _scan(llm, data, is_image=False, page_count=page_count)


# -- Use cases ------------------------------------------------------------------------


def extract_text(
    db: Session, storage: Storage, llm: LLMClient, document_id: uuid.UUID, *, force: bool = False
) -> DocumentTextRead:
    """Extract the document's text and save it; the function the 0005 agent tool calls.

    PDFs with a text layer on every page are parsed locally; images and scanned PDFs are
    transcribed page by page by the vision model. Idempotent: an existing row is returned
    without any work unless ``force`` replaces it in place.

    This commits its own row, so the result survives a later pipeline failure, and it
    commits ``db`` first so no transaction stays open during the slow vision calls: call it
    at a point where the session has nothing else pending. It never changes the document's
    status; on failure it raises and the caller marks the document ``failed``.
    """
    source = documents_service.get_document_source(db, document_id)
    with bind_document_id(str(document_id)):
        if not force:
            existing = crud.get_by_document(db, document_id)
            if existing is not None:
                logger.debug("text already extracted; reusing it")
                return _to_read(existing)
        db.commit()  # end the read transaction before the file and LLM work

        started = time.perf_counter()
        try:
            data = storage.read(source.storage_key)
        except NotFoundError as exc:
            raise TextExtractionError("The stored file could not be found.") from exc
        if source.content_type.startswith("image/"):
            result = _extract_image(data, llm)
        else:
            result = _extract_pdf(data, llm)

        # Postgres text columns reject NUL, which broken PDFs and models can emit.
        pages = [page.replace("\x00", "") for page in result.pages]
        if not any(page.strip() for page in pages):
            raise TextExtractionError("No readable text was found.", code="no_text_found")

        raw_text = _join_pages(pages, result.page_count)
        row = crud.upsert(
            db,
            values={
                "document_id": document_id,
                "raw_text": raw_text,
                "method": result.method.value,
                "page_count": result.page_count,
                "model": result.model,
                "prompt_version": (
                    vision_service.VISION_LAYOUT_VERSION
                    if result.method is ExtractionMethod.VISION
                    else None
                ),
            },
            overwrite=force,
        )
        if result.layout is not None:
            # The scan's tables and blocks, saved with its text (0009 D9).
            vision_service.save_layout(db, document_id, result.layout)
        db.commit()
        logger.info(
            "text extracted",
            extra={
                "method": result.method.value,
                "page_count": result.page_count,
                "pages_sent": len(pages),
                "chars": len(raw_text),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return _to_read(row)


def find_text(db: Session, document_id: uuid.UUID) -> DocumentTextRead | None:
    """The saved text, or ``None`` when none has been extracted. Never extracts."""
    row = crud.get_by_document(db, document_id)
    return _to_read(row) if row is not None else None


def get_text(db: Session, document_id: uuid.UUID) -> DocumentTextRead:
    """The saved text; never extracts. Explains why there is none (409) or 404 if unknown."""
    row = crud.get_by_document(db, document_id)
    if row is not None:
        return _to_read(row)
    source = documents_service.get_document_source(db, document_id)
    if source.status == DocumentStatus.PROCESSING:
        raise ConflictError(
            "The document is still processing; its text is not ready yet.", code="text_not_ready"
        )
    message = "No text is available for this document."
    if source.error:
        message = f"{message} Processing failed: {source.error}"
    raise ConflictError(message, code="text_unavailable")
