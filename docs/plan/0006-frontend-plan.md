# 0006 Frontend Implementation Plan

> **Type:** Plan | **Must stay current:** No -- record divergences in decision log, rewrite only during re-planning

<!-- AI Context
Role: This document describes *how* to build the feature, not *what* or *why*.
Read the corresponding PRD first for intent and constraints, then use this plan
to guide implementation order, component boundaries, and technical decisions.
Do not rewrite this document during coding. If the implementation diverges from
this plan, add an entry to the decision log instead. Only rewrite during a
deliberate re-planning session.
-->

## Overview

Replace the 0000 skeleton page with a three-page React app (Upload, Documents list, Document
detail) on `react-router` and TanStack Query, styled with Tailwind v4 design tokens (light +
dark, Poppins, lucide icons). All HTTP goes through the existing typed client in
`frontend/src/api/`, extended with every route the UI uses and types that mirror the backend
DTOs. One small backend module, `client_config`, adds `GET /api/config` for the upload limits
(PRD D5, D16). No other backend change; nginx and the Vite proxy stay as they are.

## Technical Approach

### Folder layout (`frontend/src/`)

```text
src/
├── main.tsx                    # fonts, QueryClientProvider, RouterProvider, ThemeProvider
├── App.tsx                     # route table (createBrowserRouter)
├── index.css                   # Tailwind import, dark variant, design tokens (@theme)
├── api/
│   ├── client.ts               # request(), ApiError, one function per endpoint
│   ├── types.ts                # DTO types mirroring the backend schemas
│   └── queries.ts              # query keys + hooks (useDocuments, useDocument, useResult, …) + mutations
├── lib/
│   ├── format.ts               # money, numbers, dates, timestamps, bytes, relative time
│   ├── issues.ts               # validation field path → field / line-item / table index
│   ├── agents.ts               # tool → agent role, lane status (multi-agent view)
│   ├── upload.ts               # client-side file checks
│   ├── errors.ts               # ApiError code → friendly message
│   └── theme.ts                # theme preference read/write/apply
├── components/
│   ├── ui/                     # Button, Badge, Card, Dialog, Skeleton, EmptyState, ErrorState,
│   │                           # CopyButton, Tabs, Pagination, Field, LiveRegion
│   ├── layout/                 # AppLayout (header, nav, ThemeToggle, HealthBadge, <main>)
│   ├── StatusBadge.tsx         # processing / completed / failed
│   └── HealthBadge.tsx         # existing; restyled to the tokens
├── features/
│   ├── upload/                 # UploadPage, DropZone, UploadQueue, useUploadQueue
│   ├── documents/              # DocumentsPage, DocumentsTable (table ≥ sm, cards < sm)
│   └── detail/                 # DocumentDetailPage, DetailHeader, SummaryCard, StructuredData,
│                               # LineItemsTable, IssuesList, ConversionCard, RawTextSection,
│                               # AgentActivity, RunHistory, ReprocessDialog, FailedPanel
├── pages/NotFoundPage.tsx
└── test/                       # setup.ts (+ dialog polyfill), render.tsx, fetchMock.ts, fixtures.ts
```

Each test sits next to its file (`*.test.ts(x)`), as in 0000.

### Routing (PRD D1)

