# Engineering Notes

Each feature appends its notes to the four sections below. Entries are tagged with the
feature number (`0000`, `0001`, ...).

## 1. Architecture decisions

### 0000 - Project foundation

- **One store: PostgreSQL 18 + pgvector.** Relational data and RAG embeddings live in the
  same database, so there is no separate vector service to run or keep consistent. pgvector
  is enabled by the first Alembic migration (not an init script), so local, Docker, and CI
  databases all follow the same path.
- **One `.env`.** A single root file configures Docker Compose and the backend (via
  `pydantic-settings`). `DATABASE_URL` is derived from `POSTGRES_*` unless set explicitly.
  The host-side `DB_PORT` is configurable because 5432 is often taken; inside Compose the
  backend is pinned to the db container's port 5432.
- **`BackgroundTasks`, no queue.** The brief needs asynchronous processing
  (`processing` -> `completed | failed`), not a distributed job system. FastAPI runs sync
  work in a threadpool, so SQLAlchemy 2.0 is used synchronously with psycopg 3.
- **A single LLM seam.** Every OpenAI call goes through `app/core/llm.py`: models come from
  config, token usage is captured on every response, calls are logged, and SDK errors become
  one `LLMError`. Features depend on the `LLMClient` protocol, so tests inject a scripted
  `FakeLLM` and never touch the network. The real client is created lazily, so the app
  starts (and `/api/health` works) without an API key.
- **Module anatomy.** Each feature is a folder under `app/modules/<module>/` containing
  only the layers it needs (`router` -> `service` -> `crud` -> `model`, plus `schema` DTOs).
  Modules import each other's `service`/`schema` only, never `crud`/`model`.
- **Consistent errors and logs.** A small `AppError` hierarchy maps to
  `{"error": {"code", "message"}}`; logs are JSON with a `document_id` context variable so
  a document's whole pipeline can be followed.
- **Same-origin API.** Everything is served under `/api`; the Vite dev server and the nginx
  container both proxy that prefix to the backend, so the browser never needs CORS.
- **Agent design rule: AI does the thinking; code does the maths and keeps the order.**
  The LLM reads, interprets, and writes. Arithmetic (totals, tax, currency conversion),
  validation, and step ordering (validate before summarising) are deterministic code that the
  agent calls as tools, never something the model is trusted to compute or sequence.

## 2. Prompt design

_TODO per feature: prompt structure, versioning (`PROMPT_VERSION`), output schemas, and how
hallucination is prevented (fields absent from the document are `null`)._

## 3. Limitations

_TODO per feature: known gaps (for example the static, dated currency-rate table)._

## 4. Production improvements

_TODO per feature: what would change for production (auth, a real job queue, object
storage such as S3 behind the `Storage` interface, secrets management, metrics and tracing,
retries and rate-limit handling, database backups)._
