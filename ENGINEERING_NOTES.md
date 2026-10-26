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

### 0003 - Structured extraction

- **One schema, two jobs.** `InvoiceData` is both the OpenAI strict structured-output schema
  and the typed DTO that validation (0004) consumes. Strict mode needs every field required
  and no defaults, so "missing" is expressed as `null`, never as an absent key, and
  `line_items` is always a list. Besides the brief's fields it has `subtotal` and `tax` (so
  0004 can check subtotal + tax = total) and the party fields `vendor_address`,
  `vendor_tax_id`, `customer_name`, `customer_address`, `payment_terms`.
- **Exact money.** Money and quantities are `Decimal` in code. Pydantic's default schema for
  `Decimal` is `number | string`, which would let the model answer `"RM 12.30"`; a
  `WithJsonSchema` override shows the model a plain JSON `number`, and Pydantic reads a JSON
  number into `Decimal` exactly (`0.1` stays `0.1`, no float rounding). In JSONB and the API
  money is a decimal string. Dates are `date` (`format: date` in the schema), stored and
  returned as ISO `YYYY-MM-DD`; the UI (0006) displays `DD-MM-YYYY`.
- **The model interprets, code checks the shape.** The model maps currency symbols to ISO
  codes and day/month order to ISO dates, because that needs the whole document as context.
  Code then strips text (blank → `null`), upper-cases the currency and rejects anything that
  is not three letters, and Pydantic rejects impossible dates. Whether a code is a real
  currency, totals and due-date order are 0004's deterministic checks, not retry triggers.
- **One retry, with the reasons.** A reply that fails validation is retried once: the same
  messages plus a user message listing each error as `field: problem (got: value)`. A refusal
  (`llm_refused`) and an API error (`llm_error`, already retried by the SDK) are not retried.
  After two invalid replies the error is `invalid_llm_output` (502). To make this possible
  the LLM seam now turns the SDK's raw `pydantic.ValidationError` into a typed
  `LLMOutputError` (with the error list) and exposes `LLMResponse.refusal`; `FakeLLM` does the
  same, so the retry path is tested without the network.
- **`unknown` is an answer, not an error.** A document that is not an invoice or receipt is
  saved with `document_type = unknown` and empty fields; the agent (0005) decides what to do.
- **Same contract as 0002.** `extract_structured_data(db, llm, document_id, force=False)` is
  idempotent (one row per document; `force` replaces it in place), commits its own row, holds
  no DB transaction during the LLM call and never changes the document status. It reads the
  text only through `text_extraction.service.find_text` and raises `text_not_extracted` (409)
  rather than extracting the text itself, so it needs no storage access and the agent is told
  which tool to call first. `GET /api/documents/{id}/extraction` is read-only with the same
  404 / 409 pattern as the text route. `model`, `prompt_version`, `attempts` and token counts
  are stored with each result.

### 0004 - Validation

