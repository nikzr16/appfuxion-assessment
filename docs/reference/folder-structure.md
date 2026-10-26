# Folder Structure Reference

> **Type:** Reference | **Must stay current:** Yes -- update when structure, routes, schemas, or config change

<!-- AI Context
Role: This document records structural facts about the codebase: files,
modules, routes, schemas, config, and their relationships.
Treat it as a lookup table. When creating or modifying files, routes, or
schemas, update this document before the coding session ends.
If this document conflicts with a PRD or plan, this document reflects the
current state; record the divergence in the decision log.
-->

## Overview

Structure of the Document Intelligence Agent repository as of feature `0004`
(validation): a FastAPI backend with shared core infrastructure, a `health` module,
the `documents` upload module, the `text_extraction` module, the `structured_extraction`
module and the pure `validation` module, a Vite + React frontend skeleton, PostgreSQL + pgvector in Docker, and CI. Each feature adds a folder under `backend/app/modules/`.

## Directory Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py                 # create_app(), ROUTERS list, /api prefix
│   │   ├── models.py               # model registry imported by Alembic (documents, text_extraction, structured_extraction)
│   │   ├── core/
│   │   │   ├── config.py           # pydantic-settings Settings, get_settings()
│   │   │   ├── db.py               # engine, SessionLocal, Base, get_db
│   │   │   ├── llm.py              # LLMClient, OpenAILLMClient, FakeLLM, TokenUsage, LLMResponse (parsed, refusal)
│   │   │   ├── storage.py          # Storage protocol, LocalStorage (save, save_as), get_storage
│   │   │   ├── errors.py           # AppError hierarchy (incl. ConflictError 409, LLMOutputError) + handlers (app, HTTP, request validation)
│   │   │   └── logging.py          # JSON formatter, document_id context var
│   │   └── modules/
│   │       ├── health/             # router.py, service.py, schema.py
│   │       ├── documents/          # model, crud, schema, service, router, pipeline (hook for 0005)
│   │       ├── text_extraction/    # model, crud, schema, service, router, prompts (PDF parser + vision)
│   │       ├── structured_extraction/  # model, crud, schema (InvoiceData), service, router, prompts
│   │       └── validation/         # pure: schema (report, issue codes), service (validate_invoice, convert_currency), currencies (data)
│   ├── migrations/
│   │   ├── env.py                  # URL from settings, metadata from app.models
│   │   ├── script.py.mako
│   │   └── versions/               # 0001_enable_pgvector.py, 0002_create_documents.py, 0003_create_document_texts.py,
│   │                               # 0004_create_extractions.py
│   ├── tests/
│   │   ├── conftest.py             # test DB, migrate once, client / fake_llm / storage fixtures
│   │   ├── core/                   # test_llm, test_storage, test_errors, test_logging
│   │   ├── modules/health/         # test_router, test_service
│   │   ├── modules/documents/      # conftest (byte samples, pipeline spy), test_router, test_service
│   │   ├── modules/text_extraction/  # conftest (make_document), samples (PDF/image builders), test_router, test_service
│   │   ├── modules/structured_extraction/  # conftest (make_document with text, invoice()), test_schema, test_service, test_router
│   │   ├── modules/validation/     # conftest (make_invoice(), line(), TODAY), test_validate_invoice, test_convert_currency, test_currencies, test_schema, test_layering
│   │   └── test_app.py, test_config.py, test_migrations.py
│   ├── alembic.ini
│   ├── pyproject.toml              # deps (pdfplumber, pypdfium2, pillow, pycountry; dev: reportlab), ruff, pytest config
│   ├── uv.lock
│   ├── .python-version             # 3.12
│   ├── Dockerfile
│   └── docker-entrypoint.sh        # alembic upgrade head, then exec the command
├── frontend/
│   ├── src/
│   │   ├── main.tsx, App.tsx, index.css
│   │   ├── api/client.ts           # typed fetch wrapper (+ client.test.ts)
│   │   ├── components/HealthBadge.tsx  # (+ HealthBadge.test.tsx)
│   │   └── test/setup.ts           # Testing Library + jest-dom setup
│   ├── vite.config.ts              # React + Tailwind plugins, /api dev proxy, Vitest config
│   ├── eslint.config.js, tsconfig*.json, package.json, package-lock.json
│   ├── Dockerfile                  # node build -> nginx
│   └── nginx.conf                  # SPA + /api/ -> backend:8000
├── db/docker-compose.yml           # appfuxion-db (pgvector pg18), standalone
├── docker-compose.yml              # includes db/, adds backend + frontend
├── .github/workflows/ci.yml        # backend + frontend jobs
├── .env.example                    # every config key, documented (.env is git-ignored)
├── .gitattributes                  # forces LF for scripts, Dockerfiles, configs
├── README.md, ENGINEERING_NOTES.md
└── docs/                           # roadmap, prd/, plan/, reference/, decisions/, templates/
```

## Routes

All routes are served under `API_PREFIX` (default `/api`). nginx and the Vite dev server
forward `/api` to the backend.

| Method | Path | Module | Response |
|---|---|---|---|
| GET | `/api/health` | `health` | 200 `{status: "ok", database: "ok"}`; 503 `{status: "degraded", database: "error"}` |
| POST | `/api/documents` | `documents` | multipart field `file` (PDF/JPEG/PNG, ≤ `MAX_UPLOAD_MB`) → 202 `DocumentUploadResponse`; 415 / 413 / 422 on rejection |
| GET | `/api/documents/{document_id}` | `documents` | 200 `DocumentRead`; 404 unknown id; 422 id not a UUID |
| GET | `/api/documents` | `documents` | `?limit=1..100 (20)&offset=0&status=` → 200 `DocumentList`, newest first |
| GET | `/api/documents/{document_id}/text` | `text_extraction` | 200 `DocumentTextResponse` once text exists (any document status); 404 unknown id; 422 id not a UUID; 409 `text_not_ready` (still `processing`) / `text_unavailable` (`completed` / `failed`, message includes the document's error). Read-only: never starts an extraction or calls OpenAI |
| GET | `/api/documents/{document_id}/extraction` | `structured_extraction` | 200 `ExtractionResponse` once structured data exists (any document status); 404 unknown id; 422 id not a UUID; 409 `extraction_not_ready` (still `processing`) / `extraction_unavailable` (`completed` / `failed`, message includes the document's error). Read-only: never extracts or calls OpenAI |
| GET | `/api/docs` | FastAPI | Swagger UI (`/api/openapi.json` for the schema) |

## Schemas (DTOs)

| Schema | Module | Fields |
|---|---|---|
| `HealthRead` | `health` | `status: "ok" \| "degraded"`, `database: "ok" \| "error"` |
| `DocumentStatus` | `documents` | `processing` \| `completed` \| `failed` |
| `DocumentUploadResponse` | `documents` | `document_id: UUID`, `status` |
| `DocumentRead` | `documents` | `document_id: UUID`, `filename` (cleaned upload name), `version: int`, `content_type`, `size_bytes`, `status`, `error: str \| null`, `created_at`, `updated_at` (no `storage_path`) |
| `DocumentList` | `documents` | `items: DocumentRead[]`, `total`, `limit`, `offset` |
| `UploadedFile` (internal) | `documents` | `filename`, `content_type`, `data: bytes` — router → service |
| `DocumentSource` (internal) | `documents` | `document_id: UUID`, `content_type`, `storage_key` (the `storage_path` column), `status`, `error: str \| null` — returned by `documents.service.get_document_source` for other modules; no route exposes it |
| `ExtractionMethod` | `text_extraction` | `pdf_parser` \| `vision` |
| `PageTranscription` (LLM output) | `text_extraction` | `text: str`, `legible: bool` — one vision call per page, strict structured output |
| `DocumentTextRead` (internal) | `text_extraction` | every `document_texts` column (`id`, `document_id`, `raw_text`, `method`, `page_count`, `model`, `prompt_version`, `created_at`, `updated_at`) |
| `DocumentTextResponse` | `text_extraction` | `document_id: UUID`, `raw_text`, `method`, `page_count` |
| `DocumentType` | `structured_extraction` | `invoice` \| `receipt` \| `unknown` |
| `LineItem` | `structured_extraction` | `description`, `quantity`, `unit_price`, `amount` — all required, nullable; numbers are `Decimal` |
| `InvoiceData` (LLM output + 0004 input) | `structured_extraction` | `document_type`, `vendor`, `vendor_address`, `vendor_tax_id`, `customer_name`, `customer_address`, `invoice_number`, `invoice_date: date`, `due_date: date`, `payment_terms`, `currency` (3 upper-case letters), `subtotal`, `tax`, `total_amount` (`Decimal`), `line_items: LineItem[]`. Strict structured-output schema: every field required + nullable, `additionalProperties: false`, money as JSON `number`; blank text → null. In JSON (DB, API) money is a decimal string and dates are `YYYY-MM-DD` |
| `ExtractionRead` (internal) | `structured_extraction` | every `extractions` column, `data: InvoiceData` |
| `ExtractionResponse` | `structured_extraction` | `document_id: UUID`, `structured_data: InvoiceData`, `model`, `prompt_version`, `attempts` |
| `Severity` | `validation` | `error` \| `warning` \| `info` |
| `ValidationStatus` | `validation` | `pass` \| `warn` \| `fail` — any error → `fail`; else any warning → `warn`; else `pass` (info never counts) |
| `IssueCode` | `validation` | stable catalogue, see "Validation issue codes" below |
| `ValidationIssue` | `validation` | `field` (JSON path into `InvoiceData`, e.g. `line_items[2].amount`, 0-based), `code`, `severity`, `message` (sentence with the numbers), `expected` / `actual` (`Decimal \| null`, exact; set on the numeric issues) |
| `ValidationReport` | `validation` | `status`, `issues: ValidationIssue[]` (fixed order); JSON money as decimal strings |
| `ConversionResult` | `validation` | `original_amount`, `from_currency`, `to_currency`, `rate` (10 significant digits), `converted_amount` (half-up to target minor units), `rate_date: date`, `source` |
| Error body | `core/errors.py` | `{"error": {"code": str, "message": str, "details"?: any}}` — used for `AppError`, framework HTTP errors (404/405) and request validation (422, `details` = field errors) |

Error codes: `not_found` (404), `validation_failed` (422), `unsupported_media_type` (415),
`payload_too_large` (413), `llm_error` / `llm_not_configured` (502), `llm_invalid_output`
(502, `LLMOutputError`: a structured reply failed its schema; carries `errors`),
`internal_error` (500), `conflict` (409, base) with `text_not_ready` / `text_unavailable` /
`text_not_extracted` / `extraction_not_ready` / `extraction_unavailable` (409),
`unreadable_document` / `no_text_found` (422, `TextExtractionError`; raised by
`text_extraction.service.extract_text`, never returned by the GET route), and
`invalid_llm_output` / `llm_refused` (502, `StructuredExtractionError`; raised by
`structured_extraction.service.extract_structured_data`), and `unsupported_currency` /
`invalid_amount` (422, `CurrencyConversionError`; raised by
`validation.service.convert_currency`).

### Validation issue codes

Stable: codes may be added, never renamed. Severity is fixed per code except
`missing_field`.

| Code | Severity | Field | When |
|---|---|---|---|
| `missing_field` | by type (below) | the field | a required field is `null` / `line_items` empty |
| `not_financial_document` | warning | `document_type` | `document_type = unknown`; no other check runs |
| `invalid_currency` | error | `currency` | not an ISO 4217 code (via `pycountry`), or a metal / IMF / test code (`XAU`, `XDR`, `XTS`, `XXX`, …) |
| `subtotal_tax_mismatch` | warning | `total_amount` | `subtotal + tax` (or `subtotal` without tax) differs from the total by more than one minor unit |
| `tax_included` | info | `total_amount` | `subtotal` already equals the total although `tax` is set |
| `line_items_sum_mismatch` | warning | `line_items` | Σ line amounts ≠ subtotal (or ≠ both total and total − tax without a subtotal) |
| `line_items_incomplete` | info | `line_items` | a line has no amount, so the sum is not checked |
| `line_amount_mismatch` | warning | `line_items[i].amount` | quantity × unit price ≠ amount |
| `negative_amount` | warning | `subtotal` / `tax` / `total_amount` | a headline amount is negative (lines may be) |
| `due_before_invoice` | error | `due_date` | due date before invoice date |
| `date_in_future` | warning | `invoice_date` | more than 1 day after today |
| `date_too_old` | info | `invoice_date` | more than 10 years before today |

`missing_field` severity — invoice: `vendor`, `total_amount` error; `invoice_number`,
`invoice_date`, `currency` warning; `due_date`, empty `line_items` info. Receipt: `vendor`,
`total_amount` error; `invoice_date`, `currency` warning; empty `line_items` info. Tolerance
for every comparison is one minor unit of the currency (JPY 1, MYR 0.01, KWD 0.001; 0.01
when the currency is missing or invalid).

## Database

| Item | Value |
|---|---|
| Engine | PostgreSQL 18 + pgvector (`pgvector/pgvector:pg18-trixie`) |
| Container / volume | `appfuxion-db` / `appfuxion_pgdata` (mounted at `/var/lib/postgresql`) |
| Driver | SQLAlchemy 2.0 + psycopg 3 (`postgresql+psycopg://`) |
| Migrations | `0001` enables `CREATE EXTENSION IF NOT EXISTS vector`; `0002` creates `documents`; `0003` creates `document_texts`; `0004` creates `extractions` |
| ID rule | Every table's primary key is a native `UUID` (v4, `uuid.uuid4()`), exposed as a plain dashed UUID |
| Test database | `appfuxion_test` on the same server (created and migrated by `conftest.py`) |

