"""Deterministic table and block analysis of text PDFs (PRD 0009 D3, D4, D5)."""

from decimal import Decimal

import pytest

from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.vision import layout
from app.modules.vision.schema import BlockType, ColumnRole, TableKind, TableStrategy
from tests.modules.vision import samples

ROLES = [ColumnRole.DESCRIPTION, ColumnRole.QUANTITY, ColumnRole.UNIT_PRICE, ColumnRole.AMOUNT]
ROWS = [
    ["Widget A", "2", "100.00", "200.00"],
    ["Installation service", "1", "350.00", "350.00"],
    ["Cable 5m", "10", "12.50", "125.00"],
]


def _within(box: tuple[float, float, float, float] | None) -> bool:
    return box is not None and all(0 <= v <= 1 for v in box) and box[0] < box[2] and box[1] < box[3]


# -- Tables ------------------------------------------------------------------------------


def test_ruled_table_is_found_with_header_roles_and_boxes() -> None:
    analysis = layout.analyse_pdf(samples.invoice_pdf())

    assert analysis.source is ExtractionMethod.PDF_PARSER
    assert analysis.layout_version == "layout.v1"
    assert analysis.page_count == 1
    assert analysis.pages[0].width == pytest.approx(samples.PAGE_WIDTH, abs=0.01)
    [table] = analysis.tables
    assert table.strategy is TableStrategy.LINES
    assert table.kind is TableKind.LINE_ITEMS
    assert table.header == list(samples.HEADER)
    assert table.columns == ROLES
    assert [row.cells for row in table.rows] == ROWS
    assert table.pages == [1]
    # The table's box matches where it was drawn (x 50..545 of a 595-point page).
    assert table.box is not None
    assert table.box[0] == pytest.approx(50 / samples.PAGE_WIDTH, abs=0.002)
    assert table.box[2] == pytest.approx(545 / samples.PAGE_WIDTH, abs=0.002)
    assert all(_within(row.box) for row in table.rows)
    assert all(row.cell_boxes and len(row.cell_boxes) == 4 for row in table.rows)


def test_unruled_table_is_cut_at_the_header_columns_and_stops_at_the_totals() -> None:
    analysis = layout.analyse_pdf(samples.invoice_pdf(samples.InvoiceSpec(ruled=False)))

    [table] = analysis.tables
    assert table.strategy is TableStrategy.TEXT
    assert table.columns == ROLES
    assert [row.cells for row in table.rows] == ROWS  # no Subtotal / Total rows
    assert all(_within(row.box) for row in table.rows)


def test_wrapped_description_continues_the_previous_row() -> None:
    spec = samples.InvoiceSpec(ruled=False, wrapped={1: "for 2 rooms"})

    [table] = layout.analyse_pdf(samples.invoice_pdf(spec)).tables

    assert table.rows[1].cells == ["Installation service for 2 rooms", "1", "350.00", "350.00"]
    assert len(table.rows) == 3


def test_wrapped_text_inside_a_ruled_cell_is_joined_with_spaces() -> None:
    spec = samples.InvoiceSpec(wrapped={0: "blue colour"})

    [table] = layout.analyse_pdf(samples.invoice_pdf(spec)).tables

    assert table.rows[0].cells[0] == "Widget A blue colour"


def test_merged_cell_keeps_its_value_in_the_first_cell() -> None:
    spec = samples.InvoiceSpec(section_row=(1, "Services"))

    [table] = layout.analyse_pdf(samples.invoice_pdf(spec)).tables

    assert table.rows[1].cells == ["Services", None, None, None]
    assert len(table.rows) == 4


def test_malay_header_maps_to_the_same_roles() -> None:
    spec = samples.InvoiceSpec(header=samples.MALAY_HEADER, ruled=False)

    [table] = layout.analyse_pdf(samples.invoice_pdf(spec)).tables

    assert table.columns == ROLES
    assert table.kind is TableKind.LINE_ITEMS


@pytest.mark.parametrize("ruled", [True, False])
def test_a_table_continued_on_the_next_pages_is_stitched(ruled: bool) -> None:
    spec = samples.long_invoice_spec(60)
    spec.ruled = ruled

    analysis = layout.analyse_pdf(samples.invoice_pdf(spec))

    assert analysis.page_count == 3
    [table] = analysis.tables
    assert table.pages == [1, 2, 3]
    assert len(table.rows) == 60  # the repeated header rows were dropped
    assert table.rows[0].cells[0] == "Spare part 0001 model X1"
    assert table.rows[-1].cells[0] == "Spare part 0060 model X4"
    assert {row.page for row in table.rows} == {1, 2, 3}


def test_a_pdf_without_a_table_has_none() -> None:
    from tests.modules.text_extraction import samples as text_samples

    analysis = layout.analyse_pdf(text_samples.text_pdf())

    assert analysis.tables == []
    assert analysis.blocks  # its lines still form blocks


