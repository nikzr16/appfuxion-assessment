# 0007 Observability Implementation Plan

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

Three layers of change:

1. **Core seam** (`app/core/llm.py`, `app/core/logging.py`): every `complete` / `embed` call
   of `OpenAILLMClient` **and** `FakeLLM` is measured by one shared helper, which logs one
   `llm.call` line and hands an `LLMCallRecord` to a registered **recorder hook**. Labels
   (`run_id`, `agent`, `purpose`, `prompt_version`, `step_index`) come from context vars bound
   with one context manager, `bind_trace(...)`, next to the existing `document_id`.
2. **`observability` module** (model, crud, schema, service, router, `pricing.py`) + migration
   `0006_create_llm_calls`: the recorder writes ledger rows in its own session;
   `GET /api/documents/{id}/trace` and `GET /api/metrics/summary` read them, joining the agent
   run and document data through those modules' services.
3. **Labels in existing callers** (0002, 0003, 0005 — one `with bind_trace(...)` each) and the
   **frontend**: a Trace card with a waterfall timeline, token chips on the agent lanes, and a
   `/metrics` page.

No response contract of 0001–0006 changes. Behaviour of every LLM call (return values,
exceptions, SDK retries) stays the same.

## Technical Approach

### Context labels (`app/core/logging.py`, PRD D2, D9)

```python
document_id_var: ContextVar[str | None]          # exists (0000)
run_id_var: ContextVar[str | None]
agent_var: ContextVar[str | None]
purpose_var: ContextVar[str | None]
prompt_version_var: ContextVar[str | None]
step_index_var: ContextVar[int | None]

@contextmanager
def bind_trace(*, run_id: str | None = ..., agent: str | None = ..., purpose: str | None = ...,
               prompt_version: str | None = ..., step_index: int | None = ...) -> Iterator[None]
    """Set only the labels passed (a sentinel default means "leave as is"); reset on exit."""

def trace_labels() -> TraceLabels   # frozen dataclass snapshot of all six vars
```
- `JsonFormatter` adds `run_id`, `agent`, `purpose`, `step_index` (and `prompt_version`) to every
  line when set, like `document_id` today. Explicit `extra=` keys still win only when the
  context is unset (no duplicate keys).
- `bind_document_id` stays as is (callers unchanged).
- Constants for the label values live in `app/core/llm.py` so callers and the module share them:
  `Purpose(StrEnum)`: `vision_transcription`, `structured_extraction`, `agent_loop`, `summary`,
  `embedding`, `unknown`; `Agent(StrEnum)`: `document` (B4 adds more).

### Recording seam (`app/core/llm.py`, PRD D1, D3, D5, D9)

```python
@dataclass(frozen=True)
class LLMCallRecord:
    kind: Literal["chat", "embedding"]
    model: str                     # the model the API reported (or the one requested on error)
    usage: TokenUsage              # TokenUsage() when the call raised
    latency_ms: int
    status: Literal["ok", "error"]
    error_code: str | None         # LLMError.code / LLMOutputError.code
    started_at: datetime           # UTC
    labels: TraceLabels            # document_id, run_id, agent, purpose, prompt_version, step_index

LLMRecorder = Callable[[LLMCallRecord], None]
def register_llm_recorder(recorder: LLMRecorder | None) -> None   # module-level, like the pipeline hook

@contextmanager
def _observe(kind, requested_model) -> Iterator[_Meter]:
    """Times the block; on exit (success or exception) logs `llm.call` and calls the recorder.
    The block sets meter.model / meter.usage from the response. Exceptions from the block
    are re-raised unchanged; exceptions from the recorder are caught and logged as WARNING
    `llm.call not recorded`."""
```
- `OpenAILLMClient.complete` / `.embed` and `FakeLLM.complete` / `.embed` all run their body inside
  `_observe(...)`. The existing `llm.complete` / `llm.embed` / `llm.complete failed` log lines
  are replaced by the single `llm.call` line (INFO ok, ERROR failed) with `kind`, `model`,
  `purpose`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `status`, `error_code`
  (`cost_usd` is not known in core; it is in the ledger row). The SDK error text stays in an
  `error` field on the ERROR line, as today. No message content is ever logged.