### Table `documents`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | API field `document_id` |
| `filename` | `VARCHAR(255)` | Cleaned upload name (basename, safe characters) |
| `version` | `INTEGER` | 1 for the first upload of a name; 2, 3, … for re-uploads (case-sensitive match) |
| `storage_path` | `VARCHAR(255)` UNIQUE | Name on disk under `STORAGE_DIR`: `invoice.pdf`, `invoice(2).pdf`, …; internal only |
| `content_type` | `VARCHAR(100)` | Sniffed from magic bytes |
| `size_bytes` | `BIGINT` | |
| `status` | `VARCHAR(20)` | `CHECK` `processing` / `completed` / `failed` |
| `error` | `TEXT` NULL | Failure message (≤ 1000 chars) |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | `now()` defaults; `updated_at` bumped on update |

Constraints: `pk_documents`, `uq_documents_filename_version (filename, version)`,
`uq_documents_storage_path`, `ck_documents_status_valid`; index `ix_documents_created_at`.

### Table `document_texts`

One row per document, written by `text_extraction.service.extract_text`.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | v4 |
| `document_id` | `UUID` UNIQUE | FK `documents.id`, `ON DELETE CASCADE` |
| `raw_text` | `TEXT` | Pages joined by a blank line with `--- Page N ---` markers when the file has several pages |
| `method` | `VARCHAR(20)` | `CHECK` `pdf_parser` / `vision` |
| `page_count` | `INTEGER` | `CHECK >= 1`; pages in the file (1 for images), even when vision was capped |
| `model` | `VARCHAR(100)` NULL | Vision model that answered; null for `pdf_parser` |
| `prompt_version` | `VARCHAR(50)` NULL | `text_extraction.v1` for vision rows; null for `pdf_parser` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | `now()` defaults; `updated_at` bumped when `force=True` replaces the row |

