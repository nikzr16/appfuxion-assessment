"""Tables, layout blocks and page images (feature 0009).

Text PDFs are analysed locally with ``pdfplumber`` (``layout.py``, no LLM). Scans and images
get one vision call per page that returns their text, tables and blocks together; the
caller (``text_extraction``) builds ``raw_text`` from the text and asks this module to save
the layout. Every analysis is a new ``document_layouts`` row; the newest is current (D9).

This module never imports ``text_extraction.service``, ``structured_extraction.service`` or
``guardrails.service``: they call it, so callers pass the text method in (PRD D1).
"""

import base64
import logging
import time
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError, ConflictError, LLMError, NotFoundError
from app.core.llm import LLMClient, Purpose
from app.core.logging import bind_document_id, bind_trace, run_id_var
from app.core.storage import Storage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.vision import crud, images, layout, prompts
from app.modules.vision.model import DocumentLayout
from app.modules.vision.schema import (
    BlockType,
    LayoutAnalysis,
    LayoutBlock,
    LayoutHistoryItem,
    LayoutRead,
    LayoutResponse,
    LayoutStats,
    PageAnalysis,
    PageInfo,
    Table,
    TableKind,
    TableLineItems,
    TablesSummary,
    TableSummary,
)

logger = logging.getLogger(__name__)

LAYOUT_VERSION = layout.LAYOUT_VERSION
VISION_LAYOUT_VERSION = prompts.PROMPT_VERSION
# Raised when an image or a PDF page cannot be read or rendered (re-exported for callers).
UnreadableImageError = images.UnreadableImageError


class LayoutAnalysisError(AppError):
    """The PDF could not be analysed for tables and layout."""

    status_code = 422
    code = "unreadable_document"


@dataclass(frozen=True)
class ScannedResult:
    """What the vision pages gave: one text per sent page, the layout and the model."""

    texts: list[str]
    analysis: LayoutAnalysis
    model: str | None


def _to_read(row: DocumentLayout) -> LayoutRead:
    return LayoutRead.model_validate(row)


# -- Vision (scans and images, PRD D2) ----------------------------------------------------


@bind_trace(purpose=Purpose.VISION_TRANSCRIPTION, prompt_version=prompts.PROMPT_VERSION)
def _analyse_pages(
    llm: LLMClient, pages: Sequence[images.PageImage], page_count: int
) -> tuple[list[PageAnalysis], str | None]:
    """One structured vision call per page. Returns the analyses and the model used."""
    analyses: list[PageAnalysis] = []
    model: str | None = None
    for number, page in enumerate(pages, start=1):
        encoded = base64.b64encode(page.jpeg).decode("ascii")
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
            response_format=PageAnalysis,
            temperature=0,
        )
        parsed = response.parsed
        if not isinstance(parsed, PageAnalysis):
            raise LLMError(f"The vision model returned no transcription for page {number}.")
        model = model or response.model
        analyses.append(parsed)
    return analyses, model


def _vision_layout(
    analyses: Sequence[PageAnalysis],
    pages: Sequence[images.PageImage],
    page_count: int,
    model: str | None,
) -> LayoutAnalysis:
    tables: list[Table] = []
    blocks: list[LayoutBlock] = []
    for number, analysis in enumerate(analyses, start=1):
        if not analysis.legible:
            continue
        for found in analysis.tables:
            table = layout.table_from_vision(len(tables), number, found.header, found.rows)
            if table is not None:
                tables.append(table)
        for block in analysis.blocks:
            if block.text.strip():
                blocks.append(
                    LayoutBlock(
                        type=BlockType(block.type),
                        page=number,
                        order=len(blocks),
                        text=block.text.strip(),
                        box=None,
                    )
                )
    return LayoutAnalysis(
        source=ExtractionMethod.VISION,
        layout_version=VISION_LAYOUT_VERSION,
        page_count=page_count,
        pages=[PageInfo(page=i, width=p.width, height=p.height) for i, p in enumerate(pages, 1)],
        tables=layout.stitch_vision_tables(tables),
        blocks=blocks,
        model=model,
    )


def analyse_scanned(
    llm: LLMClient, data: bytes, *, is_image: bool, page_count: int, max_pages: int
) -> ScannedResult:
    """Send an image or the first ``max_pages`` PDF pages to vision: text + tables + blocks.

    Pure apart from the LLM: nothing is saved (``text_extraction`` saves the text, then calls
    ``save_layout``).
    """
    pages = [images.prepare_image(data)] if is_image else images.render_pages(data, max_pages)
    analyses, model = _analyse_pages(llm, pages, page_count)
    texts = [a.text.strip() if a.legible else "" for a in analyses]
    return ScannedResult(texts, _vision_layout(analyses, pages, page_count, model), model)


# -- Text PDFs (PRD D3, D4) -----------------------------------------------------------------


def analyse_text_pdf(data: bytes) -> LayoutAnalysis:
    """Tables and blocks of a text PDF, with ``pdfplumber`` only (no LLM)."""
    try:
        return layout.analyse_pdf(data)
    except Exception as exc:  # pdfminer raises many unrelated types on bad or locked files
        raise LayoutAnalysisError("The PDF could not be analysed for tables.") from exc


# -- Storage ----------------------------------------------------------------------------------


def _current_run_id() -> uuid.UUID | None:
    value = run_id_var.get()
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def save_layout(db: Session, document_id: uuid.UUID, analysis: LayoutAnalysis) -> LayoutRead:
    """Append one analysis row (linked to the current agent run, if any); the caller commits."""
    row = crud.insert(
        db,
        document_id=document_id,
        run_id=_current_run_id(),
        **analysis.model_dump(mode="json"),
    )
    return _to_read(row)


