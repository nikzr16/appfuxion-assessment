# Document Intelligence Agent

An AI/ML take-home assessment for AppFuxion. Upload a financial document (an invoice or
receipt as PDF, JPG, or PNG) and the system extracts its text, uses an LLM to turn it into
structured JSON, validates the numbers with deterministic code, and writes a short AI
summary. AI agents (OpenAI tool calling) orchestrate the steps, and past invoices are
searchable with pgvector.

> **Status:** the project foundation (feature `0000`) and the document upload API
> (feature `0001`: `POST/GET /api/documents`) are in place. Extraction, validation and
> the agents land in later numbered features; see
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

Upload a document (returns `{document_id, status: "processing"}`), then poll it:

```bash
curl -F "file=@invoice.pdf;type=application/pdf" http://localhost:8080/api/documents
```

```bash
curl http://localhost:8080/api/documents/<document_id>
```

The backend waits for the database, applies the Alembic migrations (which enable the
`vector` extension), then starts. The app and `/api/health` work without an
`OPENAI_API_KEY`; the key is only needed once the AI features are used.

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
credentials and ports, `AGENT_MODE`, `MAX_UPLOAD_MB`, `STORAGE_DIR`, and more.

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
