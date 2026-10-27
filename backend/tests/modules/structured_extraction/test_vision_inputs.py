"""Feature 0009 inputs to structured extraction: tables in the prompt, line items copied from
the table for text PDFs, page images for scans, and layout-aware grounding."""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.llm import FakeLLM, LLMCall, Purpose
from app.core.storage import LocalStorage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import UploadedFile
from app.modules.guardrails.schema import GroundingStatus, MatchKind
from app.modules.structured_extraction import service
from app.modules.structured_extraction.schema import InvoiceData
from app.modules.text_extraction import service as text_service
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.vision import service as vision_service
from app.modules.vision.schema import (
    BlockType,
    ColumnRole,
    LayoutAnalysis,
    LayoutBlock,
    PageAnalysis,
    PageInfo,
    Table,
    TableKind,
    TableRow,
    TableStrategy,
    VisionBlock,
    VisionTable,
)
from tests.modules.structured_extraction.conftest import MakeDocument
from tests.modules.vision import samples

TABLE_ITEMS = [
    ("Widget A", "2", "100.00", "200.00"),
    ("Installation service", "1", "350.00", "350.00"),
    ("Cable 5m", "10", "12.50", "125.00"),
]


def acme(**overrides: Any) -> InvoiceData:
    """A valid reply for ``samples.invoice_pdf()`` with only one (wrong) line item."""
    data: dict[str, Any] = {
        "document_type": "invoice",
        "vendor": "Acme Trading Sdn Bhd",
        "vendor_address": "12 Jalan Ampang, 50450 Kuala Lumpur",
        "vendor_tax_id": "W10-1808-32000123",
        "customer_name": "Kedai Maju Enterprise",
        "customer_address": None,
        "invoice_number": "INV-2026-001",
        "invoice_date": "2026-10-15",
        "due_date": "2026-11-14",
        "payment_terms": "Net 30",
        "currency": "MYR",
        "subtotal": "675.00",
        "tax": "54.00",
        "total_amount": "729.00",
        "line_items": [
            {"description": "Widget A", "quantity": "2", "unit_price": "100.00", "amount": "999.00"}
        ],
    }
    data.update(overrides)
    return InvoiceData.model_validate(data)


def _upload(db: Session, storage: LocalStorage, content_type: str, data: bytes) -> uuid.UUID:
    name = "invoice.png" if content_type == "image/png" else "invoice.pdf"
    upload = UploadedFile(filename=name, content_type=content_type, data=data)
    return documents_service.create_document(db, storage, upload).document_id


def _text_pdf_with_tables(db: Session, storage: LocalStorage, fake_llm: FakeLLM) -> uuid.UUID:
    document_id = _upload(db, storage, "application/pdf", samples.invoice_pdf())
    text_service.extract_text(db, storage, fake_llm, document_id)
    vision_service.extract_tables(db, storage, document_id, method=ExtractionMethod.PDF_PARSER)
    return document_id


def _user_text(call: LLMCall) -> str:
    content = call.messages[1]["content"]
    return content if isinstance(content, str) else content[0]["text"]


def _image_parts(call: LLMCall) -> list[dict[str, Any]]:
    content = call.messages[1]["content"]
    return [] if isinstance(content, str) else [p for p in content if p["type"] == "image_url"]


# -- Text PDFs: tables in the prompt, line items from the table (D5) -----------------------


def test_text_pdf_line_items_are_copied_from_the_table(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM
) -> None:
    document_id = _text_pdf_with_tables(db_session, storage, fake_llm)
    fake_llm.queue(acme())

    result = service.extract_structured_data(db_session, fake_llm, document_id, storage=storage)

    assert result.line_items_source == "table"
    assert [
        (i.description, str(i.quantity), str(i.unit_price), str(i.amount))
        for i in result.data.line_items
    ] == TABLE_ITEMS
    assert result.data.vendor == "Acme Trading Sdn Bhd"  # header fields stay the model's
    [call] = fake_llm.calls
    prompt = _user_text(call)
    assert "<tables>" in prompt
    assert (
        "Table 1 (page 1, line items; columns: Description | Qty | Unit Price | Amount)" in prompt
    )
    assert "Cable 5m | 10 | 12.50 | 125.00" in prompt
    assert _image_parts(call) == []  # text PDFs never send images