def find_layout(db: Session, document_id: uuid.UUID) -> LayoutRead | None:
    """The newest analysis, or ``None``. Never analyses."""
    row = crud.latest_by_document(db, document_id)
    return _to_read(row) if row is not None else None


def _summary(row: LayoutRead | None, method: ExtractionMethod, *, reused: bool) -> TablesSummary:
    if row is None:
        return TablesSummary(
            source=method,
            available=False,
            pages=0,
            tables=[],
            line_item_table=False,
            blocks={},
            reused=False,
        )
    return TablesSummary(
        source=row.source,
        available=True,
        pages=row.page_count,
        tables=[
            TableSummary(
                index=t.index, pages=t.pages, kind=t.kind, columns=t.columns, rows=len(t.rows)
            )
            for t in row.tables
        ],
        line_item_table=any(t.kind is TableKind.LINE_ITEMS for t in row.tables),
        blocks=dict(Counter(b.type.value for b in row.blocks)),
        reused=reused,
    )


def extract_tables(
    db: Session,
    storage: Storage,
    document_id: uuid.UUID,
    *,
    method: ExtractionMethod,
    force: bool = False,
) -> TablesSummary:
    """Tables and layout for the document; the 0009 agent tool's use case (PRD D7).

    Text PDFs: ``pdfplumber``, reusing the newest row of the current ``layout.v1`` unless
    ``force``. Scans: the row the vision page call already wrote during ``extract_text`` (no
    LLM call); a scan analysed before 0009 has none (``available = False``). Commits ``db``
    before the file work and commits its own row; never changes the document's status.
    """
    source = documents_service.get_document_source(db, document_id)
    with bind_document_id(str(document_id)):
        if method is ExtractionMethod.VISION:
            row = crud.latest_by_document(db, document_id, source=ExtractionMethod.VISION.value)
            return _summary(_to_read(row) if row else None, method, reused=True)

        if not force:
            row = crud.latest_by_document(db, document_id, source=method.value)
            if row is not None and row.layout_version == LAYOUT_VERSION:
                logger.debug("layout already analysed; reusing it")
                return _summary(_to_read(row), method, reused=True)
        db.commit()  # end the read transaction before the file work

        started = time.perf_counter()
        try:
            data = storage.read(source.storage_key)
        except NotFoundError as exc:
            raise LayoutAnalysisError("The stored file could not be found.") from exc
        analysis = analyse_text_pdf(data)
        saved = save_layout(db, document_id, analysis)
        db.commit()
        logger.info(
            "layout analysed",
            extra={
                "pages": analysis.page_count,
                "tables": len(analysis.tables),
                "blocks": len(analysis.blocks),
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return _summary(saved, method, reused=False)


def get_layout(db: Session, document_id: uuid.UUID) -> LayoutResponse:
    """The newest analysis + history metadata; never analyses. 409 / 404 like ``get_text``."""
    rows = crud.list_by_document(db, document_id)
    if not rows:
        source = documents_service.get_document_source(db, document_id)
        if source.status == DocumentStatus.PROCESSING:
            raise ConflictError(
                "The document is still processing; its layout is not ready yet.",
                code="layout_not_ready",
            )
        raise ConflictError(
            "No layout analysis exists for this document; reprocess it to analyse its layout.",
            code="layout_unavailable",
        )
    current, *older = [_to_read(row) for row in rows]
    return LayoutResponse(
        document_id=document_id,
        layout_id=current.id,
        source=current.source,
        layout_version=current.layout_version,
        run_id=current.run_id,
        created_at=current.created_at,
        page_count=current.page_count,
        pages=current.pages,
        tables=current.tables,
        blocks=current.blocks,
        history=[
            LayoutHistoryItem(
                layout_id=row.id,
                created_at=row.created_at,
                source=row.source,
                layout_version=row.layout_version,
                run_id=row.run_id,
            )
            for row in older
        ],
    )


# -- Used by other modules --------------------------------------------------------------------


def line_items_from_layout(analysis: LayoutAnalysis) -> TableLineItems | None:
    """Line items copied by code from the line-item table, or ``None`` (PRD D5)."""
    return layout.line_items_from_tables(analysis.tables)


def page_images(
    db: Session, storage: Storage, document_id: uuid.UUID, max_pages: int
) -> list[bytes]:
    """The page JPEGs vision gets (D2 sizes), for multimodal extraction (PRD D6)."""
    source = documents_service.get_document_source(db, document_id)
    data = storage.read(source.storage_key)
    if source.content_type.startswith("image/"):
        return [images.prepare_image(data).jpeg]
    return [page.jpeg for page in images.render_pages(data, max_pages)]


def render_page_image(db: Session, storage: Storage, document_id: uuid.UUID, page: int) -> bytes:
    """A preview JPEG of one page, rendered on request (``GET /pages/{n}/image``)."""
    source = documents_service.get_document_source(db, document_id)
    db.commit()  # rendering can wait on the lock; hold no transaction meanwhile
    data = storage.read(source.storage_key)
    preview = images.render_preview(data, source.content_type, page)
    if preview is None:
        raise NotFoundError(f"The document has no page {page}.", code="page_not_found")
    return preview.jpeg


def layout_stats(db: Session, *, since: datetime | None = None) -> LayoutStats:
    row = crud.stats(db, since=since)
    return LayoutStats(
        layouts_analysed=int(row.layouts),
        documents_with_line_item_table=int(row.documents_with_line_item_table),
        tables_found=int(row.tables_found),
    )
