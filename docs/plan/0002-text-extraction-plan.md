# 0002 Text Extraction Implementation Plan

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

Add the `text_extraction` module (model, crud, schema, service, router, prompts), one
Alembic migration for `document_texts`, a small additive read on the documents module
(`DocumentSource` + `get_document_source`), a generic `ConflictError` (409) in
`app.core.errors`, and one setting (`VISION_MAX_PAGES`). PDFs with a text layer go
through pdfplumber; images and scanned PDFs are normalised with Pillow (pages rendered by
pypdfium2) and transcribed page by page through `app.core.llm` with structured output.
Nothing is wired into the upload pipeline (PRD D7): `service.extract_text` is the function
the 0005 agent tool will call.

## Technical Approach

### Layers
`model.py`, `crud.py`, `schema.py`, `service.py`, `router.py`, plus `prompts.py`
(versioned prompt constants, required by the project's LLM rule). PDF/image helpers stay
private functions in `service.py`; if it grows past ~300 lines they move to a private
`_pdf.py`/`_images.py` (recorded in the decision log if so).

### Service API
```python
def extract_text(
    db: Session, storage: Storage, llm: LLMClient, document_id: UUID, *, force: bool = False
) -> DocumentTextRead
def get_text(db: Session, document_id: UUID) -> DocumentTextRead      # read-only, for GET
```
`extract_text` **commits its own row** (a tool result that survives later pipeline
failures, so `GET /text` still answers when a later step fails — PRD D6). It never
changes the document's status (PRD D7).

### `extract_text` algorithm
```
source = documents_service.get_document_source(db, id)     # 404 not_found if unknown
if not force and (row := crud.get_by_document(db, id)): return row (no LLM call)
db.commit()                                                 # end the read transaction:
                                                            # no DB txn open during LLM calls
data = storage.read(source.storage_key)                     # missing file → unreadable_document
if content_type is image/*:  result = _vision([_prepare_image(data)], page_count=1)
else (PDF):
    open with pdfplumber (BytesIO)                          # any open/parse error, 0 pages,
                                                            # password → unreadable_document
    texts = [page.extract_text() or "" for page in pdf.pages]
    if all(_has_text(t) for t in texts): result = pdf_parser(texts)
    else: images = _render_pages(data, first VISION_MAX_PAGES); result = _vision(images, page_count)
if result text is empty after strip → no_text_found
crud.upsert(db, ..., overwrite=force); db.commit()          # INSERT … ON CONFLICT (document_id)
return DocumentTextRead                                     #   DO UPDATE (force) / DO NOTHING
```
On `ON CONFLICT DO NOTHING` (a concurrent call won the race) the existing row is
re-read and returned. Exceptions from `app.core.llm` (`LLMError`, 502 `llm_error`) pass
through unchanged; nothing is saved.

### No-text-layer check (`_has_text`, PRD D2)
Remove whitespace and pdfminer glyph placeholders (`re.sub(r"\(cid:\d+\)|\s", "", t)`);
the page has text if ≥ `MIN_PAGE_CHARS = 20` characters remain. Any failing page sends the
whole document to vision. The stored `pdf_parser` text is the parser output with trailing
whitespace trimmed per page (no other rewriting).

### Rendering and image normalisation (PRD D3)
- `_render_pages(data, max_pages)`: `pypdfium2.PdfDocument(data)`, for each of the first
  `max_pages` pages `page.render(scale=RENDER_DPI / 72).to_pil()` with
  `RENDER_DPI = 200`; pages beyond the cap are skipped with a `WARNING` log
  (`pages_total`, `pages_sent`).
- `_prepare_image(img_or_bytes) -> bytes`: `Image.open` (uploads) →
  `ImageOps.exif_transpose` → `convert("RGB")` → `thumbnail((2048, 2048))` → JPEG,
  quality 90. `Image.DecompressionBombError` / `UnidentifiedImageError` / `OSError` →
  `unreadable_document`. JPEG keeps base64 payloads small; q90 keeps print legible.
- Constants (`RENDER_DPI`, `MAX_IMAGE_SIDE = 2048`, `JPEG_QUALITY = 90`,
  `MIN_PAGE_CHARS = 20`) live at the top of `service.py`; only the page cap is config.

### Vision call (PRD D4)
One `llm.complete(...)` per page:
```python
messages = [
    {"role": "system", "content": prompts.SYSTEM_PROMPT},
    {"role": "user", "content": [
        {"type": "text", "text": prompts.page_prompt(page=n, total=total)},
        {"type": "image_url",
         "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
    ]},
]
llm.complete(messages, vision=True, response_format=PageTranscription, temperature=0)
```
`PageTranscription {text: str, legible: bool}` (all fields required — OpenAI strict
structured output). `response.parsed is None` (refusal / malformed) → `LLMError`.
`legible=False` counts as empty text for that page. The stored `model` is the first
response's `model`; `prompt_version = prompts.PROMPT_VERSION`.

`prompts.py`:
- `PROMPT_VERSION = "text_extraction.v1"`
- `SYSTEM_PROMPT`: you are a transcription engine for financial documents; copy every
  visible character exactly, in natural reading order (top-to-bottom, left-to-right);
  keep line breaks; one table row per line with cells separated by `" | "`; keep numbers,
  currency symbols and punctuation exactly as printed; do not summarise, translate,
  correct, reformat or add anything; do not describe images or logos; `legible=false` and
  `text=""` only when no text can be read.
- `page_prompt(page, total)`: `"Transcribe page {page} of {total}."`

### Page joining (PRD D5)
One page → the text as is. More than one page → `"--- Page N ---\n" + text` blocks joined
by `"\n\n"`, for both methods. Empty vision pages keep their marker (page numbering stays
true). `page_count` = pages in the file (1 for images), even when vision was capped.

### Route (PRD D6)
`router = APIRouter(prefix="/documents", tags=["text_extraction"])`,
`GET /{document_id}/text` → `DocumentTextResponse {document_id, raw_text, method,
page_count}`. `service.get_text`:
```
row exists                      → DocumentTextRead
no row: source = get_document_source (404 not_found if unknown)
  status processing             → ConflictError("text_not_ready")
  status completed / failed     → ConflictError("text_unavailable"; message includes source.error)
```
The router registers after `documents_router` in `ROUTERS`; no path clash with
`GET /documents/{document_id}`.

### Errors
| Code | Status | Class | Raised when |
|---|---|---|---|
| `not_found` | 404 | `NotFoundError` (existing) | unknown document |
| `text_not_ready` / `text_unavailable` | 409 | new `ConflictError` in `app/core/errors.py` (generic, default code `conflict`) | GET with no text row |
| `unreadable_document` / `no_text_found` | 422 | new `TextExtractionError(AppError)` in `text_extraction/service.py` | file cannot be opened / no legible text |
| `llm_error` | 502 | `LLMError` (existing) | OpenAI failure or no parsed output |

### Documents module addition (PRD D9)
- `documents/schema.py`: `DocumentSource` (internal DTO, `from_attributes`):
  `document_id` (alias `id`), `content_type`, `storage_key` (alias `storage_path`),
  `status`, `error`. Not used by any route.
- `documents/service.py`: `get_document_source(db, document_id) -> DocumentSource`
  (404 if unknown). Tests added to `tests/modules/documents/test_service.py`.

### Data model (`document_texts`)
| Column | Type |
|---|---|
| `id` | `Uuid` PK, `default=uuid.uuid4` |
| `document_id` | `Uuid`, `ForeignKey("documents.id", ondelete="CASCADE")`, `UNIQUE` |
| `raw_text` | `Text` |
| `method` | `String(20)` + `CHECK (method IN ('pdf_parser','vision'))` |
| `page_count` | `Integer` + `CHECK (page_count >= 1)` |
| `model` | `String(100)` NULL |
| `prompt_version` | `String(50)` NULL |
| `created_at`, `updated_at` | `DateTime(timezone=True)`, `server_default=now()`, `updated_at` `onupdate=now()` |

The FK is a string reference — `text_extraction.model` never imports `documents.model`.
`ExtractionMethod(StrEnum)` lives in `schema.py`; the model imports it (same pattern as
`DocumentStatus`).

### Logging
Inside `bind_document_id`: `text extracted` (`method`, `page_count`, `pages_sent`,
`chars`, `duration_ms`); `vision page cap applied` warning; reuse of an existing row at
`DEBUG`. LLM token usage is already logged per call by `app.core.llm`.

## System Components

| Component | Responsibility |
|---|---|
| `modules/text_extraction/model.py` | `DocumentText` table (above) |
| `modules/text_extraction/crud.py` | `get_by_document(db, document_id)`, `upsert(db, *, values, overwrite)` → row (Postgres `insert … on_conflict_do_update / do_nothing`) |
| `modules/text_extraction/schema.py` | `ExtractionMethod`, `PageTranscription` (LLM output), `DocumentTextRead` (internal, all columns), `DocumentTextResponse` (API) |
| `modules/text_extraction/prompts.py` | `PROMPT_VERSION`, `SYSTEM_PROMPT`, `page_prompt()` |
| `modules/text_extraction/service.py` | `extract_text`, `get_text`, `TextExtractionError`, `_has_text`, `_render_pages`, `_prepare_image`, `_transcribe_pages`, `_join_pages` |
| `modules/text_extraction/router.py` | `GET /documents/{document_id}/text` |
| `modules/documents/schema.py` / `service.py` | `DocumentSource`, `get_document_source` (additive) |
| `app/core/errors.py` | `ConflictError` (409) |
| `app/core/config.py` + `.env.example` + `CLAUDE.project.md` env list | `VISION_MAX_PAGES` (default 5, ≥ 1) |
| `app/main.py` | add `text_extraction_router` to `ROUTERS` |
| `app/models.py` | import `text_extraction.model` |
| `migrations/versions/0003_create_document_texts.py` | table, FK (cascade), unique, both checks |

## Processing Flow

```
(0005 agent tool / tests) ── extract_text(db, storage, llm, id, force?) ──▶ service
  get_document_source ── 404 ──▶ NotFoundError
  existing row & !force ──▶ return it (no LLM)
  commit (close read txn) → storage.read
  image ─────────────▶ prepare (EXIF, RGB, ≤2048px, JPEG) ─▶ vision ×1
  PDF ─▶ pdfplumber ─┬─ every page ≥20 chars ─▶ pdf_parser text
                     └─ otherwise ─▶ pypdfium2 200 DPI, first N pages ─▶ prepare ─▶ vision ×N
  empty → no_text_found · unopenable → unreadable_document · OpenAI → llm_error
  upsert row → commit ──▶ DocumentTextRead
  (document status untouched; on raise, 0001's run_pipeline marks the document failed)

client ── GET /api/documents/{id}/text ──▶ router ─▶ service.get_text
  row → 200 {document_id, raw_text, method, page_count}
  none → 404 unknown · 409 text_not_ready (processing) · 409 text_unavailable (completed/failed)
```

## Dependencies

| Dependency | Licence | Purpose |
|---|---|---|
| `pdfplumber` | MIT | Text-layer extraction (pulls in `pdfminer.six`, MIT) |
| `pypdfium2` | Apache-2.0 / BSD-3 | Page rendering (already a pdfplumber dependency; declared because we import it) |
| `pillow` | MIT-CMU (HPND) | Image decode, EXIF rotation, resize, JPEG encode (declared because we import it) |
| `reportlab` *(dev only)* | BSD | Test fixtures: text PDFs (1 and many pages) and a password-protected PDF |

All ship wheels for Windows and Linux; no system packages. Docker image unchanged apart
from `uv sync`.

## Implementation Phases

### Phase 1: Foundations + data layer
`uv add pdfplumber pypdfium2 pillow`, `uv add --dev reportlab`. `ConflictError` +
test in `tests/core/test_errors.py`. `VISION_MAX_PAGES` setting + `.env.example` +
`CLAUDE.project.md` env list + `tests/test_config.py`. `DocumentSource` +
`get_document_source` + tests. `model.py`, `app/models.py`, autogenerate
`0003_create_document_texts`, review (FK cascade, unique, both checks), `crud.py`.
Extend `tests/test_migrations.py`.

### Phase 2: Extraction service
`schema.py`, `prompts.py`, `service.py` (PDF path first, then vision path).
Fixture builders + `tests/modules/text_extraction/test_service.py`.

### Phase 3: HTTP
`router.py`, wire into `ROUTERS`. `tests/modules/text_extraction/test_router.py`.

### Phase 4: Close-out
`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` green (DB via
`docker compose --env-file .env -f db/docker-compose.yml up -d`). Update
`docs/reference/folder-structure.md` (module files, route, `document_texts`,
`DocumentSource`, `ConflictError`, `VISION_MAX_PAGES`, new deps); append the 0002 section
to `ENGINEERING_NOTES.md` (method choice, no-text-layer heuristic, prompt design +
`PROMPT_VERSION`, cost bounds; limitations: vision cap drops pages beyond 5, whole-doc
vision fallback for mixed PDFs, vision may misread digits — guarded later by 0004
validation / B2; reportlab only for tests); README API list if it lists endpoints;
decision log entry for any divergence; roadmap stays `in progress` until you confirm the
merge; commit on `feature/0002-text-extraction`.

## Testing Strategy

- **Fixtures** (`tests/modules/text_extraction/conftest.py` + `samples.py`), all built in
  code at test time, no binaries in the repo:
  - `text_pdf(pages=1|3)` — reportlab, an invoice-like page ("INVOICE INV-001", vendor,
    lines, "Total RM 123.45").
  - `scanned_pdf(pages=1|7)` — Pillow-drawn invoice image(s) saved with
    `save(format="PDF", save_all=True)` → no text layer.
  - `mixed_pdf` — reportlab page + image-only page (concatenated via reportlab
    `drawImage` on a page with no text).
  - `png_invoice`, `jpg_invoice` (incl. an oversized 4000 px variant and one with an EXIF
    rotation tag).
  - `encrypted_pdf` — reportlab `encrypt="secret"`; `corrupt_pdf` — `b"%PDF-1.4\n" + junk`.
  - `stored_document(content_type, data)` helper: uploads through
    `documents.service.create_document` with the `storage` fixture (real row + file), so
    no test touches `documents.crud`.
- **`test_service.py`** (FakeLLM; scripted `PageTranscription` replies):
  - text PDF → `pdf_parser`, words present, `page_count`, `fake_llm.calls == []`,
    `model`/`prompt_version` null; 3-page PDF has `--- Page 2 ---` markers
  - scanned PDF → `vision`, one call per page, each with `vision=True`,
    `response_format=PageTranscription`, `temperature=0`, a `data:image/jpeg;base64,`
    image; `model`/`prompt_version` stored
  - mixed PDF → whole document via vision (2 calls)
  - PNG / JPG → `vision`, `page_count=1`; 4000 px image arrives ≤ 2048 px (decode the
    sent base64); EXIF-rotated image arrives upright (dimensions swapped)
  - 7-page scanned PDF with `VISION_MAX_PAGES=5` (monkeypatched setting) → 5 calls,
    `page_count=7`
  - idempotent: second call returns the same row id, no new LLM call; `force=True` →
    new LLM calls, same row id, new text, `updated_at` bumped
  - errors: all pages `legible=False` → `no_text_found`; corrupt and encrypted PDFs →
    `unreadable_document`; missing stored file → `unreadable_document`;
    `FakeLLM` raising `LLMError` → `LLMError`; in every case no row and document status
    still `processing`
  - unknown document → `NotFoundError`
  - `_has_text`: `(cid:3)` noise and whitespace do not count; exactly 20 chars passes
  - `get_text`: row → DTO; processing → `ConflictError text_not_ready`; failed →
    `text_unavailable` with the document error in the message
  - layering guard: AST scan of `app/modules/text_extraction/*.py` finds no import of
    `app.modules.documents.crud` / `.model`
- **`test_router.py`**: 200 with exactly `{document_id, raw_text, method, page_count}`;
  404 unknown; 422 malformed id; 409 `text_not_ready` (fresh upload); 409
  `text_unavailable` (document marked failed via `documents.service.mark_failed`); GET
  never calls the LLM (`fake_llm.calls == []`).
- Never the real OpenAI API.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Vision misreads digits or invents text | Wrong totals downstream | Strict "verbatim, never invent" prompt, temperature 0; deterministic validation in 0004; grounding checks in B2 |
| Scanned documents > 5 pages | Totals on later pages lost | Configurable cap; warning log; documented limitation |
| Mixed PDFs (text + scanned page) pay for vision on every page | Cost | Accepted for simplicity (PRD D2); per-page hybrid is a B5 option |
| Broken font encodings give garbage text that still passes 20 chars | Bad `pdf_parser` text | `(cid:N)` stripped before counting; 0003 / B2 can force re-extraction (`force=True`) |
| Large or malicious images | Memory / CPU | Upload cap (10 MB), Pillow decompression-bomb guard, downscale before encode |
| `extract_text` commits on the caller's session | Caller's pending changes get committed | Documented in the docstring; 0005 tools call it at a clean point |
| pdfplumber slower than pypdf | Latency on long PDFs | Invoices are short; acceptable |

## Roadmap Phase

**Phase:** Phase 1 — Core Pipeline (brief Parts 1–5)

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0002-text-extraction-prd.md` | Intent | Product goals and decisions (D1–D9) this plan implements |
| `docs/plan/0001-documents-plan.md` | Plan | Documents module, storage and status helpers reused here |
| `docs/reference/folder-structure.md` | Reference | Structural placement of planned components |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this plan |

## Open Questions

None.
