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

Structure of the Document Intelligence Agent repository as of feature `0001`
(documents): a FastAPI backend with shared core infrastructure, a `health` module and the
`documents` upload module, a Vite + React frontend skeleton, PostgreSQL + pgvector in
Docker, and CI. Each feature adds a folder under `backend/app/modules/`.

## Directory Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py                 # create_app(), ROUTERS list, /api prefix
│   │   ├── models.py               # model registry imported by Alembic (documents)
│   │   ├── core/
│   │   │   ├── config.py           # pydantic-settings Settings, get_settings()
│   │   │   ├── db.py               # engine, SessionLocal, Base, get_db
│   │   │   ├── llm.py              # LLMClient, OpenAILLMClient, FakeLLM, TokenUsage
│   │   │   ├── storage.py          # Storage protocol, LocalStorage (save, save_as), get_storage
│   │   │   ├── errors.py           # AppError hierarchy + handlers (app, HTTP, request validation)
│   │   │   └── logging.py          # JSON formatter, document_id context var
│   │   └── modules/
│   │       ├── health/             # router.py, service.py, schema.py
│   │       └── documents/          # model, crud, schema, service, router, pipeline (hook for 0005)
│   ├── migrations/
│   │   ├── env.py                  # URL from settings, metadata from app.models
│   │   ├── script.py.mako
│   │   └── versions/               # 0001_enable_pgvector.py, 0002_create_documents.py
│   ├── tests/
│   │   ├── conftest.py             # test DB, migrate once, client / fake_llm / storage fixtures
│   │   ├── core/                   # test_llm, test_storage, test_errors, test_logging
│   │   ├── modules/health/         # test_router, test_service
│   │   ├── modules/documents/      # conftest (byte samples, pipeline spy), test_router, test_service
│   │   └── test_app.py, test_config.py, test_migrations.py
│   ├── alembic.ini
│   ├── pyproject.toml              # deps, ruff, pytest config
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
| Error body | `core/errors.py` | `{"error": {"code": str, "message": str, "details"?: any}}` — used for `AppError`, framework HTTP errors (404/405) and request validation (422, `details` = field errors) |

Error codes: `not_found` (404), `validation_failed` (422), `unsupported_media_type` (415),
`payload_too_large` (413), `llm_error` / `llm_not_configured` (502), `internal_error` (500).

## Database

| Item | Value |
|---|---|
| Engine | PostgreSQL 18 + pgvector (`pgvector/pgvector:pg18-trixie`) |
| Container / volume | `appfuxion-db` / `appfuxion_pgdata` (mounted at `/var/lib/postgresql`) |
| Driver | SQLAlchemy 2.0 + psycopg 3 (`postgresql+psycopg://`) |
| Migrations | `0001` enables `CREATE EXTENSION IF NOT EXISTS vector`; `0002` creates `documents` |
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
]
```

A new module's ORM models are imported in `app/models.py` so Alembic autogenerate sees them.
LLM access is injected with `Depends(get_llm_client)`; tests override it with `FakeLLM`.

The document pipeline is injected with `Depends(get_document_pipeline)`
(`app/modules/documents/pipeline.py`, signature `(document_id: UUID) -> None`). Until
0005 it is a no-op, so uploads stay `processing`. `service.run_pipeline` runs it as a
background task in its own DB session and marks the document `failed` if it raises; the
pipeline marks `completed` itself via `service.mark_completed` (flushes only; the caller commits).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/prd/0000-setup-prd.md` | Intent | Product goals behind the structures documented here |
| `docs/plan/0000-setup-plan.md` | Plan | Planned architecture these structures realize |
| `docs/prd/0001-documents-prd.md` | Intent | Upload API goals and decisions |
| `docs/plan/0001-documents-plan.md` | Plan | Upload API implementation path |
| `docs/decisions/0001-setup-implementation-divergences.md` | Decision log | Where the implementation differs from the plan |
