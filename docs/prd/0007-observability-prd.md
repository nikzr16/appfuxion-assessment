# 0007 Observability PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Make every document's processing visible and measurable: **which LLM calls ran, for what,
on which model, how many tokens they used, what they cost (estimated) and how long each
step took**, plus a few product-wide numbers (documents, success rate, processing time,
tokens). This is the brief's observability bonus (B1: `document_id`, processing time, LLM
tokens). It ships first among the bonus tasks so B2–B4 get traces and token counts for free.

## Goals

- A **token ledger**: one `llm_calls` row per LLM call — vision transcription, structured
  extraction (each attempt), the agent loop (each turn) and the summary (each attempt) — with
  purpose, agent, model, prompt / completion tokens, estimated cost, latency, status,
  `document_id` and `run_id`.
- Recording happens **in one place** (`app/core/llm.py`), so no future LLM call can be missed
  and callers only say *what* the call is for.
- A **trace** per run: the run's timeline of tool steps (already timed in `agent_runs.steps`)
  with the LLM calls inside them, plus document-level timing (upload → run start → finish).
- **JSON logs** that carry `document_id`, `run_id`, `agent` and `purpose` on every line
  written while a document is processed.
- `GET /api/documents/{id}/trace` and `GET /api/metrics/summary`.
- UI: a **Trace** section on the document detail page, token / cost totals per agent lane,
  and a small **Metrics** page.
- Recording **never fails or noticeably slows** a document run.
- Tests use `FakeLLM` (which is recorded exactly like the real client); never OpenAI.

## Non-Goals

- Grounding / hallucination checks, confidence scores, new retry strategies — **B2 (0008)**.
- Table / layout extraction — **B5 (0009)**.
- Embeddings in use, retrieval, the Query Agent — **B3 (0010)** (the ledger already records
  `embed` calls so B3 needs no change here).
- Extraction / Validation / Reporting agents and the Coordinator — **B4 (0011)** (the ledger
  has an `agent` column ready for them).
- External observability stacks (OpenTelemetry exporters, Prometheus, Grafana, Langfuse),
  alerting, dashboards outside the app — production improvements only.
- Storing prompts, model replies or document text (see D3).
- Authentication, per-user metrics, editing or deleting ledger rows.

## Scope

| In Scope | Out of Scope |
|---|---|
| `backend/app/modules/observability/`: router, service, schema, crud, model (+ `pricing.py`) | OpenTelemetry / Prometheus exporters |
| `llm_calls` table + Alembic migration | A generic `trace_events` span table (D2) |
| Recording hook + context vars in `app/core/llm.py` / `app/core/logging.py` | Recording at each call site (D1) |
| Small additive changes: callers set a `purpose` (0002, 0003, 0005), the agent binds `run_id` and the current step | Changing 0002–0005 behaviour or response contracts |
| `GET /api/documents/{id}/trace`, `GET /api/metrics/summary` | Write endpoints, exports (CSV) |
| Trace section, per-lane token chips, `/metrics` page in the frontend | Charts over time (per-day series) |
| Static, dated model price table for estimated USD cost | Live pricing, billing reconciliation |
| Tests with `FakeLLM` on real Postgres; frontend Vitest | Real OpenAI calls in tests |
| README, ENGINEERING_NOTES 0007 sections, folder-structure reference | — |

## User Stories

1. **As a reviewer of the assessment**, I want to open a document and see a timeline of what
   the agent did — each tool, each LLM call inside it, its model, tokens, cost and time — so
   that I can see the agent's real work, not just its result.
2. **As an operator**, I want one page with totals (documents, success rate, average and p95
   processing time, tokens and cost per document, by model and purpose) so that I can see
   whether the system is healthy and what it costs.
3. **As a developer**, I want every log line of a document's processing to carry
   `document_id` and `run_id` so that I can grep one document's story out of the logs.
4. **As the developer of B2–B4**, I want new LLM calls to be recorded automatically, with only
   a `purpose` label to set, so that my feature is observable from day one.

## Product Decisions

> **Status: final.** D1–D14 agreed with the user on 2026-10-27: every decision as
> recommended.

