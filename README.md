# Document Intelligence Agent

An AI/ML take-home assessment for AppFuxion. Upload a financial document (an invoice or
receipt as PDF, JPG, or PNG) and the system extracts its text, uses an LLM to turn it into
structured JSON, validates the numbers with deterministic code, and writes a short AI
summary. AI agents (OpenAI tool calling) orchestrate the steps, and past invoices are
searchable with pgvector.

> **Status:** the core pipeline works end to end (features `0000`–`0005`): upload a
> document and the **Document Agent** extracts its text (PDF parser or OpenAI vision),
> turns it into structured JSON, validates it with deterministic code, converts a foreign
> total to `BASE_CURRENCY` when needed, and writes a summary that mentions every validation
> problem. The web UI (`0006`), observability (`0007`: a token ledger, per-document traces
> and a metrics page) and guardrails (`0008`: every extracted value is checked against the
> document's text, each field and document gets a confidence score, and API errors and
> invented values are retried) are in place; the other bonus tasks land in later numbered
> features; see [`docs/product-roadmap.md`](docs/product-roadmap.md).

## Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (psycopg 3), Alembic
- **AI:** OpenAI API (structured outputs, tool calling, vision, embeddings)
- **Frontend:** React + TypeScript (Vite), Tailwind CSS v4
- **Database:** PostgreSQL 18 + pgvector (`pgvector/pgvector:pg18-trixie`)
- **Tooling:** uv, npm, ruff, pytest, ESLint, Vitest, GitHub Actions

## Quick start (Docker)

Requires Docker with Compose **v2.24 or newer** (the root `docker-compose.yml` uses `include` with `env_file`).

```bash
cp .env.example .env        # then set OPENAI_API_KEY in .env
docker compose up --build
```

| What | Where |
|---|---|
| Web UI | http://localhost:8080 (change with `FRONTEND_PORT`) |
| API (through the UI's proxy) | http://localhost:8080/api/health |
| API docs (Swagger) | http://localhost:8080/api/docs |

### Use the web UI

Open http://localhost:8080 (or http://localhost:5173 in local development).

1. **Upload** — drag up to 5 invoices or receipts (PDF, JPG or PNG, up to `MAX_UPLOAD_MB`
   each) onto the page, or press Enter on the drop zone to pick them. Files are checked
   before anything is sent; press **Upload** and the app opens the documents list.
2. **Documents** — every upload, newest first, with its status. Filter by status and page
   through the list; it refreshes every 10 seconds while something is processing.
3. **Document detail** — while processing, the *Agent activity* panel shows the Extraction →
   Validation → Reporting steps as they happen. When done: the AI summary and validation
   status first, then the extracted fields, line items, validation issues (each one
   highlighted on the value it concerns; click it to jump there), the currency conversion,
   the raw text and earlier runs. A failed document shows the reason and any data saved
   before the failure. **Reprocess** runs the whole agent again after a confirmation.
   The **Trace** card shows where the time and tokens went: processing and queue time, LLM
   calls, tokens and estimated cost, and a timeline of every tool step with the LLM calls made
   in it (pick an earlier run from the menu). Each agent lane shows its own tokens and cost.
   **Confidence:** every extracted value and line-item cell is marked high (shield icon),
   medium or low; hover for the score and why. Values that were not found in the document's
   text say "Not found in document", a **Needs review** banner lists the fields to check, and
   the text-search button next to a value opens the raw text with that value highlighted.
   Documents processed before this feature say "Confidence not available"; reprocess them.
4. **Metrics** — documents, success rate, average / p95 processing time, tokens and estimated
   cost per document, LLM usage by model and by purpose, and a **Guardrails** section
   (average confidence, share needing review, grounding rate, retries and the high / medium /
   low split), for the last 7 or 30 days or all time.

The header shows the backend's health and a System / Light / Dark theme switch.

### Or use the API

1. Upload it. The response is `{document_id, status: "processing"}` and the Document Agent
   starts in the background:

   ```bash
   curl -F "file=@invoice.pdf;type=application/pdf" http://localhost:8080/api/documents
   ```

2. Poll until `status` is `completed` (or `failed`, with the reason in `error`):

   ```bash
   curl http://localhost:8080/api/documents/<document_id>
   ```

3. Get the result `{document_id, structured_data, validation, conversion, summary,
   confidence}` (`confidence`: overall and per-field scores, `needs_review`, and where each
   value was found in the text):

   ```bash
   curl http://localhost:8080/api/documents/<document_id>/result
   ```

4. Optional: see which tools the agent called, in order, with results and timings (including
   `check_grounding`; the grounding report itself is on `GET /documents/<document_id>/extraction`):

   ```bash
   curl http://localhost:8080/api/documents/<document_id>/runs
   ```

5. Optional: see the run's trace — timing, every LLM call (purpose, model, tokens, estimated
   cost, latency) and the tool steps they ran in (`?run_id=` for an earlier run):

   ```bash
   curl http://localhost:8080/api/documents/<document_id>/trace
   ```