@pytest.mark.parametrize(
    ("title", "role"),
    [
        ("Description", ColumnRole.DESCRIPTION),
        ("Item", ColumnRole.DESCRIPTION),
        ("Qty", ColumnRole.QUANTITY),
        ("Kuantiti", ColumnRole.QUANTITY),
        ("Unit Price", ColumnRole.UNIT_PRICE),
        ("Harga Seunit", ColumnRole.UNIT_PRICE),
        ("Amount (RM)", ColumnRole.AMOUNT),
        ("Line Total", ColumnRole.AMOUNT),
        ("Jumlah", ColumnRole.AMOUNT),
        ("SKU", None),
        (None, None),
    ],
)
def test_column_role(title: str | None, role: ColumnRole | None) -> None:
    assert layout.column_role(title) is role


# -- Blocks ------------------------------------------------------------------------------


def test_blocks_are_typed_ordered_and_placed() -> None:
    analysis = layout.analyse_pdf(samples.invoice_pdf())

    types = [block.type for block in analysis.blocks]
    assert types == [
        BlockType.HEADER,
        BlockType.DOCUMENT_INFO,
        BlockType.BILL_TO,
        BlockType.LINE_ITEMS,
        BlockType.TOTALS,
        BlockType.PAYMENT,
    ]
    assert [block.order for block in analysis.blocks] == list(range(6))
    assert all(_within(block.box) for block in analysis.blocks)
    by_type = {block.type: block for block in analysis.blocks}
    assert by_type[BlockType.HEADER].text.startswith("Acme Trading Sdn Bhd")
    assert "Invoice No: INV-2026-001" in by_type[BlockType.DOCUMENT_INFO].text
    assert by_type[BlockType.TOTALS].text.splitlines() == [
        "Subtotal 675.00",
        "SST 8% 54.00",
        "Total (RM) 729.00",
    ]
    # The vendor header (left) and the document info (right) sit side by side.
    header_box = by_type[BlockType.HEADER].box
    info_box = by_type[BlockType.DOCUMENT_INFO].box
    assert header_box is not None and info_box is not None
    assert header_box[2] < info_box[0]


# -- Numbers and line items --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "comma", "expected"),
    [
        ("1,234.56", False, Decimal("1234.56")),
        ("1.234,56", True, Decimal("1234.56")),
        ("RM 200.00", False, Decimal("200.00")),
        ("(50.00)", False, Decimal("-50.00")),
        ("-12.5", False, Decimal("-12.5")),
        ("2 pcs", False, Decimal("2")),
        ("", False, None),
        (None, False, None),
        ("N/A", False, None),
        ("1.2.3", False, None),
    ],
)
def test_parse_cell_number(text: str | None, comma: bool, expected: Decimal | None) -> None:
    assert layout.parse_cell_number(text, decimal_comma=comma) == expected


def test_comma_decimal_is_decided_by_most_cells() -> None:
    assert layout.comma_decimal(["1.234,56", "12,00", "100.00"])
    assert not layout.comma_decimal(["1,234.56", "12.00", "3"])


def test_line_items_come_from_the_table_with_refs() -> None:
    analysis = layout.analyse_pdf(
        samples.invoice_pdf(samples.InvoiceSpec(section_row=(1, "Services")))
    )

    result = layout.line_items_from_tables(analysis.tables)

    assert result is not None
    assert [(i.description, i.quantity, i.unit_price, i.amount) for i in result.items] == [
        ("Widget A", Decimal("2"), Decimal("100.00"), Decimal("200.00")),
        ("Installation service", Decimal("1"), Decimal("350.00"), Decimal("350.00")),
        ("Cable 5m", Decimal("10"), Decimal("12.50"), Decimal("125.00")),
    ]
    # The section heading (row 1) is skipped; refs point at the printed rows.
    assert [ref.row for ref in result.refs] == [0, 2, 3]
    assert all(ref.table == 0 and ref.page == 1 and _within(ref.box) for ref in result.refs)


def test_a_totals_row_inside_the_table_ends_the_items() -> None:
    table = layout.table_from_vision(
        0,
        1,
        ["Item", "Amount"],
        [["Widget", "10.00"], ["Subtotal", "10.00"], ["Total", "10.00"]],
    )
    assert table is not None

    result = layout.line_items_from_tables([table])

    assert result is not None
    assert [i.description for i in result.items] == ["Widget"]


def test_no_line_items_without_a_confident_mapping() -> None:
    table = layout.table_from_vision(0, 1, ["Code", "Qty"], [["A1", "2"]])
    assert table is not None
    assert table.kind is TableKind.OTHER
    assert layout.line_items_from_tables([table]) is None


def test_vision_tables_are_padded_and_stitched_by_header() -> None:
    first = layout.table_from_vision(0, 1, ["Item", "Qty", "Amount"], [["A", "1", "5.00"]])
    second = layout.table_from_vision(1, 2, ["Item", "Qty", "Amount"], [["B", "2"]])
    assert first is not None and second is not None

    [joined] = layout.stitch_vision_tables([first, second])

    assert joined.pages == [1, 2]
    assert [row.cells for row in joined.rows] == [["A", "1", "5.00"], ["B", "2", None]]
    assert joined.strategy is TableStrategy.VISION
    assert joined.box is None


def test_a_vision_table_with_one_column_is_ignored() -> None:
    assert layout.table_from_vision(0, 1, ["Notes"], [["Thank you"]]) is None
    assert layout.table_from_vision(0, 1, ["Item", "Qty"], []) is None
