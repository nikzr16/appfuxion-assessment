"""Page rendering and image preparation (moved from ``text_extraction``, PRD 0009 D1).

Pure helpers: no DB, no LLM. pypdfium2 is not thread-safe and background runs share a
thread pool, so every render holds ``_RENDER_LOCK`` (PRD 0005 D12).
"""

import io
import threading
from dataclasses import dataclass

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import AppError

RENDER_DPI = 200
# Pages with an absurd size are rendered smaller than RENDER_DPI so memory stays bounded.
MAX_RENDER_SIDE = 4096
MAX_IMAGE_SIDE = 2048
# The page preview in the UI (``GET /pages/{n}/image``) is smaller than what vision gets.
PREVIEW_SIDE = 1600
JPEG_QUALITY = 90
PREVIEW_JPEG_QUALITY = 85
# Serialises pypdfium2, which is not thread-safe (see ``render_pages``).
_RENDER_LOCK = threading.Lock()


class UnreadableImageError(AppError):
    """An image or PDF page cannot be read or rendered."""

    status_code = 422
    code = "unreadable_document"


@dataclass(frozen=True)
class PageImage:
    """A prepared JPEG and its pixel size."""

    jpeg: bytes
    width: int
    height: int


def to_rgb(image: Image.Image) -> Image.Image:
    """Convert to RGB, flattening transparency onto white (black would hide dark text)."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return image.convert("RGB")


def prepare_image(
    source: bytes | Image.Image, *, max_side: int = MAX_IMAGE_SIDE, quality: int = JPEG_QUALITY
) -> PageImage:
    """Upright, RGB, long side <= ``max_side``, JPEG bytes (smaller base64 payload)."""
    try:
        image = Image.open(io.BytesIO(source)) if isinstance(source, bytes) else source
        image = to_rgb(ImageOps.exif_transpose(image))
        image.thumbnail((max_side, max_side))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise UnreadableImageError("The image could not be read.") from exc
    return PageImage(buffer.getvalue(), image.width, image.height)


def _render(page: pdfium.PdfPage, max_side: int) -> Image.Image:
    width, height = page.get_size()
    scale = min(RENDER_DPI / 72, max_side / (max(width, height) or 1))
    return page.render(scale=scale).to_pil()


def render_pages(data: bytes, max_pages: int) -> list[PageImage]:
    """Render the first ``max_pages`` PDF pages at ``RENDER_DPI`` and prepare them for vision.

    The whole render holds ``_RENDER_LOCK`` (the rendered bitmaps share memory with pdfium
    until prepared).
    """
    try:
        with _RENDER_LOCK:
            pdf = pdfium.PdfDocument(data)
            try:
                return [
                    prepare_image(_render(pdf[index], MAX_RENDER_SIDE))
                    for index in range(min(max_pages, len(pdf)))
                ]
            finally:
                pdf.close()
    except pdfium.PdfiumError as exc:
        raise UnreadableImageError("The PDF pages could not be rendered.") from exc


def pdf_page_count(data: bytes) -> int:
    try:
        with _RENDER_LOCK:
            pdf = pdfium.PdfDocument(data)
            try:
                return len(pdf)
            finally:
                pdf.close()
    except pdfium.PdfiumError as exc:
        raise UnreadableImageError("The PDF could not be opened.") from exc


def render_preview(data: bytes, content_type: str, page: int) -> PageImage | None:
    """A JPEG of page ``page`` (1-based) for the UI preview; ``None`` when there is no such page.

    Images have one page. PDF pages are rendered on request at ``PREVIEW_SIDE``.
    """
    if content_type.startswith("image/"):
        if page != 1:
            return None
        return prepare_image(data, max_side=PREVIEW_SIDE, quality=PREVIEW_JPEG_QUALITY)
    try:
        with _RENDER_LOCK:
            pdf = pdfium.PdfDocument(data)
            try:
                if not 1 <= page <= len(pdf):
                    return None
                return prepare_image(
                    _render(pdf[page - 1], PREVIEW_SIDE),
                    max_side=PREVIEW_SIDE,
                    quality=PREVIEW_JPEG_QUALITY,
                )
            finally:
                pdf.close()
    except pdfium.PdfiumError as exc:
        raise UnreadableImageError("The PDF page could not be rendered.") from exc