Constraints: `pk_document_texts`, `uq_document_texts_document_id`,
`fk_document_texts_document_id_documents`, `ck_document_texts_method_valid`,
`ck_document_texts_page_count_positive`.

### Table `extractions`

One row per document, written by `structured_extraction.service.extract_structured_data`.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | v4 |
| `document_id` | `UUID` UNIQUE | FK `documents.id`, `ON DELETE CASCADE` |
| `data` | `JSONB` | `InvoiceData` in JSON mode: money as decimal strings, dates as ISO strings |
| `model` | `VARCHAR(100)` | Model that answered |
| `prompt_version` | `VARCHAR(50)` | `structured_extraction.v1` |
| `attempts` | `INTEGER` | `CHECK >= 1`; 2 when the retry was used |
| `prompt_tokens`, `completion_tokens` | `INTEGER` | `CHECK >= 0`; summed over the replies received (a reply rejected by validation is not counted) |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | `now()` defaults; `updated_at` bumped when `force=True` replaces the row |

Constraints: `pk_extractions`, `uq_extractions_document_id`,
`fk_extractions_document_id_documents`, `ck_extractions_attempts_positive`,
`ck_extractions_prompt_tokens_non_negative`, `ck_extractions_completion_tokens_non_negative`.

## Configuration

Read by `app/core/config.py` from environment variables, then `../.env` / `.env`.