6. Optional: product-wide numbers (documents, success rate, processing time, tokens, cost;
   `?days=7` for a window):

   ```bash
   curl http://localhost:8080/api/metrics/summary
   ```

7. Optional: run the whole agent again (text and data are re-extracted):

   ```bash
   curl -X POST http://localhost:8080/api/documents/<document_id>/reprocess
   ```

`/result` answers 409 `result_not_ready` while the document is processing and 409
`result_unavailable` (with the error) when processing failed. The intermediate steps are also
readable on their own: `GET /api/documents/<document_id>/text` and `/extraction`.
`GET /api/config` returns the upload limit and accepted file types the UI uses.

Every LLM call is recorded in the `llm_calls` table (counts and timings only — never prompts,
replies or document text), and every backend log line written while a document is processed
is JSON carrying its `document_id` and `run_id`, so one document's story can be followed with
`docker compose logs backend | grep <document_id>`. Costs are estimates from a static price
table dated 2026-10-27.

The backend waits for the database, applies the Alembic migrations (which enable the
`vector` extension), then starts. The app and `/api/health` work without an
`OPENAI_API_KEY`, but processing needs it: without a key, an upload is rejected with 502
`llm_not_configured` and nothing is stored.

Stop with `docker compose down`. Data lives in the `appfuxion_pgdata` and
`appfuxion_uploads` volumes and survives `down` (use `down -v` only if you want to wipe it).

> If another Postgres already uses host port 5432, set `DB_PORT=5433` (or any free port)
> in `.env`. Containers are unaffected: the backend always reaches the database on 5432
> inside the Compose network.

## Local development (hot reload)

Run only the database in Docker and the backend and frontend on your machine.
Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
cp .env.example .env                                         # once
docker compose --env-file .env -f db/docker-compose.yml up -d    # database only

# Backend (http://localhost:8000, docs at /api/docs)
cd backend
uv sync                                  # installs Python 3.12 + dependencies
uv run alembic upgrade head              # creates the schema + pgvector extension
uv run uvicorn app.main:app --reload

# Frontend (http://localhost:5173, proxies /api to localhost:8000)
cd frontend
npm install
npm run dev
```

## Commands

Run backend commands from `backend/` and frontend commands from `frontend/`.

| Purpose | Command |
|---|---|
| Full stack | `docker compose up --build` |
| Database only | `docker compose --env-file .env -f db/docker-compose.yml up -d` |
| Install backend deps | `uv sync` |
| Apply migrations | `uv run alembic upgrade head` |
| New migration | `uv run alembic revision --autogenerate -m "<message>"` |
| Run API | `uv run uvicorn app.main:app --reload` |
| Backend tests | `uv run pytest` (needs the database; OpenAI is always faked) |
| Lint / format | `uv run ruff check .` / `uv run ruff format .` |
| Install frontend deps | `npm install` |
| Run UI | `npm run dev` |
| Frontend checks | `npm run lint` / `npm run typecheck` / `npm run test` / `npm run build` |

Tests create and migrate a separate `appfuxion_test` database on the same server, so they
never touch your development data, and they never call the real OpenAI API.

## Configuration

One root `.env` (git-ignored) drives Docker Compose and the backend. Every key is
documented in [`.env.example`](.env.example): OpenAI key and model names, Postgres
credentials and ports, `AGENT_MODE`, `BASE_CURRENCY` (default `MYR`: totals in another
currency are converted to it), `AGENT_MAX_STEPS` (default 10 model turns per agent run),
`OPENAI_MAX_RETRIES` (default 2 retries of a rate-limited, timed-out or failed OpenAI call,
with backoff),
`MAX_UPLOAD_MB`, `STORAGE_DIR`, and more. `AGENT_MODE=multi` is the default; until the
multi-agent bonus ships it logs a warning and runs the single Document Agent.

## Project layout

```text
backend/        FastAPI app (app/core shared infrastructure, app/modules/<feature>), Alembic, tests
frontend/       Vite + React + TypeScript + Tailwind UI
db/             Standalone Postgres + pgvector compose file
docs/           Roadmap, PRDs, plans, reference docs, decision log
.github/        CI workflow
ENGINEERING_NOTES.md   Architecture decisions, prompt design, limitations, production improvements
```

The full structural reference is [`docs/reference/folder-structure.md`](docs/reference/folder-structure.md).

## Documentation

- [`ENGINEERING_NOTES.md`](ENGINEERING_NOTES.md) - design decisions, limitations, and next steps
- [`docs/product-roadmap.md`](docs/product-roadmap.md) - phases and feature status

## Built on the Orchestral Harness

This repository was built with an agent-orchestration harness for Claude Code that keeps
work docs-first (PRD, then plan, then code). Its policy and routing rules live in
[`CLAUDE.md`](CLAUDE.md), with the project-specific context in
[`CLAUDE.project.md`](CLAUDE.project.md) and the agents, skills, and workflows under
[`.claude/`](.claude/). None of it is needed to run the application.