| # | Decision (recommended) | Rationale |
|---|---|---|
| D1 | **Record every call inside `app/core/llm.py`, in one place.** Every `complete` and `embed` call of every `LLMClient` (the OpenAI client **and `FakeLLM`**) produces one record — on success *and* on failure — and hands it to a **recorder hook**. The `observability` module registers the hook at app start (`app/main.py`), the same pattern as 0001's pipeline hook, so `core` never imports a module. Callers do not write ledger rows; they only label the call (D2). With no hook registered (unit tests of other modules) nothing is written. | One place cannot be forgotten by a new caller (B2–B4 get it free), keeps the "every OpenAI call goes through `llm.py`" rule meaningful, and means tests exercise the same path as production. |
| D2 | **Labels come from context vars, set by the callers.** `app/core/logging.py` gains `run_id`, `agent`, `purpose` and `step_index` context vars next to the existing `document_id`, with one small context manager to bind them. **Purposes:** `vision_transcription` (0002), `structured_extraction` (0003), `agent_loop` (0005 runner, one row per turn), `summary` (0005 tool), `embedding` (B3 later). **Agent:** `document` (the Document Agent) today; B4 adds `extraction` / `validation` / `reporting` / `query`. The agent service binds `run_id`; the runner binds `step_index` while a tool runs, so LLM calls made *inside* a tool (vision, extraction, summary) are linked to that step. A call with no purpose is recorded as `unknown` and logged as a warning. | Context vars already carry `document_id` (0000), so this extends a known pattern; callers add one `with` line instead of passing IDs through every function signature. Linking calls to steps is what makes the trace nested and the per-lane totals possible. |
| D3 | **A ledger row stores numbers and labels only — never prompts, replies or document text.** Columns: `id`, `document_id` (FK, cascade, nullable), `run_id` (FK `agent_runs`, cascade, nullable), `step_index` (nullable), `agent`, `purpose`, `kind` (`chat \| embedding`), `model`, `prompt_version` (nullable), `prompt_tokens`, `completion_tokens`, `cost_usd` (nullable, D4), `latency_ms`, `status` (`ok \| error`), `error_code` (nullable), `started_at`. **Failed calls are rows too** (`status = error`, the error code, latency; tokens `0` because the API returns no usage on failure — documented). A structured reply rejected by validation is an `error` row with `invalid_llm_output`. | Invoices are financial documents: keeping their text out of a second table means the ledger can be kept longer and shown to anyone who sees the trace. Counts and timings answer the brief's question (tokens, time) and the 0003 / 0005 limitations ("rejected replies are invisible", "a call that raised is not counted"). |
| D4 | **Estimated cost in USD from a static, dated price table** (`observability/pricing.py`, USD per 1M input / output tokens for the models we use, e.g. `gpt-4.1-mini`, `text-embedding-3-small`; dated on the day it is written and checked against OpenAI's pricing page). `cost_usd` is **computed when the row is written** and stored (`NUMERIC(12,6)`); an unknown model → `null`, shown as "—". Cached-input discounts and the Batch API are ignored. | Cost is what a business asks about first; tokens alone mean little to a reader. Same honest pattern as 0004's dated currency table. Storing at write time keeps old rows at the price that applied then. |
| D5 | **Recording is isolated from the run.** The hook writes each row in its **own short DB session and transaction** (never the run's session, never held across an LLM call); any recording error is **caught, logged as a warning and dropped** — the LLM call's result or error is returned exactly as before. Writing is synchronous (one small insert, a few ms) so a live trace shows calls as they happen. | The document run must not fail because observability failed. A separate session also means a rolled-back run (0005 rolls back on failure) keeps its ledger rows — which is exactly when you want them. |
| D6 | **`GET /api/documents/{id}/trace[?run_id=]` — the latest run by default, as a flat timeline.** Response: `document_id`; **document timing** (`uploaded_at`, run `started_at` / `finished_at`, `queue_ms` = upload → run start, `processing_ms` = run duration); the **run** (`run_id`, mode, trigger, status, error); **totals** (LLM calls, prompt / completion / total tokens, cost, and the same per `purpose` and per `agent`); and **`spans`**, ordered by start: `tool` spans from `agent_runs.steps` and `llm` spans from the ledger, each with `offset_ms` from the run start, `duration_ms`, `status`, and for `llm` spans the step they belong to (`step_index`, `null` for agent-loop turns). `run_id` picks an older run (404 if it is not this document's). Unknown document → 404; non-UUID → 422. A run from before 0007 returns its tool spans and run-level tokens with `llm_calls_recorded: false`. | A flat, ordered list with offsets is what a waterfall timeline draws directly, and the step link gives nesting without a recursive schema. Earlier runs stay reachable through `GET /runs` (0005) + `run_id`. |
| D7 | **`GET /api/metrics/summary[?days=N]` — all time by default, computed live, no cache.** Numbers: documents total and by status; **success rate** (completed ÷ finished); runs total and failed; **processing time avg, p50, p95** (completed runs' duration); LLM calls total and **error rate**; tokens total and **average per completed document**; **estimated cost total and per document**; breakdowns **by model** and **by purpose** (calls, tokens, cost, avg latency). `days` (1–365) limits everything to rows started in that window; the response states the window and when it was generated. | These are the numbers the brief names (processing time, tokens) plus the two an operator checks first (success rate, cost). One SQL pass per group is cheap at assessment scale; a cache would only add staleness. |
| D8 | **No backfill.** Per-call data for documents processed before 0007 does not exist and cannot be rebuilt; their runs keep the run-level token totals from 0005. The trace shows their tool steps with a "token detail not recorded for this run" note; metrics count only ledger rows for tokens / cost (the response says so). | Inventing per-call rows from run totals would be fake data. Reprocessing an old document gives it a full trace. |
| D9 | **Logging.** The JSON formatter adds `run_id`, `agent`, `purpose` (and `step_index`) whenever they are bound, next to `document_id`. Each LLM call logs **one** line, `llm.call`, with the ledger fields (`model`, `purpose`, tokens, `cost_usd`, `latency_ms`, `status`) — **INFO** on success, **ERROR** on failure (it replaces today's `llm.complete` / `llm.embed` lines). A dropped ledger write logs **WARNING** `llm.call not recorded`. Prompts, replies and document text are never logged (unchanged). | One line per call with the same fields as the ledger makes logs and database tell the same story; levels follow what needs attention. |
| D10 | **UI — Trace section on the detail page, as a waterfall timeline.** A new "Trace" card below Agent activity: a **totals strip** (processing time, queue time, LLM calls, tokens, est. cost) and a **timeline**: one row per tool step with a bar on a shared time axis, its LLM calls nested under it (purpose, model, tokens, cost, latency, ok / error), agent-loop turns as their own rows. On phones (< 640 px) the bars stack into a list with durations. A run picker reuses the run list. Live while processing (same 10 s polling as 0006). | A waterfall is the standard way to read a trace (where did the time go?) and what reviewers expect; the list fallback keeps it usable at 375 px. |
| D11 | **UI — tokens per agent lane.** Each lane in the 0006 multi-agent view gets a small chip with its tokens and est. cost (LLM calls linked to the lane's steps: vision + structured extraction → Extraction, summary → Reporting). Agent-loop turns (the Document Agent deciding which tool to call) are shown once in the Agent activity header ("planning: N turns · X tokens"), not in a lane, until B4 gives each lane its own agent. | Answers "which agent cost what" in the view people already look at, without pretending the single agent's planning belongs to one lane. |
| D12 | **UI — a small `/metrics` page now.** Linked in the header nav: KPI tiles (documents, success rate, avg / p95 processing time, tokens per document, cost per document), tables by model and by purpose, and a window switch (7 days / 30 days / all time). No time-series charts. Production-ready UI/UX (light + dark, 375 px), same design system as 0006. | Makes B1 visible at a glance for a reviewer and costs little on top of D7. Charts over time need per-day queries and a chart library — not worth it at this scale. |
| D13 | **Growth and indexes: keep rows as long as their document; no retention job.** Rows are deleted only by the FK cascade with their document / run. Indexes: `(document_id, started_at)`, `(run_id)`, `(started_at)` for windowed metrics. ~5–10 rows per document is tiny at assessment scale; a retention / roll-up job is a production improvement. | Keeps the feature small and the data complete; the indexes cover every query D6 / D7 need. |
| D14 | **Scope guard confirmed:** B2 (grounding, confidence, retries), B3 (retrieval, Query Agent), B4 (multi-agent, Coordinator), B5 (vision tables / layout) and authentication stay out of 0007. 0007 only adds labels to existing calls; it does not change what any call does. | Keeps 0007 to the brief's observability bonus. |

## Constraints

- Layering: router → service → crud → model; `service.py` never imports FastAPI.
- `app/core/` never imports a module: the recorder is a hook that `observability` registers
  at app start (as `documents.pipeline` does).
- Cross-module: `observability` reads `documents` and `agent` data only through their
  `service` / `schema` (never their `crud` / `model`); the `llm_calls` FKs use string
  references (`"documents.id"`, `"agent_runs.id"`), as `agent_runs` does.
- All OpenAI access still goes through `app/core/llm.py`; recording must not change any
  return value, exception or retry behaviour of the client.
- Recording opens its own session; no transaction is held open across an LLM call.
- No prompts, replies or document text in the ledger or in logs.
- UUID v4 primary keys; timezone-aware timestamps; money / cost as `Decimal`.
- Error responses use the shared `{error: {code, message}}` shape; routes live under `/api`.
- Frontend: one typed API client, TanStack Query, Tailwind, light + dark, works at 375 px.

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | A scripted happy path (FakeLLM) writes one `llm_calls` row per LLM call — agent-loop turns, structured extraction, summary (and vision for a scanned file) — each with the right `document_id`, `run_id`, `agent`, `purpose`, `model`, tokens, `latency_ms`, `status = ok` | service test |
| 2 | LLM calls made inside a tool carry that tool's `step_index`; agent-loop turns have none | service test |
| 3 | A failing call (`LLMError`) and a rejected structured reply (`LLMOutputError`) each write an `error` row with its code; the caller sees the same exception as before | core + service tests |
| 4 | If writing the ledger row fails, the LLM call and the run still succeed and a `llm.call not recorded` warning is logged | core test |
| 5 | `cost_usd` matches the price table for a known model and is `null` for an unknown one | unit test |
| 6 | Every log line written during a run carries `document_id` and `run_id`; each LLM call logs one `llm.call` line (INFO ok / ERROR failed) with no prompt or reply text | logging test |
| 7 | `GET /trace` returns the latest run's timing, totals (overall, by purpose, by agent) and ordered `tool` + `llm` spans with offsets; `?run_id=` selects an older run; another document's run → 404; unknown document → 404; non-UUID → 422 | router tests |
| 8 | A run with no ledger rows (pre-0007) returns its tool spans and `llm_calls_recorded: false` | router test |
| 9 | `GET /metrics/summary` returns the D7 numbers for seeded data (incl. p50 / p95 and success rate); `?days=` narrows the window; out-of-range `days` → 422 | service + router tests |
| 10 | `alembic upgrade head` creates `llm_calls` with UUID PK, both FKs with cascade, the check constraints and the three indexes | migration test |
| 11 | `observability` imports nothing from another module's `crud` / `model`; `app/core` imports nothing from `app/modules` | import test |
| 12 | Detail page shows the Trace card (totals + timeline, nested LLM calls, error states, pre-0007 note) and token chips per lane; `/metrics` shows KPI tiles, both tables and the window switch | Vitest + browser check (desktop + 375 px, light + dark) |
| 13 | `ruff check`, `ruff format --check`, `pytest`, `npm run lint`, `typecheck`, `test` (also with `TZ=UTC`), `build` pass; CI green | CI run |

## Roadmap Phase

**Phase:** Phase 3 — Bonus Tasks (B1, first of the five so later features get traces and
token counts).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0007-observability-plan.md` | Plan | Implementation path (written after this PRD is final) |
| `docs/prd/0000-setup-prd.md` | Intent | `llm.py` seam, JSON logging, `document_id` context var |
| `docs/prd/0005-agent-prd.md` | Intent | `agent_runs`, `steps`, `GET /runs` this trace builds on |
| `docs/prd/0006-frontend-prd.md` | Intent | Detail page and lanes the trace UI extends (D17, D19) |
| `docs/reference/folder-structure.md` | Reference | Structural placement of the module |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this PRD |

## Open Questions

None — D1–D14 agreed with the user on 2026-10-27 (record every call in `llm.py` through a
hook, FakeLLM included; labels from context vars; `llm_calls` only, step timing reused from
`agent_runs.steps`; counts, timings and labels only — no prompts, replies or document text;
failed calls recorded; estimated USD from a static, dated price table, stored at write time;
own session per row, recording errors swallowed and logged; `/trace` = latest run (+
`?run_id=`) as a flat timeline with step links; full metrics set, all time + `?days=`, live;
no backfill; `run_id` / `agent` / `purpose` in logs and one `llm.call` line per call;
waterfall trace UI with a list on phones; token chips per lane; a small `/metrics` page now;
rows kept with their document, three indexes; B2–B5 and auth out of scope).
