import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.text_extraction.schema import ExtractionMethod

# x0, y0, x1, y1 as fractions of the page (0-1), origin at the top-left corner.
Box = tuple[float, float, float, float]


class BlockType(StrEnum):
    HEADER = "header"
    DOCUMENT_INFO = "document_info"
    BILL_TO = "bill_to"
    LINE_ITEMS = "line_items"
    TOTALS = "totals"
    PAYMENT = "payment"
    OTHER = "other"


class TableKind(StrEnum):
    LINE_ITEMS = "line_items"
    OTHER = "other"


class ColumnRole(StrEnum):
    DESCRIPTION = "description"
    QUANTITY = "quantity"
    UNIT_PRICE = "unit_price"
    AMOUNT = "amount"
    OTHER = "other"


class TableStrategy(StrEnum):
    LINES = "lines"
    TEXT = "text"
    VISION = "vision"


class PageInfo(BaseModel):
    """One page's size: PDF points for ``pdf_parser``, rendered pixels for ``vision``."""

    page: int
    width: float
    height: float


class TableRow(BaseModel):
    page: int
    cells: list[str | None]
    box: Box | None = None
    cell_boxes: list[Box | None] | None = None


class Table(BaseModel):
    index: int
    pages: list[int]
    box: Box | None = None
    strategy: TableStrategy
    header: list[str | None] | None = None
    columns: list[ColumnRole]
    kind: TableKind
    rows: list[TableRow]


class LayoutBlock(BaseModel):
    type: BlockType
    page: int
    order: int
    text: str
    box: Box | None = None


class LayoutAnalysis(BaseModel):
    """The result of one analysis, as stored in ``document_layouts`` (PRD D9)."""

    source: ExtractionMethod
    layout_version: str
    page_count: int
    pages: list[PageInfo]
    tables: list[Table]
    blocks: list[LayoutBlock]
    model: str | None = None


class LayoutRead(LayoutAnalysis):
    """Internal DTO: one ``document_layouts`` row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    run_id: uuid.UUID | None
    created_at: datetime


class LayoutHistoryItem(BaseModel):
    layout_id: uuid.UUID
    created_at: datetime
    source: ExtractionMethod
    layout_version: str
    run_id: uuid.UUID | None


class LayoutResponse(BaseModel):
    """Body of ``GET /api/documents/{document_id}/layout``: the newest analysis."""

    document_id: uuid.UUID
    layout_id: uuid.UUID
    source: ExtractionMethod
    layout_version: str
    run_id: uuid.UUID | None
    created_at: datetime
    page_count: int
    pages: list[PageInfo]
    tables: list[Table]
    blocks: list[LayoutBlock]
    # Earlier analyses of the same document, newest first (metadata only).
    history: list[LayoutHistoryItem]


class TableRef(BaseModel):
    """Where one table-derived line item was printed."""

    table: int
    row: int
    page: int
    box: Box | None = None
    cell_boxes: list[Box | None] | None = None
    columns: list[ColumnRole]


class TableItem(BaseModel):
    """One line item copied from a table row by code (printed values only)."""

    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None


class TableLineItems(BaseModel):
    """Line items copied from a table by code, with one ``TableRef`` per item."""

    items: list[TableItem]
    refs: list[TableRef]


class TableSummary(BaseModel):
    index: int
    pages: list[int]
    kind: TableKind
    columns: list[ColumnRole]
    rows: int


class TablesSummary(BaseModel):
    """What the ``extract_tables`` agent tool returns: counts and shapes, never cell text."""

    source: ExtractionMethod
    available: bool
    pages: int
    tables: list[TableSummary]
    line_item_table: bool
    blocks: dict[str, int]
    reused: bool


class LayoutStats(BaseModel):
    """Layout numbers for the ``vision`` metrics block (newest analysis per document)."""

    layouts_analysed: int
    documents_with_line_item_table: int
    tables_found: int


# -- LLM output (strict structured output: every field required) ----------------------


class VisionTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: list[str] = Field(description="Column titles as printed; [] when there are none.")
    rows: list[list[str]] = Field(
        description="Each printed body row's cells in order, copied exactly; '' for an empty cell."
    )


class VisionBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "header", "document_info", "bill_to", "line_items", "totals", "payment", "other"
    ] = Field(description="The kind of area this block is.")
    text: str = Field(description="The block's text, copied exactly as printed.")


class PageAnalysis(BaseModel):
    """Structured output of one vision call per page: text, tables and blocks (PRD D2)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The page's text, copied exactly as printed.")
    legible: bool = Field(description="False only when no text on the page can be read.")
    tables: list[VisionTable] = Field(description="Every table on the page, in order.")
    blocks: list[VisionBlock] = Field(description="The page's blocks in reading order.")
