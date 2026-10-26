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

### 0001 - Documents (upload API)

- **UUID v4 primary keys everywhere.** Every table uses a native Postgres `UUID` key
  generated with `uuid.uuid4()`, returned as the plain dashed UUID with no prefix. Random
  IDs cannot be guessed or enumerated; "newest first" ordering uses `created_at`.
- **The file's bytes decide its type.** The upload's first bytes (`%PDF-`, the PNG
  signature, `FF D8 FF`) are sniffed, and the `Content-Type` header must agree, otherwise
  415. The sniffed type is what gets stored, because extraction (0002) routes on it.
- **Real file names on disk, never overwritten.** Files keep their cleaned upload name
  (basename only, unsafe characters replaced, Windows-reserved names prefixed). Re-uploading
  the same name (case-sensitive) stores `invoice(2).pdf`, `invoice(3).pdf`, … and the API
  reports `filename` + `version`. `LocalStorage.save_as` opens files in exclusive-create
  mode, so a name that is already taken on disk (a case-insensitive Windows disk, or a file
  literally named `invoice(2).pdf`) moves to the next version instead of replacing it. A
  `UNIQUE (filename, version)` constraint plus a retry loop handles concurrent uploads, and
  a saved file is deleted again if its row cannot be inserted.
- **One pipeline hook.** The router schedules `service.run_pipeline` with FastAPI
  `BackgroundTasks`; the pipeline itself comes from a dependency
  (`get_document_pipeline`, a `(document_id) -> None` callable), so 0005 plugs in the
  agent by replacing one function. `run_pipeline` binds the `document_id` log context and
  marks the document `failed` with the error message if the pipeline raises. The pipeline
  marks `completed` itself, so completion can be saved in the same transaction as its
  results; until 0005 the hook is a no-op and documents stay `processing`.

## 2. Prompt design

_TODO per feature: prompt structure, versioning (`PROMPT_VERSION`), output schemas, and how
hallucination is prevented (fields absent from the document are `null`)._

## 3. Limitations

_TODO per feature: known gaps (for example the static, dated currency-rate table)._

**0001 - Documents**
- The upload size check runs after Starlette has received the multipart body (it is
  spooled to a temp file first), so it protects storage and the database, not the request
  itself. nginx has no `client_max_body_size` override yet.
- No queue: if the backend stops mid-pipeline, that document stays `processing` and
  nothing retries it.
- On a case-insensitive disk (Windows development) a name that differs only in case from
  an existing file is stored with the next version, so its `version` can skip a number.
  In Docker (Linux) names are matched exactly.
- Until 0005 the pipeline is a no-op, so documents never leave `processing`.

## 4. Production improvements

_TODO per feature: what would change for production (auth, a real job queue, object
storage such as S3 behind the `Storage` interface, secrets management, metrics and tracing,
retries and rate-limit handling, database backups)._

**0001 - Documents**
- Enforce the body size limit at the edge (nginx `client_max_body_size`) and stream
  uploads straight to object storage.
- Run the pipeline on a job queue with retries and a sweeper that fails or re-queues
  documents stuck in `processing`.
- Scan uploads for malware and sanitise PDFs before parsing; add auth and per-user
  ownership of documents.
