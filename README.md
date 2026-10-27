# Document Intelligence Agent

An AI/ML take-home assessment for AppFuxion. Upload a financial document (an invoice or
receipt as PDF, JPG, or PNG) and the system extracts its text, uses an LLM to turn it into
structured JSON, validates the numbers with deterministic code, and writes a short AI
summary. AI agents (OpenAI tool calling) orchestrate the steps, and past invoices are
searchable with pgvector.

## What it does

The five core parts of the brief and all five bonus tasks are done
([roadmap](docs/product-roadmap.md)).

- **Upload** a PDF, JPG or PNG through the web UI or `POST /api/documents`; processing runs
  in the background.
- **Three AI agents** run in order under a plain-Python Coordinator: an **Extraction**, a
  **Validation** and a **Reporting** agent, each with its own prompt and tools
  (`AGENT_MODE=single` runs one Document Agent with every tool instead).
- **Text extraction:** text PDFs are parsed locally for free; scans and photos are read by an
  OpenAI vision model. Tables and layout blocks are found on every page.
- **Structured JSON** through OpenAI structured outputs, then a **grounding check**: every
  value is looked up in the document's own text, and each field gets a confidence score.
- **Deterministic validation:** totals, tax, line items, dates and currency are checked by
  code; a foreign total is converted to `BASE_CURRENCY` (MYR); duplicate invoice numbers and
  unusual amounts are flagged against the vendor's history.
- **A summary** that must mention every validation problem (checked by code).
- **Ask AI:** a chat over all stored invoices (pgvector search, with every number checked
  against the data).
- **Observability:** every LLM call's tokens, cost and latency; a per-document trace; and a
  metrics page.

