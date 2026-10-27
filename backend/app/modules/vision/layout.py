"""Deterministic table and layout analysis of text PDFs with ``pdfplumber`` (PRD 0009 D3, D4).

Pure helpers: no DB, no LLM. Same input, same output.

Tables come from two detectors: ruled tables through pdfplumber's ``lines`` strategy, and
unruled tables through a header-anchored word-column detector (a keyword header row gives
the column positions; the rows below are cut at those positions). Blocks come from the
page's words: lines → segments (split at wide gaps) → blocks (stacked segments), classified
by label keywords and position.
"""

import io
import itertools
import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import pdfplumber
from pdfplumber.page import Page

from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.vision.schema import (
    BlockType,
    Box,
    ColumnRole,
    LayoutAnalysis,
    LayoutBlock,
    PageInfo,
    Table,
    TableItem,
    TableKind,
    TableLineItems,
    TableRef,
    TableRow,
    TableStrategy,
)

LAYOUT_VERSION = "layout.v1"

# Words whose tops are this close (points) are on the same line.
LINE_TOLERANCE = 3.0
# A horizontal gap wider than this many median character widths starts a new segment.
SEGMENT_GAP_CHARS = 2.0
# A segment joins the block above when the vertical gap is below this many line heights.
BLOCK_GAP_LINES = 1.2
# An unruled table ends at a vertical gap wider than this many median row pitches.
TABLE_GAP_ROWS = 3.0
# Tables are stitched across pages when the first ends in the bottom part of its page and
# the next starts in the top part of the next page (fractions of the page height).
STITCH_EDGE = 0.30
# Without a table, the header block must start in the top part of page 1.
HEADER_TOP = 0.30


# -- Keywords ---------------------------------------------------------------------------

# Column titles (English + Malay), checked in this order; matched as whole words.
_COLUMN_KEYWORDS: tuple[tuple[ColumnRole, tuple[str, ...]], ...] = (
    (
        ColumnRole.DESCRIPTION,
        (
            "description",
            "item",
            "items",
            "product",
            "products",
            "service",
            "services",
            "particulars",
            "details",
            "perkara",
            "butiran",
            "keterangan",
            "barang",
        ),
    ),
    (
        ColumnRole.UNIT_PRICE,
        ("unit price", "price", "rate", "unit cost", "harga seunit", "harga unit", "harga"),
    ),
    (ColumnRole.QUANTITY, ("qty", "quantity", "units", "kuantiti", "kuantiti unit", "unit count")),
    (ColumnRole.AMOUNT, ("amount", "total", "line total", "subtotal", "jumlah", "amaun")),
)

_TOTALS_LABEL = re.compile(
    r"^\s*(sub[\s-]?total|grand\s+total|total|tax|sst|gst|vat|service\s+(tax|charge)|"
    r"amount\s+due|balance\s+due|rounding|discount|jumlah\s+besar|jumlah|cukai)\b",
    re.IGNORECASE,
)
_BILL_TO = re.compile(
    r"\b(bill(ed)?\s+to|sold\s+to|ship\s+to|customer|kepada|dibilkan\s+kepada)\b", re.IGNORECASE
)
_DOCUMENT_INFO = re.compile(
    r"\b(invoice\s*(no|number|#)|receipt\s*(no|number|#)|inv\s*no|date|due\s+date|po\s*(no|#)|"
    r"tarikh|no\.?\s*invois|no\.?\s*resit|invoice|receipt|resit|invois)\b",
    re.IGNORECASE,
)
_PAYMENT = re.compile(
    r"\b(bank|account|acc\s*no|payment|terms|swift|akaun|pembayaran)\b", re.IGNORECASE
)
_NUMBER_AT_END = re.compile(r"[\d][\d.,]*\)?\s*$")
_COMMA_DECIMAL = re.compile(r"\d,\d{2}\)?$")
_DOT_DECIMAL = re.compile(r"\d\.\d{2}\)?$")
_NUMBER_CHARS = re.compile(r"[^\d.,()\-]")
_PLAIN_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def _normalise_title(text: str) -> str:
    text = re.sub(r"\(.*?\)", " ", text.casefold())
    return " ".join(re.findall(r"[a-z#]+", text))