| Key | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | blank | Required only for real LLM calls; created lazily |
| `OPENAI_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_EMBEDDING_MODEL` | `gpt-4.1-mini`, `gpt-4.1-mini`, `text-embedding-3-small` | Model names |
| `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES` | `60`, `2` | SDK client settings |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `appfuxion`, `change_me_locally`, `appfuxion` | Database credentials (also used by the db container) |
| `POSTGRES_HOST` | `localhost` | `db` inside Compose |
| `DB_PORT` | `5432` | Host port for the db container / a local backend; Compose pins the backend to 5432 |
| `DATABASE_URL` | blank | Optional full URL; derived from `POSTGRES_*` when blank |
| `AGENT_MODE` | `multi` | `single` or `multi` |
| `MAX_UPLOAD_MB` | `10` | Upload size limit |
| `STORAGE_DIR` | `./storage` | Upload directory (relative to `backend/`); `/app/storage` in Compose |
| `VISION_MAX_PAGES` | `5` | Most pages of a scanned PDF sent to the vision model (>= 1); later pages are skipped and logged |
| `LOG_LEVEL` | `INFO` | Root log level |
| `FRONTEND_PORT` | `8080` | Published port of the nginx frontend (Compose only) |

## Docker Compose

| Service | Defined in | Notes |
|---|---|---|
| `db` | `db/docker-compose.yml` | Published on `${DB_PORT:-5432}`; `pg_isready` healthcheck; `TZ=Asia/Kuala_Lumpur` |
| `backend` | `docker-compose.yml` | Builds `backend/`; waits for `db` healthy; runs migrations then uvicorn on 8000; `appfuxion_uploads` volume at `/app/storage` |
| `frontend` | `docker-compose.yml` | Builds `frontend/`; nginx on 80, published on `${FRONTEND_PORT:-8080}`; waits for `backend` healthy |

