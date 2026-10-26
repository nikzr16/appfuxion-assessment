# 0002 Text Extraction PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Turn a stored upload (PDF, JPG or PNG) into plain text, so structured extraction (0003)
has something to read. PDFs with a real text layer use a PDF parser (fast, free, exact);
images and scanned PDFs are rendered and transcribed by an OpenAI vision model. This is
brief Part 2: Text Extraction → `{document_id, raw_text}`.

## Goals

- One service function, `extract_text(document_id)`, that reads the stored file, picks
  the method (PDF parser or vision), saves the result in `document_texts`, and returns it.
  This is the function the 0005 agent's `extract_text` tool wraps.
- `GET /api/documents/{id}/text` returns `{document_id, raw_text}` for a document whose
  text has been extracted, and a clear error when it has not (yet).
- Vision is used only when needed and with hard limits on pages and image size, so cost
  per document is bounded.
- Every vision call goes through `app/core/llm.py` with a versioned prompt in
  `prompts.py`; tests use `FakeLLM` only.

## Non-Goals

- Structured fields (vendor, totals, line items) — 0003.
- Table / layout extraction and bounding boxes — B5 `vision` (0009).
- Wiring extraction into the upload pipeline or changing document status on success —
  0005 owns orchestration and completion (see D7).
- Language detection, translation, spell-correction of the text.
- Classic OCR engines (Tesseract etc.) — vision LLM covers images in this brief.
- Re-run / delete endpoints.

## Scope

| In Scope | Out of Scope |
|---|---|
| `backend/app/modules/text_extraction/` (router, service, schema, crud, model, prompts) | Agent tool registration (0005) |
| `document_texts` table + Alembic migration | Per-page or per-block storage (B5) |
| PDF text-layer extraction; "no text layer" detection | Table extraction (B5) |
| PDF page rendering + image normalisation for vision | OCR engines other than the vision LLM |
| `GET /api/documents/{id}/text` | `POST` / re-run endpoints |
| Small additive read in `documents.service` / `documents.schema` so this module can locate the stored file (D9) | Any other change to the documents module |
| New error codes for extraction failures | Changing the 0001 status lifecycle |
| Service + router tests on real Postgres with generated fixtures and `FakeLLM` | Real OpenAI calls in tests |

## User Stories

1. **As a user**, I want the text of my uploaded invoice — typed or photographed — so
   that the later steps can read it.
2. **As a user**, I want a clear message when my document is still processing or has no
   readable text, so that I know what to do.
3. **As the 0005 agent**, I want one `extract_text(document_id)` call that is safe to
   repeat, so that a retry or a second tool call does not pay for vision twice.
4. **As the developer**, I want the extraction method, page count, model and prompt
   version stored, so that I can explain and debug a result.

## Product Decisions

All decisions agreed with the user on 2026-10-26.

