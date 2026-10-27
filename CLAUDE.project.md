# Project Context

This file is the project-specific context layer for this repository.

The reusable harness policy lives in `CLAUDE.md`; keep this file focused on the
actual product, codebase, team conventions, and commands for the project created
from the harness.

When guidance conflicts:
- Project behavior, domain rules, architecture, and commands in this file take
  precedence for project work.
- Harness routing, capability placement, and validation rules in `CLAUDE.md`
  still apply.

## Project Overview

**Document Intelligence Agent** — an AI/ML take-home assessment for AppFuxion. A user
uploads a financial document (invoice or receipt; PDF, JPG, or PNG). The system
extracts its text, uses an LLM to turn it into structured JSON, validates the values
with deterministic tools, and produces a short AI-written summary. AI agents
(OpenAI tool calling) orchestrate the steps; past invoices are searchable with
pgvector.

The brief is `docs/prd/source/appfuxion-ai-engineer-assessment-v1.pdf` and the
private build-order guide is `docs/prd/source/feature-map.md`. Both are
**gitignored** (the brief is confidential; the map is a local guideline). Read the
feature map to decide what to build next and what it depends on; the roadmap stays
the status source of truth.

Submission requires: a public git repo, a product `README.md` with setup steps, and
`ENGINEERING_NOTES.md` (architecture decisions, prompt design, limitations,
production improvements). Every feature appends its notes to `ENGINEERING_NOTES.md`.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (psycopg 3), Alembic
- **AI:** OpenAI API (structured outputs, tool calling, vision, embeddings); model names come from env vars
- **Frontend:** React + TypeScript (Vite), Tailwind CSS
- **Storage:** PostgreSQL 18 + pgvector (Docker image `pgvector/pgvector:pg18-trixie`); uploaded files on local disk / Docker volume
- **Packaging:** uv (`backend/pyproject.toml`, `backend/uv.lock`); npm (`frontend/package-lock.json`)
- **Background work:** FastAPI `BackgroundTasks` (no queue)
- **Deployment:** Docker Compose — `docker compose up --build` runs db + backend (with agents) + frontend
- **CI:** GitHub Actions (`.github/workflows/ci.yml`)

## Repository Layout

Full structural reference: `docs/reference/folder-structure.md` (created in 0000; keep
it current when structure, routes, schemas, or config change).

- **`backend/app/main.py`** — FastAPI app factory; mounts every module router.
- **`backend/app/core/`** — shared infrastructure: `config`, `db`, `llm` (the only
  OpenAI entry point), `storage`, `errors`, `logging`.
- **`backend/app/modules/<module>/`** — one folder per feature module (see Module Anatomy).
- **`backend/migrations/`** — Alembic migrations.
- **`backend/tests/`** — pytest; mirrors `app/` (`tests/modules/<module>/`).
- **`frontend/`** — Vite + React + TS + Tailwind UI.
- **`db/docker-compose.yml`** — Postgres + pgvector on its own (local dev).
- **`docker-compose.yml`** — full stack (includes `db/`, adds backend + frontend).
- **`ENGINEERING_NOTES.md`**, **`README.md`** — submission documents.
- **`docs/`** — docs-first source of truth: `docs/product-roadmap.md`,
  `docs/prd/`, `docs/plan/`, `docs/reference/`, `docs/decisions/`. `docs/draft/` is the
  user's personal scratch space — never read or act on it unless explicitly referenced.

Mapping to the brief's example layout (`api/ agent/ tools/ vision/ tests/`): routers =
`api/`, `modules/agent` = `agent/`, agent tools + `modules/validation` = `tools/`,
`modules/text_extraction` (+ `modules/vision`) = `vision/`, `backend/tests` = `tests/`.

## Commands

Available once 0000 has shipped. Run backend commands from `backend/`, frontend
commands from `frontend/`.

| Purpose | Command | Notes |
|---|---|---|
| Full stack | `docker compose up --build` | From repo root, after `cp .env.example .env` and setting `OPENAI_API_KEY` |
| DB only | `docker compose --env-file .env -f db/docker-compose.yml up -d` | For local backend dev / tests |
| Backend deps | `uv sync` | |
| Migrate | `uv run alembic upgrade head` | Needs the DB running |
| New migration | `uv run alembic revision --autogenerate -m "<msg>"` | Review the generated file |
| Run API | `uv run uvicorn app.main:app --reload` | |
| Backend tests | `uv run pytest` | Needs the DB running; OpenAI is always faked |
| Lint / format | `uv run ruff check .` · `uv run ruff format .` | |
| Frontend deps | `npm install` | |
| Run UI | `npm run dev` | Proxies `/api` to the backend |
| Frontend checks | `npm run lint` · `npm run typecheck` · `npm run test` · `npm run build` | |