def column_role(title: str | None) -> ColumnRole | None:
    """The role a header cell names, or ``None`` when it is no known column title."""
    if not title:
        return None
    normalised = f" {_normalise_title(title)} "
    for role, keywords in _COLUMN_KEYWORDS:
        if any(f" {keyword} " in normalised for keyword in keywords):
            return role
    return None


def _roles(header: Sequence[str | None]) -> list[ColumnRole]:
    roles = [column_role(cell) or ColumnRole.OTHER for cell in header]
    # Two amount columns: the rightmost is the line total.
    amounts = [i for i, role in enumerate(roles) if role is ColumnRole.AMOUNT]
    for index in amounts[:-1]:
        roles[index] = ColumnRole.OTHER
    for role in (ColumnRole.DESCRIPTION, ColumnRole.QUANTITY, ColumnRole.UNIT_PRICE):
        found = [i for i, r in enumerate(roles) if r is role]
        for index in found[1:]:
            roles[index] = ColumnRole.OTHER
    return roles


def _is_header(cells: Sequence[str | None]) -> bool:
    return sum(column_role(cell) is not None for cell in cells) >= 2


def _kind(columns: Sequence[ColumnRole]) -> TableKind:
    has = set(columns)
    if ColumnRole.DESCRIPTION in has and has & {ColumnRole.AMOUNT, ColumnRole.UNIT_PRICE}:
        return TableKind.LINE_ITEMS
    return TableKind.OTHER


def is_totals_label(text: str | None) -> bool:
    return bool(text) and _TOTALS_LABEL.match(text or "") is not None


# -- Numbers -----------------------------------------------------------------------------


def comma_decimal(cells: Iterable[str | None]) -> bool:
    """True when most cells with two decimals use a comma (``1.234,56``)."""
    comma = dot = 0
    for cell in cells:
        if not cell:
            continue
        text = cell.strip()
        if _COMMA_DECIMAL.search(text):
            comma += 1
        elif _DOT_DECIMAL.search(text):
            dot += 1
    return comma > dot


def parse_cell_number(text: str | None, *, decimal_comma: bool = False) -> Decimal | None:
    """A printed number as ``Decimal``: symbols dropped, ``(x)`` / ``-x`` negative."""
    if not text:
        return None
    raw = _NUMBER_CHARS.sub("", text.replace(" ", ""))
    if not any(ch.isdigit() for ch in raw):
        return None
    negative = (
        (raw.startswith("(") and raw.endswith(")")) or raw.startswith("-") or raw.endswith("-")
    )
    raw = raw.strip("()-")
    raw = raw.replace(".", "").replace(",", ".") if decimal_comma else raw.replace(",", "")
    if not _PLAIN_NUMBER.fullmatch(raw):
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return -value if negative else value


# -- Geometry ----------------------------------------------------------------------------


@dataclass
class _Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class _Segment:
    words: list[_Word]

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class _Block:
    segments: list[_Segment] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return min(s.x0 for s in self.segments)

    @property
    def x1(self) -> float:
        return max(s.x1 for s in self.segments)

    @property
    def top(self) -> float:
        return min(s.top for s in self.segments)

    @property
    def bottom(self) -> float:
        return max(s.bottom for s in self.segments)

    def lines(self) -> list[str]:
        return [s.text for s in self.segments]


def _box(x0: float, top: float, x1: float, bottom: float, width: float, height: float) -> Box:
    def clamp(value: float) -> float:
        return round(min(max(value, 0.0), 1.0), 4)

    return (clamp(x0 / width), clamp(top / height), clamp(x1 / width), clamp(bottom / height))