- No purpose bound → `purpose = unknown` and a WARNING `llm.call without purpose` (catches a
  future caller that forgot its label).
- **Error codes:** the row stores the exception's own code — `llm_error` for API failures and
  `llm_invalid_output` for a structured reply that failed validation (the client's code for
  what the PRD calls a rejected reply; 0003 later maps it to its own `invalid_llm_output`).
- `FakeLLM` keeps `calls`, `total_usage` etc. unchanged; its latency is real (~0 ms).

### Labels in callers (PRD D2)

| Where | Binding |
|---|---|
| `agent/service.py` `run_document_agent`, right after `create_run` | `bind_trace(run_id=str(run.id), agent=Agent.DOCUMENT)` around `_execute` |
| `agent/runner.py` around `self._llm.complete(...)` | `bind_trace(purpose=Purpose.AGENT_LOOP, prompt_version=self._prompt_version)` — the runner gains an optional `prompt_version` argument; the service passes `AGENT_PROMPT_VERSION` |
| `agent/runner.py` `_call`, around `tool.handler(arguments)` | `bind_trace(step_index=index)` |
| `agent/tools.py` `_complete` (summary + its retry) | `bind_trace(purpose=Purpose.SUMMARY, prompt_version=SUMMARY_PROMPT_VERSION)` |
| `text_extraction/service.py` `_transcribe_pages` | `bind_trace(purpose=Purpose.VISION_TRANSCRIPTION, prompt_version=prompts.PROMPT_VERSION)` |
| `structured_extraction/service.py` `_extract_with_retry` | `bind_trace(purpose=Purpose.STRUCTURED_EXTRACTION, prompt_version=prompts.PROMPT_VERSION)` |

`runner.py` stays document-agnostic: it only sets generic labels. Context vars are per thread
/ task, so parallel background runs never mix labels.

### Ledger table (`observability/model.py`, PRD D3, D4, D13)

```
llm_calls
  id               UUID PK (uuid4)
  document_id      UUID NULL  FK documents.id   ON DELETE CASCADE
  run_id           UUID NULL  FK agent_runs.id  ON DELETE CASCADE
  step_index       INTEGER NULL
  agent            VARCHAR(30) NULL
  purpose          VARCHAR(40) NOT NULL
  kind             VARCHAR(20) NOT NULL         CHECK kind IN ('chat','embedding')
  model            VARCHAR(100) NOT NULL
  prompt_version   VARCHAR(50) NULL
  prompt_tokens    INTEGER NOT NULL DEFAULT 0   CHECK >= 0
  completion_tokens INTEGER NOT NULL DEFAULT 0  CHECK >= 0
  cost_usd         NUMERIC(12,6) NULL           CHECK >= 0
  latency_ms       INTEGER NOT NULL             CHECK >= 0
  status           VARCHAR(10) NOT NULL         CHECK status IN ('ok','error')
  error_code       VARCHAR(50) NULL
  started_at       TIMESTAMPTZ NOT NULL
indexes: ix_llm_calls_document_id_started_at (document_id, started_at)
         ix_llm_calls_run_id (run_id)
         ix_llm_calls_started_at (started_at)
```
FKs are string references (`"documents.id"`, `"agent_runs.id"`), as in `agent_runs`.
Migration `0006_create_llm_calls.py` (revision `"0006"`, down → `"0005"`), hand-checked after
autogenerate.

### Pricing (`observability/pricing.py`, PRD D4)

```python
PRICES_AS_OF = date(2026, 10, 27)    # checked against openai.com/api/pricing on the day written
PRICES: dict[str, ModelPrice]        # USD per 1M tokens: input, output
    "gpt-4.1-mini", "gpt-4.1", "gpt-4.1-nano", "gpt-4o-mini", "gpt-4o",
    "text-embedding-3-small", "text-embedding-3-large"
def estimate_cost(model: str, usage: TokenUsage) -> Decimal | None
```
- Model lookup: exact name, then the **longest known prefix** (the API reports dated names such
  as `gpt-4.1-mini-2025-04-14`); unknown → `None`. `fake-model` is unknown on purpose, and tests
  use a priced model name where cost matters.