## Code Conventions

1. **Docs-first:** Read `docs/product-roadmap.md` and the relevant PRD/plan before feature
   work; follow `docs/documentation-standard.md` for doc maintenance and the session-close
   checklist.
2. **Numbered module docs:** every module the user asks to develop gets a PRD and a plan
   that share one 4-digit, zero-padded number, assigned incrementally:
   - `0000` is reserved for the project setup / foundation; features start at `0001`.
   - PRD → `docs/prd/NNNN-<module>-prd.md`
   - Plan → `docs/plan/NNNN-<module>-plan.md`
   - Next number = highest existing `NNNN` in `docs/prd/` + 1. Never reuse or renumber.
   - Write both (from `docs/templates/`) and register the PRD in `docs/product-roadmap.md`
     before any code is written for that module.
   - Numbers are assigned only when a feature starts; the feature map's numbers are expectations.
3. **Module anatomy (DTO style)** — use the `proj-fastapi-module` skill when creating or
   extending a backend module. Each module lives in `backend/app/modules/<module>/` and
   contains **only the layers it needs**:
   | File | Holds | Must not |
   |---|---|---|
   | `router.py` | HTTP: params, status codes, calls service, returns schemas | touch `crud`/`model` or hold business logic |
   | `service.py` | Business logic; returns schemas (DTOs) | import FastAPI |
   | `schema.py` | Pydantic DTOs (`XCreate`, `XRead`, internal DTOs, LLM output schemas) | import ORM models |
   | `crud.py` | SQLAlchemy queries; takes a `Session` | contain business rules |
   | `model.py` | SQLAlchemy ORM tables | — |
   Extra files only when justified: `prompts.py` (versioned prompt constants), `tools.py`,
   `runner.py`, `coordinator.py`. A pure module (e.g. `validation`) has only
   `service.py` + `schema.py`.
4. **Layering:** router → service → crud → model. Across modules, import another
   module's `service` or `schema` only — never its `crud` or `model`.
5. **LLM access:** every OpenAI call goes through `app/core/llm.py` (model from config,
   token capture, logging, retries). Never instantiate the OpenAI client elsewhere.
   Prompts live in the module's `prompts.py` with a `PROMPT_VERSION`.
6. **Typing & style:** full type hints; ruff for lint + format; money as `Decimal` in
   code and `NUMERIC(14,2)` in the DB; dates as ISO 8601.
7. **Frontend:** TypeScript strict; one typed API client in `frontend/src/api/`; Tailwind
   utility classes, no other CSS framework.

## Agent Design

Rule of thumb: **AI does the thinking; code does the maths and keeps the order.**

| Agent | LLM? | Tools | Source |
|---|---|---|---|
| Document Agent (single mode) | yes | extract_text, extract_tables, extract_structured_data, check_grounding, validate_invoice, check_vendor_history, convert_currency, search_similar_invoices, generate_summary | Brief Part 4 (+ B2 grounding, B5 tables, B3 vendor history) |
| Extraction Agent | yes | extract_text, extract_tables, extract_structured_data, check_grounding | Brief bonus (multi-agent) |
| Validation Agent | yes — checks are deterministic code | validate_invoice, check_vendor_history, convert_currency | Brief bonus (multi-agent) |
| Reporting Agent | yes | search_similar_invoices, generate_summary | Brief bonus (multi-agent) |
| Query Agent | yes | search_invoices, get_vendor_history, submit_answer | Added for the RAG bonus (`POST /query`, the Ask AI chat; memory per conversation) |
| Coordinator | **no** — plain Python | runs Extraction → Validation → Reporting | Added glue |

- All LLM agents share one `AgentRunner` (OpenAI tool-calling loop with a max-steps limit
  and a recorded tool-call log).
- `AGENT_MODE=single|multi` (default `multi`). `multi` (0011): the Coordinator runs the
  Extraction (≤6 turns), Validation (≤6) and Reporting (≤4) agents in order on one shared tool
  context, each with only its own tools and a code-written hand-off brief; the first failing
  agent fails the run. `single`: the Document Agent with every tool (`AGENT_MAX_STEPS`).