`createBrowserRouter` with one layout route (`AppLayout`) and children `/` → `UploadPage`,
`/documents` → `DocumentsPage`, `/documents/:id` → `DocumentDetailPage`, `*` →
`NotFoundPage`. Each page sets `document.title` with a small `useDocumentTitle` hook (D18e).
On a route change (not the first render) `AppLayout` moves focus to the page's `<h1
tabIndex={-1}>` (D15). nginx's `try_files $uri /index.html` already serves deep links.

### API client and types (constraints, D2)

- `types.ts` mirrors `docs/reference/folder-structure.md`: `DocumentStatus`, `DocumentRead`,
  `DocumentList`, `DocumentUploadResponse`, `DocumentTextResponse`, `ExtractionResponse`,
  `InvoiceData`, `LineItem`, `Severity`, `ValidationStatus`, `ValidationIssue`,
  `ValidationReport`, `ConversionResult`, `AgentResult`, `AgentMode`, `RunTrigger`,
  `RunStatus`, `ToolStep`, `AgentRunRead`, `ClientConfig`. Money / quantity / dates /
  timestamps are `string` (decimal strings, ISO dates); IDs are `string`.
- `client.ts` keeps `request<T>()` and `ApiError` and adds: `getConfig()`,
  `uploadDocument(file)` (`FormData` field `file`; no `Content-Type` header so the browser
  sets the boundary), `listDocuments({limit, offset, status})`, `getDocument(id)`,
  `getResult(id)`, `getExtraction(id)`, `getText(id)`, `getRuns(id)`,
  `reprocessDocument(id)`. A network failure (`fetch` rejects) becomes
  `ApiError(0, "network_error", …)` so every caller handles one error type.
- No runtime validation of response bodies (types are trusted, as 0000's client does), except
  where a status code carries data (health 503, already handled).

### Data fetching and polling (D2, D3)

- One `QueryClient`: `retry` up to 3 with exponential backoff **only for network / 5xx**
  (never 4xx), `refetchOnWindowFocus: true`, `refetchIntervalInBackground: false`.
- `POLL_INTERVAL_MS = 10_000` in `api/queries.ts`.
- `useDocument(id)`: `refetchInterval: q => q.state.data?.status === "processing" ?
  POLL_INTERVAL_MS : false`. TanStack Query does not run intervals while the tab is hidden
  and refetches on visibility return, which gives "pause when hidden" (D3).
- `useRuns(id, {live})`: polls at the same interval while the document is processing.
- `useResult(id)`: `enabled` only when the document is `completed`; `staleTime: Infinity`.
- Detail page effect: when the document's status changes from `processing` to a final
  status, invalidate `runs` and `result` once (final step list + result).
- `useDocuments({status, page})`: `refetchInterval` set only while an item on the page is
  `processing`.
- `useClientConfig()`: `staleTime: Infinity`, `retry: 1`; on error the hook returns
  `DEFAULT_CONFIG` (10 MB, PDF/JPEG/PNG) silently (D5).
- `useText(id, {enabled})` / `useExtraction(id, {enabled})`: a 409 means "nothing saved" and
  resolves to `null` instead of an error (used for raw text and failed-state partial data).
- Mutations: `useUploadDocument`, `useReprocess` (on success: set the cached document to
  `processing`, remove the cached result, invalidate runs and the list).
- "Reconnecting…": a query with data whose latest refetch failed with `network_error` shows a
  small note in the page header; it never changes the displayed status.

### Upload (D4, D5)

- `lib/upload.ts`: `checkFile(file, config)` → `null | {code, message}` for empty file, type
  (extension **and** `file.type`, matched against `accepted_content_types`), size
  (`> max_upload_mb`). `MAX_FILES = 5`.
- `useUploadQueue()`: a reducer holding items `{id, file, state: queued | uploading |
  uploaded | rejected, error?, documentId?}`. `add(files)` refuses the whole drop when the
  queue would exceed 5 (message, nothing added), checks each file, queues valid ones and marks
  invalid ones `rejected`. A runner uploads queued items **two at a time**. `retry(id)`
  re-queues a rejected item that passed the client checks; `remove(id)`; `clear()`.
- `UploadPage`: `DropZone` (a `<label>` wrapping a visually hidden `<input type="file"
  multiple accept=…>`; `Enter` / `Space` open the picker; drag-over highlight; shows "PDF, JPG
  or PNG · up to N MB · max 5 files" from config) and `UploadQueue` (file-type icon, name,
  size, state badge, per-file error, Remove / Try again). Upload button disabled until there
  is a queued file. When the batch ends with every item `uploaded` → invalidate the list and
  `navigate("/documents")`; any `rejected` → stay, with "Go to documents" if anything
  uploaded. Status changes are announced in the live region (D15).

### Documents list (D6)

- URL state with `useSearchParams`: `status` (`all` when absent) and `page` (1-based);
  `offset = (page - 1) * 20`. Invalid values fall back to defaults.
- Status `Tabs` (All / Processing / Completed / Failed) with `role="tablist"`, arrow-key
  navigation; changing the filter resets `page`.
- ≥ `sm`: a table (File + version chip + shortened error for failed rows, Type, Size,
  Status, Uploaded with relative time in `title`); < `sm`: stacked cards with the same data.
  Each row is a real link (`<Link>` covering the row) to `/documents/:id`.
- `Pagination`: "21–40 of 57", Previous / Next disabled at the ends.
- Skeleton rows while loading; empty state per filter ("No documents yet" → Upload button;
  "No failed documents" → plain message); error state with Retry.

### Document detail (D7–D12, D19)

`DocumentDetailPage` loads `useDocument(id)` and picks one view:

| State | View |
|---|---|
| loading | header + card skeletons |
| `404 not_found` / 422 | "Document not found" empty state with a link to the list |
| `processing` | header (Reprocess disabled) + **AgentActivity live** + "Checking every 10 s" note |
| `completed` | header + SummaryCard + StructuredData + LineItemsTable + IssuesList + ConversionCard + RawTextSection (collapsed) + AgentActivity + RunHistory (collapsed) |
| `failed` | header + **FailedPanel** (error, Reprocess) + partial StructuredData / LineItemsTable from `useExtraction` and RawTextSection from `useText` when they exist + AgentActivity |

- **SummaryCard:** validation status pill (passed / passed with warnings / failed, icon +
  text), counts per severity, summary paragraph, document type, file name.
- **StructuredData:** a `Field` grid (1 column < `sm`, 2 at `md`, 3 at `lg`): vendor,
  vendor address, tax ID, customer, customer address, invoice number, invoice date, due date,
  payment terms, currency, subtotal, tax, total (emphasised). `null` → "—".
- **Issue mapping (`lib/issues.ts`, D8):** `parseIssuePath("line_items[2].amount")` →
  `{kind: "line", index: 2, column: "amount"}`; `"line_items"` → `{kind: "table"}`; anything
  else → `{kind: "field", name}`. `indexIssues(issues)` returns lookups by field, by line
  index (+ column) and the worst severity of each. `Field`, table cells and rows read it to
  add the severity outline / row tint / icon. Each target gets a stable `id`
  (`issue-target-line_items-2-amount`). Clicking an issue calls `scrollIntoView({block:
  "center"})` and sets a 1.5 s highlight class.
- **IssuesList:** sorted error → warning → info; icon + label + message; "Expected X · Found
  Y" when both are set (money-formatted with the document currency); "No issues found" empty
  state when the report passes.
- **ConversionCard:** original → converted amount, rate (as sent), rate date (DD-MM-YYYY),
  source.
- **RawTextSection:** `<details>`; first open enables `useText`; monospace, preserved line
  breaks, scrollable, CopyButton; method and page count shown.
- **AgentActivity (D10, D19):** from the latest run of `useRuns`. `lib/agents.ts`:
  `ROLE_OF_TOOL` (`extract_text`, `extract_structured_data` → `extraction`;
  `validate_invoice`, `convert_currency` → `validation`; `generate_summary` → `reporting`;
  else `other`), `buildLanes(run)` → lanes in order Extraction → Validation → Reporting (+
  Other only when used), each `{role, steps, status: waiting | running | done | failed,
  totalMs}`. Lane status rules: `running` = run is `running` and the lane holds the latest
  step (Extraction when there are no steps); `failed` = run is `failed` and the lane holds
  the latest step; `done` = the lane has an `ok` step and is not running / failed; else
  `waiting`. A recoverable step error (`status: error` in a run that continued) shows on the
  step only. Layout: three cards in a row with arrow connectors at `md+`, stacked with down
  arrows below `md`. Header: run mode text ("Single mode — the Document Agent played all
  three roles" for `single`; "Multi-agent mode" for `multi`), trigger, started time,
  duration.
- **RunHistory:** earlier runs (newest first) as collapsed rows: trigger, status, started,
  duration, error; expanding shows that run's `AgentActivity`.
- **Reprocess (D11):** `ReprocessDialog` on the native `<dialog>` (`showModal()`, Escape
  closes, focus returns to the button). Confirm → `useReprocess`; `409 already_processing` →
  inline note, cached document set to `processing`, polling starts; other errors inline in
  the dialog.

### Formatting (`lib/format.ts`, D9)

- `formatMoney(value: string | null, currency: string | null)`: `null` → "—"; a string not
  matching `^-?\d+(\.\d+)?$` is shown as-is; otherwise split sign / integer / fraction, group
  the integer with commas, pad the fraction to the currency's minor units
  (`new Intl.NumberFormat("en", {style: "currency", currency}).resolvedOptions()
  .maximumFractionDigits`, cached; 2 when the currency is null or unknown), never shorten a
  longer fraction; prefix `"MYR "`. No `Number()` / `parseFloat` anywhere on money.
- `formatQuantity(value)`: grouping only, fraction kept as printed.
- `formatDate("2025-03-04")` → `"04-03-2025"` by string split; anything else as-is.
- `formatTimestamp(iso)` → `DD-MM-YYYY HH:mm` local time; `formatRelative(iso, now)` via
  `Intl.RelativeTimeFormat`; `formatBytes(n)` → `"842 KB"`, `"2.4 MB"`;
  `formatDuration(ms)` → `"850 ms"`, `"3.2 s"`.

### Errors (`lib/errors.ts`, D12)

`friendlyError(error)` → `{title, message}` keyed by `ApiError.code`:
`unsupported_media_type`, `payload_too_large`, `validation_failed`, `llm_not_configured`,
`already_processing`, `not_found`, `network_error`, `internal_error`, fallback (the server's
own message). `result_not_ready` is never shown (queries treat it as "still processing").
Messages render inline (`ErrorState` / per-file / in-dialog) with `role="alert"` for
action errors.

### Design system (D13, D18)

- `index.css`: `@import "tailwindcss";` and `@custom-variant dark (&:where(.dark, .dark
  *));`. Colour tokens are CSS variables on `:root` and `.dark` (`--bg`, `--surface`,
  `--surface-muted`, `--border`, `--text`, `--text-muted`, `--accent`, `--accent-fg`,
  `--success`, `--warning`, `--danger`, `--info` + their soft backgrounds), exposed to
  Tailwind with `@theme inline` (`--color-surface: var(--surface)`, …), so components use
  `bg-surface text-text-muted` once and both themes follow. Accent: indigo; neutrals: slate.
  Contrast checked against WCAG AA in both themes.
- Font: `@fontsource/poppins` 400 / 500 / 600 / 700 (Latin) imported in `main.tsx`;
  `--font-sans: "Poppins", ui-sans-serif, system-ui, …`; `tabular-nums` on money and number
  cells; raw text in `font-mono` (system).
- Theme: `lib/theme.ts` stores `system | light | dark` in `localStorage` (`theme`, wrapped in
  `try/catch`) and toggles `.dark` on `<html>`; a `matchMedia` listener follows the system
  while the preference is `system`. A tiny inline script in `index.html` applies the class
  before first paint (no flash). `ThemeToggle` is a three-option segmented control in the
  header (icons + accessible labels).
- UI primitives in `components/ui/` with variants via a small `cx()` helper (no `clsx`
  dependency): Button (primary / secondary / ghost / danger, sizes, loading), Badge (tones),
  Card, Dialog, Skeleton, EmptyState, ErrorState (+ Retry), CopyButton, Tabs, Pagination,
  Field, LiveRegion (context `useAnnounce()`).
- Icons: `lucide-react` (`FileText`, `FileImage`, `UploadCloud`, `CheckCircle2`,
  `AlertTriangle`, `XCircle`, `Info`, `Loader2`, `RefreshCw`, `Copy`, `Sun`, `Moon`,
  `Monitor`, `ArrowRight`, …), always `aria-hidden` next to text.
- `public/favicon.svg` (document mark in the accent colour), linked from `index.html`.

### Backend: `client_config` module (D5, D16)

`backend/app/modules/client_config/` — `schema.py`, `service.py`, `router.py` (no DB).

```python
class ClientConfig(BaseModel):
    max_upload_mb: int
    accepted_content_types: list[str]   # sorted
    base_currency: str

