import base64
import io
import logging
import re
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, LLMError, NotFoundError
from app.core.llm import LLMClient
from app.core.logging import bind_document_id
from app.core.storage import Storage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.text_extraction import crud, prompts
from app.modules.text_extraction.model import DocumentText
from app.modules.text_extraction.schema import (
    DocumentTextRead,
    ExtractionMethod,
    PageTranscription,
)

logger = logging.getLogger(__name__)

# A PDF page "has text" when at least this many characters remain after removing
# whitespace and pdfminer's ``(cid:N)`` glyph placeholders.
MIN_PAGE_CHARS = 20
RENDER_DPI = 200
# Pages with an absurd size are rendered smaller than RENDER_DPI so memory stays bounded.
MAX_RENDER_SIDE = 4096
MAX_IMAGE_SIDE = 2048
JPEG_QUALITY = 90
# Serialises pypdfium2, which is not thread-safe (see ``_render_pages``).
_RENDER_LOCK = threading.Lock()

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


def _to_rgb(image: Image.Image) -> Image.Image:
    """Convert to RGB, flattening transparency onto white (black would hide dark text)."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return image.convert("RGB")


def _prepare_image(source: bytes | Image.Image) -> bytes:
    """Upright, RGB, long side <= ``MAX_IMAGE_SIDE``, JPEG bytes (smaller base64 payload)."""
    try:
        image = Image.open(io.BytesIO(source)) if isinstance(source, bytes) else source
        image = _to_rgb(ImageOps.exif_transpose(image))
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise TextExtractionError("The image could not be read.") from exc
    return buffer.getvalue()


def _render_pages(data: bytes, max_pages: int) -> list[bytes]:
    """Render the first ``max_pages`` PDF pages at ``RENDER_DPI`` and prepare them for vision.

    pdfium is not thread-safe and background runs share a thread pool, so the whole render
    holds ``_RENDER_LOCK`` (the rendered bitmaps share memory with pdfium until prepared).
    """
    try:
        with _RENDER_LOCK:
            pdf = pdfium.PdfDocument(data)
            try:
                images: list[bytes] = []
                for index in range(min(max_pages, len(pdf))):
                    page = pdf[index]
                    width, height = page.get_size()
                    scale = min(RENDER_DPI / 72, MAX_RENDER_SIDE / (max(width, height) or 1))
                    images.append(_prepare_image(page.render(scale=scale).to_pil()))
            finally:
                pdf.close()
    except pdfium.PdfiumError as exc:
        raise TextExtractionError("The PDF pages could not be rendered.") from exc
    return images


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


def _transcribe_pages(
    llm: LLMClient, images: Sequence[bytes], page_count: int
) -> tuple[list[str], str | None]:
    """One structured vision call per page. Returns the page texts and the model used."""
    texts: list[str] = []
    model: str | None = None
    for number, jpeg in enumerate(images, start=1):
        encoded = base64.b64encode(jpeg).decode("ascii")
        response = llm.complete(
            [
                {"role": "system", "content": prompts.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompts.page_prompt(page=number, total=page_count),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{encoded}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            vision=True,
            response_format=PageTranscription,
            temperature=0,
        )
        parsed = response.parsed
        if not isinstance(parsed, PageTranscription):
            raise LLMError(f"The vision model returned no transcription for page {number}.")
        model = model or response.model
        texts.append(parsed.text.strip() if parsed.legible else "")
    return texts, model


def _extract_image(data: bytes, llm: LLMClient) -> _Extraction:
    texts, model = _transcribe_pages(llm, [_prepare_image(data)], page_count=1)
    return _Extraction(texts, ExtractionMethod.VISION, 1, model)


def _extract_pdf(data: bytes, llm: LLMClient) -> _Extraction:
    texts = _read_text_layer(data)
    page_count = len(texts)
    if all(_has_text(text) for text in texts):
        return _Extraction([t.rstrip() for t in texts], ExtractionMethod.PDF_PARSER, page_count)

    # No text layer on at least one page: the whole document goes through vision.
    max_pages = get_settings().vision_max_pages
    if page_count > max_pages:
        logger.warning(
            "vision page cap applied", extra={"pages_total": page_count, "pages_sent": max_pages}
        )
    images = _render_pages(data, max_pages)
    pages, model = _transcribe_pages(llm, images, page_count)
    return _Extraction(pages, ExtractionMethod.VISION, page_count, model)


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
                    prompts.PROMPT_VERSION if result.method is ExtractionMethod.VISION else None
                ),
            },
            overwrite=force,
        )
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