- **Code does the maths.** `validate_invoice(InvoiceData) -> ValidationReport` is a pure
  function: no database, network or LLM, and the same input (and `today`) always gives the
  same report in the same order. It never raises; every problem is an issue
  `{field, code, severity, message, expected, actual}`, so the agent always has something to
  summarise. Messages are finished sentences that already contain the numbers ("Subtotal
  100.00 + tax 6.00 = 106.00 MYR, but the total is 108.00 MYR (difference 2.00 MYR)"), so the
  summary model only repeats them and never calculates.
- **Three severities, one roll-up.** `error` (impossible or unusable: no vendor or total, a
  currency that does not exist, a due date before the invoice date) → `fail`; `warning`
  (probably wrong or incomplete) → `warn`; `info` (a note) never changes the status. Issue
  codes are a stable catalogue (`docs/reference/folder-structure.md`) that the UI and the
  summary prompt can rely on; `field` is a JSON path (`line_items[2].amount`) so the UI can
  highlight one line.
- **Arithmetic mismatches are warnings, not errors.** `InvoiceData` has no discount,
  shipping or cash-rounding fields, so a correct invoice with "Shipping 15.00" in its totals
  block would otherwise fail. Tax-inclusive layouts (subtotal already equals the total) pass
  with an info note, which avoids a false warning on most Southeast Asian receipts. Every
  comparison is exact `Decimal` arithmetic with a tolerance of one minor unit of the
  document's currency (JPY 1, MYR 0.01, KWD 0.001).
- **Lenient on what 0003 leaves empty on purpose.** A null date or currency is often 0003
  being honest (an ambiguous `03/04/2025`, a bare `$`), so it is a warning with a hint, not a
  fail. Receipts need no number or due date. An `unknown` document gets one warning and no
  other checks.
- **ISO 4217 via `pycountry`; minor units in a small table.** `pycountry` (LGPL-2.1, no
  dependencies) answers "is this a real currency?"; its 178 codes matched the official ISO
  list (published 2026-09-17) exactly. It has no minor units, so `currencies.py` lists the 26
  currencies that differ from 2 decimal places, checked against the same list. Metals, IMF
  units and test codes (`XAU`, `XDR`, `XTS`, `XXX`, …) are not valid invoice currencies.
- **Static, dated conversion.** `convert_currency(amount, from, to)` uses a snapshot of 25
  rates (the currencies 0003 can produce from a symbol), USD base, copied as `Decimal`
  literals from ExchangeRate-API's open endpoint on 2026-10-26. The cross rate is exact; the
  result is rounded half-up to the target's minor units and always carries `rate_date` and
  `source`, so the user sees how old the rate is. Unsupported codes and non-finite amounts
  raise `CurrencyConversionError` (422) with a reason the agent can read.
- **A pure module.** `validation/` has `schema.py`, `service.py` and a data-only
  `currencies.py`; no router, table or migration. It imports only
  `structured_extraction.schema` (a test enforces this). The 0005 agent run will store the
  report and expose it through the document result.

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

**0003 - Structured extraction** (`app/modules/structured_extraction/prompts.py`,
`PROMPT_VERSION = "structured_extraction.v1"`, stored on every row)
- **The schema is the output format.** `response_format=InvoiceData` (strict), temperature 0,
  model `OPENAI_MODEL`. Each field carries a one-line `description`; the system prompt holds
  the rules, so the reply can only be the object, with no prose.
- **Untrusted input is fenced.** The document text is sent in its own user message inside
  `<document>` … `</document>`, and the system prompt says that text is data from an uploaded
  file and any instructions in it must be ignored. 0002's `--- Page N ---` markers are kept
  (totals are often on the last page) and declared as system markers, not content.
- **"Never invent" is spelled out.** Copy values as printed; never calculate, add up, convert
  or guess; a field the document does not state is `null`; only rows printed as items are
  `line_items` (not subtotal, tax, total or payment rows); `unknown` documents get all `null`.
  No due date is computed from "Net 30", and a printed tax rate is not turned into an amount.
- **Normalisation rules are explicit.** Numbers: plain JSON numbers, `.` as decimal point,
  both `1,234.56` and `1.234,56` → `1234.56`, parentheses or a minus → negative. Dates:
  `YYYY-MM-DD`; numeric dates decided by evidence in the document (a day above 12, a printed
  format hint), otherwise `null`; two-digit years are 20YY. Currency: a printed ISO code wins,
  then a symbol table covering every Southeast Asian currency (RM, S$, Rp, ฿, ₱, ₫, B$, ៛, ₭,
  Ks, US$) and the common world symbols; a bare `$`, `¥`, `K`, `Fr` or `kr` is `null` unless the
  document names the currency elsewhere.
- **Retry feedback is factual.** The retry message lists the validation errors (field path,
  message, offending value, at most 20 lines) and asks for the complete corrected object,
  reminding the model that `null` is the answer when a value is not in the document.

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

**0003 - Structured extraction**
- Nothing checks that an extracted value really appears in the text; a confident wrong value
  passes. Grounding checks and confidence scores are planned for B2, arithmetic checks for 0004.
- A numeric date whose day/month order the document does not reveal (e.g. `03/04/2025`) is
  `null`, so 0004 will report it as missing even though a date was printed.
- Tokens of a reply rejected by validation are not counted: the OpenAI SDK raises before it
  returns usage. In strict mode only the code-side checks (currency shape, impossible date,
  non-finite number) can reject a reply, so this is rare, but `prompt_tokens` /
  `completion_tokens` under-report the retry path. The rejected reply itself is not kept
  either (no raw output is stored; B1 adds a per-call ledger).
- Trailing zeros are not preserved: a JSON number `5.00` becomes `Decimal("5")`. The value is
  exact; only its printed formatting is lost.
- Text over 60,000 characters is cut to its first 45,000 and last 15,000 characters; line
  items in the middle of a very long document are lost.
- If the text is re-extracted with `force=True`, the saved structured data is not invalidated
  automatically; it must be re-extracted with `force=True` too (0005's reprocess does both).
- Only one row per document is kept; earlier extractions are overwritten, not versioned.

**0004 - Validation**
- Exchange rates are a static snapshot dated 2026-10-26 (indicative mid-market rates from
  ExchangeRate-API, not for settlement) and only 25 currencies convert; refreshing is a manual
  code change.
- `InvoiceData` has no discount, shipping or rounding-adjustment fields, so an invoice whose
  totals block contains them gets a `subtotal_tax_mismatch` / `line_items_sum_mismatch`
  warning even when it is correct (e.g. Malaysian cash rounding to 0.05). The message shows
  the difference so a person can judge.
- The tax-inclusive rule accepts `subtotal = total` whenever tax is set, so an invoice that
  forgot to add its tax passes with only an info note.
- Each document is checked against itself only: duplicates, vendor history and outliers come
  with B3; whether a value really appears in the text comes with B2.
- `today` is the server's local date; the 1-day slack on future dates covers time zones but
  not a wrong server clock.

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

**0003 - Structured extraction**
- Add grounding (every extracted value must appear, normalised, in the raw text) and
  per-field confidence; re-ask only for the fields that failed instead of the whole object.
- Record every LLM call (raw reply, tokens, latency, validation errors) in a ledger so
  rejected replies can be inspected and their cost counted; parse the reply ourselves instead
  of through the SDK so usage survives a validation failure.
- Version extractions (keep history, link each one to the text row it came from) and
  invalidate them automatically when the text is re-extracted.
- Chunk very long documents (extract per page, merge line items) instead of cutting the
  middle; route ambiguous dates to a human or a locale setting per customer instead of `null`.
- Evaluate prompt changes against a labelled set of real invoices before bumping
  `PROMPT_VERSION`, and fall back to a stronger model when the retry also fails.

**0004 - Validation**
- Pull rates daily from a licensed provider (stored with their date) and convert at the
  invoice date's rate, not today's; keep the static table only as an offline fallback.
- Add `discount`, `shipping` and `rounding_adjustment` to `InvoiceData` so the totals check
  can be exact and mismatches can become errors.
- Make the rules configurable per customer or country (required fields, tolerance, cash
  rounding such as MYR to 0.05, the too-old limit) instead of constants.
- Validate tax rates against the vendor's country (e.g. SST 6% / 8%, GST 9%) and tax IDs
  against their national formats.