def get_client_config(settings: Settings) -> ClientConfig  # service; uses documents.service.ALLOWED_CONTENT_TYPES
router = APIRouter(prefix="/config", tags=["config"])      # GET "" → /api/config
```

The router depends on `get_settings` so tests can override it. Added to `ROUTERS` in
`app/main.py`. Importing `documents.service` respects the cross-module rule (service only)
and keeps one list of accepted types.

## System Components

| Component | Responsibility |
|---|---|
| `api/client.ts`, `api/types.ts` | The only HTTP layer; typed endpoint functions; `ApiError` |
| `api/queries.ts` | Query keys, hooks, polling rules, mutations, cache updates |
| `lib/*` | Pure logic: formatting, issue paths, agent lanes, file checks, error text, theme |
| `components/ui/*` | Design-system primitives on the tokens |
| `components/layout/AppLayout` | Header, nav, theme toggle, health badge, live region, focus on navigation |
| `features/upload/*` | Drop zone, queue, two-at-a-time uploads, navigation |
| `features/documents/*` | Filterable, paginated, polling list |
| `features/detail/*` | Detail views per status, issue highlighting, agent activity, reprocess |
| `modules/client_config` (backend) | `GET /api/config` |

## Processing Flow

1. Upload page loads `/api/config` → user drops ≤ 5 files → client checks → queued files are
   posted two at a time → all accepted → `/documents`.
2. List shows the new rows `processing` → polls every 10 s while any visible row is
   processing → rows turn `completed` / `failed`.
3. Detail page while `processing`: polls the document and runs every 10 s; the Agent
   activity lanes fill in → status becomes final → runs and result are fetched once.
4. `completed` → result view; `failed` → error + partial data. Reprocess → confirm → `202` →
   back to step 3.

## Dependencies

| Dependency | Purpose |
|---|---|
| `react-router` (runtime) | Routing (D1) |
| `@tanstack/react-query` (runtime) | Fetching, polling, cache (D2, D3) |
| `lucide-react` (runtime) | Icons (D18) |
| `@fontsource/poppins` (runtime) | Self-hosted Poppins (D18) |
| `@testing-library/user-event` (dev) | Realistic keyboard, click and file-upload events in tests |

Versions: latest stable at install time, pinned by `package-lock.json`. No backend dependency.

## Implementation Phases

### Phase 1: Backend `GET /api/config`
`client_config` module, `ROUTERS` entry, router + service tests. `ruff check`, `ruff format
--check`, `pytest` (DB up).

### Phase 2: Foundation
Dependencies; `index.css` tokens + dark variant; fonts; favicon; theme script + `lib/theme.ts`;
UI primitives; `AppLayout`, router, `QueryClient`; `types.ts`, client functions,
`queries.ts`; `lib/format.ts`, `lib/errors.ts`; test helpers (`render.tsx` with providers +
`MemoryRouter`, `fetchMock.ts` route matcher, `fixtures.ts`). Tests for client, format,
errors, theme toggle.

### Phase 3: Upload page
`lib/upload.ts`, `useUploadQueue`, `DropZone`, `UploadQueue`, `UploadPage`. Tests: checks,
5-file limit, two-at-a-time, server errors per file, navigation, keyboard, live region.

### Phase 4: Documents list
`DocumentsPage`, `DocumentsTable`, `Tabs`, `Pagination`. Tests: URL state, query params,
empty / error states, polling starts and stops (fake timers).

### Phase 5: Document detail
Views per status, `lib/issues.ts`, StructuredData, LineItemsTable, IssuesList,
ConversionCard, RawTextSection, FailedPanel, ReprocessDialog. Tests: each state, issue
highlighting + click-to-scroll, lazy raw text, partial data, reprocess confirm / 409,
polling stop and final fetch.

### Phase 6: Multi-agent view
`lib/agents.ts`, `AgentActivity`, `RunHistory`. Tests: mapping, lane statuses (running,
failed, recoverable error), mode text, live update.

### Phase 7: Polish and browser check
Run the DB, backend and `npm run dev` (Vite proxy); upload real samples; check every page at
desktop and 375 px in light and dark, keyboard-only flow, reload on a detail URL; fix what
looks wrong. Also `docker compose up --build` once to confirm the nginx build and deep links.

### Phase 8: Close-out
`npm run lint / typecheck / test / build`, backend checks; update
`docs/reference/folder-structure.md` (frontend tree, `/api/config` route, `ClientConfig`
schema, dependencies), `ENGINEERING_NOTES.md` (0006 architecture, limitations, production
improvements), `README.md` (using the UI); decision log `0007-frontend-implementation-divergences.md`
for any divergence; roadmap note; commit on `feature/0006-frontend`. No push / merge until
the user confirms.

## Testing Strategy

- **Unit (pure):** `format` (money table: MYR / JPY / KWD / null currency / negative / long
  fraction / non-numeric; dates; timestamps; bytes; durations), `issues` (path parsing,
  index, worst severity), `agents` (mapping, lane status rules), `upload` (type, extension
  vs MIME, size, empty), `errors` (code map, fallback).
- **API client:** `vi.stubGlobal("fetch", …)` as in 0000: query strings, `FormData` upload
  without a `Content-Type` header, 409 → `null` for text / extraction, network failure →
  `network_error`.
- **Components / pages:** Testing Library + user-event, rendered through `render.tsx` (fresh
  `QueryClient` with `retry: false`, `MemoryRouter` at a given URL). `fetchMock.ts` maps
  `METHOD /path` to responses or sequences (e.g. `processing`, `processing`, `completed`) and
  records calls for assertions.
- **Polling:** `vi.useFakeTimers({ shouldAdvanceTime: true })` + `advanceTimersByTimeAsync`;
  `document.visibilityState` stubbed to check the pause.
- **jsdom gaps:** `HTMLDialogElement.showModal/close`, `scrollIntoView`, `matchMedia` are
  polyfilled in `test/setup.ts`.
- **Backend:** `tests/modules/client_config/test_router.py` (200 shape, reflects an
  overridden `MAX_UPLOAD_MB`, sorted types) and `test_service.py`.
- **Manual (Phase 7):** the PRD's manual acceptance criteria (1, 8, 14, 14a, 14b, 15).
- Coverage expectation: every file in `lib/` and every component with logic has tests;
  pure-presentational primitives are covered through the pages.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| No `OPENAI_API_KEY` in the local `.env` | Uploads return 502; the end-to-end browser check cannot reach `completed` | Check before Phase 7; if missing, ask the user to add a key (never typed by me) — the 502 path is still checked |
| Fake timers + TanStack Query flakiness | Polling tests hang or pass by luck | `shouldAdvanceTime`, `advanceTimersByTimeAsync`, `waitFor`; one `QueryClient` per test |
| jsdom has no `<dialog>` modal / `scrollIntoView` | Dialog and click-to-scroll tests fail | Polyfills in `test/setup.ts` |
| Dark-mode contrast on tinted rows and badges | Unreadable text | Tokens with paired soft / strong colours; check AA in Phase 7 |
| Bundle size from icons / font | Slower first load | Named lucide imports (tree-shaken); four Poppins weights, Latin only |
| Large raw text | Slow render | Lazy fetch on open; scrollable box with a max height |
| B4 changes the run shape | Lanes need an update | All grouping lives in `lib/agents.ts` (one function to change) |

## Roadmap Phase

**Phase:** Phase 2 — User Interface.

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0006-frontend-prd.md` | Intent | Product goals and decisions D1–D19 this plan implements |
| `docs/reference/folder-structure.md` | Reference | Routes and schemas the client mirrors; updated in Phase 8 |
| `docs/decisions/0007-frontend-implementation-divergences.md` | Decision log | Divergences from this plan (created if needed) |

## Open Questions

None.