- Rounded to 6 decimal places (`ROUND_HALF_UP`).

### Recorder (`observability/service.py`, PRD D5)

```python
def record_llm_call(record: LLMCallRecord) -> None:
    """Registered with register_llm_recorder at app start. Own SessionLocal, one insert,
    commit, close. Never raises: any exception → rollback, WARNING `llm.call not recorded`."""
```
- Converts label strings to UUIDs (an invalid value → `None`, so a bad label cannot drop the row).
- A missing document / run (FK violation, e.g. a call outside a real run) is caught like any
  other error.
- `app/main.py`: `register_llm_recorder(observability_service.record_llm_call)` next to
  `register_pipeline_runner(...)`.

### Trace (`GET /api/documents/{id}/trace[?run_id=]`, PRD D6, D8)

Service `get_trace(db, document_id, run_id: UUID | None) -> DocumentTrace`:
1. `documents_service.get_document` (404 unknown).
2. `agent_service.list_runs` → the latest run, or the one with `run_id` (not found among this
   document's runs → `NotFoundError(code="run_not_found")`). No run yet → `run: null`, no spans.
3. `crud.list_for_run(db, run.id)` → ledger rows ordered by `started_at`.
4. Build spans: one `tool` span per `ToolStep` (`started_at`, `duration_ms`) and one `llm` span
   per row (`started_at`, `latency_ms`); `offset_ms = started_at − run.started_at` (clamped at
   0); sort by `started_at`, then tool before its own LLM calls.
5. Totals with `Decimal` cost (`null` if every row is unpriced; `cost_complete = false` if some are).

```python
class TraceRun(BaseModel):
    run_id; mode; trigger; status; error_code; error; started_at; finished_at
    queue_ms: int | None          # upload trigger only: run.started_at − document.created_at
    processing_ms: int | None     # finished_at − started_at; None while running
    run_prompt_tokens: int; run_completion_tokens: int   # 0005 run totals (pre-0007 fallback)

class UsageTotals(BaseModel):
    llm_calls; failed_calls; prompt_tokens; completion_tokens; total_tokens
    cost_usd: Decimal | None; cost_complete: bool

class GroupTotals(UsageTotals):
    key: str                      # the purpose or the agent

class ToolSpan(BaseModel):
    kind: Literal["tool"]; step_index; turn; tool; status; error_code
    started_at; offset_ms; duration_ms

class LLMSpan(BaseModel):
    kind: Literal["llm"]; id; step_index: int | None; purpose; agent; model; prompt_version
    prompt_tokens; completion_tokens; total_tokens; cost_usd: Decimal | None
    status; error_code; started_at; offset_ms; duration_ms

class DocumentTrace(BaseModel):
    document_id; uploaded_at
    run: TraceRun | None
    llm_calls_recorded: bool       # False when the run has no ledger rows (pre-0007)
    totals: UsageTotals
    by_purpose: list[GroupTotals]; by_agent: list[GroupTotals]
    spans: list[Annotated[ToolSpan | LLMSpan, Field(discriminator="kind")]]
    prices_as_of: date
```
Money/cost is serialised as a decimal string, like amounts elsewhere.

### Metrics (`GET /api/metrics/summary[?days=N]`, PRD D7)

`days: int | None = Query(None, ge=1, le=365)`; `since = now − days` or `None` (all time).

| Number | Source |
|---|---|
| documents total / by status, success rate = completed ÷ (completed + failed) | new `documents_service.count_by_status(db, since)` (documents created since) |
| runs total / completed / failed; processing ms avg, p50, p95 (completed runs) | new `agent_service.run_stats(db, since)` → `percentile_cont(0.5 / 0.95)` in `agent/crud.py` |
| LLM calls, failed calls, error rate, tokens, cost | `observability/crud.totals(db, since)` |
| avg tokens and cost per document | ledger sums grouped by `run_id` for the completed runs in the window (`agent_service.completed_run_ids(db, since)`), ÷ number of those runs that have ledger rows |
| by model, by purpose: calls, tokens, cost, avg latency | `crud.group_totals(db, since, by="model" \| "purpose")` |

```python
class MetricsSummary(BaseModel):
    window_days: int | None; since: datetime | None; generated_at: datetime
    ledger_since: datetime | None          # earliest ledger row (PRD D8: older runs not counted)
    documents: DocumentCounts              # total, processing, completed, failed, success_rate
    runs: RunStats                         # total, completed, failed, avg_ms, p50_ms, p95_ms
    llm: UsageTotals + error_rate, avg_tokens_per_document, avg_cost_per_document
    by_model: list[GroupTotals + avg_latency_ms]
    by_purpose: list[GroupTotals + avg_latency_ms]
    prices_as_of: date
```
Computed live on every request (a handful of aggregate queries); no cache.

### Routes (`observability/router.py`, tag `observability`)

| Method | Path | Response | Errors |
|---|---|---|---|
| GET | `/api/documents/{document_id}/trace` | `DocumentTrace` | 404 `not_found` / `run_not_found`; 422 non-UUID |
| GET | `/api/metrics/summary` | `MetricsSummary` | 422 `days` out of range |

### Additive changes to earlier modules

- `documents/service.py` + `crud.py`: `count_by_status(db, since)`.
- `agent/service.py` + `crud.py`: `run_stats(db, since)`, `completed_run_ids(db, since)`;
  `bind_trace` around `_execute`; pass `prompt_version` to the runner.
- `agent/runner.py`, `agent/tools.py`, `text_extraction/service.py`,
  `structured_extraction/service.py`: the `bind_trace` lines above.

### Frontend (PRD D10–D12)

**API** (`api/types.ts`, `client.ts`, `queries.ts`): `DocumentTrace`, `MetricsSummary` types;
`getTrace(id, runId?)`, `getMetrics(days?)`; `useTrace(id, runId, { live })` (polls every 10 s
while processing, invalidated by `useRefreshOnFinish` and `markProcessing`), `useMetrics(days)`.

**`lib/trace.ts`** (pure, unit-tested):
- `buildTraceRows(trace)` → ordered rows: each tool step with its nested LLM calls (by
  `step_index`), plus agent-loop turns (LLM spans with no step) as their own rows.
- `barGeometry(span, runDurationMs)` → `{ leftPct, widthPct }` with a minimum visible width;
  the axis length is `processing_ms`, or "now − start" while running.
- `laneUsage(lanes, trace)` → tokens / cost per lane via `step_index → step.tool → role`
  (reusing `roleOfStep`); `planningUsage(trace)` for agent-loop turns.
- `lib/format.ts`: `formatTokens` (`1,234` / `12.3k`), `formatCost` (`$0.0012`, `<$0.0001`, `—`).

**Detail page**:
- `features/detail/TraceSection.tsx`: Card "Trace" below Agent activity. Header: run picker
  (`<select>` of runs when there is more than one; latest selected). **Totals strip**: processing
  time, queue time, LLM calls (failed count when > 0), tokens (prompt / completion in a tooltip),
  est. cost with "prices as of …". **Timeline** (`TraceTimeline.tsx`): a time axis with ticks;
  tool rows (tool name, ok / error, duration) with a bar; nested LLM rows indented (purpose
  label, model, tokens, cost, latency, error code) with thinner bars; agent-loop rows labelled
  "Agent decides next step (turn N)". Below 640 px the bars are hidden and each row shows
  `+offset · duration` text instead. States: loading skeleton, error with retry, no run yet,
  pre-0007 run ("Token detail not recorded for this run" + run-level tokens), running (live,
  axis grows).
- `AgentLanes.tsx`: a small chip per lane, "1,234 tokens · $0.0004" (hidden when 0 calls).
- `AgentActivity.tsx` header: "Planning: N turns · X tokens" when the trace has agent-loop rows.

**Metrics page** (`features/metrics/MetricsPage.tsx`, route `/metrics`, nav link "Metrics"):
window switch (7 days / 30 days / All time, as a segmented control, kept in the URL `?days=`),
KPI tiles (documents, success rate, avg / p95 processing time, tokens per document, cost per
document, LLM error rate), two tables (by model, by purpose: calls, tokens, cost, avg latency),
a footnote with `prices_as_of` and `ledger_since`. Empty state when there is no data yet.
Tables scroll horizontally inside their card on phones. The `dataviz` skill is loaded before
building the timeline bars and KPI tiles so colours and marks match both themes.

All new UI uses the 0006 design system (Card, Badge, Skeleton, Alert, semantic colour tokens,
Poppins), light + dark, keyboard and screen-reader labels on bars (`aria-label` with the
numbers), and `tabular-nums` for figures.

## System Components

| Component | Responsibility |
|---|---|
| `app/core/logging.py` | Trace context vars, `bind_trace`, JSON formatter fields |
| `app/core/llm.py` | `Purpose` / `Agent` labels, `_observe` meter, `LLMCallRecord`, recorder hook, `llm.call` log |
| `observability/model.py` | `LlmCall` ORM table |
| `observability/crud.py` | Insert a row; rows of a run; totals and group totals in a window; per-run sums |
| `observability/pricing.py` | Dated price table, `estimate_cost` |
| `observability/schema.py` | `DocumentTrace`, spans, totals, `MetricsSummary` DTOs |
| `observability/service.py` | `record_llm_call` (recorder), `get_trace`, `get_metrics` |
| `observability/router.py` | `/documents/{id}/trace`, `/metrics/summary` |
| `migrations/versions/0006_create_llm_calls.py` | Table, constraints, indexes |
| `documents` / `agent` services (additive) | Status counts; run stats; completed run ids; labels |
| `frontend/src/lib/trace.ts` + `features/detail/Trace*.tsx` | Trace card and timeline |
| `frontend/src/features/metrics/` | Metrics page |

## Processing Flow

```
upload → run_pipeline → run_document_agent
  bind_document_id(doc) ─┐
  create_run, commit     │
  bind_trace(run_id, agent=document)
    runner turn: bind_trace(purpose=agent_loop) → llm.complete ─► _observe ─► llm.call log
                                                                         └► recorder → own session → INSERT llm_calls
    tool call:   bind_trace(step_index=i) → handler
                   extract_text → (scan) bind_trace(purpose=vision_transcription) → llm.complete ─► … one row per page
                   extract_structured_data → bind_trace(purpose=structured_extraction) → llm.complete ─► … one row per attempt
                   generate_summary → bind_trace(purpose=summary) → llm.complete ─► … one row per attempt
  run finishes (completed | failed); ledger rows stay even when the run's session rolls back

GET /trace   → document + run (agent service) + ledger rows → spans + totals
GET /metrics → documents counts + run stats + ledger aggregates
```

## Dependencies

| Dependency | Purpose |
|---|---|
| None new (backend) | SQLAlchemy `percentile_cont` / `func`; existing stack |
| None new (frontend) | Bars are plain `div`s with Tailwind widths; no chart library |

## Implementation Phases

### Phase 1: Core seam
`bind_trace` + formatter fields; `Purpose` / `Agent`; `_observe`, `LLMCallRecord`,
`register_llm_recorder`, `llm.call` log in both clients. Tests: `tests/core/test_logging.py`,
`tests/core/test_llm.py` (record on ok / `LLMError` / `LLMOutputError`, recorder failure
swallowed, unknown purpose warning, labels captured).

### Phase 2: Data layer
Model, migration `0006`, crud, `pricing.py`, `record_llm_call`, registration in `main.py`, a
test fixture that unregisters the recorder by default (like `no_pipeline`) with an opt-in
`llm_recorder` fixture. Tests: migration (columns, FKs, checks, indexes, head = `0006`),
pricing, recorder (row written, FK miss swallowed, invalid UUID label).

### Phase 3: Labels in callers
`bind_trace` in the agent service, runner, summary tool, vision and structured extraction;
runner `prompt_version`. Tests: an agent happy path (scripted FakeLLM, scanned + text PDF)
writes the expected rows with purposes, step indexes, run id; a failing run keeps its rows;
log lines carry `run_id`.

### Phase 4: Trace and metrics API
Schemas, `get_trace`, `get_metrics`, additive `documents` / `agent` service functions, router,
`ROUTERS` entry. Tests: service + router (latest / `run_id` / foreign run / unknown / 422 /
no run / pre-0007 run; metrics on seeded data incl. p50 / p95, window, 422), import-layering test.

### Phase 5: Frontend
Types, client, queries; `lib/trace.ts` + format helpers (unit tests); Trace card + timeline;
lane chips + planning line; Metrics page + route + nav link. Vitest for the new lib functions,
the Trace card states and the Metrics page.

### Phase 6: Browser check and close-out
Run backend + frontend, upload a text PDF and a scanned image (real OpenAI only in this manual
check), check detail + metrics at desktop and 375 px, light and dark; fix issues. Full backend
and frontend checks (`TZ=UTC` too). Update `docs/reference/folder-structure.md` (routes,
schemas, database, wiring), `ENGINEERING_NOTES.md` (architecture, limitations, production
improvements; replace the 0003 / 0005 "B1 adds a ledger" pointers with what now exists),
`README.md` (trace + metrics usage), roadmap status; decision log `0008` for any divergence;
commit on the feature branch.

## Testing Strategy

- **Never the real OpenAI API**: `FakeLLM` everywhere; it goes through the same `_observe` path.
- **Recorder isolation in tests**: an autouse fixture registers `None`; tests that check the
  ledger use an `llm_recorder` fixture that registers `record_llm_call` (real DB writes, so FKs
  are exercised). Core tests register a list-appending recorder instead.
- **Logging**: capture JSON output (existing `test_logging.py` pattern) and assert fields;
  assert no prompt text appears.
- **Timing**: span offsets are asserted by order and non-negativity, not exact milliseconds;
  metrics percentiles use seeded runs with fixed `started_at` / `finished_at`.
- **Frontend**: pure functions in `lib/trace.ts` and `format.ts` get table-driven tests; page
  tests use `fetchMock` fixtures for a completed run, a running run, a pre-0007 run, an error
  span and empty metrics; run with and without `TZ=UTC`.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| A recorder bug breaks LLM calls | Every document fails | `_observe` catches recorder exceptions; core test forces a failing recorder |
| Ledger insert adds latency | Slower runs | One small insert per call (ms) vs seconds per LLM call; measured in the browser check |
| Context vars leak between background tasks | Wrong `run_id` on rows | `bind_trace` resets tokens on exit; Starlette runs each task in its own context copy; test two runs back to back |
| `FakeLLM` rows break earlier modules' tests (FK on unknown document) | Noisy warnings / flaky tests | Recorder unregistered by default in tests |
| Prices drift | Wrong cost | `PRICES_AS_OF` shown in the API and UI; documented as an estimate |
| Waterfall unreadable at 375 px | Poor mobile UX | List layout below 640 px; checked in the browser |
| Metrics query cost grows with data | Slow page at scale | Indexes on `started_at`; documented production improvement (roll-ups) |

## Roadmap Phase

**Phase:** Phase 3 — Bonus Tasks (B1).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0007-observability-prd.md` | Intent | Product goals and constraints this plan implements |
| `docs/plan/0005-agent-plan.md` | Plan | Runner, tools and `agent_runs` this builds on |
| `docs/plan/0006-frontend-plan.md` | Plan | Detail page, lanes, design system extended here |
| `docs/reference/folder-structure.md` | Reference | Structural placement of planned components |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this plan (next: 0008) |

## Open Questions

None — the PRD's decisions are final; details above are implementation choices within them.