| # | Decision | Rationale |
|---|---|---|
| D1 | **PDF parser: `pdfplumber` (MIT)** for the text layer; its dependency **`pypdfium2` (Apache-2.0 / BSD-3)** renders pages for vision; **Pillow** normalises images. No AGPL (PyMuPDF) and no system binaries (poppler) | Permissive licences only (public repo); pure `pip`/`uv` wheels on Windows + Linux CI; pdfplumber's line grouping reads invoices well and its table API is ready for B5 |
| D2 | **No-text-layer check per page:** strip whitespace and `(cid:N)` glyph placeholders; a page has text if ≥ **20** characters remain. **All pages have text → `pdf_parser`; any page below → `vision` for the whole document** | Cheap and deterministic; catches scans, image-only pages and broken font encodings; keeps `method` a single value |
| D3 | **Rendering:** pypdfium2 at **200 DPI**, PNG; any image (uploaded or rendered) is EXIF-rotated, converted to RGB and downscaled so its long side ≤ **2048 px**; `detail: "high"`. **Max `VISION_MAX_PAGES` = 5** (env, default 5) pages sent; extra pages are skipped and logged; Pillow's decompression-bomb limit stays on | 200 DPI is legible for small print; 2048 px matches what OpenAI keeps anyway, so larger only costs upload time; the page cap bounds cost per document |
| D4 | **Vision call:** one call **per page**, structured output `PageTranscription {text: str, legible: bool}`, temperature 0, model `OPENAI_VISION_MODEL`. Prompt lives in `text_extraction/prompts.py` with `PROMPT_VERSION = "text_extraction.v1"`: transcribe verbatim in reading order, keep line breaks, table rows on one line with `" \| "` between cells, never summarise, translate, correct or invent; `legible=false` when no text can be read | Per-page keeps output order and failures clear; structured output gives a clean "unreadable" signal and no chatter like "Here is the text:" |
| D5 | **One row per document** (`document_id` UNIQUE, FK `ON DELETE CASCADE`). Pages are joined with a blank line plus a `--- Page N ---` marker when there is more than one page. `extract_text` is **idempotent**: if a row exists it is returned without re-running; `force=True` replaces it in place. Extra columns **`model`** and **`prompt_version`** (null for `pdf_parser`) and **`updated_at`** | Matches the brief's `{document_id, raw_text}`; the agent can call the tool twice for free; model + prompt version make results explainable (feeds B1) |
| D6 | **Route** lives in the `text_extraction` router (prefix `/documents`, path `/{document_id}/text`) and is **read-only — it never triggers extraction or calls OpenAI**. Text row exists → **200** `{document_id, raw_text, method, page_count}` (whatever the document status). No row: unknown document → **404** `not_found`; `processing` → **409** `text_not_ready`; `completed`/`failed` → **409** `text_unavailable` (message includes the document's error when failed) | Module owns its route; GET stays safe and free; 409 says "the resource exists but is not in a state to answer", distinct from a wrong id. Extra fields are additive to the brief's shape |
| D7 | **Trigger:** no hook into the 0001 pipeline now. `extract_text` is a plain service function the 0005 agent tool will call; documents stay `processing` until 0005, as agreed in 0001. **`extract_text` never changes document status** — it raises domain errors and the caller (`run_pipeline` wrapper / agent) marks `failed`, which 0001 already does for any exception | One owner of status (the pipeline); avoids a circular import between `documents` and `text_extraction`; no throw-away wiring to remove in 0005 |
| D8 | **Empty or unreadable text is an error, not an empty row:** vision says `legible=false` on every page, or the final text is empty → `TextExtractionError` code **`no_text_found`**; corrupt / password-protected / unopenable file → code **`unreadable_document`**. Nothing is saved; the caller marks the document `failed` with the message | An invoice without text can never produce structured data; failing here gives the user a clear reason and saves a wasted 0003 LLM call |
| D9 | **Locating the file:** add an internal DTO `DocumentSource {document_id, content_type, storage_key, status, error}` to `documents.schema` and `get_document_source(db, id)` to `documents.service`; `text_extraction` reads bytes via `app.core.storage.Storage.read(storage_key)`. `storage_path` stays out of the public API | Cross-module rule allows only `documents.service`/`schema`; `DocumentRead` deliberately hides the storage path |
| — | **`method` column:** `VARCHAR` + `CHECK (method IN ('pdf_parser','vision'))`, Python `StrEnum`; `id` UUID v4 PK; timestamps timezone-aware | Same conventions as 0001 and the project's UUID rule |
| — | **Images (JPG/PNG)** always use `vision`, `page_count = 1` | Images have no text layer |

## Constraints

- Layering: router → service → crud → model; the service never imports FastAPI.
- Cross-module: only `documents.service` / `documents.schema`; file bytes only through
  `app/core/storage`.
- All OpenAI access through `app/core/llm.py` (`complete(..., vision=True,
  response_format=...)`); tests never call OpenAI.
- Only permissively licensed dependencies (MIT / BSD / Apache / HPND), installable as
  wheels without system packages, on Windows and Linux.
- Fixtures are small and generated in code where possible (text PDF, image-only PDF,
  PNG, JPG); no confidential sample invoices in the repo.
- Extraction runs in a background task (0005), so it is synchronous code and must not
  hold a DB transaction open during the vision calls.
- Error responses use the shared `{error: {code, message}}` shape; routes live under
  `/api`.

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | A PDF with a text layer is extracted with `method = pdf_parser`, correct `page_count`, text containing the invoice's words, and **no** LLM call | service test |
| 2 | An image-only (scanned-style) PDF is extracted with `method = vision`; one vision call per page with an image attached; `model` and `prompt_version` stored | service test (FakeLLM) |
| 3 | A PNG and a JPG are extracted with `method = vision`, `page_count = 1`; oversized images are downscaled to ≤ 2048 px on the long side before sending | service test (FakeLLM) |
| 4 | A PDF with more than `VISION_MAX_PAGES` pages that needs vision sends only the first `VISION_MAX_PAGES` pages; `page_count` is the real page count | service test |
| 5 | Calling `extract_text` twice returns the same row and makes no second LLM call; `force=True` re-extracts and replaces it (still one row) | service test |
| 6 | Vision reporting no legible text → `no_text_found`; a corrupt or password-protected PDF → `unreadable_document`; an LLM failure → `llm_error`; in all cases no row is saved and document status is unchanged | service tests |
| 7 | `GET /api/documents/{id}/text` → 200 `{document_id, raw_text, method, page_count}` when a row exists | router test |
| 8 | Same route: unknown id → 404 `not_found`; non-UUID → 422; `processing` with no text → 409 `text_not_ready`; `failed`/`completed` with no text → 409 `text_unavailable` | router tests |
| 9 | `alembic upgrade head` creates `document_texts` with UUID PK, unique FK to `documents` (cascade), and the `method` CHECK constraint | migration test |
| 10 | `text_extraction` imports nothing from `documents.crud` / `documents.model` | review / import test |
| 11 | `ruff check`, `ruff format --check`, `pytest` pass; CI green | CI run |

## Roadmap Phase

**Phase:** Phase 1 — Core Pipeline (brief Parts 1–5)

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0002-text-extraction-plan.md` | Plan | Implementation path for this PRD (written after this PRD is final) |
| `docs/prd/0001-documents-prd.md` | Intent | Documents table, storage, status lifecycle and pipeline hook this builds on |
| `docs/decisions/0002-documents-implementation-divergences.md` | Decision log | Status helpers flush only; pipeline wrapper marks `failed` |
| `docs/reference/folder-structure.md` | Reference | Structural placement of the module |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this PRD |

## Open Questions

None — D1–D9 agreed with the user on 2026-10-26 (pdfplumber; whole-document vision
fallback at < 20 chars/page; 200 DPI, 2048 px, 5-page cap; per-page structured vision
calls; one idempotent row per document; read-only GET with 409s; plain service function
called by the 0005 agent; empty text is an error; `DocumentSource` via `documents.service`).
