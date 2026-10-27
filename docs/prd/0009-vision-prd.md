# 0009 Vision PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Read a document's **structure**, not only its text: find **tables** (and turn the line-item
table into line items), find **layout blocks** (vendor header, bill-to, line items, totals)
with their page and position, and let the model **look at the page images** when it
extracts fields from a scan or photo. This is the brief's computer-vision bonus (B5: layout,
tables, multimodal LLM). It closes the 0002–0008 limitations that point here: "table
structure is not extracted", "line items in the middle of a very long document are lost"
(0003 truncation), "vision can misread digits" and "grounding proves a value is printed
somewhere, not in the right place" (0008).

## Goals

- A new **`modules/vision`** that owns everything image- and layout-related: page rendering,
  the vision page call, table detection, layout analysis and its own **`document_layouts`**
  table (one row per analysis, history kept).
- **Tables from text PDFs** found deterministically with `pdfplumber` (no LLM cost), with
  header-row detection, merged cells and tables that continue on the next page.
- **Layout blocks** with a type, page, reading order and (where reliable) a normalised
  position box.
- **Scans and images:** one vision call per page returns the text **and** its tables and
  blocks, so tables cost no extra call.
- **Line items from the table:** code maps the line-item table to `line_items` (exact
  printed values), which also fixes the 0003 truncation loss for long text PDFs.
- **Multimodal structured extraction** for scans and images: page images go to the model
  together with the text.
- A new agent tool **`extract_tables`** (Extraction lane) with a code guard that keeps the
  order `extract_text` → `extract_tables` → `extract_structured_data`.
- **Layout-aware grounding:** line-item values are located in table cells and the total is
  checked against the totals block.
- Every new LLM call goes through `app/core/llm.py` with a `Purpose` label and a prompt
  version, so it shows in the 0007 ledger, trace and metrics.
- UI: a **Tables & layout** view on the document detail page.
- Tests use `FakeLLM` and generated fixtures; never the real OpenAI API.

## Non-Goals

- A trained layout / table model (LayoutLM, Table Transformer, Donut) or a classic OCR
  engine (Tesseract) — the brief allows a vision LLM, and the stack stays dependency-light.
- Pixel-accurate boxes from the LLM (see D4).
- Changing the brief's result shape `{document_id, structured_data, validation, summary}`.
- Changing 0004's validation rules or 0008's confidence formula (only its inputs improve).
- Editing or correcting tables in the UI.
- Retrieval, vendor history, the Query Agent — **B3 (0010)**.
- Extraction / Validation / Reporting agents and the Coordinator — **B4 (0011)**.
- Authentication.

## Scope

| In Scope | Out of Scope |
|---|---|
| `backend/app/modules/vision/`: `router.py`, `service.py`, `schema.py`, `crud.py`, `model.py`, `prompts.py` (D1) | Layout columns on `document_texts` (D9) |
| Page rendering + image preparation moved from `text_extraction` into `vision` | New OCR / layout model dependencies |
| `pdfplumber` table + layout analysis for text PDFs | Vision calls on text PDFs (D3) |
| One combined vision call per scanned page: text + tables + blocks | Separate table / layout calls per page |
| Table → `line_items` mapping in code; tables passed to the extraction prompt | Chunked per-page extraction of long scans |
| Multimodal `extract_structured_data` for `vision` documents | Images for text PDFs |
| `extract_tables` agent tool + guard; prompt bumps; `AGENT_MAX_STEPS` 10 → 12 | Multi-agent lanes as real agents (B4) |
| Layout-aware grounding (table cells, totals block) | New grounding statuses (D8) |
| Migration: new `document_layouts` table; `line_items_source` on `extractions` | Rewriting old rows (D13) |
| `GET /documents/{id}/layout`, `GET /documents/{id}/pages/{n}/image` | Changes to `GET /result`'s brief keys |
| Detail page: Tables & layout section, page preview with boxes; Metrics: small vision block | Table editing, review queue |
| Tests with `FakeLLM`, generated PDFs with tables, scanned-style images | Real OpenAI calls in tests |
| README, ENGINEERING_NOTES 0009 sections, folder-structure reference | — |

## User Stories

1. **As a reviewer**, I want to see the tables the system found, laid out as tables, so that
   I can check line items against the document at a glance.
