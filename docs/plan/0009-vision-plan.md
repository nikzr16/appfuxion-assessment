# 0009 Vision Implementation Plan

> **Type:** Plan | **Must stay current:** No -- record divergences in decision log, rewrite only during re-planning

<!-- AI Context
Role: This document describes *how* to build the feature, not *what* or *why*.
Read the corresponding PRD first for intent and constraints, then use this plan
to guide implementation order, component boundaries, and technical decisions.
Do not rewrite this document during coding. If the implementation diverges from
this plan, add an entry to the decision log instead. Only rewrite during a
deliberate re-planning session.
-->

## Overview

Five layers of change:

1. **`vision` module** (full: router, service, schema, crud, model, prompts + two helper files):
   page rendering and image preparation and the render lock (moved from `text_extraction`),
   the combined vision page call (moved and extended), `pdfplumber` table and layout
   analysis, the table → line-item mapping, the `document_layouts` table with history, and
   `GET /layout` + `GET /pages/{n}/image`.
2. **Callers**: `text_extraction` sends scans to `vision.service` and saves the returned
   layout through it; `structured_extraction` puts the tables in the prompt, sends page images
   for scans (`multimodal_extraction`), and builds line items from the table for text PDFs
   (`line_items_source`); `guardrails` locates line items in table cells and checks the total
   against the totals block.
3. **Agent**: the **`extract_tables`** tool, the `tables_required` guard before
   `extract_structured_data`, prompt `agent.document.v3`, `AGENT_MAX_STEPS` 10 → 12.
4. **Storage and metrics**: migration `0008_vision` (`document_layouts`,
   `extractions.line_items_source`); a `vision` block on `GET /metrics/summary`.
5. **UI**: a "Tables & layout" section on the detail page (tables, page preview with
   labelled boxes, block list for scans), "Show on page" for table-derived line items, a
   line-item source chip, lane / trace labels, and a Vision section on the Metrics page.

The brief's result keys and every existing response key stay unchanged.

**Dependency direction (PRD D1):**

```
agent.tools ──► vision.service ◄── text_extraction.service
     │                ▲                     ▲
     └──► structured_extraction.service ────┘
                      │
                      └──► guardrails.service ──► vision.schema (schema only)
vision.service ──► documents.service, core (storage, llm, logging); imports other modules' schema only
```

`vision.service` never imports `text_extraction.service`, `structured_extraction.service` or
`guardrails.service`, so there is no cycle. Callers pass the text method in.

## Technical Approach

### 1. `vision` module files

