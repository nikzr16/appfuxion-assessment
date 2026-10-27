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

Structure of the Document Intelligence Agent repository as of feature `0009`
(vision): a FastAPI backend with shared core infrastructure, a `health` module,
the `documents` upload module, the `text_extraction` module, the `vision` module (tables,
layout, page images), the `structured_extraction` module, the pure `validation` and
`guardrails` modules, the `agent` module (Document Agent, the shared `AgentRunner`, the upload
pipeline), `observability` and the small `client_config` module, a Vite + React web UI
(Upload, Documents, Document detail with the multi-agent view and Tables & layout, Metrics),
PostgreSQL + pgvector in Docker, and CI. Each backend feature adds a folder under `backend/app/modules/`.

## Directory Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py                 # create_app(), ROUTERS list, /api prefix, registers the agent pipeline and the LLM ledger recorder
│   │   ├── models.py               # model registry imported by Alembic (agent, documents, observability, retrieval, text_extraction, structured_extraction, vision)
│   │   ├── core/
│   │   │   ├── config.py           # pydantic-settings Settings, get_settings()
│   │   │   ├── db.py               # engine, SessionLocal, Base, get_db
│   │   │   ├── llm.py              # LLMClient, OpenAILLMClient, FakeLLM, TokenUsage, LLMResponse (parsed, refusal);
│   │   │   │                       # Purpose / Agent labels, LLMCallRecord, register_llm_recorder, one `llm.call` log per call;
│   │   │   │                       # optional tool_choice ("required" for the Query Agent, 0010); FakeLLM embedder / embed_error hooks;
│   │   │   │                       # transient-error retries (_classify, _with_retries, backoff + jitter; SDK retries off)
│   │   │   ├── storage.py          # Storage protocol, LocalStorage (save, save_as), get_storage
│   │   │   ├── errors.py           # AppError hierarchy (incl. ConflictError 409, LLMError retryable / retry_after, LLMOutputError) + handlers
│   │   │   └── logging.py          # JSON formatter; trace context vars (document_id, run_id, agent, purpose,
│   │   │                           # prompt_version, step_index, query_run_id), bind_document_id, bind_trace, trace_labels
│   │   └── modules/
│   │       ├── health/             # router.py, service.py, schema.py
│   │       ├── documents/          # model, crud, schema, service, router, pipeline (hook + register_pipeline_runner)
│   │       ├── text_extraction/    # model, crud, schema, service (PDF text layer; scans via vision.service), router
│   │       ├── vision/             # 0009: model (document_layouts), crud, schema (layout DTOs, PageAnalysis), service
│   │       │                       # (analyse_scanned, extract_tables, get_layout, page images), router (/layout, /pages/{n}/image),
│   │       │                       # prompts (vision.v1), images (render lock, rendering), layout (pdfplumber tables + blocks)
│   │       ├── structured_extraction/  # model, crud, schema (InvoiceData), service (extract + ground_extraction), router, prompts
│   │       ├── validation/         # pure: schema (report, issue codes), service (validate_invoice, convert_currency, expected_fields), currencies (data)
│   │       ├── guardrails/         # pure (0008): schema (grounding + confidence DTOs), service (check_grounding,
│   │       │                       # score_confidence), matching (normalisation, number / date / identifier / text / currency matchers)
│   │       ├── agent/              # model (agent_runs; 0010: query_conversations, query_runs), crud, schema, service, router
│   │       │                       # (+ query_router: /query, /conversations, /query/suggestions), prompts, runner (AgentRunner),
│   │       │                       # tools (9 document tools; 0011: per-agent tool sets), query (0010: Query Agent, its tools and checks),
│   │       │                       # coordinator (0011: multi mode, Extraction → Validation → Reporting agents, plain Python)
│   │       ├── retrieval/          # 0010: model (invoice_embeddings, pgvector), crud, schema, service (index, embeddings, vendor
│   │       │                       # history + checks, hybrid search, similar, back-fill), router (/similar, /vendor-history),
│   │       │                       # rules (pure: normalisation, invoice card, statistics, number tokens), backfill (CLI entry point)
│   │       ├── observability/      # model (llm_calls), crud, schema, service (recorder, trace, metrics), router, pricing
│   │       └── client_config/      # router, service, schema: GET /api/config (no DB)
│   ├── migrations/
│   │   ├── env.py                  # URL from settings, metadata from app.models
│   │   ├── script.py.mako
│   │   └── versions/               # 0001_enable_pgvector.py, 0002_create_documents.py, 0003_create_document_texts.py,
│   │                               # 0004_create_extractions.py, 0005_create_agent_runs.py, 0006_create_llm_calls.py,
│   │                               # 0007_guardrails.py (grounding, confidence and attempt columns),
│   │                               # 0008_vision.py (document_layouts, extractions.line_items_source),
│   │                               # 0009_retrieval.py (invoice_embeddings + HNSW index, query_conversations, query_runs,
│   │                               # llm_calls.query_run_id), 0010_multi_agent.py (agent_runs.agents)
│   ├── tests/
│   │   ├── conftest.py             # test DB, migrate once, client / fake_llm / storage fixtures, no-op pipeline,
│   │   │                           # no LLM recorder by default (opt in: agent_pipeline, llm_recorder), retry_waits (no backoff sleep)
│   │   ├── core/                   # test_llm, test_llm_retries, test_storage, test_errors, test_logging
│   │   ├── modules/health/         # test_router, test_service
│   │   ├── modules/documents/      # conftest (byte samples, pipeline spy), test_router, test_service
│   │   ├── modules/text_extraction/  # conftest (make_document), samples (PDF/image builders), test_router, test_service
│   │   ├── modules/vision/         # conftest, samples (invoice PDFs with tables, scanned images), test_layout, test_service,
│   │   │                           # test_router, test_render_lock
│   │   ├── modules/structured_extraction/  # conftest (make_document with text, invoice()), test_schema, test_service, test_grounding, test_vision_inputs, test_router
│   │   ├── modules/guardrails/     # test_matching, test_service, test_layout_grounding, test_layering
│   │   ├── modules/validation/     # conftest (make_invoice(), line(), TODAY), test_validate_invoice, test_convert_currency, test_currencies, test_schema, test_layering
│   │   ├── modules/agent/          # conftest (tool_turn, text_turn, happy_script, invoice_pdf, agent_pipeline), test_runner, test_tools,
│   │   │                           # test_service, test_router, test_guardrails, test_retrieval (0010 tools + indexing), test_query,
│   │   │                           # test_coordinator (0011 multi-agent mode)
│   │   ├── modules/retrieval/      # seed (indexed invoices with designed vectors), test_rules, test_service, test_router, test_layering
│   │   ├── modules/observability/  # conftest (reuses agent fixtures), test_pricing, test_service, test_router, test_layering
│   │   ├── modules/client_config/  # test_router, test_service
│   │   └── test_app.py, test_config.py, test_migrations.py
│   ├── alembic.ini
│   ├── pyproject.toml              # deps (pdfplumber, pypdfium2, pillow, pycountry, rapidfuzz; dev: reportlab), ruff, pytest config
│   ├── uv.lock
│   ├── .python-version             # 3.12
│   ├── Dockerfile
│   └── docker-entrypoint.sh        # alembic upgrade head, then exec the command
├── frontend/
│   ├── index.html                  # title, favicon, inline script that applies the theme before first paint
│   ├── public/favicon.svg
│   ├── src/
│   │   ├── main.tsx                # Poppins (Latin), QueryClientProvider, createBrowserRouter
│   │   ├── App.tsx                 # route table: / (Upload), /documents, /documents/:id, /metrics, * (not found)
│   │   ├── index.css               # Tailwind, `.dark` variant, semantic colour tokens (light + dark, incl. trace series,
│   │   │                           # highlight, the validated confidence-split colours and the 0009 block-type colours), base styles
│   │   ├── api/
│   │   │   ├── client.ts           # request(), ApiError (network_error for failed fetch), one function per endpoint (+ test)
│   │   │   ├── types.ts            # DTO types mirroring the backend schemas (money/dates as strings)
│   │   │   └── queries.ts          # TanStack Query keys + hooks, POLL_INTERVAL_MS (10 s), PAGE_SIZE (20), mutations
│   │   ├── lib/                    # pure logic, each with a test: format (money/dates/sizes), issues (path → target),
│   │   │                           # chat (0010: stored conversation, step labels), vendorHistory (0010: range bar, position),
│   │   │                           # agents (tool → role lanes), trace (timeline rows, bar geometry, usage per lane),
│   │   │                           # upload (client checks, MAX_FILES 5), errors (friendly text),
│   │   │                           # confidence (labels, score format, highlight spans),
│   │   │                           # layout (0009: block meta, box geometry, "Show on page" rows),
│   │   │                           # theme, cx, useDocumentTitle
│   │   ├── components/
│   │   │   ├── ui/                 # Button (+ buttonClasses), Badge, Card, Alert/ErrorAlert, Dialog (native <dialog>),
│   │   │   │                       # Skeleton, EmptyState, CopyButton, Tabs, Pagination, LiveRegion (+ announce)
│   │   │   ├── layout/             # AppLayout (header, nav, skip link, footer, focus on navigation, Ask AI launcher), ThemeToggle (+ test)
│   │   │   ├── HealthBadge.tsx     # compact backend status in the header (+ test)
│   │   │   ├── StatusBadge.tsx, severity.tsx, FileIcon.tsx, PageHeader.tsx
│   │   │   ├── ConfidenceBadge.tsx  # ConfidenceBadge (pill / icon), NotFoundMarker, ShowInTextButton (0008)
│   │   │   ├── confidenceStyle.ts   # high / medium / low: tone, icon, text colour
│   │   ├── features/
│   │   │   ├── upload/             # UploadPage, DropZone, UploadQueue, useUploadQueue (two uploads at a time) (+ page test)
│   │   │   ├── chat/               # 0010: ChatLauncher (floating button, chat state), ChatPanel (lazy-loaded panel / sheet),
│   │   │   │                       # ChatMessages (bubbles, answer card, citations, "How I found this"), useChat (+ test)
│   │   │   ├── documents/          # DocumentsPage (URL filter/page, polling), DocumentsTable (table ≥ sm, cards < sm) (+ test)
│   │   │   ├── detail/             # DocumentDetailPage (processing / completed / failed / not found), SummaryCard,
│   │   │   │                       # StructuredData, LineItemsTable, IssuesList, IssueMarker, ConversionCard,
│   │   │   │                       # RawTextSection (lazy), AgentActivity + AgentLanes (multi-agent view, tokens per lane),
│   │   │   │                       # TraceSection + TraceTimeline (0007 waterfall), ReprocessButton (confirm dialog),
│   │   │   │                       # ConfidenceSummary (0008: overall chip, Needs review banner),
│   │   │   │                       # LayoutSection + TablesView + PagePreview (0009: Tables & layout card),
│   │   │   │                       # VendorHistorySection (0010: vendor statistics, range bar, duplicates, similar invoices),
│   │   │   │                       # labels (+ page, TraceSection, LayoutSection and VendorHistorySection tests)
│   │   │   └── metrics/            # MetricsPage (/metrics: KPI tiles, Guardrails section, by model / by purpose,
│   │   │                           # ?days= window) (+ test), GuardrailsSection (0008, confidence split bar),
│   │   │                           # VisionSection (0009), RetrievalSection (0010)
│   │   ├── pages/NotFoundPage.tsx
│   │   └── test/                   # setup (jsdom polyfills), fetchMock (route-based fetch stub), fixtures, render (whole app)
│   ├── vite.config.ts              # React + Tailwind plugins, /api dev proxy (VITE_BACKEND_URL), vendor chunks, Vitest config
│   ├── eslint.config.js, tsconfig*.json, package.json, package-lock.json
│   ├── Dockerfile                  # node build -> nginx
│   └── nginx.conf                  # SPA + /api/ -> backend:8000
├── db/docker-compose.yml           # appfuxion-db (pgvector pg18), standalone
├── docker-compose.yml              # includes db/, adds backend + frontend
├── .github/workflows/ci.yml        # backend + frontend jobs
├── .env.example                    # every config key, documented (.env is git-ignored)
├── .claude/launch.json             # dev servers (backend :8000, frontend :5173) for the desktop app's preview
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
| POST | `/api/documents` | `documents` | multipart field `file` (PDF/JPEG/PNG, ≤ `MAX_UPLOAD_MB`) → 202 `DocumentUploadResponse` and a background Document Agent run; 415 / 413 / 422 on rejection; 502 `llm_not_configured` without `OPENAI_API_KEY` (nothing stored) |
| GET | `/api/documents/{document_id}` | `documents` | 200 `DocumentRead`; 404 unknown id; 422 id not a UUID |
| GET | `/api/documents` | `documents` | `?limit=1..100 (20)&offset=0&status=` → 200 `DocumentList`, newest first |
| GET | `/api/documents/{document_id}/text` | `text_extraction` | 200 `DocumentTextResponse` once text exists (any document status); 404 unknown id; 422 id not a UUID; 409 `text_not_ready` (still `processing`) / `text_unavailable` (`completed` / `failed`, message includes the document's error). Read-only: never starts an extraction or calls OpenAI |
| GET | `/api/documents/{document_id}/extraction` | `structured_extraction` | 200 `ExtractionResponse` once structured data exists (any document status); 404 unknown id; 422 id not a UUID; 409 `extraction_not_ready` (still `processing`) / `extraction_unavailable` (`completed` / `failed`, message includes the document's error). Read-only: never extracts or calls OpenAI. Includes `grounding` (0008; null until checked) and `line_items_source` (0009: `table` / `model`; null before 0009) |
| GET | `/api/documents/{document_id}/layout` | `vision` | 200 `LayoutResponse` (newest analysis + `history` metadata); 404 unknown id; 422 id not a UUID; 409 `layout_not_ready` (still `processing`) / `layout_unavailable` (no analysis: before 0009 or failed early). Read-only |
| GET | `/api/documents/{document_id}/pages/{n}/image` | `vision` | 200 `image/jpeg` preview (long side 1600 px, rendered on request under the render lock, `Cache-Control: private, max-age=3600`); PDFs: any page 1..N, images: page 1; 404 `page_not_found` / `not_found`; 422 `n < 1` |
| GET | `/api/documents/{document_id}/result` | `agent` | 200 `AgentResult` (incl. `confidence`, 0008) when `completed` (latest completed run); 409 `result_not_ready` (`processing`) / `result_unavailable` (`failed`, message includes the document's error); 404; 422. Read-only |
| POST | `/api/documents/{document_id}/reprocess` | `agent` | 202 `DocumentUploadResponse` (`processing`) and a background agent run with forced re-extraction; 409 `already_processing`; 404; 422; 502 `llm_not_configured` |
| GET | `/api/documents/{document_id}/runs` | `agent` | 200 `AgentRunRead[]`, newest first, each with its tool-call `steps`; 404; 422 |
| GET | `/api/documents/{document_id}/trace` | `observability` | `?run_id=` (default: latest run) → 200 `DocumentTrace`; 404 `not_found` (document) / `run_not_found` (run not of this document); 422 non-UUID. A document with no run yet → `run: null`, `spans: []`. Read-only |
| GET | `/api/metrics/summary` | `observability` | `?days=1..365` (default: all time) → 200 `MetricsSummary` (incl. `guardrails`, 0008, `vision`, 0009, and `retrieval`, 0010), computed live; 422 out of range |
| GET | `/api/documents/{document_id}/similar` | `retrieval` | `?limit=1..20 (5)` → 200 `SimilarInvoices` (cosine ≥ 0.30, itself excluded; `available: false` without a vector); 409 `not_indexed`; 404; 422. Read-only |
| GET | `/api/documents/{document_id}/vendor-history` | `retrieval` | 200 `VendorHistory` (computed live: earlier and later invoices of the same vendor, statistics of the others, this invoice's position, same-number duplicates); 409 `not_indexed`; 404; 422. Read-only |
| POST | `/api/query` | `agent` | body `QueryRequest` → 200 `QueryResponse` (one Query Agent turn, sync); 404 unknown `conversation_id` / `document_id`; 422 question not 3–500 chars; 502 `llm_not_configured` (nothing stored), `llm_*`, `query_failed` (the turn is stored as `failed`) |
| GET | `/api/conversations/{conversation_id}` | `agent` | 200 `ConversationRead` (turns in order); 404; 422 |
| GET | `/api/query/suggestions` | `agent` | `?document_id=` → 200 `QuerySuggestions` (example questions built by code from the index; no LLM) |
| GET | `/api/config` | `client_config` | 200 `ClientConfig` — public settings for the UI; no secrets, no DB |
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
| `DocumentTextRead` (internal) | `text_extraction` | every `document_texts` column (`id`, `document_id`, `raw_text`, `method`, `page_count`, `model`, `prompt_version`, `created_at`, `updated_at`) |
| `DocumentTextResponse` | `text_extraction` | `document_id: UUID`, `raw_text`, `method`, `page_count` |
| `DocumentType` | `structured_extraction` | `invoice` \| `receipt` \| `unknown` |
| `LineItem` | `structured_extraction` | `description`, `quantity`, `unit_price`, `amount` — all required, nullable; numbers are `Decimal` |
| `InvoiceData` (LLM output + 0004 input) | `structured_extraction` | `document_type`, `vendor`, `vendor_address`, `vendor_tax_id`, `customer_name`, `customer_address`, `invoice_number`, `invoice_date: date`, `due_date: date`, `payment_terms`, `currency` (3 upper-case letters), `subtotal`, `tax`, `total_amount` (`Decimal`), `line_items: LineItem[]`. Strict structured-output schema: every field required + nullable, `additionalProperties: false`, money as JSON `number`; blank text → null. In JSON (DB, API) money is a decimal string and dates are `YYYY-MM-DD` |
| `PageAnalysis` (LLM output) | `vision` | `text`, `legible`, `tables: {header: str[], rows: str[][]}[]`, `blocks: {type, text}[]` — one vision call per page (0009 D2), strict structured output |
| `BlockType` / `ColumnRole` / `TableKind` / `TableStrategy` | `vision` | `header \| document_info \| bill_to \| line_items \| totals \| payment \| other` / `description \| quantity \| unit_price \| amount \| other` / `line_items \| other` / `lines \| text \| vision` |
| `Box` | `vision` | `[x0, y0, x1, y1]`, fractions (0–1) of the page, origin top-left |
| `Table` | `vision` | `index`, `pages[]`, `box` (first page; null for vision), `strategy`, `header[] \| null`, `columns: ColumnRole[]`, `kind`, `rows: {page, cells[], box, cell_boxes[]}[]` (body rows only) |
| `LayoutBlock` | `vision` | `type`, `page`, `order` (reading order, 0-based), `text`, `box` (null for vision) |
| `LayoutAnalysis` / `LayoutRead` (internal) | `vision` | `source: ExtractionMethod`, `layout_version` (`layout.v1` / `vision.v1`), `page_count`, `pages: {page, width, height}[]`, `tables`, `blocks`, `model`; `LayoutRead` adds `id`, `document_id`, `run_id`, `created_at` |
| `LayoutResponse` | `vision` | `document_id`, `layout_id`, `source`, `layout_version`, `run_id`, `created_at`, `page_count`, `pages`, `tables`, `blocks`, `history: {layout_id, created_at, source, layout_version, run_id}[]` (older analyses, newest first) |
| `TablesSummary` | `vision` | `source`, `available`, `pages`, `tables: {index, pages, kind, columns, rows}[]`, `line_item_table`, `blocks: {type: count}`, `reused` — what the `extract_tables` tool returns (no cell text) |
| `TableItem` / `TableRef` / `TableLineItems` (internal) | `vision` | a line item copied from a table row (`Decimal` values), where it was printed (`table`, `row`, `page`, `box`, `cell_boxes`, `columns`), and the pair lists |
| `LayoutStats` (internal) | `vision` | `layouts_analysed`, `documents_with_line_item_table`, `tables_found` (newest analysis per document) |
| `ExtractionRead` (internal) | `structured_extraction` | every `extractions` column, `data: InvoiceData`, `grounding: ExtractionGrounding \| null`, `line_items_source` (0009) |
| `ExtractionResponse` | `structured_extraction` | `document_id: UUID`, `structured_data: InvoiceData`, `model`, `prompt_version`, `attempts`, `grounding: ExtractionGrounding \| null` (0008), `line_items_source: table \| model \| null` (0009) |
| `LineItemSourceStats` (internal) | `structured_extraction` | `from_table`, `from_model` — line items by source, for metrics (0009) |
| `GroundingStats` (internal) | `structured_extraction` | `extractions`, `values_checked`, `values_grounded`, `grounding_retry_extractions` — for metrics |
| `GroundingStatus` / `ValueKind` / `MatchKind` | `guardrails` | `grounded \| weak \| ungrounded \| inferred \| skipped` / `number \| date \| identifier \| text \| currency \| classification` / `exact \| number \| date \| identifier \| fuzzy \| symbol \| ocr \| table` (`table`: copied by code from a table cell, 0009) |
| `FieldLocation` | `guardrails` | `page`, `box`, `block: BlockType \| null`, `table`, `row`, `column: ColumnRole \| null` — where a value sits on the page (0009) |
| `FieldGrounding` | `guardrails` | `path` (`vendor`, `line_items[2].amount`), `value` (as checked), `kind`, `status`, `match`, `similarity` (fuzzy 0–100), `page`, `start` / `end` (offsets into `raw_text`), `note`, `location: FieldLocation \| null` (0009) |
| `GroundingReport` | `guardrails` | `method`, `checked`, `grounded`, `weak`, `ungrounded`, `inferred`, `fields: FieldGrounding[]` (schema order; nulls absent) |
| `ExtractionGrounding` | `guardrails` | `report` (kept attempt), `kept_attempt`, `grounding_retries`, `attempts: {attempt, reason: initial \| schema \| grounding, valid, ungrounded[]}[]`, `checked_at` — stored in `extractions.grounding` |
| `FieldConfidence` | `guardrails` | `path`, `score` (0–1, 3 decimals), `label: high \| medium \| low`, `grounding`, `page`, `start`, `end`, `location` (0009), `reasons[]` |
| `ConfidenceReport` | `guardrails` | `overall`, `label`, `needs_review`, `review_fields[]` (key fields first), `components {fields, completeness, validation}`, `fields: {path: FieldConfidence}` — `AgentResult.confidence` |
| `Severity` | `validation` | `error` \| `warning` \| `info` |
| `ValidationStatus` | `validation` | `pass` \| `warn` \| `fail` — any error → `fail`; else any warning → `warn`; else `pass` (info never counts) |
| `IssueCode` | `validation` | stable catalogue, see "Validation issue codes" below |
| `ValidationIssue` | `validation` | `field` (JSON path into `InvoiceData`, e.g. `line_items[2].amount`, 0-based), `code`, `severity`, `message` (sentence with the numbers), `expected` / `actual` (`Decimal \| null`, exact; set on the numeric issues) |
| `ValidationReport` | `validation` | `status`, `issues: ValidationIssue[]` (fixed order); JSON money as decimal strings |
| `ConversionResult` | `validation` | `original_amount`, `from_currency`, `to_currency`, `rate` (10 significant digits), `converted_amount` (half-up to target minor units), `rate_date: date`, `source` |
| `AgentMode` / `RunTrigger` / `RunStatus` / `StepStatus` | `agent` | `single \| multi` / `upload \| reprocess` / `running \| completed \| failed` / `ok \| error` |
| `ToolStep` | `agent` | `index`, `turn` (model turn, 1-based; both continue across agents in multi mode), `agent` (0011: `document` in single mode, `extraction` / `validation` / `reporting` in multi; absent on older runs), `tool`, `arguments`, `status`, `result` (exactly what the model was sent; never raw text), `error: {code, message} \| null`, `duration_ms`, `started_at` |
| `AgentResult` | `agent` | `document_id`, `structured_data: InvoiceData`, `validation: ValidationReport`, `conversion: ConversionResult \| null`, `summary`, `confidence: ConfidenceReport \| null` (0008; null for unknown documents and older results) — body of `GET /result`, stored in `agent_runs.result` |
| `AgentPart` | `agent` | 0011: one agent of a multi-agent run — `agent`, `status` (`completed \| failed`), `prompt_version`, `turns`, `steps`, `prompt_tokens`, `completion_tokens` (agent loop, + the summary call for Reporting), `started_at`, `finished_at`, `error_code` |
| `AgentRunRead` | `agent` | every `agent_runs` column except `result` (`agents: AgentPart[]` since 0011) |
| `UsageTotals` | `observability` | `llm_calls`, `failed_calls`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd: Decimal \| null` (sum of known costs; 0 with no calls; null when calls exist but none is priced), `cost_complete` (false when some model is unpriced) |
| `GroupTotals` | `observability` | `UsageTotals` + `key` (purpose, agent or model), `avg_latency_ms` |
| `TraceRun` | `observability` | `run_id`, `mode`, `trigger`, `status`, `error_code`, `error`, `started_at`, `finished_at`, `queue_ms` (upload runs only: upload → run start), `processing_ms` (null while running), `run_prompt_tokens`, `run_completion_tokens` (0005 run totals) |
| `ToolSpan` | `observability` | `kind: "tool"`, `step_index`, `turn`, `tool`, `status`, `error_code`, `started_at`, `offset_ms` (from run start), `duration_ms` |
| `LLMSpan` | `observability` | `kind: "llm"`, `id`, `step_index` (null for agent-loop turns), `purpose`, `agent`, `model`, `prompt_version`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`, `status: ok \| error`, `error_code`, `started_at`, `offset_ms`, `duration_ms`, `attempt` (1 = first try; 2+ = transient retry, 0008) |
| `DocumentTrace` | `observability` | `document_id`, `uploaded_at`, `run: TraceRun \| null`, `llm_calls_recorded` (false for runs before 0007), `totals: UsageTotals`, `by_purpose` / `by_agent: GroupTotals[]` (timeline order), `spans: (ToolSpan \| LLMSpan)[]` (start order; a step before the calls made in it), `prices_as_of` |
| `MetricsSummary` | `observability` | `window_days`, `since`, `generated_at`, `ledger_since` (earliest ledger row), `documents {total, processing, completed, failed, success_rate}`, `runs: RunStats`, `llm` (`UsageTotals` + `error_rate`, `documents_with_usage`, `avg_tokens_per_document`, `avg_cost_per_document` over completed runs that have ledger rows), `by_model` / `by_purpose` / `by_agent` (0011; null agent → `unknown`): `GroupTotals[]` (most tokens first), `guardrails` (0008: `runs_scored`, `avg_confidence`, `by_label`, `needs_review`, `needs_review_rate`, `values_checked`, `values_grounded`, `grounding_rate`, `grounding_retry_extractions`, `transient_retries`), `vision` (0009: `layouts_analysed`, `documents_with_line_item_table`, `tables_found`, `line_items_from_table`, `line_items_from_model`, `line_items_table_share`, `pages_via_vision` (ok `vision_transcription` ledger rows), `multimodal_calls`), `prices_as_of` |
| `ConfidenceStats` (internal) | `agent` | `runs_scored`, `avg_confidence`, `needs_review`, `by_label` — `agent.service.confidence_stats` |
| `RunStats` | `agent` | `total`, `running`, `completed`, `failed`, `avg_ms`, `p50_ms`, `p95_ms` (completed runs; `percentile_cont`) — `agent.service.run_stats`, part of `MetricsSummary` |
| `DocumentCounts` (internal) | `documents` | `processing`, `completed`, `failed` — `documents.service.count_by_status` |
| `LLMCallRecord` (internal) | `core/llm.py` | `kind: chat \| embedding`, `model`, `usage`, `latency_ms`, `status`, `error_code`, `started_at`, `labels: TraceLabels`, `attempt` (0008) — handed to the registered recorder; never prompts or replies |
| `IndexEntry` / `InvoiceHit` | `retrieval` | one `invoice_embeddings` row as the API sees it (`document_id`, `filename`, `uploaded_at`, `run_id`, `document_type`, `vendor`, `vendor_tax_id`, `invoice_number`, `invoice_date`, `currency`, `total_amount`, `total_base`, `base_currency`, `needs_review`, `embedded`); `InvoiceHit` adds `similarity` (cosine, 3 decimals; null for exact matches) |
| `SimilarInvoices` | `retrieval` | `document_id`, `available`, `items: InvoiceHit[]` |
| `MatchRule` / `VendorKey` | `retrieval` | `tax_id \| name` / `display`, `name_key`, `tax_key` (normalised, PRD 0010 D4) |
| `HistoryStats` | `retrieval` | `base_currency`, `count`, `with_total`, `skipped_currencies[]`, `sum`, `min`, `max`, `mean`, `median`, `q1`, `q3`, `low_fence`, `high_fence` (`Decimal`, 2 places) |
| `TargetPosition` | `retrieval` | `document_id`, `total_base`, `diff_vs_median`, `diff_pct`, `rank` (1 = largest), `position: below \| within \| above` (vs Q1–Q3) |
| `VendorHistory` | `retrieval` | `document_id`, `vendor`, `match_rule`, `base_currency`, `invoices: IndexEntry[]` (≤ 50, newest invoice date first, incl. the target), `earlier`, `later`, `stats` (of the other invoices), `target`, `duplicates` |
| `SearchFilters` / `SearchResult` | `retrieval` | `text`, `vendor`, `invoice_number`, `date_from`, `date_to`, `currency`, `min_total`, `max_total` (base currency), `document_type`, `limit` 1–20 (5) / `items`, `total_matches`, `aggregates`, `vendor_candidates`, `note` |
| `PreparedEmbedding` / `IndexRequest` (internal) | `retrieval` | the card, its hash, vector (or null + `error_code`), model, `reused` / what the agent hands over at run completion |
| `HistoryCheck` (internal) | `retrieval` | `skipped`, `reason`, `vendor`, `match_rule`, `earlier_invoices`, `issues: ValidationIssue[]` — what `check_vendor_history` returns |
| `RetrievalStats` / `BackfillReport` (internal) | `retrieval` | index counts / back-fill counts (`indexed`, `embedded`, `skipped`, `failed`) |
| `QueryRequest` | `agent` | `question` (stripped, 3–500 chars), `conversation_id`, `document_id` |
| `Citation` | `agent` | `document_id`, `filename`, `vendor`, `invoice_number`, `invoice_date`, `total_amount`, `currency`, `needs_review` |
| `QueryTurn` / `QueryResponse` | `agent` | `turn_id`, `turn`, `question`, `document_id`, `status`, `answer`, `answerable`, `numbers_verified`, `citations`, `steps: ToolStep[]`, `error_code`, `error`, `started_at`, `finished_at`, `duration_ms`; `QueryResponse` adds `conversation_id`, `usage {prompt_tokens, completion_tokens, embedding_tokens}` |
| `ConversationRead` / `QuerySuggestions` | `agent` | `conversation_id`, `created_at`, `turns: QueryTurn[]` / `indexed_documents`, `questions[]` |
| `QueryStats` / `IssueCounts` (internal) | `agent` | questions for metrics / completed runs per vendor-history code |
| `RetrievalMetrics` | `observability` | `documents_indexed`, `documents_embedded`, `documents_not_embedded` (now), `duplicate_flags`, `outlier_flags`, `new_vendor_flags`, `conversations`, `questions`, `questions_failed`, `questions_unanswerable`, `questions_unverified`, `avg_question_ms`, `avg_cost_per_question` — `MetricsSummary.retrieval` |
| `ClientConfig` | `client_config` | `max_upload_mb: int`, `accepted_content_types: string[]` (sorted; the same set the upload service accepts), `base_currency` |
| Error body | `core/errors.py` | `{"error": {"code": str, "message": str, "details"?: any}}` — used for `AppError`, framework HTTP errors (404/405) and request validation (422, `details` = field errors) |

Error codes: `not_found` (404), `validation_failed` (422), `unsupported_media_type` (415),
`payload_too_large` (413), `llm_error` / `llm_not_configured` / `llm_rate_limited` /
`llm_timeout` / `llm_unavailable` / `llm_quota_exceeded` (502; the first three are retried in
`app/core/llm.py` before they surface), `llm_invalid_output`
(502, `LLMOutputError`: a structured reply failed its schema; carries `errors`),
`run_not_found` (404, trace route),
`internal_error` (500), `conflict` (409, base) with `text_not_ready` / `text_unavailable` /
`text_not_extracted` / `extraction_not_ready` / `extraction_unavailable` / `layout_not_ready` /
`layout_unavailable` (409), `page_not_found` (404, page image route),
`unreadable_document` / `no_text_found` (422, `TextExtractionError`; raised by
`text_extraction.service.extract_text`, never returned by the GET route), and
`invalid_llm_output` / `llm_refused` (502, `StructuredExtractionError`; raised by
`structured_extraction.service.extract_structured_data`), and `unsupported_currency` /
`invalid_amount` (422, `CurrencyConversionError`; raised by
`validation.service.convert_currency`), and `result_not_ready` / `result_unavailable` /
`already_processing` (409, agent routes), and `not_indexed` (409, retrieval routes) and
`query_failed` (502, `POST /query`: the turn ended without an answer).

Agent run error codes (stored in `agent_runs.error_code` and as `documents.error =
"code: message"`, never an HTTP response): `agent_incomplete` (the model stopped calling
tools before the summary), `agent_max_steps`, `internal_error`, `run_abandoned` (a stale
`running` row closed by the next run), or the fatal tool error's own code
(`unreadable_document`, `no_text_found`, `invalid_llm_output`, `llm_refused`, `llm_error`, …).
Recoverable tool error codes (sent back to the model only): `text_not_extracted`,
`tables_required` (0009), `structured_data_missing`, `grounding_required` (0008), `validation_required`,
`history_check_required`, `similar_search_required` (0010), `conversion_not_needed`,
`unsupported_currency`, `invalid_amount`, `invalid_arguments`, `unknown_tool`.

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
| `duplicate_invoice_number` | warning | `invoice_number` | 0010, `check_vendor_history`: an earlier-uploaded document from the same vendor has the same normalised invoice number |
| `amount_outlier` | warning | `total_amount` | 0010: ≥ 5 earlier totals of the vendor (base currency); outside Q1 − 1.5·IQR … Q3 + 1.5·IQR and ≥ 25 % from the median; `expected` = median, `actual` = this total in the base currency |
| `new_vendor` | info | `vendor` | 0010: no earlier-uploaded document from this vendor |

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
| Migrations | `0001` enables `CREATE EXTENSION IF NOT EXISTS vector`; `0002` creates `documents`; `0003` creates `document_texts`; `0004` creates `extractions`; `0005` creates `agent_runs`; `0006` creates `llm_calls`; `0007` adds `extractions.grounding`, `agent_runs.overall_confidence` / `needs_review`, `llm_calls.attempt`; `0008` creates `document_layouts` and adds `extractions.line_items_source`; `0009` creates `invoice_embeddings` (with an HNSW cosine index), `query_conversations`, `query_runs` and adds `llm_calls.query_run_id` |
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
| `prompt_version` | `VARCHAR(50)` NULL | `vision.v1` for vision rows since 0009 (`text_extraction.v1` before); null for `pdf_parser` |
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
| `prompt_version` | `VARCHAR(50)` | `structured_extraction.v3` (0009) |
| `attempts` | `INTEGER` | `CHECK >= 1`; extraction calls in total (schema + grounding retries, ≤ 3) |
| `prompt_tokens`, `completion_tokens` | `INTEGER` | `CHECK >= 0`; summed over the replies received (a reply rejected by validation is not counted) |
| `grounding` | `JSONB` NULL | `ExtractionGrounding` once `check_grounding` ran (0008); reset to NULL when the row is re-extracted |
| `line_items_source` | `VARCHAR(10)` NULL | `CHECK` `table` / `model` (0009); null for rows from before 0009 |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | `now()` defaults; `updated_at` bumped when `force=True` replaces the row |

Constraints: `pk_extractions`, `uq_extractions_document_id`,
`fk_extractions_document_id_documents`, `ck_extractions_attempts_positive`,
`ck_extractions_prompt_tokens_non_negative`, `ck_extractions_completion_tokens_non_negative`,
`ck_extractions_line_items_source_valid`.

### Table `document_layouts`

One row per layout analysis (0009, append-only: a reprocess adds a row; the newest is current).
Written by `vision.service.save_layout` (scans: during `extract_text`; text PDFs: by `extract_tables`).

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | v4 |
| `document_id` | `UUID` | FK `documents.id`, `ON DELETE CASCADE` |
| `run_id` | `UUID` NULL | FK `agent_runs.id`, `ON DELETE SET NULL`; the run that made it (from the trace context) |
| `source` | `VARCHAR(20)` | `CHECK` `pdf_parser` / `vision` |
| `layout_version` | `VARCHAR(50)` | `layout.v1` (pdfplumber rules) or `vision.v1` (prompt) |
| `model` | `VARCHAR(100)` NULL | Vision model; null for `pdf_parser` |
| `page_count` | `INTEGER` | `CHECK >= 1`; pages in the file |
| `pages` | `JSONB` | `PageInfo[]` (pages analysed: every page for text PDFs, ≤ `VISION_MAX_PAGES` for scans) |
| `tables` | `JSONB` | `Table[]` |
| `blocks` | `JSONB` | `LayoutBlock[]` |
| `created_at` | `TIMESTAMPTZ` | `clock_timestamp()` default (distinct within one transaction) |

Constraints: `pk_document_layouts`, `fk_document_layouts_document_id_documents`,
`fk_document_layouts_run_id_agent_runs`, `ck_document_layouts_source_valid`,
`ck_document_layouts_page_count_positive`; index `ix_document_layouts_document_created`
(`document_id`, `created_at`).

### Table `agent_runs`

One row per agent run (upload and every reprocess), written by `agent.service`.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | v4 |
| `document_id` | `UUID` | FK `documents.id`, `ON DELETE CASCADE` |
| `mode` | `VARCHAR(20)` | `CHECK` `single` / `multi`; the mode that ran (`AGENT_MODE` when the run started; runs before 0011 are all `single`) |
| `trigger` | `VARCHAR(20)` | `CHECK` `upload` / `reprocess` |
| `status` | `VARCHAR(20)` | `CHECK` `running` / `completed` / `failed` |
| `steps` | `JSONB` | `ToolStep[]` in JSON mode, default `[]`; saved after every tool call |
| `agents` | `JSONB` | 0011: `AgentPart[]`, default `[]`; one entry per agent that started in multi mode (saved as each agent ends); `[]` in single mode |
| `result` | `JSONB` NULL | `AgentResult` once completed |
| `summary` | `TEXT` NULL | The final summary |
| `error_code`, `error` | `VARCHAR(50)` / `TEXT` NULL | Why a run failed |
| `model` | `VARCHAR(100)` NULL | Model that answered the agent loop |
| `agent_prompt_version`, `summary_prompt_version` | `VARCHAR(50)` | single: `agent.document.vN`; multi: the bundle `agent.multi.v1` (per-agent versions in `agents`); `agent.summary.vN` |
| `prompt_tokens`, `completion_tokens` | `INTEGER` | `CHECK >= 0`, default 0; agent-loop + summary calls only |
| `overall_confidence` | `NUMERIC(4,3)` NULL | `CHECK BETWEEN 0 AND 1`; copy of `result.confidence.overall` for metrics (0008) |
| `needs_review` | `BOOLEAN` NULL | Copy of `result.confidence.needs_review` (0008) |
| `started_at`, `finished_at` | `TIMESTAMPTZ` | `now()` default / set when the run ends |

Constraints: `pk_agent_runs`, `fk_agent_runs_document_id_documents`,
`ck_agent_runs_mode_valid`, `ck_agent_runs_trigger_valid`, `ck_agent_runs_status_valid`,
`ck_agent_runs_prompt_tokens_non_negative`, `ck_agent_runs_completion_tokens_non_negative`,
`ck_agent_runs_overall_confidence_range`;
indexes `ix_agent_runs_document_id_started_at (document_id, started_at DESC)` and the partial
unique `uq_agent_runs_document_running (document_id) WHERE status = 'running'` (one running
run per document).

### Table `llm_calls`

The token ledger (0007): one row per LLM call of any client, written by
`observability.service.record_llm_call` in its own session. Counts, timings and labels
only — never prompts, replies or document text.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | v4 |
| `document_id` | `UUID` NULL | FK `documents.id`, `ON DELETE CASCADE`; from the `document_id` context var |
| `run_id` | `UUID` NULL | FK `agent_runs.id`, `ON DELETE CASCADE`; from the `run_id` context var |
| `step_index` | `INTEGER` NULL | The tool step the call was made in; null for agent-loop turns |
| `agent` | `VARCHAR(30)` NULL | `document`, `query` (0010; B4 adds more) |
| `purpose` | `VARCHAR(40)` | `vision_transcription`, `structured_extraction`, `multimodal_extraction` (0009), `grounding_retry` (0008), `agent_loop`, `summary`, `embedding`, `query_embedding` (0010), `unknown` |
| `kind` | `VARCHAR(20)` | `CHECK` `chat` / `embedding` |
| `model` | `VARCHAR(100)` | Model the API reported (requested model on failure) |
| `prompt_version` | `VARCHAR(50)` NULL | The caller's `PROMPT_VERSION` |
| `prompt_tokens`, `completion_tokens` | `INTEGER` | `CHECK >= 0`, default 0; 0 on a failed call (no usage returned) |
| `cost_usd` | `NUMERIC(12,6)` NULL | `CHECK >= 0`; estimated at write time from `observability/pricing.py`; null for an unpriced model |
| `latency_ms` | `INTEGER` | `CHECK >= 0`; one attempt (0008: retries are their own rows; backoff waits are in no row) |
| `status`, `error_code` | `VARCHAR(10)` / `VARCHAR(50)` NULL | `CHECK` `ok` / `error`; the exception's code (`llm_error`, `llm_rate_limited`, `llm_timeout`, `llm_unavailable`, `llm_quota_exceeded`, `llm_invalid_output`, `internal_error`) |
| `started_at` | `TIMESTAMPTZ` | When the call started (app clock, UTC) |
| `attempt` | `INTEGER` | `CHECK >= 1`, default 1; 2+ for a transient-error retry of the same call (0008) |
| `query_run_id` | `UUID` NULL | FK `query_runs.id`, `ON DELETE CASCADE`; the Query Agent turn the call belongs to (0010); such rows have no `document_id` / `run_id` |

Constraints: `pk_llm_calls`, `fk_llm_calls_document_id_documents`,
`fk_llm_calls_run_id_agent_runs`, `fk_llm_calls_query_run_id_query_runs`, `ck_llm_calls_kind_valid`,
`ck_llm_calls_status_valid`, and non-negative checks on tokens, cost and latency,
`ck_llm_calls_attempt_positive`; indexes `ix_llm_calls_document_id_started_at`,
`ix_llm_calls_run_id`, `ix_llm_calls_started_at`, `ix_llm_calls_query_run_id`. No retention
job: rows go with their document (or chat turn).

### Table `invoice_embeddings`

The invoice index (0010): one row per completed invoice / receipt, written by
`retrieval.service.index_document` in the run's completing transaction (savepoint) or by the
back-fill; replaced on reprocess; `unknown` documents have none.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | v4 |
| `document_id` | `UUID` | FK `documents.id`, `ON DELETE CASCADE`, unique (`uq_invoice_embeddings_document_id`) |
| `run_id` | `UUID` NULL | FK `agent_runs.id`, `ON DELETE SET NULL`; null for back-filled rows |
| `filename`, `uploaded_at` | `VARCHAR(255)` / `TIMESTAMPTZ` | Copied from the document; "earlier" = `uploaded_at` before |
| `document_type` | `VARCHAR(20)` | `CHECK` `invoice` / `receipt` |
| `vendor`, `vendor_tax_id` | `TEXT` / `VARCHAR(100)` NULL | As extracted |
| `vendor_name_key`, `vendor_tax_key` | `VARCHAR(255)` / `VARCHAR(100)` NULL | Normalised (PRD 0010 D4), indexed |
| `invoice_number`, `invoice_number_key` | `VARCHAR(100)` NULL | As extracted / letters + digits upper-case, indexed |
| `invoice_date` | `DATE` NULL | Indexed |
| `currency`, `total_amount` | `VARCHAR(3)` / `NUMERIC(14,2)` NULL | As extracted |
| `total_base`, `base_currency` | `NUMERIC(14,2)` NULL / `VARCHAR(3)` | The total converted with the static rate table at index time; null when it cannot be converted |
| `needs_review` | `BOOLEAN` NULL | From the run's confidence (back-fill: recomputed from the stored extraction) |
| `card`, `card_hash`, `card_version` | `TEXT` / `VARCHAR(64)` / `VARCHAR(50)` | The embedded text, SHA-256 of version + card + model, `retrieval.card.v1` |
| `embedding` | `vector(1536)` NULL | Null when the embedding call failed (the back-fill fills it); HNSW index `ix_invoice_embeddings_embedding_hnsw` (`vector_cosine_ops`, `m = 16`, `ef_construction = 64`) |
| `embedding_model` | `VARCHAR(100)` NULL | Model the API reported |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | |

### Table `query_conversations`

One Ask AI chat (0010): `id` (UUID PK), `created_at`, `updated_at` (bumped by every turn).
"New chat" in the UI just starts another one; old ones stay for metrics and costs.

### Table `query_runs`

One question and its answer (0010), written by `agent.query.ask`.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | v4; the `turn_id` in the API and `llm_calls.query_run_id` |
| `conversation_id` | `UUID` | FK `query_conversations.id`, `ON DELETE CASCADE` |
| `turn` | `INTEGER` | `CHECK >= 1`; unique with `conversation_id` (`uq_query_runs_conversation_turn`; the conversation row is locked while numbering) |
| `question` | `TEXT` | As asked (stripped) |
| `document_id` | `UUID` NULL | FK `documents.id`, `ON DELETE SET NULL`; the page the user was on |
| `status` | `VARCHAR(20)` | `CHECK` `running` / `completed` / `failed` |
| `answer`, `answerable`, `numbers_verified` | `TEXT` / `BOOLEAN` / `BOOLEAN` NULL | Set when completed |
| `citations`, `steps` | `JSONB` | `Citation[]`, `ToolStep[]`; default `[]` |
| `model`, `prompt_version` | `VARCHAR(100)` NULL / `VARCHAR(50)` | `agent.query.v1` |
| `prompt_tokens`, `completion_tokens`, `embedding_tokens` | `INTEGER` | `CHECK >= 0`, default 0 |
| `error_code`, `error` | `VARCHAR(50)` / `TEXT` NULL | Why a turn failed (`agent_max_steps`, `agent_incomplete`, `llm_*`, `internal_error`) |
| `started_at`, `finished_at` | `TIMESTAMPTZ` | `clock_timestamp()` default / set when the turn ends |

Index `ix_query_runs_started_at` (metrics windows).

## Configuration

Read by `app/core/config.py` from environment variables, then `../.env` / `.env`.

| Key | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | blank | Required only for real LLM calls; created lazily |
| `OPENAI_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_EMBEDDING_MODEL` | `gpt-4.1-mini`, `gpt-4.1-mini`, `text-embedding-3-small` | Model names |
| `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES` | `60`, `2` | Per-attempt timeout; transient-error retries per call (0–10), done by `app/core/llm.py` with backoff + jitter (the SDK's own retries are off) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `appfuxion`, `change_me_locally`, `appfuxion` | Database credentials (also used by the db container) |
| `POSTGRES_HOST` | `localhost` | `db` inside Compose |
| `DB_PORT` | `5432` | Host port for the db container / a local backend; Compose pins the backend to 5432 |
| `DATABASE_URL` | blank | Optional full URL; derived from `POSTGRES_*` when blank |
| `AGENT_MODE` | `multi` | `multi`: the Coordinator runs the Extraction, Validation and Reporting agents (0011); `single`: the Document Agent alone |
| `BASE_CURRENCY` | `MYR` | 3-letter ISO 4217 code; totals in another currency are converted to it (it must be in the rate table for a conversion to succeed) |
| `AGENT_MAX_STEPS` | `14` | 1–30; most model turns per agent run (`agent_max_steps` when reached); 10 since 0008 added `check_grounding`, 12 since 0009 added `extract_tables`, 14 since 0010 added `check_vendor_history` and `search_similar_invoices` |
| `QUERY_MAX_STEPS` | `6` | 1–20; most model turns per Ask AI question (0010) |
| `MAX_UPLOAD_MB` | `10` | Upload size limit |
| `STORAGE_DIR` | `./storage` | Upload directory (relative to `backend/`); `/app/storage` in Compose |
| `VISION_MAX_PAGES` | `5` | Most pages of a scanned PDF sent to the vision model (>= 1), for the page call and for multimodal extraction (0009); later pages are skipped and logged |
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
    vision_router,
    structured_extraction_router,
    agent_router,
    query_router,       # 0010: /query, /conversations, /query/suggestions (in agent/router.py)
    retrieval_router,   # 0010: /documents/{id}/similar, /vendor-history
    observability_router,
    client_config_router,
]
```

A new module's ORM models are imported in `app/models.py` so Alembic autogenerate sees them.
LLM access is injected with `Depends(get_llm_client)`; tests override it with `FakeLLM`.

The document pipeline is injected with `Depends(get_document_pipeline)`
(`app/modules/documents/pipeline.py`, signature `(document_id: UUID) -> None`). The dependency
resolves `get_llm_client` and `get_storage` and returns the runner registered with
`register_pipeline_runner` (bound to them), or a no-op when none is registered. `app/main.py`
registers `agent.service.run_document_agent`, so `documents` never imports `agent`.
`service.run_pipeline` runs the pipeline as a background task and marks the document `failed`
if it raises (a safety net: the agent marks `completed` / `failed` itself, together with its
run). Tests register no runner by default (autouse fixture); agent tests opt in with
`agent_pipeline`. `documents.service.restart_processing(db, id)` flips a finished document
back to `processing` with one conditional `UPDATE` (409 `already_processing` otherwise).

The agent (`app/modules/agent/`): `runner.AgentRunner(llm, tools, max_steps=…)` is the
shared OpenAI tool-calling loop (one step = one model turn, temperature 0, strict function
tools, `ToolError(code, message, fatal)`); `tools.build_document_tools(ctx)` binds the seven
tools to one document and enforces the order (each tool needs its predecessor *in this run*;
0009: `extract_structured_data` refuses with `tables_required` until `extract_tables` ran after
the current `extract_text`; 0008: `validate_invoice` refuses with `grounding_required` until `check_grounding` ran for the
current extraction, and computes the confidence report right after validating);
`service.run_document_agent(document_id, *, llm, storage, trigger, force)` opens its own
session, records an `agent_runs` row, saves each step as it happens, and completes or fails
the run and the document in one transaction. Since 0010 the order adds `check_vendor_history`
after `validate_invoice` and `search_similar_invoices` before `generate_summary`, which
refuses with `history_check_required` / `similar_search_required` until both ran for the
current validation; the completing transaction also indexes the document
(`retrieval.service.index_document` in a savepoint). `AgentRunner(..., tool_choice=None)`
passes `tool_choice` to every model turn when set.

Multi-agent mode (0011, `AGENT_MODE=multi`): `coordinator.run_agents(ctx, llm, content_type,
*, on_progress)` runs `AGENTS = (EXTRACTION, VALIDATION, REPORTING)`, each an `AgentSpec`
(agent label, name, prompt version, system prompt, code-written hand-off brief, tool names,
`max_steps` 6 / 6 / 4, `done(ctx)` check) on one shared `DocumentToolContext`, so the tool
guards hold across agents. Each agent gets `tools.build_agent_tools(ctx, names)`
(`EXTRACTION_TOOLS`, `VALIDATION_TOOLS`, `REPORTING_TOOLS`), a fresh conversation,
`tool_choice="required"` and `AgentRunner(..., agent=…, step_offset=…, turn_offset=…)`, inside
`bind_trace(agent=…)`. Validation is done when `validate_invoice` and `check_vendor_history`
succeeded and, when `tools.conversion_needed(ctx)`, `convert_currency` was tried
(`ctx.conversion_tried`). The first failing agent raises `CoordinatorError` (its message
starts with the agent's name); later agents never start. `service.run_document_agent` picks
the mode, and both modes share `_complete` / `_fail`.

Retrieval (0010): `retrieval.service` is called by the agent (and observability) and calls only
`documents.service`, `structured_extraction.service` + `guardrails.service` (back-fill) and
`validation.service` (conversion, `merge_issues`); it never imports `agent`. The document
tools use `check_vendor_history(db, document_id, data, *, base_currency)` +
`merge_report`, `prepare_embedding(db, llm, document_id, data)` (card → vector, reused when
the card hash is unchanged, never raises on an LLM error) and `similar_to(..., earlier_only=True)`.
The Query Agent (`agent/query.py`: `ask(db, llm, request)`) builds three tools on
`QueryToolContext` — `search_invoices` → `retrieval.service.search`, `get_vendor_history` →
`retrieval.service.vendor_history`, `submit_answer` (citation filter, number check via
`retrieval.service.unverified_numbers`) — and runs `AgentRunner(tool_choice="required",
max_steps=QUERY_MAX_STEPS)` under `bind_trace(agent="query", query_run_id=…)`. The back-fill
command is `python -m app.modules.retrieval.backfill` (it registers the ledger recorder itself).

Text extraction is a plain service function, called by the agent's tool:
`text_extraction.service.extract_text(db, storage, llm, document_id, *, force=False)` is what
the 0005 `extract_text` tool calls. Since 0009 scans go through
`vision.service.analyse_scanned` (one `PageAnalysis` call per page: text + tables + blocks);
`text_extraction` builds `raw_text` from the texts and saves the layout with
`vision.service.save_layout` in the same commit. PDF rendering holds `vision/images.py`'s
`_RENDER_LOCK` (pypdfium2 is not thread-safe). It commits its own row, never changes the
document status and raises `TextExtractionError` / `LLMError` for the caller to turn into
`failed`.
`text_extraction.service.find_text(db, document_id)` returns the saved text or `None` (never
extracts) for other modules.

Vision (0009): `vision.service.extract_tables(db, storage, document_id, *, method, force)` is
what the `extract_tables` tool calls (text PDFs: `pdfplumber` analysis in `vision/layout.py`,
no LLM, reusing the newest `layout.v1` row unless forced; scans: the row `extract_text` wrote).
`find_layout` returns the newest analysis, `line_items_from_layout` the line items code copies
from a confident line-item table, `page_images` the vision JPEGs for multimodal extraction, and
`render_page_image` the preview JPEG. `vision.service` calls only `documents.service` and reads
`run_id` from the trace context; `text_extraction`, `structured_extraction`, `agent` and
`observability` call it (one way, no cycles).

Structured extraction is the same kind of function:
`structured_extraction.service.extract_structured_data(db, llm, document_id, *, force=False,
storage=None)`
reads the saved text through `text_extraction.service.find_text` (409 `text_not_extracted`
when there is none), makes one `response_format=InvoiceData` call (temperature 0), retries
once with the validation errors fed back, commits its own row, never changes the document
status, and raises `StructuredExtractionError` / `LLMError` for the caller to turn into
`failed`. Since 0009 the prompt (`structured_extraction.v3`) carries the newest layout's tables
in a `<tables>` section; for text PDFs with a confident line-item table code replaces the
model's `line_items` after every call (`line_items_source = table`); for scans with `storage`
the page images are attached and the call is labelled `multimodal_extraction`.

Guardrails (0008) are pure too: `guardrails.service.check_grounding(data, raw_text, method, *,
layout=None, table_refs=None)`
looks every non-null value up in the full text (rules in `guardrails/matching.py`) and
`score_confidence(data, grounding, validation)` returns the `ConfidenceReport` (or `None` for
unknown documents). With a layout (0009) table-copied line items are `grounded` at their cell
(`MatchKind.TABLE`, `location`) and a total found only away from the totals block and from any
total label becomes `weak`. `structured_extraction.service.ground_extraction(db, llm,
document_id, *, storage=None)`
is what the `check_grounding` tool calls: it checks the saved extraction, re-asks the model
with the ungrounded values (`Purpose.GROUNDING_RETRY`) while the 3-call budget
(`EXTRACTION_BUDGET`, shared with the schema retry) lasts, keeps the attempt with the fewest
ungrounded values and saves it with its report; a row that already has a report is returned
unchanged.

Validation is pure (no DB, LLM or network):
`validation.service.validate_invoice(data: InvoiceData, *, today=None) -> ValidationReport`
never raises, and `validation.service.convert_currency(amount: Decimal, from_currency,
to_currency) -> ConversionResult` uses the static rate snapshot in
`validation/currencies.py` (25 currencies, USD base, `RATES_AS_OF` 2026-10-26, source
ExchangeRate-API open access). `is_iso_currency(code)` and `minor_units(code)` are public
helpers. The 0005 agent tools call them.

LLM seam: `LLMClient.complete(..., response_format=X)` returns `LLMResponse.parsed`; a reply
that fails `X`'s validation raises `LLMOutputError` (both `OpenAILLMClient` and `FakeLLM`),
and a refusal is returned as `LLMResponse.refusal` with `parsed=None`. Since 0008 both clients
run each call through `_with_retries`: an `LLMError` with `retryable=True` (rate limit,
timeout, connection, 408/409/5xx) is retried up to `1 + OPENAI_MAX_RETRIES` attempts with
full-jitter backoff (1 s base, 20 s cap) or the server's `Retry-After` (≤ 60 s); tests
replace `llm._sleep` (autouse `retry_waits` fixture).

Observability (0007): every `complete` / `embed` call of `OpenAILLMClient` and `FakeLLM` runs
inside `llm._observe`, which snapshots the trace labels, times the call, logs one `llm.call`
line (INFO ok / ERROR failed) and hands an `LLMCallRecord` to the recorder registered with
`register_llm_recorder` — `app/main.py` registers `observability.service.record_llm_call`, so
`core` never imports a module. Recorder errors are logged (`llm.call not recorded`) and
dropped. Callers only label their calls with `app.core.logging.bind_trace(...)` (a context
manager that also works as a decorator): the agent service binds `run_id` + `agent`, the
runner binds `purpose=agent_loop` around each turn and `step_index` around each tool
handler, and `vision.service._analyse_pages` (vision), `_extract_with_retry` (structured or
multimodal extraction) and
the summary tool's `_complete` are decorated with their `purpose` and `prompt_version`. An
unlabelled chat call is recorded as `unknown` with a warning. Tests register no recorder by
default; ledger tests opt in with `llm_recorder`. The trace and metrics read other modules
through `documents.service` (`get_document`, `count_by_status`) and `agent.service`
(`list_runs`, `run_stats`, `completed_run_ids`, `confidence_stats`), and since 0008
`structured_extraction.service.grounding_stats` for the metrics `guardrails` block; since 0009
`vision.service.layout_stats`, `structured_extraction.service.line_item_source_stats` and the
ledger counts by purpose fill the `vision` block; since 0010 `retrieval.service.stats`,
`agent.service.vendor_issue_counts` / `query_stats` and the ledger's cost per `query_run_id`
fill the `retrieval` block.

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

## Dependencies added in 0008

| Package | Used for |
|---|---|
| `rapidfuzz` | Fuzzy partial matching with alignment for the grounding check (MIT) |

## Frontend dependencies added in 0006

| Package | Used for |
|---|---|
| `react-router` | Routing (`createBrowserRouter`; memory router in tests) |
| `@tanstack/react-query` | Fetching, polling, retries, cache invalidation |
| `lucide-react` | Icons |
| `@fontsource/poppins` | Self-hosted Poppins (Latin 400/500/600/700) |
| `@testing-library/user-event` (dev) | Keyboard, click and file-upload events in tests |

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
| `docs/prd/0005-agent-prd.md` | Intent | Agent goals and decisions (D1-D16) |
| `docs/plan/0005-agent-plan.md` | Plan | Agent implementation path |
| `docs/decisions/0006-agent-implementation-divergences.md` | Decision log | 0005 agent divergences |
| `docs/prd/0006-frontend-prd.md` | Intent | Frontend goals and decisions (D1-D19) |
| `docs/plan/0006-frontend-plan.md` | Plan | Frontend implementation path |
| `docs/decisions/0007-frontend-implementation-divergences.md` | Decision log | 0006 frontend divergences |