## Wiring

A new module's router is added to the single list in `app/main.py`:

```python
ROUTERS: list[APIRouter] = [
    health_router,
    documents_router,
    text_extraction_router,
    structured_extraction_router,
]
```

A new module's ORM models are imported in `app/models.py` so Alembic autogenerate sees them.
LLM access is injected with `Depends(get_llm_client)`; tests override it with `FakeLLM`.

The document pipeline is injected with `Depends(get_document_pipeline)`
(`app/modules/documents/pipeline.py`, signature `(document_id: UUID) -> None`). Until
0005 it is a no-op, so uploads stay `processing`. `service.run_pipeline` runs it as a
background task in its own DB session and marks the document `failed` if it raises; the
pipeline marks `completed` itself via `service.mark_completed` (flushes only; the caller commits).

Text extraction is a plain service function, not wired into the upload pipeline:
`text_extraction.service.extract_text(db, storage, llm, document_id, *, force=False)` is what
the 0005 agent tool will call. It commits its own row, never changes the document status and
raises `TextExtractionError` / `LLMError` for the caller to turn into `failed`.
`text_extraction.service.find_text(db, document_id)` returns the saved text or `None` (never
extracts) for other modules.

Structured extraction is the same kind of function:
`structured_extraction.service.extract_structured_data(db, llm, document_id, *, force=False)`
reads the saved text through `text_extraction.service.find_text` (409 `text_not_extracted`
when there is none), makes one `response_format=InvoiceData` call (temperature 0), retries
once with the validation errors fed back, commits its own row, never changes the document
status, and raises `StructuredExtractionError` / `LLMError` for the caller to turn into
`failed`.

