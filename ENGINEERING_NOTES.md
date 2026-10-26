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

### 0002 - Text extraction

- **Two methods, chosen per document.** A PDF whose every page has a text layer is parsed
  locally with `pdfplumber` (free, instant, exact). Everything else (JPG, PNG, scanned or
  partly scanned PDFs) is rendered and transcribed by the OpenAI vision model. `method`,
  `page_count`, `model` and `prompt_version` are stored with the text so a result can be
  explained later. Only permissive licences (MIT / BSD / Apache / HPND) were used, so the
  repo can be public: `pdfplumber`, `pypdfium2` and Pillow, all pure wheels with no system
  packages. PyMuPDF (AGPL) and poppler were rejected for that reason.
- **No-text-layer heuristic.** Per page, whitespace and pdfminer's `(cid:N)` glyph
  placeholders are removed; the page "has text" when at least 20 characters remain. If any
  page fails the check the whole document goes to vision. That is deliberately simple:
  it catches scans, image-only pages and broken font encodings, and keeps `method` a single
  value per document.
- **Bounded cost.** At most `VISION_MAX_PAGES` (default 5) pages are sent; pages are
  rendered at 200 DPI, EXIF-rotated, flattened to RGB (transparency goes onto white) and
  downscaled to a 2048 px long side before being sent as JPEG with `detail: "high"`. One
  call per page, temperature 0. Text-layer PDFs cost no LLM tokens at all.
- **A plain service function, not a pipeline step.** `extract_text(db, storage, llm,
  document_id, force=False)` is what the 0005 agent tool will call. It is idempotent (an
  existing row is returned without any LLM call; `force=True` replaces it in place, and an
  upsert on the unique `document_id` makes concurrent calls end with one row). It commits
  its own row, so the text survives a later pipeline failure, and it ends the read
  transaction before the slow vision calls so no connection is held open. It never changes
  the document status; `run_pipeline` already marks the document `failed` when anything
  raises.
- **`GET /api/documents/{id}/text` is read-only.** It never extracts and never calls
  OpenAI. No text yet gives a 409 (`text_not_ready` while processing, `text_unavailable`
  with the document's error otherwise), which is distinct from the 404 of a wrong id.
- **Cross-module access stays on the rules.** The module learns where the file is through
  `documents.service.get_document_source` (a small internal DTO; the storage path is never in
  the API) and reads bytes through `Storage`. An AST test guards against imports of
  `documents.crud` / `documents.model`.
- **Failures are errors, not empty rows.** An unopenable, corrupt or password-protected
  file is `unreadable_document` and a document with no legible text is `no_text_found`
  (both 422); an OpenAI failure stays `llm_error` (502). Nothing is saved, so the caller can
  mark the document `failed` with a clear reason instead of feeding empty text to 0003.

## 2. Prompt design

_TODO per feature: prompt structure, versioning (`PROMPT_VERSION`), output schemas, and how
hallucination is prevented (fields absent from the document are `null`)._

**0002 - Text extraction** (`app/modules/text_extraction/prompts.py`, `PROMPT_VERSION =
"text_extraction.v1"`, stored on every vision row)
- **Transcribe, never interpret.** The system prompt makes the model a "transcription
  engine": copy every visible character exactly in reading order, keep line breaks, put each
  table row on one line with cells separated by `" | "`, keep numbers, currency symbols and
  punctuation as printed, and never summarise, translate, correct, reformat, describe
  logos or add anything. Meaning (vendor, totals, `null` for missing fields) is left to 0003.
- **One page per call, structured output.** The user message is `Transcribe page N of M.`
  plus the page image. The reply is `PageTranscription {text, legible}` (all fields required,
  as strict structured output needs), so there is no chatter like "Here is the text:" and an
  unreadable page is an explicit `legible=false` with `text=""` rather than invented text.
  `M` is the real page count even when the page cap applies. A reply that cannot be parsed
  (refusal, malformed) is an `LLMError`.
- **Deterministic settings.** Temperature 0 and the model from `OPENAI_VISION_MODEL`.
  Bump `PROMPT_VERSION` on any prompt change so stored rows say which wording produced them.

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

**0002 - Text extraction**
- Only the first `VISION_MAX_PAGES` (5) pages of a scanned PDF are read; totals on later
  pages are lost. The cap is configurable and logged as a warning when it applies.
- A PDF that mixes text pages and scanned pages is sent to vision as a whole document, so
  the text pages pay for vision too. A per-page hybrid would be cheaper but gives a mixed
  `method`.
- Vision can misread digits or drop a line. The text is not checked against the image here;
  that is guarded later by the deterministic validation in 0004 and by grounding checks.
- A broken font encoding can produce garbage that still has 20 or more characters and is
  then trusted as `pdf_parser` text. `force=True` re-extracts it, but there is no automatic
  re-extraction or per-page comparison.
- Table structure is not extracted (rows are only kept on one line with `" | "` in vision
  text); positions and bounding boxes are out of scope.
- `reportlab` is a dev-only dependency used to build test PDFs; the production image does
  not contain it.
- No extraction runs on upload until 0005; the text endpoint answers 409 until then.
- pypdfium2 (PDF rendering) is not thread-safe. Background tasks run in a thread pool, so
  0005 must serialise rendering (a lock) if several extractions can run at once.

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

**0002 - Text extraction**
- Move PDF parsing and rendering into a worker with a CPU / time limit (and a page-count
  limit before rendering) so a hostile PDF cannot stall the API process; sandbox the parsers.
- Add a cheap quality check on parsed text (language / garbage ratio) and a per-page hybrid
  that sends only the scanned pages to vision.
- Cache and de-duplicate by file hash so identical uploads reuse one extraction; track
  vision token cost per document and alert on spend.
- Retry vision pages with backoff and a fallback model, and allow resuming a partly
  transcribed document instead of starting over.
