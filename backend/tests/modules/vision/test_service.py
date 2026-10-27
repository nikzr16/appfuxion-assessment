"""Vision service: scans through vision, tables for text PDFs, history, previews (PRD 0009)."""

import ast
import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.llm import FakeLLM, Purpose
from app.core.logging import bind_trace
from app.core.storage import LocalStorage
from app.modules.documents import service as documents_service
from app.modules.text_extraction import service as text_service
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.vision import prompts, service
from app.modules.vision.schema import (
    BlockType,
    PageAnalysis,
    TableKind,
    TableStrategy,
    VisionBlock,
    VisionTable,
)
from tests.modules.vision import samples
from tests.modules.vision.conftest import MakeDocument

PDF = "application/pdf"
PNG = "image/png"


def _page(text: str = "Acme Trading Sdn Bhd\nTotal (RM) 200.00") -> PageAnalysis:
    return PageAnalysis(
        text=text,
        legible=True,
        tables=[
            VisionTable(
                header=["Description", "Qty", "Unit Price", "Amount"],
                rows=[["Widget A", "2", "100.00", "200.00"]],
            )
        ],
        blocks=[
            VisionBlock(type="header", text="Acme Trading Sdn Bhd"),
            VisionBlock(type="line_items", text="Widget A | 2 | 100.00 | 200.00"),
            VisionBlock(type="totals", text="Total (RM) 200.00"),
        ],
    )


def _layout_count(db: Session) -> int:
    return int(db.execute(text("SELECT count(*) FROM document_layouts")).scalar_one())


def _insert_run(db: Session, document_id: uuid.UUID) -> uuid.UUID:
    run_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO agent_runs (id, document_id, mode, trigger, status, steps, "
            "agent_prompt_version, summary_prompt_version) VALUES (:id, :document_id, 'single', "
            "'upload', 'running', '[]'::jsonb, 'a', 's')"
        ),
        {"id": run_id, "document_id": document_id},
    )
    db.commit()
    return run_id


# -- Scans (PRD D2) ----------------------------------------------------------------------


def test_scan_gets_one_vision_call_per_page_with_tables_and_blocks(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.scanned_pdf(pages=2))
    fake_llm.queue(_page("page one text"), _page("page two text"))

    result = text_service.extract_text(db_session, storage, fake_llm, document_id)

    assert result.raw_text == "--- Page 1 ---\npage one text\n\n--- Page 2 ---\npage two text"
    assert len(fake_llm.calls) == 2
    assert all(call.response_format is PageAnalysis for call in fake_llm.calls)
    assert fake_llm.calls[0].messages[0]["content"] == prompts.SYSTEM_PROMPT
    layout = service.find_layout(db_session, document_id)
    assert layout is not None
    assert layout.source is ExtractionMethod.VISION
    assert layout.layout_version == "vision.v1"
    assert layout.model == "fake-model"
    assert layout.page_count == 2
    assert [p.page for p in layout.pages] == [1, 2]
    # The same table header on both pages: stitched into one table.
    [table] = layout.tables
    assert table.pages == [1, 2]
    assert table.strategy is TableStrategy.VISION
    assert table.kind is TableKind.LINE_ITEMS
    assert table.box is None
    assert [b.type for b in layout.blocks[:3]] == [
        BlockType.HEADER,
        BlockType.LINE_ITEMS,
        BlockType.TOTALS,
    ]
    assert all(b.box is None for b in layout.blocks)
    assert [b.order for b in layout.blocks] == list(range(6))


def test_scan_calls_are_labelled_vision_transcription(
    db_session: Session,
    storage: LocalStorage,
    fake_llm: FakeLLM,
    make_document: MakeDocument,
    llm_recorder: None,
) -> None:
    document_id = make_document(PNG, samples.scanned_png())
    fake_llm.queue(_page())

    text_service.extract_text(db_session, storage, fake_llm, document_id)

    row = db_session.execute(text("SELECT purpose, prompt_version FROM llm_calls")).one()
    assert tuple(row) == (Purpose.VISION_TRANSCRIPTION.value, "vision.v1")


def test_illegible_page_has_no_tables_or_blocks(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.scanned_pdf(pages=2))
    fake_llm.queue(
        PageAnalysis(
            text="noise",
            legible=False,
            tables=[VisionTable(header=[], rows=[["a", "b"]])],
            blocks=[],
        ),
        _page("page two"),
    )

    text_service.extract_text(db_session, storage, fake_llm, document_id)

    layout = service.find_layout(db_session, document_id)
    assert layout is not None
    assert [t.pages for t in layout.tables] == [[2]]
    assert {b.page for b in layout.blocks} == {2}


# -- Text PDFs: extract_tables (PRD D3, D7, D9) --------------------------------------------


def test_extract_tables_analyses_a_text_pdf_without_an_llm(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.invoice_pdf())

    summary = service.extract_tables(
        db_session, storage, document_id, method=ExtractionMethod.PDF_PARSER
    )

    assert fake_llm.calls == []
    assert summary.available and not summary.reused
    assert summary.source is ExtractionMethod.PDF_PARSER
    assert summary.line_item_table
    assert [(t.kind, t.rows) for t in summary.tables] == [(TableKind.LINE_ITEMS, 3)]
    assert summary.blocks["totals"] == 1
    assert "Widget" not in summary.model_dump_json()  # counts and shapes only
    assert _layout_count(db_session) == 1


