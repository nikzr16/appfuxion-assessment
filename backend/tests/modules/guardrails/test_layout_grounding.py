"""Layout-aware grounding: the total and the totals block (PRD 0009 D8)."""

from typing import Any

from app.modules.guardrails import service
from app.modules.guardrails.schema import GroundingStatus
from app.modules.structured_extraction.schema import InvoiceData
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.vision.schema import BlockType, LayoutAnalysis, LayoutBlock, PageInfo

PDF = ExtractionMethod.PDF_PARSER


def _data(total: str) -> InvoiceData:
    values: dict[str, Any] = {
        "document_type": "invoice",
        "vendor": None,
        "vendor_address": None,
        "vendor_tax_id": None,
        "customer_name": None,
        "customer_address": None,
        "invoice_number": None,
        "invoice_date": None,
        "due_date": None,
        "payment_terms": None,
        "currency": None,
        "subtotal": None,
        "tax": None,
        "total_amount": total,
        "line_items": [],
    }
    return InvoiceData.model_validate(values)


def _layout(*blocks: tuple[BlockType, str]) -> LayoutAnalysis:
    return LayoutAnalysis(
        source=PDF,
        layout_version="layout.v1",
        page_count=1,
        pages=[PageInfo(page=1, width=595, height=842)],
        tables=[],
        blocks=[
            LayoutBlock(type=kind, page=1, order=i, text=text, box=(0.5, 0.4, 0.9, 0.5))
            for i, (kind, text) in enumerate(blocks)
        ],
    )


def _total(raw_text: str, total: str, layout: LayoutAnalysis | None) -> Any:
    report = service.check_grounding(_data(total), raw_text, PDF, layout=layout)
    return next(f for f in report.fields if f.path == "total_amount")


def test_a_total_inside_the_totals_block_is_located_there() -> None:
    raw = "Widget 50.00\nSubtotal 50.00\nTotal 55.00"
    layout = _layout((BlockType.TOTALS, "Subtotal 50.00\nTotal 55.00"))

    field = _total(raw, "55.00", layout)

    assert field.status is GroundingStatus.GROUNDED
    assert field.location is not None
    assert field.location.block is BlockType.TOTALS
    assert field.location.box == (0.5, 0.4, 0.9, 0.5)


def test_a_total_found_only_away_from_a_total_label_is_weak() -> None:
    # The model took a line amount as the total; the totals block says otherwise.
    raw = "Widget 50.00\nGadget 5.00\nTotal 55.00"
    layout = _layout((BlockType.TOTALS, "Total 55.00"))

    field = _total(raw, "50.00", layout)

    assert field.status is GroundingStatus.WEAK
    assert field.note == service.NOT_NEXT_TO_TOTAL


def test_a_total_on_a_labelled_line_outside_the_block_keeps_its_status() -> None:
    raw = "Amount due: 55.00\nTotal 55.00"
    layout = _layout((BlockType.TOTALS, "Rounding 0.00"))

    field = _total(raw, "55.00", layout)

    assert field.status is GroundingStatus.GROUNDED


def test_without_a_totals_block_the_0008_result_stands() -> None:
    raw = "Widget 50.00\nTotal 55.00"

    with_layout = _total(raw, "50.00", _layout((BlockType.HEADER, "ACME")))
    without = _total(raw, "50.00", None)

    assert with_layout.status is without.status is GroundingStatus.GROUNDED
    assert with_layout.location is None
