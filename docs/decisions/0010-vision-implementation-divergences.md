# 0010 - Vision implementation details that differ from the 0009 plan

> **Date:** 2026-10-27 | **Status:** Accepted

<!-- AI Context
Role: This is an append-only record of a single implementation divergence.
Each entry captures why the deviation happened and what it affects.
Never edit an existing decision log entry. To reverse a previous decision,
create a new entry that references the original. After adding an entry,
check the impact checklist below and update affected workflow or reference
docs before the session ends.
-->

## Context

Implementing `docs/plan/0009-vision-plan.md`, testing it against generated invoices, running
real documents through it with OpenAI and checking the UI in the browser at desktop and
375 px (light and dark) changed a few details the plan had sketched. None changes the PRD's
decisions D1–D14, the stored table or the API shapes.

## Decision

1. **Unruled tables use our own header-anchored detector, not pdfplumber's `text`
   strategy.** The plan used `find_tables` with the `text` strategy as the fallback. On the
   test invoices it split words inside cells (`Descriptio | n`, `Acme T | rading`) and turned
   the whole page into one table. The fallback now finds a header line with at least two
   known column titles, takes the column positions from its word groups, cuts the lines below
   at those positions, joins wrapped descriptions to the row above, and stops at a totals line
   or a wide gap. The `strategy` value is still `text`.
2. **A totals label keeps its amount in one segment.** Splitting lines at wide gaps (to
   separate a two-column header) also split right-aligned totals (`Subtotal ……… 675.00`) into
   a label block and a number block, so neither was typed `totals`. A segment that is a
   totals label now absorbs the number segment that follows it on the same line.
3. **`TableItem` instead of `LineItem` in `vision.schema`.** The plan returned
   `structured_extraction.schema.LineItem` from the table mapping. That made the schemas import
   each other in a cycle (`structured_extraction.schema` → `guardrails.schema` →
   `vision.schema` → `structured_extraction.schema`). `vision` returns its own `TableItem`
   (same four fields, `Decimal` values) and `structured_extraction` builds the `LineItem`s.
4. **The metrics vision block is assembled by `observability`.** The plan named a
   `VisionStats` DTO in `vision.schema` covering every number. The ledger counts (pages read
   by vision, multimodal calls) live in `observability`, which `vision` must not import, so
   `vision.service.layout_stats` returns only `LayoutStats` (layouts, documents with a
   line-item table, tables found) and `observability` builds `VisionMetrics` from it,
   `structured_extraction.service.line_item_source_stats` and its own ledger counts.
5. **Small UI changes after the browser check.**
   - The labels on the page boxes are dark text on white with a coloured border, not white
     text on the block colour: white on the yellow and orange steps fails contrast at 10 px.
   - Boxes are drawn 0.6 % of the page wider than the text on each side (`BLOCK_PAD`), so
     the outline never touches the letters.
   - The box colours are one fixed set for both themes (the reference palette's dark steps):
     the outlines are drawn on the page image, which is white in both themes, and that set
     passes the palette validator on the white page, the light surface and the dark surface.
   - On phones a box shows only its reading-order number; the label is in the legend and in
     the block list. The "Show on page" button sits next to the row number.
6. **`document_layouts.created_at` uses `clock_timestamp()`.** `now()` is the transaction
   start, so two analyses saved in one transaction (tests, and a forced re-analysis in the
   same request) had the same time and history order was undefined.

## Reason

Each change came from a test, a real document or the visual check, and keeps the PRD's intent
(deterministic tables for text PDFs, one-way dependencies, readable labels, never colour
alone) with less code or a clearer screen.

## Impact

- [x] Reference doc updated (`docs/reference/folder-structure.md`)
- [x] ENGINEERING_NOTES.md 0009 sections describe the shipped behaviour
- [ ] No upstream doc update needed