- Code guards: `generate_summary` refuses to run until `validate_invoice` has run, and
  `validate_invoice` refuses until `check_grounding` has run for the current extraction (0008),
  and `extract_structured_data` refuses until `extract_tables` has run after the current
  `extract_text` (0009), and `generate_summary` refuses until `check_vendor_history` and
  `search_similar_invoices` have run for the current validation (0010).

## Git Branching Model

Three tiers. Never commit directly to `main` or `dev`.

| Branch | Role | Updated by |
|---|---|---|
| `main` | Production | Merge from `dev` only, and only when the user asks for a release |
| `dev` | Integration / staging | Merge from a stable feature branch |
| `feature/NNNN-<module>` | One module's work (`NNNN` matches its PRD/plan) | Commits during development |

Flow for each module:
1. `git switch dev && git pull` — always start from the latest `dev`.
2. `git switch -c feature/NNNN-<module>` — write the PRD + plan, then implement.
3. When the module is stable (tests pass, user confirms), push the branch and merge it
   into `dev`; push `dev`.
4. The next module branches from the updated `dev` (back to step 1).
5. Promote `dev` → `main` only on an explicit user request.

## Domain Rules

1. **Supported uploads:** `application/pdf`, `image/jpeg`, `image/png`; size limit from
   config (default 10 MB). Anything else → 415/413.
2. **IDs:** every table's primary key is a native Postgres `UUID` (v4, generated with
   Python's `uuid.uuid4()`), exposed in the API as the plain dashed UUID with no prefix.
   **Status lifecycle:** `processing` → `completed` | `failed`. `POST /documents`
   returns `{document_id, status: "processing"}`.
3. **Structured invoice fields** (brief): `document_type` (`invoice | receipt | unknown`),
   `vendor`, `invoice_number`, `invoice_date`, `due_date`, `total_amount`, `currency`,
   `line_items[]` (`description`, `quantity`, `unit_price`, `amount`).
4. **Never invent values:** a field not present in the document is `null`. Currency is an
   ISO 4217 code only when the document supports it (e.g. "RM" → `MYR`).
5. **Validation is deterministic code** (totals, missing fields, dates, currency); the LLM
   never does arithmetic. Validation runs **before** the summary, and the summary must
   mention validation issues.
6. **Final result shape:** `{document_id, structured_data, validation, summary}`.
7. **Currency conversion** uses a static, dated rate table (documented limitation).

## Environment And Secrets

- One root `.env` (gitignored) drives Docker Compose and the backend; `.env.example` is
  committed. Keys: `OPENAI_API_KEY`, model names (`OPENAI_MODEL`, `OPENAI_VISION_MODEL`,
  `OPENAI_EMBEDDING_MODEL`), `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`,
  `POSTGRES_HOST` (`localhost` locally, `db` in Compose), `DB_PORT`, `AGENT_MODE`,
  `MAX_UPLOAD_MB`, `STORAGE_DIR`, `VISION_MAX_PAGES`, `BASE_CURRENCY`,
  `AGENT_MAX_STEPS`, `QUERY_MAX_STEPS`.
- Never commit real keys or passwords. The repo is public at submission.

## Testing And Definition Of Done

- Backend: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` must pass.
  Frontend (once touched): `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build`.
- **Tests never call the real OpenAI API** — use the `FakeLLM` from `app/core/llm.py`.
  Tests run against a real Postgres test database (Docker locally, service container in CI).
- Treat tests as part of implementation, not a follow-up task.
- Each feature appends its section to `ENGINEERING_NOTES.md` and updates `README.md` when
  setup or usage changes.
- Never rewrite intent docs (PRDs/plans) during coding — record divergences in
  `docs/decisions/` instead.
- After a coding task, run the session-close checklist in `docs/documentation-standard.md`
  and keep `docs/reference/` in sync with structural changes.
- Mark a roadmap item `shipped` only when its deliverables and acceptance criteria are
  fully implemented and passing.

## Operational Notes

- `backend/storage/` (uploads) and the `appfuxion_pgdata` volume are runtime data — never
  delete them without asking.
- `docs/prd/source/` is gitignored; never `git add -f` anything in it.
- The suaramu-db container from another project may already use host port 5432; set
  `DB_PORT` in `.env` to avoid the clash.