2. **As a reviewer**, I want to see where each part of the invoice is on the page (vendor,
   bill-to, line items, totals), so that I trust the system read the right area.
3. **As a reviewer of a long invoice**, I want every line item extracted, not only those at
   the start and end, so that the totals check is meaningful.
4. **As a reviewer of a photo or scan**, I want the model to look at the image itself when it
   reads the fields, so that misread digits are caught more often.
5. **As an operator**, I want vision pages, tables found and their cost on the Metrics page,
   so that I can see what the vision features cost and how often they help.

## Product Decisions

> **Status: final.** D1–D14 answered by the user on 2026-10-27:
> D9 changed to a new `document_layouts` table with history per analysis (user's choice),
> which turns `vision` into a full module with its own table and router (D1, D10 adjusted);
> all others as recommended.

| # | Decision (recommended) | Rationale |
|---|---|---|
| D1 | **Module shape: a new full `modules/vision` (`router.py`, `service.py`, `schema.py`, `crud.py`, `model.py`, `prompts.py`)** — full because it owns the `document_layouts` table (D9) and the two read endpoints (D10). It owns page rendering + image preparation and the render lock (moved from `text_extraction`), the vision page call (moved, see D2), `pdfplumber` table and layout analysis, the table → line-item mapping and the `extract_tables` use case. **`text_extraction` keeps `document_texts`, `raw_text` and `GET /text`**; for scans it calls `vision.service` for the page call and asks it to save the returned layout. **Dependency direction is one-way:** `text_extraction`, `structured_extraction` and `agent` call `vision.service`; `vision.service` calls only `documents.service` (file source) and imports other modules' `schema` — never `text_extraction.service`, so there is no import cycle (the agent tool passes the text method in). | One owner per table keeps layering simple (router → service → crud → model), and everything image- and layout-related sits in one place that maps onto the brief's `vision/` folder. Alternative: extend `text_extraction` (fewer files, but it grows to ~600 lines and mixes concerns). |
| D2 | **Scans and images: one combined vision call per page.** The page call returns `PageAnalysis {legible, text, tables[], blocks[]}` (strict structured output) instead of `PageTranscription`; `raw_text` is built from `text` exactly as today. Purpose stays **`vision_transcription`** (same call, richer answer), prompt `vision.v1`. Limits unchanged: `VISION_MAX_PAGES` (5), long side 2048 px, JPEG, `detail: high`. | Tables and blocks come from the same look at the page, so they add output tokens (roughly +50–100 % per page) but **no extra call or image input**. Keeping the purpose label keeps 0007 metrics comparable over time. Alternative: a separate table/layout call per page (cleaner prompts, ~2× image cost). |
| D3 | **Text PDFs: `pdfplumber` tables, no LLM.** Try the `lines` strategy first, then `text` (for invoices without ruling lines). **A table** = at least 2 rows × 2 columns after dropping empty rows/columns. **Header row:** the first row whose cells match column keywords (English + Malay: description / item / perkara, qty / kuantiti, unit price / harga, amount / total / jumlah). **Merged cells:** the value stays in its first cell, the others are `null`; wrapped cell text is joined with spaces. **Multi-page:** a table on the next page with the same column count is stitched on (a repeated header row is dropped). Each table gets a `kind`: `line_items` (header maps to description + amount or unit price) or `other`. | Text PDFs are exact and free today; a vision call for their tables would add cost and new misreads. Two strategies cover ruled and unruled invoices; keyword headers make "which table is the line items" a code decision. Alternative: send text PDFs' pages to vision for tables too (more robust on odd layouts, costs money). |
| D4 | **Layout blocks: 7 types — `header` (vendor), `document_info` (number, dates), `bill_to`, `line_items`, `totals`, `payment` (bank, terms), `other`.** Each block: type, page, reading order, text, and a **normalised 0–1 box `[x0, y0, x1, y1]`**. **Text PDFs:** deterministic — `pdfplumber` words → lines → blocks split by vertical gaps; classified by label keywords and position (the table's box is the `line_items` block); boxes exact. **Scans:** blocks come from the D2 call, **without boxes** (`box: null`); reading order from the model. | Rule-based blocks are free and repeatable for text PDFs. LLM boxes are unreliable (they drift by tens of pixels), so a scan's blocks are shown as a list, not drawn. Alternatives: ask the model for rough boxes on scans (drawable, often misplaced), or no blocks at all (tables only). |
| D5 | **Line items come from the table when one is found; the model does the rest.** When a `line_items` table has a confident column mapping (description + amount, or description + quantity + unit price), **code builds `line_items`** from its rows (values parsed with 0008's number rules; subtotal / tax / total rows dropped). The model still extracts all header fields, and the table is also shown in its prompt. **Text PDFs: the table wins** over the model's line items (exact source); **scans: the model's line items win** (both come from the model, so the table is only a hint). `extractions.line_items_source` records `table` or `model`. Because the table is read from the whole document, **long text PDFs no longer lose middle line items** (0003 truncation); the prompt gets the table instead of the cut text. | "Code does the maths and keeps the order": copying printed cells is a deterministic job, and it closes the truncation gap. Alternatives: (b) only put the tables in the prompt and let the model decide (simpler, does not fix truncation, can still drop rows); (c) use the table only to *check* the model's line items (flag differences). |
| D6 | **Multimodal extraction for scans and images.** When `document_texts.method = vision`, `extract_structured_data` sends the page images (re-rendered from the stored file, same limits as D2) **plus** the text to the model. New **`Purpose.MULTIMODAL_EXTRACTION`** (the grounding retry keeps `grounding_retry` and also gets the images). Text PDFs stay text-only. Prompt bump `structured_extraction.v3`. | The image lets the model cross-check digits and see which number sits next to "Total" — the brief's "multimodal LLM extraction". It adds roughly 1–2.5 k input tokens per page per call; text PDFs gain nothing from images. Alternatives: text only (today, cheapest), or images only on a grounding retry (cheaper happy path, slower fix). |
| D7 | **`extract_tables` is its own agent tool, required by a guard.** Order: `extract_text` → **`extract_tables`** → `extract_structured_data` → `check_grounding` → `validate_invoice` → (`convert_currency`) → `generate_summary`. `extract_structured_data` refuses (recoverable `tables_required`) until `extract_tables` has run in this run; a new `extract_text` resets it. The tool always succeeds when text exists (it may return 0 tables). For text PDFs it runs D3/D4; for scans it reads what the D2 call already returned (no LLM call). It returns counts, kinds and column headers to the model, never cell text. Extraction lane in the UI. Agent prompt `agent.v3`; **`AGENT_MAX_STEPS` 10 → 12**. | Same pattern as 0008's `check_grounding`: a visible step in the trace and lanes, a rule enforced by code, and it maps onto B4's Extraction Agent (which lists `extract_tables`). Alternative: fold it into `extract_text` (one fewer turn, but no visible step and B4's tool list would not match). |
| D8 | **Layout-aware grounding, no new statuses.** (a) A line item built from a table is `grounded` with the cell as its location (page + box + "table 1, row 3, Amount"). (b) **The total** must be found inside the `totals` block (or on the same line as a total label); found only elsewhere → `weak` with reason "found, but not next to a total label". Only applied when a totals block was detected. (c) Every grounding match gains an optional `location` (block type, page, box). Confidence formula unchanged (0008 D4); scores move only because statuses do. | Closes the 0008 limitation "printed somewhere, not in the right place" for the value that matters most. Keeping the status set avoids touching the UI badges and the confidence maths. Alternative: new statuses (`misplaced`) — more precise, but ripples through confidence, UI and metrics. |
| D9 | **Storage: a new `document_layouts` table with history (user's choice).** One row **per analysis**: `id` (UUID), `document_id` (FK, cascade), `run_id` (nullable FK to `agent_runs`, set when made inside an agent run), `source` (`pdf_parser` / `vision`), `layout_version` (`layout.v1` for `pdfplumber`, `vision.v1` for scans), `page_count`, `pages` (JSONB: size per page), `tables` (JSONB: page, box, header, rows, kind), `blocks` (JSONB), `created_at`. Rows are **append-only**: a reprocess adds a row; the **newest row is current**; older rows stay as history. `extract_tables` reuses the newest row unless the run forces a new analysis. `extractions` gets `line_items_source` (`table` / `model`, nullable). | Each run's layout can be compared with earlier ones (e.g. after a prompt or rule change), and it is linked to the run that made it, which fits the per-run trace (0007) and confidence (0008). A table of its own also keeps `document_texts` unchanged. Cost: one more table, crud and model in `vision`. |
| D10 | **API: two new read endpoints in `vision/router.py`; existing responses unchanged.** `GET /documents/{id}/layout` → the newest analysis `{document_id, layout_id, source, layout_version, run_id, created_at, pages: [{page, width, height}], tables, blocks, history: [{layout_id, created_at, source, layout_version, run_id}]}` (history is metadata only; 409 `layout_not_ready` / `layout_unavailable` like `/text`). `GET /documents/{id}/pages/{n}/image` → a JPEG of page *n* (rendered on request, long side 1600 px, `Cache-Control: private, max-age`) for the page preview; images return page 1. `GET /text`, `/result`, `/extraction` keep their shapes (`/extraction` adds `line_items_source`). | Layout can be large; a separate endpoint keeps `/text` light and the brief's shapes intact. Rendering on request needs no image storage. Alternative: add `tables` / `layout` to `GET /text` (one call less, heavier payload). |
| D11 | **UI: a "Tables & layout" section on the detail page, next to Raw text.** (a) **Tables:** each table rendered as a real table with its page and kind; the line-item table is marked "Used for line items" (or "Hint only" on scans). (b) **Page preview** with the layout boxes drawn over the page image (colour **and** a text label per block type, legend), page switcher; scans show the block list instead of boxes. (c) Line items built from a table get **"Show on page"**, which opens the preview and highlights that row's box; header fields keep 0008's "Show in text". Light + dark, 375 px (preview scales to width). Old documents: "Reprocess to analyse layout". | Shows the new data where reviewers already look, and "show on page" turns a table row into a one-click proof. Alternatives: tables only (no page image endpoint; simpler), or "Show on page" for every field too (needs word-level boxes for every grounding match — a bigger change). |
| D12 | **Metrics: a small vision block.** `/metrics/summary` and the Metrics page add: documents with a line-item table, share of line items from tables vs the model, pages read by vision, and multimodal extraction calls. Tokens and cost stay in the existing by-purpose table (it already splits `vision_transcription` and will show `multimodal_extraction`). Same `?days=` window. | Shows how often B5 helps and what it costs, reusing 0007's ledger instead of new counters. Alternative: no metrics change (by-purpose already shows cost). |
| D13 | **No backfill.** Documents from before 0009 keep `null` tables / layout; the UI says "Reprocess to analyse layout" (same pattern as 0007 D8 / 0008 D11). | Keeps the migration schema-only; reprocessing one document gives it the full analysis. Alternative: a one-off command that back-fills text PDFs only with `pdfplumber` (no LLM cost; scans would still need a reprocess). |
| D14 | **Scope guard:** B3 (retrieval, Query Agent), B4 (multi-agent, Coordinator) and authentication stay out of 0009. | Keeps 0009 to the brief's computer-vision bonus. |

## Constraints

- Layering: router → service → crud → model; `service.py` never imports FastAPI.
- Cross-module: modules import each other's `service` / `schema` only. `vision.service`
  calls only `documents.service` and imports other modules' `schema`; `text_extraction`,
  `structured_extraction` and `agent` call `vision.service` (one-way, no cycles).
- All OpenAI access stays in `app/core/llm.py`; every call has a `Purpose` and a
  `prompt_version`.
- Table detection, layout blocks for text PDFs, the table → line-item mapping and grounding
  are deterministic code — same input, same output.
- Domain Rule 4 ("never invent values"): table-derived line items copy printed cells only; an
  empty cell is `null`.
- Bounded cost: vision pages ≤ `VISION_MAX_PAGES`; images ≤ 2048 px long side; at most 3
  extraction calls per extraction (0008).
- pypdfium2 rendering stays serialised by one process-wide lock (now in `vision`), including
  the page-image endpoint.
- Money as `Decimal`; UUID v4 PKs; timezone-aware timestamps; errors use the shared
  `{error: {code, message}}` shape; routes under `/api`.
- Frontend: one typed API client, TanStack Query, Tailwind tokens, light + dark, 375 px;
  block types never shown by colour alone.

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | Generated text PDFs with a ruled table, an unruled table, a merged cell, wrapped descriptions and a table continued on page 2 give the expected tables (rows, header, kind, page, box) | unit tests |
| 2 | Layout blocks for a generated text PDF have the expected types, reading order and boxes (0–1) | unit tests |
| 3 | A scanned-style image / PDF makes one vision call per page (FakeLLM) returning text + tables + blocks; `raw_text` matches the 0002 format; ledger rows have purpose `vision_transcription` and prompt `vision.v1` | service tests |
| 4 | A line-item table maps to `line_items` (Decimal values, totals rows dropped, empty cells `null`); text PDFs use the table (`line_items_source = table`), scans keep the model's; a text PDF over 60,000 characters keeps every middle line item | service tests |
| 5 | For `vision` documents, `extract_structured_data` sends page images + text with purpose `multimodal_extraction`; text PDFs send text only | service tests (FakeLLM) |
| 6 | `extract_structured_data` before `extract_tables` (or after a new `extract_text`) returns the recoverable `tables_required`; a scripted happy path fits in `AGENT_MAX_STEPS = 12` | agent tests (FakeLLM) |
| 7 | Table-derived line items are grounded with a cell location; a total found only outside the totals block is `weak` with its reason; without a totals block behaviour equals 0008 | unit tests |
| 8 | `GET /layout` returns the newest analysis + history metadata (409 before / without analysis); a reprocess adds a row and keeps the old one; `GET /pages/{n}/image` returns a JPEG (404 for a bad page); existing endpoints keep their keys | router + crud tests |
| 9 | `/metrics/summary` returns the vision block for seeded data and respects `?days=` | service + router tests |
| 10 | `alembic upgrade head` creates `document_layouts` and adds `extractions.line_items_source` | migration test |
| 11 | `vision` imports no other module's `crud` / `model`; `vision.service` imports nothing from FastAPI and does not import `text_extraction.service` | import test |
| 12 | Detail page shows the Tables & layout section (tables, page preview with labelled boxes, block list for scans, "Show on page" for table rows, "reprocess" state); Metrics page shows the vision block | Vitest + browser check (desktop + 375 px, light + dark) |
| 13 | `ruff check`, `ruff format --check`, `pytest`, `npm run lint`, `typecheck`, `test` (also with `TZ=UTC`), `build` pass; CI green | CI run |

## Roadmap Phase

**Phase:** Phase 3 — Bonus Tasks (B5, after B1 and B2 so every vision call is traced and
its values grounded).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0009-vision-plan.md` | Plan | Implementation path (written after this PRD is final) |
| `docs/prd/0002-text-extraction-prd.md` | Intent | `document_texts`, `pdf_parser` / `vision`, page markers, `VISION_MAX_PAGES` |
| `docs/prd/0003-structured-extraction-prd.md` | Intent | `InvoiceData`, truncation limit, `extractions` |
| `docs/prd/0004-validation-prd.md` | Intent | Line-item checks that benefit from complete line items |
| `docs/prd/0005-agent-prd.md` | Intent | Tools, guards, `AGENT_MAX_STEPS` |
| `docs/prd/0006-frontend-prd.md` | Intent | Detail page sections and agent lanes |
| `docs/prd/0007-observability-prd.md` | Intent | `llm_calls` ledger, `Purpose` labels, metrics |
| `docs/prd/0008-guardrails-prd.md` | Intent | Grounding statuses, locations, confidence |
| `docs/reference/folder-structure.md` | Reference | Structural placement of the module |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this PRD |

## Open Questions

None — D1–D14 answered by the user on 2026-10-27 (a new `vision` module owning rendering,
the vision page call, tables and layout; one combined vision call per scanned page;
`pdfplumber` tables for text PDFs; 7 block types, boxes only for text PDFs; line items built
by code from the table, table wins on text PDFs, fixing truncation; page images sent with
the text for scans; `extract_tables` as its own guarded tool, `AGENT_MAX_STEPS` 12;
layout-aware grounding without new statuses; **a new `document_layouts` table with history
per analysis** (user's choice); `GET /layout` + page-image endpoint; Tables & layout section
with page preview and "Show on page" for table rows; a small vision metrics block; no
backfill; B3 / B4 / auth out of scope). Signed off as final on 2026-10-27.