def test_extract_tables_reuses_the_newest_row_unless_forced(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.invoice_pdf())
    method = ExtractionMethod.PDF_PARSER

    service.extract_tables(db_session, storage, document_id, method=method)
    again = service.extract_tables(db_session, storage, document_id, method=method)
    forced = service.extract_tables(db_session, storage, document_id, method=method, force=True)

    assert again.reused
    assert not forced.reused
    assert _layout_count(db_session) == 2  # history kept, newest is current
    response = service.get_layout(db_session, document_id)
    assert len(response.history) == 1
    assert response.history[0].created_at < response.created_at


def test_extract_tables_for_a_scan_reads_the_vision_row(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.scanned_png())
    fake_llm.queue(_page())
    text_service.extract_text(db_session, storage, fake_llm, document_id)

    summary = service.extract_tables(
        db_session, storage, document_id, method=ExtractionMethod.VISION, force=True
    )

    assert len(fake_llm.calls) == 1  # no extra LLM call
    assert summary.available and summary.reused and summary.line_item_table
    assert _layout_count(db_session) == 1


def test_extract_tables_for_a_scan_analysed_before_0009_is_unavailable(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.scanned_png())

    summary = service.extract_tables(
        db_session, storage, document_id, method=ExtractionMethod.VISION
    )

    assert not summary.available
    assert summary.tables == []


def test_a_layout_made_inside_a_run_is_linked_to_it(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.invoice_pdf())
    run_id = _insert_run(db_session, document_id)

    with bind_trace(run_id=str(run_id)):
        service.extract_tables(db_session, storage, document_id, method=ExtractionMethod.PDF_PARSER)

    layout = service.find_layout(db_session, document_id)
    assert layout is not None and layout.run_id == run_id


def test_extract_tables_raises_not_found_for_an_unknown_document(
    db_session: Session, storage: LocalStorage
) -> None:
    with pytest.raises(NotFoundError):
        service.extract_tables(
            db_session, storage, uuid.uuid4(), method=ExtractionMethod.PDF_PARSER
        )


# -- get_layout ------------------------------------------------------------------------------


def test_get_layout_explains_why_there_is_none(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.invoice_pdf())

    with pytest.raises(ConflictError) as processing:
        service.get_layout(db_session, document_id)
    documents_service.mark_failed(db_session, document_id, "boom")
    db_session.commit()
    with pytest.raises(ConflictError) as finished:
        service.get_layout(db_session, document_id)

    assert processing.value.code == "layout_not_ready"
    assert finished.value.code == "layout_unavailable"


# -- Page images ------------------------------------------------------------------------------


def test_render_page_image_returns_a_jpeg_per_pdf_page(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.invoice_pdf(samples.long_invoice_spec(60)))

    jpeg = service.render_page_image(db_session, storage, document_id, 3)

    image = Image.open(io.BytesIO(jpeg))
    assert image.format == "JPEG"
    assert max(image.size) == 1600
    with pytest.raises(NotFoundError) as caught:
        service.render_page_image(db_session, storage, document_id, 4)
    assert caught.value.code == "page_not_found"


def test_an_image_has_only_page_one(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    document_id = make_document(PNG, samples.scanned_png())

    assert service.render_page_image(db_session, storage, document_id, 1)
    with pytest.raises(NotFoundError):
        service.render_page_image(db_session, storage, document_id, 2)


def test_page_images_are_the_vision_jpegs(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.scanned_pdf(pages=3))

    pages = service.page_images(db_session, storage, document_id, max_pages=2)

    assert len(pages) == 2
    assert all(Image.open(io.BytesIO(p)).format == "JPEG" for p in pages)


# -- Stats -------------------------------------------------------------------------------------


def test_layout_stats_count_the_newest_analysis_per_document(
    db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    with_table = make_document(PDF, samples.invoice_pdf())
    from tests.modules.text_extraction import samples as text_samples

    without = make_document(PDF, text_samples.text_pdf())
    method = ExtractionMethod.PDF_PARSER
    service.extract_tables(db_session, storage, with_table, method=method)
    service.extract_tables(db_session, storage, with_table, method=method, force=True)
    service.extract_tables(db_session, storage, without, method=method)

    stats = service.layout_stats(db_session)
    future = service.layout_stats(db_session, since=datetime.now(UTC) + timedelta(days=1))

    assert stats.layouts_analysed == 2
    assert stats.documents_with_line_item_table == 1
    assert stats.tables_found == 1
    assert future.layouts_analysed == 0


# -- Layering ------------------------------------------------------------------------------------


def test_vision_imports_no_other_module_crud_model_or_calling_service() -> None:
    module_dir = Path(service.__file__).parent
    offenders: list[str] = []
    for path in module_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module} | {f"{node.module}.{alias.name}" for alias in node.names}
            else:
                continue
            for name in names:
                if not name.startswith("app.modules.") or name.startswith("app.modules.vision"):
                    continue
                if name.endswith((".crud", ".model")) or name in {
                    "app.modules.text_extraction.service",
                    "app.modules.structured_extraction.service",
                    "app.modules.guardrails.service",
                    "app.modules.agent.service",
                }:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == []


def test_service_does_not_import_fastapi() -> None:
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "fastapi" not in source
