# 0006 Frontend PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Give the Document Intelligence Agent a usable browser UI: upload an invoice or receipt,
watch it being processed, and read the result (summary, structured data, line items,
validation issues, currency conversion, raw text). The 0000 skeleton only shows a health
badge; 0001–0005 built the whole API this UI consumes.

## Goals

- **Production-ready UI/UX:** it must look good and be easy to use — a consistent visual
  system, light and dark themes, loading skeletons, helpful empty states, clear focus and
  hover states, icons, and a layout that works from phone to desktop (D18).
- **Upload page:** drag and drop or a file picker for **one or several files**, with type and
  size checks before anything is sent, per-file progress, and clear messages when the server
  rejects a file.
- **Documents list:** every upload, newest first, with status badges, a status filter,
  pagination and automatic refresh while something is processing.
- **Document detail:** the summary and validation status first, then the structured data,
  line items, validation issues highlighted on the fields they concern, the conversion, the
  raw text and the agent's tool-call steps; a reprocess button; a clear failed state with
  the error and whatever partial data was saved.
- **Multi-agent view:** the agent's work shown as three roles — Extraction → Validation →
  Reporting — with each tool call in its role's lane, live while processing (D19).
- **One typed API client** in `frontend/src/api/` whose types mirror the backend schemas in
  `docs/reference/folder-structure.md`.
- Works the same in Docker (nginx `/api` proxy) and in dev (Vite `/api` proxy).
- Vitest + Testing Library tests for every component or hook that holds logic.

## Non-Goals

- Trace and token view (`GET /trace`, `/metrics`) — **B1 (0007)**.
- Confidence badges and grounding results — **B2 (0008)**.
- Query page (`POST /query`) — **B3 (0010)**.
- Authentication, users, roles.
- Editing or correcting extracted values; deleting documents (no API exists for either).
- Translations / other languages.

## Scope

| In Scope | Out of Scope |
|---|---|
| Pages: Upload, Documents list, Document detail (D1) | Query page (B3), metrics dashboard (B1) |
| Typed API client for every 0001–0005 route used by the UI | `/trace`, `/metrics`, `/query` (later features) |
| Polling while a document is processing (D3) | Server push (WebSocket / SSE) |
| Validation issues mapped onto fields and line items (D8) | Confidence per field (B2) |
| Simple tool-call step list from `GET /runs` (D10) | Token / latency trace view (B1) |
| Multi-agent view: Extraction / Validation / Reporting lanes (D19) | Backend multi-agent mode itself (B4) |
| Reprocess with a confirm step (D11) | Cancelling a running agent |
| Money and date formatting without float maths (D9) | Currency conversion in the browser |
| Tailwind-only styling, light + dark, responsive down to phone width (D13, D18) | Any other CSS framework or component library |
| Several files per upload, each its own `POST /documents` (D4) | A batch upload endpoint |
| Vitest + Testing Library tests (D14) | End-to-end browser tests in CI (D14) |
| One additive backend route `GET /api/config` (D5, D16) | Changing 0001–0005 contracts |
| README (using the UI), ENGINEERING_NOTES 0006 sections, folder-structure reference | — |

## User Stories

1. **As a user**, I want to drag one or several invoices onto the page (or pick them with the
   keyboard) and be told straight away if a file is the wrong type or too large, so that I do
   not wait for a server error.
2. **As a user**, I want to see my document move from *processing* to *completed* or
   *failed* without reloading the page, so that I know when the result is ready.
3. **As a user**, I want the summary and the validation status at the top, and every
   validation issue shown next to the value it concerns (with the expected and found
   numbers), so that I can see at a glance what is wrong and where.
4. **As a user**, I want money shown with thousands separators and the right number of
   decimals for its currency, and dates as `DD-MM-YYYY`, so that the numbers read naturally.
5. **As a user**, I want to see why a document failed and to reprocess it, so that a
   temporary failure is not permanent.
6. **As a reviewer of the assessment**, I want to see which tools the agent called, in what
   order and how long each took, so that the agent's work is visible in the UI.
7. **As a user**, I want a list of every document I uploaded, filterable by status, so that
   I can find an earlier result.

## Product Decisions