| File | Holds |
|---|---|
| `schema.py` | DTOs below, LLM output schema `PageAnalysis` |
| `prompts.py` | `PROMPT_VERSION = "vision.v1"`, page-analysis system prompt, `page_prompt(page, total)` |
| `images.py` | Moved from `text_extraction/service.py`: `_RENDER_LOCK`, `to_rgb`, `prepare_image`, `render_pages` (now also returns each page's pixel size), plus `render_page_jpeg(data, page, long_side)` for the preview. Pure, no DB. |
| `layout.py` | Pure `pdfplumber` analysis: words → lines → segments → blocks, block classification, table detection + stitching, column roles, cell number parsing, table → line items. ~400 lines of unit-tested helpers (justified like `guardrails/matching.py`). |
| `service.py` | Use cases (below); the only file other modules import, together with `schema.py` |
| `crud.py` | `insert`, `latest_by_document`, `history_by_document`, `stats(since)` |
| `model.py` | `DocumentLayout` ORM |
| `router.py` | `GET /documents/{id}/layout`, `GET /documents/{id}/pages/{n}/image` |

`text_extraction/prompts.py` is deleted (it no longer calls an LLM); `text_extraction` keeps
`raw_text`, `document_texts`, `GET /text`. New scan rows store `prompt_version = "vision.v1"`.

### 2. Schemas (`vision/schema.py`)

```python
Box = tuple[float, float, float, float]   # x0, y0, x1, y1 as 0–1 page fractions, top-left origin

class BlockType(StrEnum): HEADER, DOCUMENT_INFO, BILL_TO, LINE_ITEMS, TOTALS, PAYMENT, OTHER
class TableKind(StrEnum): LINE_ITEMS, OTHER
class ColumnRole(StrEnum): DESCRIPTION, QUANTITY, UNIT_PRICE, AMOUNT, OTHER
class TableStrategy(StrEnum): LINES, TEXT, VISION

class PageInfo(BaseModel):  page: int; width: float; height: float   # PDF points or image pixels
class TableRow(BaseModel):  page: int; cells: list[str | None]; box: Box | None; cell_boxes: list[Box | None] | None
class Table(BaseModel):
    index: int                         # 0-based, document order
    pages: list[int]                   # several when stitched across pages
    box: Box | None                    # on the first page
    strategy: TableStrategy
    header: list[str | None] | None
    columns: list[ColumnRole]          # one per column
    kind: TableKind
    rows: list[TableRow]               # body rows only (header and repeated headers removed)
class LayoutBlock(BaseModel): type: BlockType; page: int; order: int; text: str; box: Box | None

class LayoutAnalysis(BaseModel):       # what is stored (minus id / run / timestamps)
    source: ExtractionMethod           # text_extraction.schema — pdf_parser | vision
    layout_version: str                # "layout.v1" | "vision.v1"
    page_count: int
    pages: list[PageInfo]
    tables: list[Table]
    blocks: list[LayoutBlock]
    model: str | None                  # vision model; None for pdf_parser

class LayoutRead(LayoutAnalysis):      # + id, document_id, run_id, created_at
class LayoutHistoryItem(BaseModel):    layout_id, created_at, source, layout_version, run_id
class LayoutResponse(BaseModel):       # GET /layout
    document_id, layout_id, source, layout_version, run_id, created_at, page_count,
    pages, tables, blocks, history: list[LayoutHistoryItem]    # newest first, current excluded

class TableRef(BaseModel):  table: int; row: int; page: int; box: Box | None; cell_boxes: list[Box | None] | None; columns: list[ColumnRole]
class TableLineItems(BaseModel):  items: list[LineItem]; refs: list[TableRef]   # same length

class TablesSummary(BaseModel):        # what the agent tool returns (no cell text)
    source; available: bool; pages: int; tables: list[{index, pages, kind, columns, rows}]
    line_item_table: bool; blocks: dict[BlockType, int]; reused: bool

class VisionStats(BaseModel): ...      # metrics block, §8

# LLM output (strict structured output; every field required)
class VisionTable(BaseModel):  header: list[str]; rows: list[list[str]]
class VisionBlock(BaseModel):  type: BlockType; text: str
class PageAnalysis(BaseModel): legible: bool; text: str; tables: list[VisionTable]; blocks: list[VisionBlock]
```

`LineItem` comes from `structured_extraction.schema` (schema import only).

### 3. Text PDFs — tables and layout (`layout.py`, PRD D3, D4)

Opened once with `pdfplumber`; every page (no page cap: it is local and cheap). Coordinates are
divided by the page width / height → `Box`.

**Tables**

1. `page.find_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines"})`;
   accepted when ≥ 2 rows × ≥ 2 columns after dropping fully empty rows and columns.
2. Only if a page has no accepted `lines` table: `text` strategy
   (`{"vertical_strategy": "text", "horizontal_strategy": "text"}`). A `text` table is accepted
   only when it has a **keyword header** (≥ 2 cells map to a known column role); rows above the
   header are dropped, and rows stop at the first totals row (first cell matches a totals label)
   or a vertical gap > 3 × the median row height. This stops the `text` strategy from turning
   the whole page into one "table".
3. **Header row** = the first row with ≥ 2 keyword cells. **Column roles** (case-folded,
   punctuation-stripped, English + Malay):

   | Role | Keywords |
   |---|---|
   | description | description, item, items, product, service, particulars, details, perkara, butiran, keterangan, barang |
   | quantity | qty, quantity, units, kuantiti, kuantiti (unit), unit count |
   | unit_price | unit price, price, rate, unit cost, harga, harga seunit, harga unit |
   | amount | amount, total, line total, subtotal (column), jumlah, amaun, jumlah (rm) |

   When two columns map to `amount`, the rightmost wins and the other becomes `other`.
4. **Merged cells**: `pdfplumber` returns `None` for the covered cells — kept as `None`.
   **Wrapped text** inside a cell: newlines joined with single spaces. **Continuation rows**
   (a row with only a description, directly after an item row, `text` strategy) are appended to
   the previous row's description.
5. **Multi-page stitching**: a table that starts within the top 25 % of page *n + 1* and has the
   same column count as the last table of page *n* (which ends within its bottom 25 %) is
   appended to it; a first row equal to the header (normalised) is dropped. `pages` lists both.
6. `kind = line_items` when the roles include `description` and (`amount` or `unit_price`);
   else `other`. `strategy` records `lines` / `text`.

**Blocks**

1. `page.extract_words(keep_blank_chars=False, use_text_flow=True)` → **lines** (words whose
   `top` is within 3 pt, sorted by `x0`).
2. Each line is split into **segments** at horizontal gaps > 2 × the median character width (a
   two-column header gives two segments).
3. Segments merge into a **block** when the vertical gap to the block is < 1.2 × the line height
   and they overlap horizontally. Words inside an accepted table's box form the `line_items`
   block (box = the table's box) and are not reused.
4. **Classification** (first rule that matches, on the block's first two lines):
   `totals` (subtotal, total, grand total, tax, SST, GST, VAT, amount due, balance due, rounding,
   jumlah, cukai, jumlah besar), `bill_to` (bill to, billed to, sold to, ship to, customer,
   kepada, dibilkan kepada), `document_info` (invoice no / number / #, receipt no, date, due
   date, PO, tarikh, no. invois, no. resit), `payment` (bank, account, acc no, payment, terms,
   swift, akaun, pembayaran), `header` (the first unclassified block on page 1 above the table,
   or in the top 30 % when there is no table), else `other`.
5. **Reading order**: blocks sorted by page, then by `round(y0, 2)` bands, then `x0`; `order`
   is 0-based across the document.

**Cell numbers** (`parse_cell_number(text, decimal)`): strip currency symbols / codes and
spaces; `(x)` or a leading / trailing `-` → negative; the table's decimal separator is decided
once per table (the separator followed by exactly 2 digits in most numeric cells; default `.`),
the other separator is a thousands separator. Not a number → `None`.

**Table → line items** (`line_items_from_tables(tables) -> TableLineItems | None`): the first
`line_items` table with a **confident mapping** (description + amount, or description +
quantity + unit_price). Each body row → `LineItem(description, quantity, unit_price, amount)`
from its role columns; a row with no description and no numbers is skipped; a row whose
description matches a totals label ends the table. `None` when no table qualifies.

### 4. Scans and images — the combined vision call (`service.analyse_scanned`, PRD D2)

- `render_pages` / `prepare_image` as in 0002 (`VISION_MAX_PAGES`, 200 DPI, long side 2048,
  JPEG q90, `detail: high`), now also returning each page's pixel size.
- One `llm.complete(..., vision=True, response_format=PageAnalysis, temperature=0)` per page,
  under `bind_trace(purpose=Purpose.VISION_TRANSCRIPTION, prompt_version="vision.v1")`.
- **Prompt `vision.v1`** = the 0002 transcription rules unchanged for `text` (so `raw_text`,
  `" | "` table rows and grounding behave as before), plus: "List every table: `header` = the
  column titles as printed (empty list if none), `rows` = each printed row's cells in order,
  copied exactly, an empty string for an empty cell. List the page's blocks in reading order,
  each with one `type` from the list and its text copied exactly. Do not invent rows or blocks."
  The block types are described in one line each.
- Result → `LayoutAnalysis(source=vision, layout_version="vision.v1")`: tables get
  `strategy = vision`, `box = None`, column roles from the same header keywords; a table on
  consecutive pages with the same header is stitched; blocks get `order` from the model's order
  and `box = None`. `text` per page goes back to `text_extraction` to build `raw_text` exactly as
  today (`--- Page N ---` markers, illegible → `""`).
- `text_extraction.extract_text` (scan path): `analysis, pages, model =
  vision_service.analyse_scanned(llm, data, content_type, max_pages)` → upsert the text row →
  `vision_service.save_layout(db, document_id, analysis)` in the same commit.

### 5. `vision.service` use cases

```python
def analyse_scanned(llm, data: bytes, content_type: str, max_pages: int) -> ScannedResult
def analyse_text_pdf(data: bytes) -> LayoutAnalysis                      # pure, §3
def save_layout(db, document_id, analysis: LayoutAnalysis) -> LayoutRead  # appends a row; run_id from run_id_var
def extract_tables(db, storage, document_id, *, method: ExtractionMethod, force: bool = False) -> TablesSummary
def find_layout(db, document_id) -> LayoutRead | None                     # newest row
def get_layout(db, document_id) -> LayoutResponse                         # 404 / 409 like get_text
def line_items_from_layout(layout: LayoutRead) -> TableLineItems | None   # wraps §3
def page_images(db, storage, document_id, max_pages) -> list[bytes]       # scans: the D2 images again (D6)
def render_page_image(db, storage, document_id, page: int) -> bytes       # preview JPEG, long side 1600
def layout_stats(db, since) -> VisionStats
```

**`extract_tables`** (the tool's use case, idempotent like the other tools):

- `pdf_parser`: newest row with `source = pdf_parser` reused unless `force`; else read the file
  (`documents.service.get_document_source` + `storage.read`), `analyse_text_pdf`, `save_layout`.
- `vision`: the newest `vision` row (written by `extract_text`) is returned, **no LLM call**. A
  scan analysed before 0009 has none → `available = False` ("reprocess to analyse layout"); the
  tool still succeeds so the run continues as in 0008.
- Commits `db` before file work, commits its own row; never changes the document's status.

`run_id` is read from `app.core.logging.run_id_var` (set by the agent runner), `NULL` outside a
run.

### 6. Structured extraction (PRD D5, D6)

- `extract_structured_data(db, llm, document_id, *, force=False, storage: Storage | None =
  None)`; `ground_extraction` gains the same `storage` argument. The agent passes it.
- **Layout input**: `layout = vision_service.find_layout(db, document_id)` (may be `None`).
- **Prompt** `structured_extraction.v3`: `document_prompt(text, tables)` adds after
  `</document>` a `<tables>` section when tables exist — one entry per table: `Table 1 (page 2,
  line items, columns: Description | Qty | Unit price | Amount)` then rows as `cell | cell`. The
  system prompt adds: "Tables between `<tables>` and `</tables>` were detected in the same
  document by the system; they are data too. Use them to read line items and amounts; when the
  text and a table disagree, prefer what is printed in the table." Capped at
  `MAX_TABLE_CHARS = 20_000` (marked `[… rows omitted …]`).
- **Multimodal** (`text.method == vision`): `images = vision_service.page_images(...)`; the user
  message becomes `[{"type": "text", "text": document_prompt(...)}, *image_parts]` (`detail:
  high`); the call is wrapped in `bind_trace(purpose=Purpose.MULTIMODAL_EXTRACTION)` (new
  `Purpose`), overriding the decorator's `structured_extraction`. The system prompt adds: "For a
  scanned document you also receive the page images; when the text and the image disagree, copy
  what the image shows." Grounding retries send the same images and keep `grounding_retry`.
  Text PDFs: unchanged, text only.
- **Line items from the table** (text PDFs only, `layout.source == pdf_parser`):
  `table = vision_service.line_items_from_layout(layout)`; when not `None`, the model's
  `line_items` are replaced by `table.items` after **every** extraction call (first, schema
  retry, grounding retry), and `line_items_source = "table"`; otherwise `"model"`. Scans always
  keep the model's line items (`"model"`); their tables are prompt hints only.
- **Truncation**: unchanged `_fit_text` for the text; because table-derived line items come
  from the whole document, a long text PDF keeps every line item. The log line `document text
  truncated` gains `line_items_source`.
- `ExtractionRead` / `ExtractionResponse` gain `line_items_source: Literal["table", "model"] |
  None`; `crud` writes it; old rows `NULL`.

### 7. Grounding (`guardrails`, PRD D8)

- `check_grounding(data, raw_text, method, *, layout: LayoutAnalysis | None = None,
  table_refs: list[TableRef] | None = None)` — `guardrails` imports `vision.schema` only.
  `structured_extraction` passes `layout` and, when `line_items_source == "table"`, the refs.
- New `MatchKind.TABLE`; new optional `FieldGrounding.location: FieldLocation | None`
  (`page, box, block: BlockType | None, table: int | None, row: int | None, column: ColumnRole |
  None`). `FieldConfidence` carries the same `location` (so the UI can "Show on page").
- **Table cells**: for `line_items[i].<field>` with a ref, the value came from a printed cell →
  `grounded`, `match = TABLE`, location = the cell (page, cell box, table, row, column). The
  lexical lookup still runs to fill `start` / `end` for "Show in text".
- **Total placement**: when the layout has a `totals` block, `total_amount` keeps its status
  only if its value is among the numbers of a `totals` block's text **or** one of its lexical
  matches is on a line containing a total label (`matching.find_number_all` returns every
  match); otherwise `grounded` → `weak` with note "found, but not next to a total label".
  Location = that totals block. No totals block → 0008 behaviour.
- Confidence formula unchanged; `_grounding_reason` adds "Read from table 1, row 3" and "Not
  next to a total label".

### 8. Agent (PRD D7)

- **Tool `extract_tables`** (no arguments), registered between `extract_text` and
  `extract_structured_data`. Needs `ctx.text_done` (`text_not_extracted`). Calls
  `vision_service.extract_tables(ctx.db, ctx.storage, ctx.document_id, method=ctx.text_method,
  force=...)` (forced once per reprocess run, like the other tools); sets `ctx.tables_done`.
  Returns `TablesSummary` JSON (counts, kinds, column roles, block counts; never cell text).
- `_extract_text` stores `ctx.text_method` and resets `ctx.tables_done = False`.
- **Guard** in `_extract_structured_data`: `not ctx.tables_done` → `ToolError("tables_required",
  "Call extract_tables before extract_structured_data.")`; `tables_required` joins
  `RECOVERABLE_CODES`. The tool now passes `storage` to the structured-extraction calls.
- **Agent prompt** `agent.document.v3`: the order gains step 2 `extract_tables` ("always, even
  when the document may have no table").
- `AGENT_MAX_STEPS` default 10 → **12** (`config.py`, `.env.example`, README).

### 9. Storage — migration `0008_vision.py` (revision `"0008"`, down → `"0007"`, PRD D9)

```
document_layouts
  id               UUID PK
  document_id      UUID NOT NULL  FK documents.id ON DELETE CASCADE
  run_id           UUID NULL      FK agent_runs.id ON DELETE SET NULL
  source           VARCHAR(20) NOT NULL  CHECK (source IN ('pdf_parser', 'vision'))
  layout_version   VARCHAR(50) NOT NULL
  model            VARCHAR(100) NULL
  page_count       INTEGER NOT NULL  CHECK (page_count >= 1)
  pages            JSONB NOT NULL
  tables           JSONB NOT NULL
  blocks           JSONB NOT NULL
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
  INDEX ix_document_layouts_document_created (document_id, created_at DESC)

extractions.line_items_source   VARCHAR(10) NULL  CHECK (line_items_source IN ('table', 'model'))
```

Append-only (no update path in `crud`). Schema-only: no backfill (D13).

### 10. API (PRD D10, D12)

| Endpoint | Change |
|---|---|
| `GET /api/documents/{id}/layout` (new, `vision/router.py`) | `LayoutResponse`; 404 unknown document; 409 `layout_not_ready` while processing, `layout_unavailable` otherwise |
| `GET /api/documents/{id}/pages/{n}/image` (new) | `image/jpeg`, `Cache-Control: private, max-age=3600`; PDFs any page 1..page_count, images page 1; 404 `page_not_found`; rendering under the shared lock |
| `GET /api/documents/{id}/extraction` | `+ line_items_source` |
| `GET /api/documents/{id}/result` | `confidence.fields[*].location` (additive, nullable) |
| `GET /api/metrics/summary` | `+ vision: {layouts_analysed, documents_with_line_item_table, tables_found, line_items_from_table, line_items_from_model, line_items_table_share, pages_via_vision, multimodal_calls}` (same `?days=` window; per document the newest layout in the window; line items counted from `extractions.data`, split by `line_items_source`; `pages_via_vision` and `multimodal_calls` from the ledger by purpose) |

`observability.service` gets the numbers from `vision.service.layout_stats` and
`structured_extraction.service.line_item_source_stats` (new), as it does for guardrails.

### 11. Frontend (PRD D11, D12)

- **Types / client / queries**: `LayoutResponse` and friends, `ExtractionResponse.
  line_items_source`, `FieldConfidence.location`, `MetricsSummary.vision`; `getLayout(id)`
  (`null` on 409, like `getText`), `pageImageUrl(id, page)`; `useLayout(id)` (same polling and
  invalidation on reprocess as `/text`).
- **`lib/layout.ts`** (pure, unit-tested): `blockMeta(type)` → `{label, icon, token}`,
  `boxStyle(box)` → `{left, top, width, height}` in %, `rowHighlight(location)`, `tableTitle`,
  `columnLabel(role)`.
- **`features/detail/LayoutSection.tsx`** — card "Tables & layout", placed after Line items and
  before Raw text, with a two-tab switch **Tables | Page**:
  - **Tables** (`TablesView.tsx`): each table as a real `<table>` (header row, `tabular-nums`,
    numbers right-aligned, horizontal scroll inside the card at 375 px), a caption "Table 1 ·
    page 2 · 6 rows" and a chip: "Used for line items" (text PDF line-item table), "Hint only"
    (scan line-item table) or "Other table". Empty: "No tables found".
  - **Page** (`PagePreview.tsx`): the page image (`loading="lazy"`, width 100 %, aspect ratio
    from `pages[n]`), boxes absolutely positioned in %, each with an outline in its block colour
    **and** a small text label + icon (never colour alone); a legend; previous / next page
    buttons with "Page 2 of 3". A highlighted row (from "Show on page") gets a thicker accent
    ring and is scrolled into view. **Scans** (no boxes): the image is still shown, and the
    blocks appear as an ordered list (`BlockList.tsx`) with type chips and text.
  - Old documents / no layout: muted line "Layout not analysed — reprocess to analyse layout".
- **`LineItemsTable.tsx`**: a chip in the header "From table" / "From model" (from
  `line_items_source`); per row a small "Show on page" button when the row's `location.box` is
  set → `DocumentDetailPage` state `pageHighlight` → `LayoutSection` switches to Page, opens
  that page and highlights the row (`cell_boxes` union → row box).
- **Block colours**: 7 categorical tokens (`--block-header` … `--block-other`) added to the
  theme for light and dark; the `dataviz` skill is loaded first and its validator run on both
  themes; labels and icons carry the meaning.
- **Lanes / trace**: `roleOfTool("extract_tables") = "extraction"`, `toolLabel` "Extract
  tables"; purpose label "Multimodal extraction".
- **Metrics page**: a "Vision" section — tiles for documents with a line-item table (x of y),
  line items from tables (%), tables found, pages read by vision, multimodal calls; empty state.
- 0006 design system, light + dark, 375 px.

## System Components

| Component | Responsibility |
|---|---|
| `vision/images.py` | Render lock, page rendering with sizes, image preparation, preview JPEG |
| `vision/layout.py` | Words → blocks, classification, tables (lines / text), stitching, column roles, cell numbers, table → line items |
| `vision/prompts.py` | `vision.v1` page-analysis prompt |
| `vision/schema.py` | Layout DTOs, `PageAnalysis`, `TablesSummary`, `VisionStats` |
| `vision/service.py` | `analyse_scanned`, `analyse_text_pdf`, `save_layout`, `extract_tables`, `find_layout`, `get_layout`, `line_items_from_layout`, `page_images`, `render_page_image`, `layout_stats` |
| `vision/crud.py`, `vision/model.py` | `document_layouts` (append-only) |
| `vision/router.py` | `/layout`, `/pages/{n}/image` |
| `text_extraction/service.py` | Scan path via `vision.service`; render helpers and prompts removed |
| `structured_extraction` (service, prompts, schema, crud, model) | Tables in prompt, multimodal path, table line items, `line_items_source`, v3 prompt, stats |
| `guardrails` (service, matching, schema) | `TABLE` match, `location`, total placement |
| `agent` (tools, prompts) | `extract_tables` tool + guard, v3 prompt |
| `app/core/llm.py`, `app/core/config.py` | `Purpose.MULTIMODAL_EXTRACTION`; `AGENT_MAX_STEPS = 12` |
| `observability` (service, schema) | `vision` metrics block |
| `migrations/versions/0008_vision.py` | `document_layouts`, `extractions.line_items_source` |
| `app/main.py` | Mount `vision.router` |
| `frontend/src/lib/layout.ts`, `features/detail/{LayoutSection,TablesView,PagePreview,BlockList}.tsx` | Tables & layout section |
| `frontend/src/features/detail/*`, `features/metrics/*`, `lib/agents.ts`, `lib/trace.ts`, `api/*`, theme CSS | Wiring, "Show on page", source chip, labels, Vision metrics, block tokens |

## Processing Flow

```
run_document_agent
  extract_text ────────────► text PDF: pdfplumber text (as 0002)
                             scan:     vision.analyse_scanned → 1 call per page [vision_transcription, vision.v1]
                                       → document_texts (raw_text) + document_layouts row (source vision)
  extract_tables ──────────► guard: text_not_extracted
                             text PDF: vision.analyse_text_pdf (pdfplumber, no LLM) → document_layouts row
                             scan:     newest vision row (no LLM)
  extract_structured_data ─► guard: tables_required
                             prompt v3 = text + <tables>; scans + page images [multimodal_extraction]
                             text PDF with line-item table → line_items := table rows (line_items_source = table)
  check_grounding ─────────► check_grounding(..., layout, table_refs): TABLE matches, total placement
                             retries (grounding_retry; scans with images) re-apply table line items
  validate_invoice → (convert_currency) → generate_summary   (unchanged)

GET /layout              → newest document_layouts row + history
GET /pages/{n}/image     → JPEG rendered on request (lock)
GET /metrics/summary     → … + vision
```

## Dependencies

| Dependency | Purpose |
|---|---|
| None new (backend) | `pdfplumber`, `pypdfium2`, Pillow and `rapidfuzz` are already installed; `reportlab` (dev) builds table fixtures |
| None new (frontend) | Tailwind + lucide; boxes are absolutely positioned elements over an `<img>` |

## Implementation Phases

### Phase 1: `vision` core (pure)
Move `images.py` helpers (render lock test moves too); `schema.py`; `layout.py`. Fixtures (built
with `reportlab` in `tests/modules/vision/samples.py`): a ruled line-item table, an unruled
table, a merged cell, wrapped descriptions, a table continued on page 2 with a repeated header,
a two-column header (vendor | invoice info), bill-to, totals and payment blocks, a Malay-header
invoice, comma-decimal amounts. Unit tests: tables (rows, header, roles, kind, strategy, pages,
boxes in 0–1), stitching, blocks (types, order, boxes), cell numbers, table → line items
(totals row stops, empty rows skipped, `None` without a confident mapping).

### Phase 2: Storage and service
Migration `0008`, model, crud, `save_layout` / `find_layout` / `get_layout` / `extract_tables`
/ `page_images` / `render_page_image`; `run_id` from the context var. Migration test (table,
columns, checks, index, head = `0008`, downgrade). Service tests: append-only history, reuse
vs force, scan without a vision row → `available = False`, `run_id` set inside a bound run.

### Phase 3: Scans
`vision.v1` prompt, `PageAnalysis`, `analyse_scanned`; `text_extraction` switched over, its
prompts removed. Tests (FakeLLM): one call per page with purpose `vision_transcription` and
prompt `vision.v1`; `raw_text` identical in format to 0002 for the same page texts; tables /
blocks stored with `box = None`; illegible page; page cap; existing text-extraction tests still
pass.

### Phase 4: Structured extraction + grounding
Prompt v3 with `<tables>`, multimodal path + `Purpose.MULTIMODAL_EXTRACTION`, table line items
after every call, `line_items_source`, `line_item_source_stats`; guardrails `TABLE` match,
`location`, total placement, `find_number_all`. Tests: text PDF with a table →
`line_items_source = table` and line items equal the table; a > 60,000-character text PDF keeps
its middle line items; scan → model's line items, images sent, ledger purpose
`multimodal_extraction`, retries carry images; text PDFs send no images; grounding locations on
table cells; total outside the totals block → `weak`; no totals block → unchanged 0008 results.

### Phase 5: Agent
Tool, guard, `RECOVERABLE_CODES`, `ctx.text_method`, prompt v3, `AGENT_MAX_STEPS = 12`. Tests:
happy path with `extract_tables` within 12 steps; model skips `extract_tables` →
`tables_required` → recovers; a new `extract_text` resets the guard; reprocess forces a new
layout row.

### Phase 6: API and metrics
`vision.router` mounted; `/layout` (200 / 404 / 409 states, history), `/pages/{n}/image` (JPEG
header, PDF page n, image page 1, 404 bad page), `/extraction` `line_items_source`, `/result`
locations, `/metrics/summary` vision block with `?days=`. Import-layering test: `vision` imports
no other module's `crud` / `model`; `vision.service` imports no `text_extraction.service`,
`structured_extraction.service` or `guardrails.service`; `guardrails` still imports nothing from
the DB.

### Phase 7: Frontend
Types, client, query, `lib/layout.ts`, `LayoutSection` / `TablesView` / `PagePreview` /
`BlockList`, "Show on page" + source chip in Line items, lanes / trace labels, Metrics Vision
section, block tokens (dataviz validator). Vitest: `layout.ts` table tests; tables render with
headers and chips; page preview places labelled boxes and switches pages; scans show the block
list; "Show on page" switches tab and highlights; no-layout state; metrics section + empty
state; run with and without `TZ=UTC`.

### Phase 8: Browser check and close-out
Run the DB, backend and frontend; process a text PDF with a table, a multi-page text PDF and a
scanned image (real OpenAI only in this manual check), plus a reprocess (history grows); check
the detail page (tables, page preview, "Show on page") and Metrics at desktop and 375 px, light
and dark; fix issues. Full backend and frontend checks. Update
`docs/reference/folder-structure.md` (module, routes, schemas, database, wiring, config
default), `ENGINEERING_NOTES.md` (architecture, prompt design for `vision.v1`, extraction v3
and agent v3, limitations, production improvements; resolve the "table structure is not
extracted" / truncation / "ground by layout" pointers), `README.md` (vision features,
`AGENT_MAX_STEPS`), roadmap; decision log `0010` for any divergence; commit on the feature
branch.

## Testing Strategy

- **Never the real OpenAI API**: `FakeLLM` scripts `PageAnalysis` replies for scans and
  `InvoiceData` replies for extraction; tests assert the messages (image parts present or not)
  and the ledger purpose / prompt version.
- **Generated fixtures only**: `reportlab` PDFs with known table geometry (so expected boxes are
  computable) and Pillow-made "scanned" PNGs / image-only PDFs; no binary fixtures committed
  beyond what the tests generate.
- **Determinism**: `layout.py` is pure — table-driven tests with exact rows, roles, kinds and
  boxes (rounded to 3 decimals).
- **Regression**: the full 0002–0008 suite must pass unchanged apart from the expected new tool
  step in scripted agent runs and the moved render-lock test.
- **Frontend**: pure helpers table-tested; component tests with `fetchMock` fixtures for a text
  PDF layout, a scan layout, no layout and empty vision metrics; the page image is a stub URL.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| `text` strategy finds false tables or splits real ones | Wrong line items on unruled invoices | Keyword header required; stop at totals row / big gap; only a confident mapping replaces the model's line items; fixtures for ruled and unruled |
| Table line items replace correct model items with worse ones | Lower quality on odd layouts | Only text PDFs; only confident mappings; grounding and 0004 arithmetic still run; source chip visible; documented limitation |
| Larger vision output (tables + blocks per page) | More output tokens, slower scans | Same single call; prompt asks for exact copies only; cost visible by purpose in metrics |
| Multimodal extraction tokens (images on every extraction call) | Higher cost for scans | Scans only, ≤ `VISION_MAX_PAGES`; `detail: high` justified for digits; documented |
| Page image endpoint renders under the global lock | Slow previews while scans render | Lazy loading, one page at a time, `Cache-Control`; preview size 1600 px |
| Agent loops on `tables_required` | Step limit reached | Clear message + prompt order; `AGENT_MAX_STEPS = 12`; recovery test |
| History grows on every reprocess | Table growth | Small JSONB rows; documented; retention is a production improvement |
| Block classification by keywords misses unusual labels | Blocks typed `other`; total placement check skipped | Placement check only when a totals block exists; `other` is harmless |

## Roadmap Phase

**Phase:** Phase 3 — Bonus Tasks (B5).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0009-vision-prd.md` | Intent | Product goals and constraints this plan implements |
| `docs/plan/0002-text-extraction-plan.md` | Plan | Rendering, vision call and `document_texts` this moves and extends |
| `docs/plan/0003-structured-extraction-plan.md` | Plan | Extraction prompt and truncation this extends |
| `docs/plan/0005-agent-plan.md` | Plan | Tools and guards this extends |
| `docs/plan/0008-guardrails-plan.md` | Plan | Grounding and confidence this extends |
| `docs/reference/folder-structure.md` | Reference | Structural placement of planned components |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this plan (next: 0010) |

## Open Questions

None — the PRD's decisions are final; details above are implementation choices within them.