Validation is pure (no DB, LLM or network):
`validation.service.validate_invoice(data: InvoiceData, *, today=None) -> ValidationReport`
never raises, and `validation.service.convert_currency(amount: Decimal, from_currency,
to_currency) -> ConversionResult` uses the static rate snapshot in
`validation/currencies.py` (25 currencies, USD base, `RATES_AS_OF` 2026-10-26, source
ExchangeRate-API open access). `is_iso_currency(code)` and `minor_units(code)` are public
helpers. Nothing calls them yet; the 0005 agent tools will.

LLM seam: `LLMClient.complete(..., response_format=X)` returns `LLMResponse.parsed`; a reply
that fails `X`'s validation raises `LLMOutputError` (both `OpenAILLMClient` and `FakeLLM`),
and a refusal is returned as `LLMResponse.refusal` with `parsed=None`.

## Dependencies added in 0002

| Package | Used for |
|---|---|
| `pdfplumber` | Text layer of PDFs (pulls in `pdfminer.six`) |
| `pypdfium2` | Rendering PDF pages to images for vision |
| `pillow` | Image decode, EXIF rotation, resize, JPEG encode |
| `reportlab` (dev only) | Test fixtures: text, mixed and password-protected PDFs |

## Dependencies added in 0004

| Package | Used for |
|---|---|
| `pycountry` | ISO 4217 currency code lookup (LGPL-2.1, no dependencies of its own) |

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/prd/0000-setup-prd.md` | Intent | Product goals behind the structures documented here |
| `docs/plan/0000-setup-plan.md` | Plan | Planned architecture these structures realize |
| `docs/prd/0001-documents-prd.md` | Intent | Upload API goals and decisions |
| `docs/plan/0001-documents-plan.md` | Plan | Upload API implementation path |
| `docs/prd/0002-text-extraction-prd.md` | Intent | Text extraction goals and decisions (D1-D9) |
| `docs/plan/0002-text-extraction-plan.md` | Plan | Text extraction implementation path |
| `docs/decisions/0001-setup-implementation-divergences.md` | Decision log | Where the implementation differs from the plan |
| `docs/decisions/0002-documents-implementation-divergences.md` | Decision log | 0001 documents divergences |
| `docs/decisions/0003-text-extraction-implementation-divergences.md` | Decision log | 0002 text extraction divergences |
| `docs/prd/0003-structured-extraction-prd.md` | Intent | Structured extraction goals and decisions (D1-D12) |
| `docs/plan/0003-structured-extraction-plan.md` | Plan | Structured extraction implementation path |
| `docs/decisions/0004-structured-extraction-implementation-divergences.md` | Decision log | 0003 structured extraction divergences |
| `docs/prd/0004-validation-prd.md` | Intent | Validation goals and decisions (D1-D12) |
| `docs/plan/0004-validation-plan.md` | Plan | Validation implementation path |
| `docs/decisions/0005-validation-implementation-divergences.md` | Decision log | 0004 validation divergences |
