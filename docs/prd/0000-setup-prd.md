# 0000 Project Setup PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Give every later feature a working, tested, containerized foundation, so that features
0001+ only add their own module and never re-decide infrastructure.

## Goals

- A uv-managed FastAPI backend with shared core infrastructure (config, DB, LLM client,
  file storage, errors, logging) and a `/health` endpoint.
- PostgreSQL 18 + pgvector in Docker, with Alembic migrations that enable `vector`.
- A Vite + React + TypeScript + Tailwind frontend skeleton that talks to the backend.
- One command (`docker compose up --build`, after filling `.env`) runs db + backend + frontend.
- GitHub Actions CI that lints, tests, and builds both apps, with no real OpenAI calls.
- Stub submission documents (`README.md`, `ENGINEERING_NOTES.md`) and the structural
  reference doc.

## Non-Goals

- Any feature endpoint (upload, extraction, agents) — those are 0001+.
- Production deployment, auth, HTTPS, or a job queue.

## Scope

| In Scope | Out of Scope |
|---|---|
| `backend/` skeleton + `app/core/*` + `/health` | Feature modules |
| `FakeLLM` for tests; token capture on every LLM call | Prompting / agents |
| Alembic + first migration (`CREATE EXTENSION vector`) | Feature tables |
| `db/docker-compose.yml` + root `docker-compose.yml` + Dockerfiles | Cloud deployment |
| Frontend skeleton showing backend health | Real UI pages (0006) |
| CI workflow | Release / deploy pipeline |
| `.env.example`, README + ENGINEERING_NOTES stubs, folder-structure reference | Final submission docs |

## User Stories

1. **As a reviewer**, I want to copy `.env.example` to `.env`, add my OpenAI key, run one
   command, and see the app running, so that I can evaluate it without setup friction.
2. **As a developer**, I want the DB in Docker and the backend/frontend running locally
   with hot reload, so that I can iterate quickly.
3. **As a developer**, I want CI to catch lint, type, test, and build failures on every
   push and PR, so that `dev` stays green.
4. **As a developer**, I want one LLM entry point with a fake, so that tests are
   deterministic and free.

## Product Decisions

| Decision | Rationale |
|---|---|
| Postgres 18 + pgvector (`pgvector/pgvector:pg18-trixie`) | User preference; one store for relational data and RAG vectors |
| `db/docker-compose.yml` standalone + root compose that `include`s it | DB alone for local dev; full stack for reviewers |
| Single root `.env` | One place to configure everything; backend and Compose share it |
| pgvector enabled by an Alembic migration, not an init script | Same path for local, Docker, and CI databases |
| SQLAlchemy 2.0 sync + psycopg 3 | Simple; FastAPI runs sync routes/background tasks in a threadpool |
| FastAPI `BackgroundTasks` for the pipeline | Brief needs async processing, not a distributed queue |
| Frontend served by nginx in Docker, `/api` proxied to backend | Same-origin calls, no CORS in the container setup |
| Python 3.12 | Broad library support |

## Constraints

- No secrets in the repo; the repo becomes public.
- Tests must never call the real OpenAI API.
- Host port 5432 may already be taken (suaramu-db) — DB host port is configurable.
- Must work on Windows (developer machine) and Linux (CI, containers).

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | `docker compose up --build` with a filled `.env` starts db (healthy), backend (migrated), frontend | manual check |
| 2 | `GET /health` returns 200 with app + DB status | test + manual check |
| 3 | `uv run alembic upgrade head` creates the `vector` extension | test (query `pg_extension`) |
| 4 | `app/core/llm.py` exposes a client with token capture and a `FakeLLM` used by tests | test |
| 5 | Frontend dev server and Docker build both show backend health | manual check |
| 6 | CI runs backend (ruff, pytest against Postgres service) and frontend (lint, typecheck, test, build) and passes | CI run |
| 7 | `docker compose --env-file .env -f db/docker-compose.yml up -d` starts only the DB | manual check |
| 8 | `README.md`, `ENGINEERING_NOTES.md`, `docs/reference/folder-structure.md` exist and describe the setup | manual check |

## Roadmap Phase

**Phase:** Phase 0 — Foundation

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0000-setup-plan.md` | Plan | Implementation path for this PRD |