How it fits together, and why, is in the
[summary for reviewers](ENGINEERING_NOTES.md#summary-for-reviewers) at the top of
`ENGINEERING_NOTES.md`: an architecture diagram, the
[step-by-step flow](ENGINEERING_NOTES.md#how-a-document-flows-step-by-step),
[the agents and their tools](ENGINEERING_NOTES.md#the-agents),
[the bonus tasks](ENGINEERING_NOTES.md#the-bonus-tasks-in-brief) and the
[engineering practices](ENGINEERING_NOTES.md#production-style-engineering-practices).

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

### Try it with the samples

[`samples/`](samples/) holds five made-up documents, each showing a different path. Drag them
onto the upload page; each takes about 10–20 seconds and costs under a cent.

| File | What it shows |
|---|---|
| `lumen-office-INV-2026-0418.pdf` | A clean invoice: validation passes, line items copied from the ruled table |
| `damai-perabot-unruled-malay.pdf` | Malay column titles, an unruled table found by code, `DD/MM/YYYY` dates |
| `harbourline-cloud-USD-HC-2291.pdf` | A USD total converted to MYR with a dated rate |
| `brightpath-logistics-with-errors.pdf` | Validation **fails**: due date before the invoice date, and a total that does not add up |
| `kopi-contoh-receipt.png` | A tilted receipt image read by the vision model |

Upload the same file twice to see the duplicate-invoice-number warning. Then open **Ask AI**
and ask "How much have we spent in total?". The samples are rebuilt with
`uv run --project backend python samples/make_samples.py`.

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
   **Tables & layout:** the **Tables** tab shows every table found (and whether it fed the
   line items); the **Page** tab shows the page with its vendor, document info, bill-to, line
   items, totals and payment areas outlined and numbered. Line items copied from a table say
   so, and their locate button opens the page with that row highlighted. Scans list their
   areas instead of drawing them. Older documents say "Layout not analysed"; reprocess them.
   **Vendor history:** how this invoice compares with the vendor's other invoices (median,
   usual range, where this total sits), invoices with the same number, and the five most
   similar invoices. A duplicate invoice number or an unusual amount is also a validation
   warning that the summary mentions.
4. **Metrics** — documents, success rate, average / p95 processing time, tokens and estimated
   cost per document, LLM usage by model and by purpose, and a **Guardrails** section
   (average confidence, share needing review, grounding rate, retries and the high / medium /
   low split) and a **Vision** section (documents with a line-item table, share of line items
   copied by code, pages read by vision, multimodal extractions) and a **Retrieval & Ask AI**
   section (indexed invoices, duplicate / unusual-amount flags, questions asked, answer time
   and cost), for the last 7 or 30 days or all time.
5. **Ask AI** — the button at the bottom right of every page opens a chat about your stored
   invoices ("How much have we spent with ABC Supplies this year?", "Compare this invoice with
   previous ABC Supplies invoices"). Follow-up questions remember the chat; **New chat**
   starts over. Answers link to the invoices they used, code does every sum, and numbers that
   could not be matched to the data are flagged. On a document page, "this invoice" means that
   document. The chat survives page changes and reloads in the same tab.

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
   `extract_tables` and `check_grounding`; the grounding report itself is on
   `GET /documents/<document_id>/extraction`):

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

7. Optional: see the tables and layout blocks found (with page positions for text PDFs and
   the earlier analyses in `history`), or a page image:

   ```bash
   curl http://localhost:8080/api/documents/<document_id>/layout
   curl -o page1.jpg http://localhost:8080/api/documents/<document_id>/pages/1/image
   ```

8. Optional: run the whole agent again (text, tables and data are re-extracted):

   ```bash
   curl -X POST http://localhost:8080/api/documents/<document_id>/reprocess
   ```

9. Optional: compare with earlier invoices (409 `not_indexed` before the document is indexed):

   ```bash
   curl http://localhost:8080/api/documents/<document_id>/vendor-history
   curl http://localhost:8080/api/documents/<document_id>/similar
   ```

10. Optional: ask a question; pass the returned `conversation_id` to ask a follow-up, and
    `document_id` to give the document you mean:

    ```bash
    curl -X POST http://localhost:8080/api/query -H "Content-Type: application/json" \
      -d '{"question": "How much have we spent with ABC Supplies in total?"}'
    curl http://localhost:8080/api/conversations/<conversation_id>
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

Documents processed before feature `0010` are not in the search index yet. Index them once
(Docker: `docker compose exec backend python -m app.modules.retrieval.backfill`); new
and reprocessed documents are indexed automatically.

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
| Index older documents | `uv run python -m app.modules.retrieval.backfill` (one embedding call each, about $0.00001) |

Tests create and migrate a separate `appfuxion_test` database on the same server, so they
never touch your development data, and they never call the real OpenAI API.

## Configuration

One root `.env` (git-ignored) drives Docker Compose and the backend. Every key is
documented in [`.env.example`](.env.example): OpenAI key and model names, Postgres
credentials and ports, `AGENT_MODE`, `BASE_CURRENCY` (default `MYR`: totals in another
currency are converted to it), `AGENT_MAX_STEPS` (default 14 model turns per single-mode run;
multi mode limits each agent in code to 6 / 6 / 4 turns),
`QUERY_MAX_STEPS` (default 6 model turns per Ask AI question),
`OPENAI_MAX_RETRIES` (default 2 retries of a rate-limited, timed-out or failed OpenAI call,
with backoff),
`MAX_UPLOAD_MB`, `STORAGE_DIR`, and more. `AGENT_MODE=multi` (the default) runs the
Coordinator's three agents (Extraction → Validation → Reporting); `AGENT_MODE=single` runs the
one Document Agent with every tool. Both give the same result shape; restart the backend after
changing it.

## Project layout

```text
backend/        FastAPI app (app/core shared infrastructure, app/modules/<feature>), Alembic, tests
frontend/       Vite + React + TypeScript + Tailwind UI
db/             Standalone Postgres + pgvector compose file
samples/        Made-up invoices and a receipt to try the app with, plus their generator
docs/           Roadmap, PRDs, plans, reference docs, decision log
.github/        CI workflow
ENGINEERING_NOTES.md   Architecture decisions, prompt design, limitations, production improvements
```

The full structural reference is [`docs/reference/folder-structure.md`](docs/reference/folder-structure.md).

### Where the brief's example folders are

The backend is organised by feature (`backend/app/modules/<feature>/`), each with only the
layers it needs (`router` → `service` → `crud` → `model`, plus `schema`), rather than by
technical layer. The brief's example folders map onto it like this:

| Brief's example | In this repo |
|---|---|
| `api/` | Each module's `router.py` (for example `modules/documents/router.py` serves `POST /api/documents`); wired in `backend/app/main.py` |
| `agent/` | `modules/agent/`: `runner.py` (the shared tool-calling loop), `coordinator.py` (the three agents), `tools.py`, `prompts.py`, `query.py` (Ask AI) |
| `tools/` | Plain service functions in the modules the agents call: `text_extraction`, `vision`, `structured_extraction`, `guardrails`, `validation`, `retrieval`; `modules/agent/tools.py` exposes them to the model |
| `vision/` | `modules/vision/` (page rendering, the vision model call, table and layout detection) and `modules/text_extraction/` |
| `tests/` | `backend/tests/` (mirrors `app/modules/`) and `frontend/src/**/*.test.ts(x)` |
| `README.md`, `ENGINEERING_NOTES.md` | At the repository root |

## Documentation

- [`ENGINEERING_NOTES.md`](ENGINEERING_NOTES.md) - design decisions, prompt design, limitations, and production improvements (start with its summary for reviewers)
- [`docs/product-roadmap.md`](docs/product-roadmap.md) - phases and feature status
- [`docs/prd/`](docs/prd/), [`docs/plan/`](docs/plan/), [`docs/decisions/`](docs/decisions/) - per feature: the requirements, the implementation plan, and where the build differed from the plan
- [`docs/reference/folder-structure.md`](docs/reference/folder-structure.md) - every module, endpoint, table and issue code

## Built on the Orchestral Harness

This repository was built with an agent-orchestration harness for Claude Code that keeps
work docs-first (PRD, then plan, then code). Its policy and routing rules live in
[`CLAUDE.md`](CLAUDE.md), with the project-specific context in
[`CLAUDE.project.md`](CLAUDE.project.md) and the agents, skills, and workflows under
[`.claude/`](.claude/). None of it is needed to run the application.
