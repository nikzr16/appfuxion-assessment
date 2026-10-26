# 0000 Project Setup Implementation Plan

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

Scaffold the backend (uv + FastAPI + SQLAlchemy + Alembic), the frontend (Vite + React +
TS + Tailwind), Docker Compose (db-only and full stack), and CI. No feature modules.

## Technical Approach

- **App factory** `create_app()` in `app/main.py`; routers registered from one list so
  later modules add one line.
- **Config** via `pydantic-settings` reading the root `.env` (`env_file=("../.env", ".env")`)
  plus real env vars (Compose). `DATABASE_URL` is derived from `POSTGRES_*` unless set
  explicitly; `POSTGRES_HOST` is `localhost` locally and `db` in Compose.
- **DB**: SQLAlchemy 2.0 engine + `sessionmaker`; `get_db()` dependency; declarative
  `Base` with a naming convention for constraints (stable Alembic diffs).
- **LLM** (`app/core/llm.py`): a thin `LLMClient` protocol with `OpenAILLMClient` (wraps
  the official SDK; models from config; returns content + `TokenUsage`) and `FakeLLM`
  (scripted responses, records calls). Retries/backoff and structured-output helpers
  are added by the features that need them (0003, 0008) — 0000 only fixes the seam.
- **Storage** (`app/core/storage.py`): `LocalStorage` saving to `STORAGE_DIR` with
  generated names; interface small enough to swap for S3 later.
- **Errors**: `AppError` hierarchy (`NotFoundError`, `ValidationFailedError`,
  `UnsupportedMediaError`, `PayloadTooLargeError`, `LLMError`) + one handler mapping to
  JSON `{error: {code, message}}`.
- **Logging**: stdlib logging with a JSON formatter and a `document_id` context var
  (B1 builds on this).
- **Tooling**: ruff (lint + format), pytest + pytest-cov, httpx `TestClient`.

## System Components

| Component | Responsibility |
|---|---|
| `backend/pyproject.toml`, `uv.lock` | Deps, ruff + pytest config |
| `backend/app/main.py` | App factory, router registration, error handlers |
| `backend/app/core/config.py` | Settings |
| `backend/app/core/db.py` | Engine, session, `Base`, `get_db` |
| `backend/app/core/llm.py` | `LLMClient`, `OpenAILLMClient`, `FakeLLM`, `TokenUsage` |
| `backend/app/core/storage.py` | File storage |
| `backend/app/core/errors.py` | Domain errors + handlers |
| `backend/app/core/logging.py` | JSON logging, context vars |
| `backend/app/modules/health/` | `router.py`, `service.py`, `schema.py` — `GET /health` (app + DB check) |
| `backend/migrations/` | Alembic env + `0001_enable_pgvector` |
| `backend/tests/conftest.py` | Test DB setup (migrate once per session), `TestClient`, `FakeLLM` fixtures |
| `backend/Dockerfile` | uv image; entrypoint waits for DB → `alembic upgrade head` → uvicorn |
| `frontend/` | Vite + React + TS + Tailwind; `src/api/client.ts`; health badge page |
| `frontend/Dockerfile`, `frontend/nginx.conf` | Build → nginx; `/api/` → `backend:8000` |
| `db/docker-compose.yml` | `appfuxion-db` (pgvector pg18), volume `appfuxion_pgdata`, `${DB_PORT:-5432}`, healthcheck, `TZ=Asia/Kuala_Lumpur` |
| `docker-compose.yml` | `include: db/docker-compose.yml` (env_file `.env`) + `backend` + `frontend` services |
| `.env.example` | All keys documented |
| `.github/workflows/ci.yml` | `backend` and `frontend` jobs |
| `README.md`, `ENGINEERING_NOTES.md` | Submission doc stubs (replace the harness README; harness info moves to a short section) |
| `docs/reference/folder-structure.md` | Structural reference |

## Processing Flow

`docker compose up --build` → db starts and turns healthy → backend container waits for DB,
runs `alembic upgrade head`, starts uvicorn on 8000 → frontend (nginx on 80, published as
`${FRONTEND_PORT:-8080}`) serves the SPA and proxies `/api` to the backend.

## Dependencies

| Dependency | Purpose |
|---|---|
| fastapi, uvicorn[standard], python-multipart | API + uploads |
| pydantic, pydantic-settings | DTOs + config |
| sqlalchemy, psycopg[binary], alembic, pgvector | DB, migrations, vectors |
| openai | LLM client |
| ruff, pytest, pytest-cov, httpx (dev) | Quality + tests |
| vite, react, react-dom, typescript, tailwindcss, @tailwindcss/vite | Frontend |
| eslint, vitest, @testing-library/react (dev) | Frontend quality + tests |

Exact versions are pinned by `uv.lock` / `package-lock.json` at implementation time.

## Implementation Phases

### Phase 1: Database
`db/docker-compose.yml`, `.env.example`; verify the container starts and is healthy.

### Phase 2: Backend skeleton
uv project, `app/core/*`, health module, Alembic + pgvector migration, tests (health,
extension present, FakeLLM, storage, error handler).

### Phase 3: Frontend skeleton
Vite + React + TS + Tailwind, API client, health badge, ESLint + Vitest, dev proxy.

### Phase 4: Containers
Backend + frontend Dockerfiles, nginx config, root `docker-compose.yml`; verify full stack.

### Phase 5: CI + docs
`ci.yml`; README (setup: Docker path + local dev path), ENGINEERING_NOTES stub
(architecture, agent design rule, sections to fill), folder-structure reference.

## Testing Strategy

- Backend tests run against a real Postgres (`appfuxion_test` database, created by
  `conftest.py` if missing; migrated once per session; tables truncated between tests).
- `FakeLLM` injected via dependency override; no network in tests.
- Frontend: Vitest + Testing Library for the health badge.
- CI: Postgres service container `pgvector/pgvector:pg18-trixie`.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Host port 5432 already used by another Postgres | DB won't start | `DB_PORT` in `.env` |
| `include` + `env_file` needs Compose ≥ 2.24 | Root compose fails on old Docker | Document minimum version in README |
| Windows line endings in shell entrypoint | Container entrypoint fails | `.gitattributes` forcing LF for `*.sh` |
| pg18 image data path differs from older images | Data not persisted | Mount `/var/lib/postgresql` (pg18 layout) |

## Roadmap Phase

**Phase:** Phase 0 — Foundation

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0000-setup-prd.md` | Intent | Product goals and constraints this plan implements |
| `docs/reference/folder-structure.md` | Reference | Structural placement of planned components |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this plan |

## Open Questions

- [ ] Replace the harness `README.md` with the product README (harness notes kept as a short section)? Planned: yes.
