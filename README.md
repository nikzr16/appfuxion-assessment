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
> problem. The UI and the bonus tasks land in later numbered features; see
> [`docs/product-roadmap.md`](docs/product-roadmap.md).

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

### Process a document end to end

1. Upload it. The response is `{document_id, status: "processing"}` and the Document Agent
   starts in the background:

   ```bash
   curl -F "file=@invoice.pdf;type=application/pdf" http://localhost:8080/api/documents
   ```

2. Poll until `status` is `completed` (or `failed`, with the reason in `error`):

   ```bash
   curl http://localhost:8080/api/documents/<document_id>
   ```

3. Get the result `{document_id, structured_data, validation, conversion, summary}`:

   ```bash
   curl http://localhost:8080/api/documents/<document_id>/result
   ```

4. Optional: see which tools the agent called, in order, with results and timings:

   ```bash
   curl http://localhost:8080/api/documents/<document_id>/runs
   ```

5. Optional: run the whole agent again (text and data are re-extracted):

   ```bash
   curl -X POST http://localhost:8080/api/documents/<document_id>/reprocess
   ```

`/result` answers 409 `result_not_ready` while the document is processing and 409
`result_unavailable` (with the error) when processing failed. The intermediate steps are also
readable on their own: `GET /api/documents/<document_id>/text` and `/extraction`.

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
currency are converted to it), `AGENT_MAX_STEPS` (default 8 model turns per agent run),
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