> **Status: final (2026-10-27).** D1, D2, D6–D12, D14–D16 as recommended; **D3 = fixed 10 s
> polling**, **D4 = up to 5 files → the list**, **D5 = backend `GET /api/config`** (hence
> D16), **D13 = light + dark with a theme toggle**, **D17 = login / edit / delete out, the
> multi-agent view in (D19)**, and a production-ready UI/UX bar (**D18**) with **Poppins**.

| # | Decision (recommended) | Rationale |
|---|---|---|
| D1 | **Routing: `react-router` (new dependency), three real URLs.** `/` Upload, `/documents` Documents list, `/documents/:id` Document detail; unknown paths show a small "not found" page with a link home. A header with the app name, links to Upload and Documents, and the existing `HealthBadge`. | Real URLs give deep links, a working back button and shareable detail pages. nginx already falls back to `index.html` for unknown paths, so no server change is needed. react-router is the standard choice reviewers will recognise. |
| D2 | **Data fetching: TanStack Query (new dependency)** on top of the typed API client. Components never call `fetch` directly; one query hook per endpoint (`useDocuments`, `useDocument`, `useResult`, `useText`, `useRuns`) and mutations for upload and reprocess. | Polling, pausing when the tab is hidden, de-duplicating requests, retries and cache invalidation after upload/reprocess are exactly what it does; writing and testing that by hand is more code than the feature itself. |
| D3 | **Polling every 10 s (user's choice), fixed interval.** While a document is `processing`, its detail page polls `GET /documents/{id}` and `GET /runs` every **10 s** (one immediate fetch on page load). Polling **stops** as soon as the status is `completed` or `failed` (then `/result` is fetched once) and **pauses while the tab is hidden** (resumes and refetches at once when it is visible again). A failed poll (network) retries with backoff and shows a "reconnecting…" note; it never marks the document failed. The list polls every **10 s only while a row on the current page is `processing`**. The interval is one constant (`POLL_INTERVAL_MS`). | A fixed 10 s interval is simple and light on the API; a typical document needs one to three polls. Stopping on a final status and pausing in the background keep idle pages from polling at all, and are free with D2. |
| D4 | **Upload: several files at once (user's choice), then go to the Documents list.** The user drops or picks up to **5 files** (user's choice); each is checked (D5) and listed in an **upload queue** with its own state (queued → uploading → uploaded / rejected, with the reason). Valid files are sent as **separate `POST /documents` requests, two at a time** (the API takes one file per request). When every file is done: **all uploaded → go to `/documents`**, where the new rows show *processing* and update by polling (D3); **any rejected → stay on the Upload page** showing which files failed and why, with a "Go to documents" button and "Remove" / "Try again" per failed file. A single dropped file follows the same flow. | Several files is the realistic case (a month of receipts). Separate requests reuse the existing API unchanged and let one bad file fail alone. Two at a time keeps uploads quick without flooding the backend's background workers. Staying on the page when something failed means no error is lost by navigating away. |
| D5 | **Upload limits come from the backend (user's choice): new `GET /api/config`** (D16) returns `{max_upload_mb, accepted_content_types}` (and `base_currency` for labels). The UI loads it once and caches it for the session. **Client-side checks before sending:** type by extension **and** browser MIME against `accepted_content_types` (`.pdf`, `.jpg`, `.jpeg`, `.png`), size **≤ `max_upload_mb`**, empty files refused. If `/api/config` cannot be loaded, the UI falls back to 10 MB and the three types and says nothing (the server still checks). The server stays the authority: its 415 / 413 / 422 answers are shown per file. | One source of truth: changing `MAX_UPLOAD_MB` in `.env` changes the UI's limit and message with no rebuild. The fallback keeps upload working if the call fails; the server sniffs magic bytes and enforces the limit itself, so a stale client can never be unsafe. |
| D6 | **Documents list:** columns **File** (name, plus `v2`, `v3`… when `version > 1`), **Type** (PDF / JPG / PNG), **Size** (KB / MB), **Status** (badge), **Uploaded** (`DD-MM-YYYY HH:mm`, local time); a failed row shows its error under the name, shortened. The whole row links to the detail page. **Status filter** as tabs: All / Processing / Completed / Failed (server-side `status=`). **Pagination: Previous / Next** with "21–40 of 57", 20 per page (the API's `limit`/`offset`/`total`); the page and filter live in the URL (`?status=failed&page=2`). | Shows everything the API returns that a user cares about. Previous/Next maps directly onto `limit`/`offset` and survives a reload because it is in the URL; "load more" would lose the position on reload. |
| D7 | **Detail layout: one page with sections, most important first** (no tabs): (1) header — file name, status badge, uploaded time, **Reprocess** button; (2) **summary** with the validation status (passed / passed with warnings / failed) and issue counts; (3) **structured data** — vendor, customer, invoice number, dates, payment terms, tax ID, currency, subtotal / tax / total; (4) **line items** table; (5) **validation issues** list; (6) **conversion** card (only when present); (7) **raw text** and (8) **agent steps**, both collapsed by default. Raw text is fetched only when its section is opened. Empty values show "—" (never invented). | A reviewer sees the answer (summary + status) without clicking, and can scroll for detail. Collapsing the long, technical sections keeps the page short; lazy-loading raw text avoids a large download nobody asked for. |
| D8 | **Issues are shown in both places:** the issues list (severity icon + label, message, and **"Expected X · Found Y"** when both are set, formatted as money) **and** on the data itself — a field with an issue gets a severity-coloured outline and icon; a line item with an issue (`line_items[2].amount`) gets its **row tinted and the cell outlined**; an issue on `line_items` as a whole marks the table heading. Clicking an issue scrolls to and briefly highlights its field. Severity order: error, warning, info; colour is never the only signal (icon + text too). | The field paths from 0004 (`line_items[2].amount`, 0-based) map directly onto the page, so the user sees *where* the problem is, not just a list. Showing expected/found in the list keeps the numbers readable on phones where outlines are small. |
| D9 | **Formatting (pure functions, no float maths):** money is formatted **from the decimal string** — thousands separators, padded to the currency's minor units (from `Intl.NumberFormat(...).resolvedOptions()`, e.g. MYR 2, JPY 0, KWD 3), extra printed precision **kept, never rounded** (unit price `12.3456` stays), shown as `MYR 1,234.50`; no currency → number only. Quantities are shown as printed. **Dates** `YYYY-MM-DD` → `DD-MM-YYYY` by splitting the string (no `Date` parsing, so no time-zone shift); **timestamps** (`created_at`, step `started_at`) → `DD-MM-YYYY HH:mm` in the browser's local time. | Decimal strings exist so money stays exact; converting to `Number` would reintroduce float errors. Intl knows every currency's minor units, so no table is duplicated in the frontend. `DD-MM-YYYY` is the 0003 D4 rule. |
| D10 | **Agent steps now, as a simple list** from `GET /runs`: for the latest run — trigger (upload / reprocess), status, started / finished, and each step's number, tool name, ok / error badge, duration and error message. Earlier runs are listed collapsed below it. **While processing, the same data is a live progress list** at the top of the page ("1 extract_text ✓ 2 extract_structured_data …"). No tokens, prompts or trace timeline. | `GET /runs` exists (0005 D11) and makes the agent visible to reviewers now; it also gives the processing state real progress instead of a spinner. Tokens and the full trace belong to B1's trace view. |
| D11 | **Reprocess:** a button in the detail header opens a **confirm dialog** ("Reprocess this document? Text and data are extracted again and the result is replaced. This uses OpenAI tokens."). On confirm → `POST /reprocess` → the page switches to the **processing view** (D3 polling + D10 live steps); the old result is hidden until the new one is ready. The button is disabled while processing. `409 already_processing` → an inline note and the page simply starts polling. | A confirm step prevents an accidental, paid re-run. `GET /result` answers 409 while processing, so showing the processing view is honest and matches what the API can return. |
| D12 | **Errors: inline messages, no toasts.** One `ApiError` (already in `client.ts`) carries `status`, `code`, `message`; a small map turns codes into friendly text: `unsupported_media_type`, `payload_too_large`, `validation_failed`, **`llm_not_configured`** ("The server has no OpenAI API key (`OPENAI_API_KEY`), so documents cannot be processed."), `already_processing`, `not_found` (detail page shows "Document not found"), network failure ("Cannot reach the server"). **`409 result_not_ready`** is not an error — it means "still processing" (keep polling). **`409 result_unavailable` / status `failed`** → a red failed panel with the document's `error`, the Reprocess button, and any **partial data that was saved** (from `GET /extraction` and `GET /text`, 0005 D8). Messages sit next to the action that caused them. | Inline messages stay visible and are easy to read with a screen reader; a toast library would be another dependency for little gain. Treating `result_not_ready` as a state, not an error, avoids a flash of red during normal processing. Partial data shows how far processing got. |
| D13 | **Styling: plain Tailwind (v4, already installed) with a few small own components** (Button, Badge, Card, Dialog via the native `<dialog>`), **light + dark themes (user's choice)** that **follow the system setting by default**, with a header toggle (System / Light / Dark) remembered in `localStorage`; no flash of the wrong theme on load. **Responsive down to 375 px** (tables scroll sideways inside their card; the data grid becomes one column). No component library. | Matches the "Tailwind only, no other CSS framework" rule. Following the system is what users expect; the toggle lets a reviewer check both themes without changing their OS. Colours come from semantic tokens (D18) so each component is styled once for both themes. |
| D14 | **Testing: Vitest + Testing Library, `fetch` stubbed with `vi.stubGlobal`** (as the existing `client.test.ts` does) so tests go through the real API client. Tested: the API client functions; formatters (money, dates); the issue-to-field mapping; Upload (checks, keyboard, server errors, navigation); Documents list (filter, pagination, polling stops); Document detail (processing / completed / failed / not found, issue highlighting, partial data); Reprocess (confirm, 409); the polling rules (fake timers). **No Playwright now**; the UI is checked manually in the browser against a running backend before commit. | Stubbing `fetch` exercises the real client and needs no new dependency (MSW would add one for the same coverage at this size). End-to-end tests need the full stack and OpenAI in CI; that is better done in the submission phase if at all. |
| D15 | **Accessibility basics:** the drop zone is a real button-like label for a hidden `<input type="file">` (Enter / Space open the picker; `accept` set); every control has a label; status badges and severities use text + icon, not colour alone; a polite **`aria-live`** region announces status changes ("Processing complete", "Processing failed", upload errors); focus moves to the page heading on navigation; the confirm dialog traps focus and closes on Escape (native `<dialog>`). | The basics that make the app usable by keyboard and screen reader at almost no cost. |
| D16 | **Backend changes: one additive, read-only route** (follows from D5). A small `client_config` module (`router.py`, `service.py`, `schema.py`; no DB) serves **`GET /api/config`** → 200 `ClientConfig {max_upload_mb: int, accepted_content_types: string[], base_currency: string}` from `Settings`; no secrets, no auth. Router + service tests; ruff + pytest. **No CORS:** the browser always talks to one origin (nginx in Docker, the Vite proxy in dev). No other backend change. | Keeps the backend the single source of upload rules (the same list the upload service enforces) without touching 0001–0005 contracts. A separate module keeps it out of `health`, whose job is liveness. |
| D17 | **Scope guard:** B1 trace + token view, B2 confidence badges, B3 Query page, authentication, editing and deleting documents stay out of 0006. **The multi-agent view is in (user's choice, D19).** The detail page's sections are separate components so B1/B2 can add a trace section and confidence badges later without a redesign. | Keeps 0006 to the brief's UI and avoids building screens for APIs that do not exist yet. |
| D19 | **Multi-agent view (user's choice), built on today's API.** The D10 step list is shown as an **"Agent activity" section with three lanes in order — Extraction Agent → Validation Agent → Reporting Agent** — matching the Agent Design table in `CLAUDE.project.md`. Each tool step goes into its role's lane through one mapping function (`extract_text`, `extract_structured_data` → Extraction; `validate_invoice`, `convert_currency` → Validation; `generate_summary` → Reporting; unknown tools → an "Other" lane). Each lane shows its status (waiting / running / done / failed), its steps (tool, ok / error, duration, error message) and its total time; arrows connect the lanes. A header line states the run's **`mode`**: today always "Single mode — the Document Agent played all three roles" (0005 D13); after B4 the same view shows the real agents. **While processing**, the lanes are the live progress view (the current lane is highlighted). Earlier runs are listed collapsed below. No backend change: the lanes come from `GET /runs` (`mode`, `steps`). | The user wants the agent's structure visible now. The three roles already exist as groups of tools, so the view is honest today and needs only the mapping function updated (or replaced by a per-step agent field) when B4 ships. Lanes also make a better progress display than a flat list. |
| D18 | **Production-ready UI/UX bar (user's requirement):** (a) **design tokens** — one accent colour, a neutral grey scale and semantic colours (success / warning / danger / info) defined once as Tailwind theme variables for both themes; one type scale, spacing scale and radius; (b) **icons** from **`lucide-react`** (new dependency, tree-shaken; only the icons used are bundled); (c) **states everywhere** — skeleton loaders (no layout jump), helpful **empty states** with a call to action ("No documents yet — upload your first invoice"), inline error states with a retry; (d) **interaction polish** — visible focus rings, hover and pressed states, disabled states with a reason, a drag-over highlight on the drop zone, file-type icons, copy-to-clipboard for raw text and IDs, relative time on hover ("3 min ago") next to `DD-MM-YYYY HH:mm`; (e) **page titles** per route (`Invoice-123.pdf · Document Intelligence`) and a favicon; (f) **font: Poppins (user's choice), self-hosted** with **`@fontsource/poppins`** (new dependency; weights 400 / 500 / 600 / 700, Latin subset, bundled by Vite — no request to Google Fonts, works offline in Docker), `font-display: swap` with the system font as fallback; money and number columns use `tabular-nums` so digits line up; raw text uses the system monospace font; (g) **visual check before commit** at desktop and 375 px, in light and dark. | "It must look good and be usable" needs a stated bar, or it gets judged by taste at the end. Tokens make both themes consistent; skeletons, empty states and focus states are what separate a product from a demo. lucide-react gives clean, consistent icons without hand-drawing SVGs. Self-hosting Poppins keeps the look the user chose without a third-party request or an internet dependency at runtime. |

## Constraints

- TypeScript `strict`; no `any` in the API client; types mirror the backend DTOs
  (`DocumentRead`, `DocumentList`, `DocumentUploadResponse`, `DocumentTextResponse`,
  `ExtractionResponse`, `InvoiceData`, `LineItem`, `ValidationReport`, `ValidationIssue`,
  `ConversionResult`, `AgentResult`, `AgentRunRead`, `ToolStep`, the error body).
- **One API client** in `frontend/src/api/`; every request goes through `request()`;
  components never call `fetch`.
- Money stays a **string** end to end in the frontend; no `Number()` / `parseFloat` on money.
- Dates in data and API are ISO; the UI shows `DD-MM-YYYY` (0003 D4).
- Tailwind utility classes only; no other CSS framework or component library.
- All API calls use relative `/api/...` URLs (the existing `VITE_API_BASE` override stays),
  so the same build works behind nginx and the Vite proxy.
- New runtime dependencies only as agreed (`react-router` D1, `@tanstack/react-query` D2,
  `lucide-react` and `@fontsource/poppins` D18); versions pinned in `package-lock.json`.
- The backend route (D16) follows the module anatomy and layering rules, is additive and
  read-only, exposes no secrets, and passes `ruff check`, `ruff format --check`, `pytest`.
- `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build` pass; CI green.
- The Docker image (`frontend/Dockerfile`, `nginx.conf`) keeps working; nginx's
  `client_max_body_size 25m` stays above the 10 MB limit.

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | `/`, `/documents`, `/documents/:id` render the Upload, list and detail pages; an unknown path shows "not found"; a reload on a detail URL works in Docker (nginx fallback) and in dev | test + manual check |
| 2 | Dropping or picking a non-PDF/JPEG/PNG, a file over `max_upload_mb` or an empty file marks that file rejected in the queue with the reason and sends no request for it; more than 5 files is refused with a message | component test |
| 3 | Several valid files are each posted as multipart field `file`, at most two at a time, each with its own state; all accepted → navigate to `/documents`; any rejected (client or 415 / 413 / 422 / 502 `llm_not_configured` / network) → stay, show the friendly reason per file, offer "Go to documents" and "Try again" | component test |
| 3a | `GET /api/config` returns `{max_upload_mb, accepted_content_types, base_currency}` from settings; the UI uses it for its checks and messages, and falls back to 10 MB + PDF/JPEG/PNG when it fails | backend router test + component test |
| 4 | The drop zone works by keyboard (Enter / Space open the picker) and upload errors and status changes are announced via `aria-live` | component test |
| 5 | The list shows File (with version), Type, Size, Status badge, Uploaded (`DD-MM-YYYY HH:mm`); the status filter and Previous/Next pagination send the right `status`/`limit`/`offset` and are kept in the URL | component test |
| 6 | The list polls every 10 s only while a row on the page is `processing` and stops when none is | test (fake timers) |
| 7 | The detail page polls every 10 s while `processing`, pauses while the tab is hidden, stops on `completed`/`failed`, then loads `/result` once; a `409 result_not_ready` is never shown as an error | test (fake timers) |
| 8 | A completed document shows summary, validation status and counts, structured data, line items, issues, conversion (when present), collapsed raw text (fetched on open) and agent steps | component test + manual check |
| 9 | Each issue shows severity (icon + text), message and "Expected · Found" when set; its field or line-item row/cell is highlighted; clicking the issue scrolls to it | component test |
| 10 | Money is formatted from the decimal string with separators and currency minor units (MYR `1234.5` → `1,234.50`, JPY `1200` → `1,200`, unit price `12.3456` kept); no float conversion; dates `2025-03-04` → `04-03-2025` | unit test |
| 11 | A failed document shows the error, the Reprocess button and any partial structured data / raw text that exists | component test |
| 12 | Reprocess asks for confirmation; on confirm it posts, switches to the processing view and polls; `409 already_processing` shows a note and polls | component test |
| 13 | While processing, the agent's steps appear live from `GET /runs`; after completion the latest run's steps are listed with tool, status, duration and error; earlier runs are collapsed | component test |
| 13a | The Agent activity section shows Extraction → Validation → Reporting lanes with each step in its lane (unknown tools in "Other"), each lane's status and total time, and the run's mode ("Single mode — the Document Agent played all three roles"); the running lane is highlighted while processing | unit test (mapping) + component test |
| 14 | The layout works at 375 px wide with no page-level horizontal scroll | manual check |
| 14a | Light and dark themes: follow the system by default; the header toggle (System / Light / Dark) switches and is remembered; no flash of the wrong theme on reload; text and badges stay readable (WCAG AA contrast) in both | test (toggle) + manual check |
| 14b | Every data view has a skeleton while loading, an empty state with a call to action, and an error state with a retry; focus rings are visible on every control | component test + manual check |
| 15 | Upload (several files) → processing → completed works end to end in the browser against a running backend (Docker or dev), checked at desktop and 375 px in both themes | manual check |
| 16 | `npm run lint`, `typecheck`, `test`, `build` pass; backend `ruff check`, `ruff format --check`, `pytest` pass; CI green | CI run |

## Roadmap Phase

**Phase:** Phase 2 — User Interface. Shipping 0006 meets the phase's graduation criterion
(upload, status and results — data, validation, summary — usable in the browser).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0006-frontend-plan.md` | Plan | Implementation path (written after this PRD is final) |
| `docs/prd/0000-setup-prd.md` | Intent | Frontend skeleton, nginx and Vite proxies this builds on |
| `docs/prd/0001-documents-prd.md` | Intent | Upload, list and status API |
| `docs/prd/0003-structured-extraction-prd.md` | Intent | `InvoiceData` shape; D4 date display rule |
| `docs/prd/0004-validation-prd.md` | Intent | Issue field paths, severities, expected/actual |
| `docs/prd/0005-agent-prd.md` | Intent | `/result`, `/runs`, `/reprocess`, partial data on failure |
| `docs/reference/folder-structure.md` | Reference | Routes and schemas (the API contract) |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this PRD |

## Open Questions

None — D1–D19 agreed with the user on 2026-10-27 (react-router; TanStack Query; fixed 10 s
polling that stops on a final status and pauses in a hidden tab; up to 5 files per upload,
then the list; limits from `GET /api/config`; paged, filterable list; one-page detail with
summary first; issues highlighted on fields and rows; money formatted from strings; agent
steps shown as a three-lane multi-agent view; confirmed reprocess; inline errors; light +
dark with a toggle; `fetch` stubbed in tests, no Playwright; accessibility basics; one
backend route; B1–B3, login, edit and delete out of scope; production-ready UI/UX with
Poppins and lucide icons).