def _inside(word: _Word, bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    middle = (word.top + word.bottom) / 2
    return x0 - 1 <= word.center <= x1 + 1 and top - 1 <= middle <= bottom + 1


def _page_words(page: Page) -> list[_Word]:
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
    return [
        _Word(str(w["text"]), float(w["x0"]), float(w["x1"]), float(w["top"]), float(w["bottom"]))
        for w in words
        if str(w["text"]).strip()
    ]


def _lines(words: Sequence[_Word]) -> list[list[_Word]]:
    lines: list[list[_Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(word.top - lines[-1][0].top) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def _char_width(words: Sequence[_Word]) -> float:
    widths = [(w.x1 - w.x0) / len(w.text) for w in words if w.text]
    return statistics.median(widths) if widths else 5.0


def _segments(line: Sequence[_Word], char_width: float) -> list[_Segment]:
    """Runs of words separated by wide gaps; a totals label keeps its amount (``Total  9.00``)."""
    segments: list[_Segment] = []
    for word in line:
        if segments and word.x0 - segments[-1].x1 <= SEGMENT_GAP_CHARS * char_width:
            segments[-1].words.append(word)
        else:
            segments.append(_Segment([word]))
    paired: list[_Segment] = []
    for segment in segments:
        previous = paired[-1] if paired else None
        if (
            previous is not None
            and is_totals_label(previous.text)
            and not _NUMBER_AT_END.search(previous.text)
            and parse_cell_number(segment.text) is not None
            and not any(ch.isalpha() for ch in segment.text.replace("RM", ""))
        ):
            previous.words.extend(segment.words)
        else:
            paired.append(segment)
    return paired


# -- Tables --------------------------------------------------------------------------------


@dataclass
class _RawTable:
    """A table on one page, before stitching."""

    page: int
    bbox: tuple[float, float, float, float]
    strategy: TableStrategy
    header: list[str | None] | None
    rows: list[TableRow]


def _clean(cell: str | None) -> str | None:
    if cell is None:
        return None
    text = " ".join(cell.split())
    return text


def _drop_empty_columns(
    header: list[str | None] | None, rows: list[TableRow]
) -> tuple[list[str | None] | None, list[TableRow]]:
    width = max([len(header or [])] + [len(r.cells) for r in rows])
    keep = [
        i
        for i in range(width)
        if (header and i < len(header) and header[i])
        or any(i < len(r.cells) and r.cells[i] for r in rows)
    ]

    def pick(values: Sequence[object]) -> list:  # type: ignore[type-arg]
        return [values[i] if i < len(values) else None for i in keep]

    new_rows = [
        r.model_copy(
            update={
                "cells": pick(r.cells),
                "cell_boxes": pick(r.cell_boxes) if r.cell_boxes is not None else None,
            }
        )
        for r in rows
    ]
    return (pick(header) if header is not None else None), new_rows


def _ruled_tables(page: Page, number: int) -> list[_RawTable]:
    width, height = float(page.width), float(page.height)
    found: list[_RawTable] = []
    for table in page.find_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines"}):
        texts = table.extract()
        rows: list[TableRow] = []
        for row, cells in zip(table.rows, texts, strict=True):
            cleaned = [_clean(c) for c in cells]
            if not any(cleaned):
                continue
            rows.append(
                TableRow(
                    page=number,
                    cells=cleaned,
                    box=_box(*row.bbox, width, height),
                    cell_boxes=[
                        _box(*cell, width, height) if cell is not None else None
                        for cell in row.cells
                    ],
                )
            )
        if len(rows) < 2:
            continue
        header: list[str | None] | None = None
        while rows and _is_header(rows[0].cells) and header is None:
            header = rows.pop(0).cells
        header, rows = _drop_empty_columns(header, rows)
        if not rows or len(rows[0].cells) < 2:
            continue
        found.append(_RawTable(number, tuple(table.bbox), TableStrategy.LINES, header, rows))
    return found


def _unruled_tables(
    lines: Sequence[list[_Word]], char_width: float, page: Page, number: int
) -> list[_RawTable]:
    """Tables without ruling lines: a keyword header line gives the column positions."""
    width, height = float(page.width), float(page.height)
    tables: list[_RawTable] = []
    index = 0
    while index < len(lines):
        header_segments = _segments(lines[index], char_width)
        titles = [s.text for s in header_segments]
        if len(header_segments) < 2 or not _is_header(titles):
            index += 1
            continue
        # Column i spans from the midpoint of the gap before it to the gap after it.
        bounds = [float("-inf")]
        for left, right in itertools.pairwise(header_segments):
            bounds.append((left.x1 + right.x0) / 2)
        bounds.append(float("inf"))
        header_bottom = max(w.bottom for w in lines[index])
        x0 = min(s.x0 for s in header_segments)
        x1 = max(s.x1 for s in header_segments)

        rows: list[TableRow] = []
        last_bottom = header_bottom
        pitches: list[float] = []
        cursor = index + 1
        while cursor < len(lines):
            line = lines[cursor]
            top = min(w.top for w in line)
            bottom = max(w.bottom for w in line)
            pitch = top - last_bottom
            typical = statistics.median(pitches) if pitches else (bottom - top)
            if rows and pitch > TABLE_GAP_ROWS * max(typical, 1.0):
                break
            text = " ".join(w.text for w in line)
            if is_totals_label(text) or any(
                is_totals_label(s.text) for s in _segments(line, char_width)
            ):
                break
            cells: list[list[_Word]] = [[] for _ in header_segments]
            for word in line:
                column = next(
                    i
                    for i in range(len(header_segments))
                    if bounds[i] <= word.center < bounds[i + 1]
                )
                cells[column].append(word)
            values = [" ".join(w.text for w in c) or None for c in cells]
            boxes = [
                _box(min(w.x0 for w in c), top, max(w.x1 for w in c), bottom, width, height)
                if c
                else None
                for c in cells
            ]
            only_first = values[0] is not None and not any(values[1:])
            if only_first and rows and pitch < (bottom - top):
                # A wrapped description: continue the previous row.
                previous = rows[-1]
                merged = list(previous.cells)
                merged[0] = f"{merged[0] or ''} {values[0]}".strip()
                previous_box = previous.box or boxes[0]
                rows[-1] = previous.model_copy(
                    update={
                        "cells": merged,
                        "box": (
                            previous_box[0],
                            previous_box[1],
                            previous_box[2],
                            round(bottom / height, 4),
                        )
                        if previous_box
                        else None,
                    }
                )
            else:
                if rows:
                    pitches.append(pitch)
                rows.append(
                    TableRow(
                        page=number,
                        cells=values,
                        box=_box(
                            min(x0, min(w.x0 for w in line)),
                            top,
                            max(x1, max(w.x1 for w in line)),
                            bottom,
                            width,
                            height,
                        ),
                        cell_boxes=boxes,
                    )
                )
            x0 = min(x0, min(w.x0 for w in line))
            x1 = max(x1, max(w.x1 for w in line))
            last_bottom = bottom
            cursor += 1
        if rows:
            header_top = min(w.top for w in lines[index])
            bbox = (x0, header_top, x1, last_bottom)
            tables.append(
                _RawTable(number, bbox, TableStrategy.TEXT, [s.text for s in header_segments], rows)
            )
        index = cursor
    return tables


def _stitch(
    raw: Sequence[_RawTable], widths: dict[int, float], heights: dict[int, float]
) -> list[Table]:
    """Tables in document order; a table continued on the next page is joined (D3)."""
    tables: list[Table] = []
    previous: _RawTable | None = None
    for item in raw:
        width = len(item.rows[0].cells)
        columns = _roles(item.header) if item.header else [ColumnRole.OTHER] * width
        if (
            previous is not None
            and tables
            and item.page == previous.page + 1
            and width == len(tables[-1].rows[0].cells)
            and previous.bbox[3] / heights[previous.page] >= 1 - STITCH_EDGE
            and item.bbox[1] / heights[item.page] <= STITCH_EDGE
            and (item.header is None or _same_header(item.header, tables[-1].header))
        ):
            last = tables[-1]
            last.pages.append(item.page)
            last.rows.extend(item.rows)
            previous = item
            continue
        tables.append(
            Table(
                index=len(tables),
                pages=[item.page],
                box=_box(*item.bbox, widths[item.page], heights[item.page]),
                strategy=item.strategy,
                header=item.header,
                columns=columns,
                kind=_kind(columns),
                rows=list(item.rows),
            )
        )
        previous = item
    return tables


def _same_header(a: Sequence[str | None], b: Sequence[str | None] | None) -> bool:
    if b is None:
        return False
    return [_normalise_title(x or "") for x in a] == [_normalise_title(x or "") for x in b]


# -- Blocks --------------------------------------------------------------------------------


def _classify(block: _Block) -> BlockType | None:
    lines = block.lines()
    head = " ".join(lines[:2])
    totals = sum(1 for line in lines if is_totals_label(line) and _NUMBER_AT_END.search(line))
    if totals and totals * 2 >= len(lines):
        return BlockType.TOTALS
    if _BILL_TO.search(lines[0]):
        return BlockType.BILL_TO
    if _DOCUMENT_INFO.search(head):
        return BlockType.DOCUMENT_INFO
    if _PAYMENT.search(head):
        return BlockType.PAYMENT
    return None


def _page_blocks(
    lines: Sequence[list[_Word]],
    char_width: float,
    exclude: Sequence[tuple[float, float, float, float]],
) -> list[_Block]:
    blocks: list[_Block] = []
    for line in lines:
        words = [w for w in line if not any(_inside(w, bbox) for bbox in exclude)]
        for segment in _segments(words, char_width):
            height = segment.bottom - segment.top
            target = None
            for block in reversed(blocks):
                gap = segment.top - block.bottom
                overlaps = segment.x0 < block.x1 + char_width and segment.x1 > block.x0 - char_width
                if overlaps and -LINE_TOLERANCE <= gap < BLOCK_GAP_LINES * max(height, 1.0):
                    target = block
                    break
            if target is None:
                blocks.append(_Block([segment]))
            else:
                target.segments.append(segment)
    return blocks


# -- Entry points ----------------------------------------------------------------------------


def analyse_pdf(data: bytes) -> LayoutAnalysis:
    """Tables and layout blocks of a text PDF (every page, no LLM)."""
    pages: list[PageInfo] = []
    raw_tables: list[_RawTable] = []
    page_blocks: list[tuple[int, float, float, list[_Block]]] = []
    table_boxes: dict[int, list[tuple[tuple[float, float, float, float], int]]] = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            width, height = float(page.width), float(page.height)
            pages.append(PageInfo(page=number, width=round(width, 2), height=round(height, 2)))
            words = _page_words(page)
            lines = _lines(words)
            char_width = _char_width(words)
            found = _ruled_tables(page, number)
            if not found:
                found = _unruled_tables(lines, char_width, page, number)
            raw_tables.extend(found)
            exclude = [t.bbox for t in found]
            page_blocks.append((number, width, height, _page_blocks(lines, char_width, exclude)))
            first = len(raw_tables) - len(found)
            table_boxes[number] = [(t.bbox, first + i) for i, t in enumerate(found)]

    heights = {p.page: p.height for p in pages}
    widths = {p.page: p.width for p in pages}
    tables = _stitch(raw_tables, widths, heights)

    blocks: list[LayoutBlock] = []
    for number, width, height, found_blocks in page_blocks:
        first_table_top = min((bbox[1] for bbox, _ in table_boxes.get(number, [])), default=None)
        for block in found_blocks:
            kind = _classify(block)
            if kind is None:
                above_table = first_table_top is not None and block.bottom <= first_table_top
                near_top = block.top / height <= HEADER_TOP
                first_header = not any(b.type is BlockType.HEADER for b in blocks)
                in_header_area = above_table or (first_table_top is None and near_top)
                if number == 1 and in_header_area and first_header:
                    kind = BlockType.HEADER
                else:
                    kind = BlockType.OTHER
            blocks.append(
                LayoutBlock(
                    type=kind,
                    page=number,
                    order=0,
                    text="\n".join(block.lines()),
                    box=_box(block.x0, block.top, block.x1, block.bottom, width, height),
                )
            )
        for bbox, raw_position in table_boxes.get(number, []):
            raw = raw_tables[raw_position]
            text_rows = [" | ".join(c or "" for c in row.cells) for row in raw.rows]
            if raw.header:
                text_rows.insert(0, " | ".join(c or "" for c in raw.header))
            blocks.append(
                LayoutBlock(
                    type=BlockType.LINE_ITEMS
                    if _kind(_roles(raw.header) if raw.header else []) is TableKind.LINE_ITEMS
                    else BlockType.OTHER,
                    page=number,
                    order=0,
                    text="\n".join(text_rows),
                    box=_box(*bbox, width, height),
                )
            )
    blocks = order_blocks(blocks)
    return LayoutAnalysis(
        source=ExtractionMethod.PDF_PARSER,
        layout_version=LAYOUT_VERSION,
        page_count=len(pages),
        pages=pages,
        tables=tables,
        blocks=blocks,
    )


def order_blocks(blocks: Sequence[LayoutBlock]) -> list[LayoutBlock]:
    """Reading order: page, then top (in bands of 1 % of the page), then left."""
    ranked = sorted(
        blocks,
        key=lambda b: (b.page, round(b.box[1], 2) if b.box else 0.0, b.box[0] if b.box else 0.0),
    )
    return [b.model_copy(update={"order": i}) for i, b in enumerate(ranked)]


def table_from_vision(
    index: int, page: int, header: Sequence[str], rows: Sequence[Sequence[str]]
) -> Table | None:
    """A table the vision model listed; ``None`` when it has fewer than 2 columns or no rows."""
    cleaned = [[_clean(c) or None for c in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    width = max([len(header)] + [len(r) for r in cleaned]) if cleaned else len(header)
    if not cleaned or width < 2:
        return None
    titles: list[str | None] | None = [_clean(h) or None for h in header] if header else None
    columns = _roles(titles) if titles else [ColumnRole.OTHER] * width
    columns = columns + [ColumnRole.OTHER] * (width - len(columns))
    return Table(
        index=index,
        pages=[page],
        box=None,
        strategy=TableStrategy.VISION,
        header=titles,
        columns=columns,
        kind=_kind(columns),
        rows=[
            TableRow(page=page, cells=row + [None] * (width - len(row)), box=None)
            for row in cleaned
        ],
    )


def stitch_vision_tables(tables: Sequence[Table]) -> list[Table]:
    """Join a vision table with the next page's table when both have the same header."""
    joined: list[Table] = []
    for table in tables:
        last = joined[-1] if joined else None
        if (
            last is not None
            and table.pages[0] == last.pages[-1] + 1
            and len(table.columns) == len(last.columns)
            and table.header is not None
            and _same_header(table.header, last.header)
        ):
            last.pages.append(table.pages[0])
            last.rows.extend(table.rows)
            continue
        joined.append(table.model_copy(update={"index": len(joined)}))
    return joined


# -- Table → line items ----------------------------------------------------------------------


def _confident(columns: Sequence[ColumnRole]) -> bool:
    has = set(columns)
    if ColumnRole.DESCRIPTION not in has:
        return False
    return ColumnRole.AMOUNT in has or {ColumnRole.QUANTITY, ColumnRole.UNIT_PRICE} <= has


def line_items_from_tables(tables: Sequence[Table]) -> TableLineItems | None:
    """Line items copied from the first line-item table with a confident column mapping."""
    for table in tables:
        if table.kind is not TableKind.LINE_ITEMS or not _confident(table.columns):
            continue
        position = {role: table.columns.index(role) for role in table.columns}
        decimal = comma_decimal(
            row.cells[i]
            for row in table.rows
            for i, role in enumerate(table.columns)
            if role in (ColumnRole.QUANTITY, ColumnRole.UNIT_PRICE, ColumnRole.AMOUNT)
        )

        def cell(
            row: TableRow, role: ColumnRole, position: dict[ColumnRole, int] = position
        ) -> str | None:
            index = position.get(role)
            return row.cells[index] if index is not None and index < len(row.cells) else None

        items: list[TableItem] = []
        refs: list[TableRef] = []
        for number, row in enumerate(table.rows):
            description = cell(row, ColumnRole.DESCRIPTION)
            quantity = parse_cell_number(cell(row, ColumnRole.QUANTITY), decimal_comma=decimal)
            unit_price = parse_cell_number(cell(row, ColumnRole.UNIT_PRICE), decimal_comma=decimal)
            amount = parse_cell_number(cell(row, ColumnRole.AMOUNT), decimal_comma=decimal)
            if is_totals_label(description) and quantity is None and unit_price is None:
                break
            if quantity is None and unit_price is None and amount is None:
                continue  # an empty row or a section heading, not an item
            items.append(
                TableItem(
                    description=description,
                    quantity=quantity,
                    unit_price=unit_price,
                    amount=amount,
                )
            )
            refs.append(
                TableRef(
                    table=table.index,
                    row=number,
                    page=row.page,
                    box=row.box,
                    cell_boxes=row.cell_boxes,
                    columns=list(table.columns),
                )
            )
        if items:
            return TableLineItems(items=items, refs=refs)
    return None