def test_without_a_layout_the_model_keeps_its_line_items(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(acme())

    result = service.extract_structured_data(db_session, fake_llm, document_id)

    assert result.line_items_source == "model"
    assert len(result.data.line_items) == 1
    assert "<tables>" not in _user_text(fake_llm.calls[0])


def _long_table_layout(count: int) -> LayoutAnalysis:
    rows = [
        TableRow(page=1 + n // 40, cells=[f"Part {n:04d}", "1", "1.00", "1.00"], box=None)
        for n in range(count)
    ]
    return LayoutAnalysis(
        source=ExtractionMethod.PDF_PARSER,
        layout_version="layout.v1",
        page_count=1 + count // 40,
        pages=[PageInfo(page=p, width=595, height=842) for p in range(1, 2 + count // 40)],
        tables=[
            Table(
                index=0,
                pages=sorted({row.page for row in rows}),
                strategy=TableStrategy.LINES,
                header=["Description", "Qty", "Unit Price", "Amount"],
                columns=[
                    ColumnRole.DESCRIPTION,
                    ColumnRole.QUANTITY,
                    ColumnRole.UNIT_PRICE,
                    ColumnRole.AMOUNT,
                ],
                kind=TableKind.LINE_ITEMS,
                rows=rows,
            )
        ],
        blocks=[],
    )


def test_a_long_text_pdf_keeps_its_middle_line_items(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    # 0003 cut text over 60,000 characters to its head and tail; the table is read whole.
    lines = [f"Part {n:04d} | 1 | 1.00 | 1.00 {'x' * 60}" for n in range(1200)]
    document_id = make_document("ACME\n" + "\n".join(lines) + "\nTotal RM 1200.00")
    vision_service.save_layout(db_session, document_id, _long_table_layout(1200))
    db_session.commit()
    fake_llm.queue(acme())

    result = service.extract_structured_data(db_session, fake_llm, document_id)

    assert "characters omitted" in _user_text(fake_llm.calls[0])
    assert len(result.data.line_items) == 1200
    assert result.data.line_items[600].description == "Part 0600"


# -- Scans: images sent, model's line items kept (D5, D6) -----------------------------------


def _scan(db: Session, storage: LocalStorage, fake_llm: FakeLLM) -> uuid.UUID:
    document_id = _upload(db, storage, "image/png", samples.scanned_png())
    fake_llm.queue(
        PageAnalysis(
            text="\n".join(samples.SCAN_LINES),
            legible=True,
            tables=[
                VisionTable(
                    header=["Description", "Qty", "Unit Price", "Amount"],
                    rows=[["Widget A", "2", "100.00", "200.00"]],
                )
            ],
            blocks=[VisionBlock(type="totals", text="Total (RM) 200.00")],
        )
    )
    text_service.extract_text(db, storage, fake_llm, document_id)
    vision_service.extract_tables(db, storage, document_id, method=ExtractionMethod.VISION)
    return document_id


def scan_reply(**overrides: Any) -> InvoiceData:
    values: dict[str, Any] = {
        "vendor_address": None,
        "vendor_tax_id": None,
        "customer_name": None,
        "due_date": None,
        "payment_terms": None,
        "invoice_date": None,
        "subtotal": None,
        "tax": None,
        "total_amount": "200.00",
        "line_items": [
            {"description": "Widget A", "quantity": "2", "unit_price": "100.00", "amount": "200.00"}
        ],
    }
    values.update(overrides)
    return acme(**values)


def test_scan_extraction_sends_page_images_and_is_labelled_multimodal(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM, llm_recorder: None
) -> None:
    document_id = _scan(db_session, storage, fake_llm)
    fake_llm.queue(scan_reply())

    result = service.extract_structured_data(db_session, fake_llm, document_id, storage=storage)

    call = fake_llm.calls[-1]
    [image] = _image_parts(call)
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert image["image_url"]["detail"] == "high"
    assert "<tables>" in _user_text(call)  # the vision table is a hint
    assert result.line_items_source == "model"
    purposes = db_session.execute(
        text("SELECT purpose FROM llm_calls ORDER BY started_at")
    ).scalars()
    assert list(purposes) == [
        Purpose.VISION_TRANSCRIPTION.value,
        Purpose.MULTIMODAL_EXTRACTION.value,
    ]


def test_scan_without_storage_sends_text_only(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM
) -> None:
    document_id = _scan(db_session, storage, fake_llm)
    fake_llm.queue(scan_reply())

    service.extract_structured_data(db_session, fake_llm, document_id)

    assert _image_parts(fake_llm.calls[-1]) == []


def test_grounding_retries_of_a_scan_send_the_images_too(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM
) -> None:
    document_id = _scan(db_session, storage, fake_llm)
    fake_llm.queue(scan_reply(vendor="Invented Vendor Bhd"), scan_reply())
    service.extract_structured_data(db_session, fake_llm, document_id, storage=storage)

    result = service.ground_extraction(db_session, fake_llm, document_id, storage=storage)

    assert result.grounding is not None and result.grounding.grounding_retries == 1
    assert len(_image_parts(fake_llm.calls[-1])) == 1


# -- Layout-aware grounding (D8) --------------------------------------------------------------


def test_table_line_items_are_grounded_at_their_cells(
    db_session: Session, storage: LocalStorage, fake_llm: FakeLLM
) -> None:
    document_id = _text_pdf_with_tables(db_session, storage, fake_llm)
    fake_llm.queue(acme())
    service.extract_structured_data(db_session, fake_llm, document_id, storage=storage)

    result = service.ground_extraction(db_session, fake_llm, document_id, storage=storage)

    assert result.grounding is not None
    fields = {f.path: f for f in result.grounding.report.fields}
    amount = fields["line_items[2].amount"]
    assert amount.status is GroundingStatus.GROUNDED
    assert amount.match is MatchKind.TABLE
    assert amount.note == "Read from table 1, row 3"
    assert amount.location is not None
    assert (amount.location.table, amount.location.row) == (0, 2)
    assert amount.location.column is ColumnRole.AMOUNT
    assert amount.location.box is not None
    assert amount.start is not None  # the text span is kept for "Show in text"
    total = fields["total_amount"]
    assert total.status is GroundingStatus.GROUNDED
    assert total.location is not None and total.location.block is BlockType.TOTALS
    assert result.data.line_items[2].amount == Decimal("125.00")


def test_a_layout_without_a_totals_block_leaves_the_total_as_in_0008(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    vision_service.save_layout(
        db_session,
        document_id,
        LayoutAnalysis(
            source=ExtractionMethod.PDF_PARSER,
            layout_version="layout.v1",
            page_count=1,
            pages=[PageInfo(page=1, width=595, height=842)],
            tables=[],
            blocks=[LayoutBlock(type=BlockType.HEADER, page=1, order=0, text="ACME", box=None)],
        ),
    )
    db_session.commit()
    from tests.modules.structured_extraction.conftest import invoice

    fake_llm.queue(invoice())
    service.extract_structured_data(db_session, fake_llm, document_id)

    result = service.ground_extraction(db_session, fake_llm, document_id)

    assert result.grounding is not None
    total = next(f for f in result.grounding.report.fields if f.path == "total_amount")
    assert total.status is GroundingStatus.GROUNDED
    assert total.location is None
