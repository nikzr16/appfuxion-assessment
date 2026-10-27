# 0008 Guardrails Implementation Plan

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

Four layers of change:

1. **Core retry seam** (`app/core/llm.py`, `app/core/errors.py`): the SDK's retries are
   switched off and replaced by our own loop (backoff + full jitter, `Retry-After`), used by
   `OpenAILLMClient` **and** `FakeLLM`. Each attempt is measured by `_observe` separately, so
   each one is its own ledger row with an `attempt` number and a specific error code.
2. **`guardrails` module** (pure, no DB, like `validation`): `schema.py`, `service.py` and one
   helper file, `matching.py`. `check_grounding(...)` looks every non-null value up in
   `raw_text`; `score_confidence(...)` turns grounding + validation + completeness into
   per-field and overall scores, labels and `needs_review`.
3. **Callers and storage**: `structured_extraction` gains `ground_extraction(...)` (check →
   re-extract with feedback within the shared 3-call budget → save the kept attempt and its
   report); the agent gains the **`check_grounding`** tool, the code guard before
   `validate_invoice`, confidence after validation and a summary that names the fields to
   review. Migration `0007_guardrails` adds `extractions.grounding`,
   `agent_runs.overall_confidence` / `needs_review` and `llm_calls.attempt`.
4. **API and UI**: additive `confidence` on `GET /result`, `grounding` on `GET /extraction`, a
   `guardrails` block on `GET /metrics/summary`; badges, overall chip, needs-review banner and
   "Show in text" on the detail page; a Guardrails section on the Metrics page.

The brief's result keys and every existing response key stay unchanged.

## Technical Approach

### 1. Transient-error retries (`app/core/llm.py`, `app/core/errors.py`, PRD D5)

```python
class LLMError(AppError):            # errors.py — additive keyword arguments
    code = "llm_error"
    def __init__(self, message, *, code=None, retryable: bool = False,
                 retry_after: float | None = None) -> None
```

**Classification** (`_classify(exc: openai.OpenAIError) -> LLMError`):

| SDK exception / status | Code | Retryable |
|---|---|---|
| `APITimeoutError`, status 408 | `llm_timeout` | yes |
| `APIConnectionError`, status 409, status ≥ 500 | `llm_unavailable` | yes |
| `RateLimitError` (429) with error code `insufficient_quota` | `llm_quota_exceeded` | no |
| `RateLimitError` (429) otherwise | `llm_rate_limited` | yes (`Retry-After` / `retry-after-ms` header read) |
| any other `OpenAIError` (400, 401, 403, 404, 422 …) | `llm_error` | no |
| structured reply fails validation | `llm_invalid_output` (`LLMOutputError`) | no — 0003 / D3 handle it |

**Loop** (shared by both clients):

```python
_sleep: Callable[[float], None] = time.sleep          # tests replace it (no waiting)
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 20.0
RETRY_AFTER_CAP_SECONDS = 60.0

def _with_retries(kind, model, max_attempts, call: Callable[[_Meter], T]) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            with _observe(kind, model, attempt=attempt) as meter:
                return call(meter)
        except LLMError as exc:
            if not exc.retryable or attempt == max_attempts:
                raise
            _sleep(_backoff(attempt, exc.retry_after))
            # logged: WARNING "llm.call retrying" {attempt, wait_ms, error_code}

def _backoff(attempt, retry_after) -> float:
    if retry_after is not None:
        return min(retry_after, RETRY_AFTER_CAP_SECONDS)
    return random.uniform(0, min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)))
```

- `OpenAILLMClient`: `openai.OpenAI(..., max_retries=0)`; `max_attempts = 1 +
  settings.openai_max_retries` (default 2 → 3 attempts). `complete` and `embed` run their SDK
  call inside `_with_retries`.
- `FakeLLM(max_retries: int = 2)` runs `_next_response` inside the same loop: a scripted
  `LLMError(..., retryable=True)` is retried and the next scripted reply is used, exactly like
  the real client.
- `LLMCallRecord` gains `attempt: int` (1-based); `_log_call` adds it to `llm.call`.
- The agent treats every new `llm_*` code as fatal, as it does `llm_error` today (they are not
  in `RECOVERABLE_CODES`).
- `Purpose` gains `GROUNDING_RETRY = "grounding_retry"`.

### 2. `guardrails` module (PRD D1, D2, D4)

Files: `schema.py`, `service.py`, `matching.py` (normalisation, number / date / identifier /
fuzzy / currency matchers — justified: ~300 lines of pure helpers that are unit-tested on
their own). No router, crud or model: results are stored by their owners (D6).
Imports: `structured_extraction.schema` (`InvoiceData`), `validation.schema`
(`ValidationReport`, `Severity`), `text_extraction.schema` (`ExtractionMethod`),
`validation.service.expected_fields` (new, see §5). Never FastAPI or the DB.

**Schemas:**

```python
class GroundingStatus(StrEnum): GROUNDED, WEAK, UNGROUNDED, INFERRED, SKIPPED
class ValueKind(StrEnum): NUMBER, DATE, IDENTIFIER, TEXT, CURRENCY, CLASSIFICATION
class MatchKind(StrEnum): EXACT, NUMBER, DATE, IDENTIFIER, FUZZY, SYMBOL, OCR

class FieldGrounding(BaseModel):
    path: str                      # "vendor", "line_items[2].amount"
    value: str                     # the value as checked (JSON-mode string), for feedback/UI
    kind: ValueKind
    status: GroundingStatus
    match: MatchKind | None
    similarity: int | None         # fuzzy score 0–100
    page: int | None               # from the "--- Page N ---" markers (1 when there are none)
    start: int | None              # character offsets into raw_text (the UI highlights them)
    end: int | None
    note: str | None               # "ambiguous day/month", "OCR digit correction", ...

class GroundingReport(BaseModel):
    method: ExtractionMethod
    checked: int; grounded: int; weak: int; ungrounded: int; inferred: int
    fields: list[FieldGrounding]   # every non-null value incl. skipped ones, in schema order

class GroundingAttempt(BaseModel):
    attempt: int                   # extraction call number (1–3)
    reason: Literal["initial", "schema", "grounding"]
    valid: bool                    # False when the reply failed the schema
    ungrounded: list[str]          # paths

class ExtractionGrounding(BaseModel):   # stored in extractions.grounding
    report: GroundingReport        # of the kept attempt
    kept_attempt: int
    grounding_retries: int
    attempts: list[GroundingAttempt]
    checked_at: datetime

class ConfidenceLabel(StrEnum): HIGH, MEDIUM, LOW

class FieldConfidence(BaseModel):
    path: str
    score: float                   # 0–1, 3 decimals
    label: ConfidenceLabel
    grounding: GroundingStatus
    page: int | None; start: int | None; end: int | None
    reasons: list[str]             # "Found on page 1", "Close match (88)", "Validation warning: …"

class ConfidenceComponents(BaseModel):
    fields: float; completeness: float; validation: float

class ConfidenceReport(BaseModel):   # AgentResult.confidence
    overall: float; label: ConfidenceLabel; needs_review: bool
    review_fields: list[str]       # paths, key fields first
    components: ConfidenceComponents
    fields: dict[str, FieldConfidence]   # keyed by path; null values are absent
```

**Grounding (`check_grounding(data, raw_text, method) -> GroundingReport`)** — rules from D2:

| Field(s) | Kind | Rule |
|---|---|---|
| `subtotal`, `tax`, `total_amount`, line `quantity` / `unit_price` / `amount` | number | Tokenise `raw_text` once (`[(\-]?[$€£¥₹₩₱฿₫]?\d[\d.,'  ]*\d\)?` and single digits); parse each token under both conventions (`.` decimal / `,` decimal; a lone separator with 3 trailing digits gives both readings); strip symbols; parentheses / minus → sign, compared by absolute value. Match = equal `Decimal`. Vision text: a token that only matches after `O→0, o→0, I/l/|→1, S→5, B→8` → `weak` (`OCR`). |
| `invoice_date`, `due_date` | date | Generate printed forms: `D/M/Y`, `M/D/Y`, `Y/M/D` with separators `/ - . space`, 2- and 4-digit years, padded and unpadded; `D Month Y`, `Month D, Y`, `D-Mon-Y` with English and Malay names (`Januari…Disember`, `Jan, Feb, Mac, Apr, Mei, Jun, Jul, Ogos, Sep, Okt, Nov, Dis`). Search with word boundaries in the normalised text. Matched only by a numeric form where day ≤ 12, month ≤ 12 and day ≠ month → `weak` (note "ambiguous day/month"). |
| `invoice_number`, `vendor_tax_id` | identifier | Compare after removing whitespace and `- / . _ :`, case-folded; exact substring of the equally reduced text (offsets mapped back). No fuzzy. Vision: one OCR confusion allowed → `weak`. |
| `vendor`, `vendor_address`, `customer_name`, `customer_address`, `payment_terms`, line `description` | text | Normalised exact substring → `grounded`. Else `rapidfuzz.fuzz.partial_ratio_alignment` against the normalised text (addresses: `token_set_ratio` against the best window, because the model joins lines with ", "); ≥ 85 (pdf) / ≥ 80 (vision) → `weak`; below → `ungrounded`. |
| `currency` | currency | ISO code printed (word boundary) → `grounded`; else a symbol in `CURRENCY_SYMBOLS` that maps to the code (`RM`, `Ringgit` → MYR, `S$` → SGD …, mirroring the 0003 prompt table) → `inferred`; else `ungrounded`. |
| `document_type` | classification | `skipped`. |

Normalisation (`matching.normalise`) = NFKC, case-fold, collapse whitespace, keeping an index
map back to `raw_text` offsets so every match has a correct `start` / `end` and page (the page
comes from the nearest preceding `--- Page N ---` marker). Page markers themselves are never
matched. Grounding always uses the **full** `raw_text` (the model may have seen a truncated
head + tail).

**Confidence (`score_confidence(data, grounding, validation) -> ConfidenceReport | None`)** — D4:

```
GROUNDING_SCORE = {grounded: 1.0, inferred: 0.9, weak: 0.7, ungrounded: 0.2}
field = GROUNDING_SCORE[status]
        × (0.5 if an error issue applies, else 0.8 if a warning applies, else 1.0)
        × (0.9 if method == vision else 1.0)
# an issue applies when issue.field == path or path starts with issue.field + "[" / "."

WEIGHTS = {total_amount: 3, vendor: 2, invoice_number: 2, invoice_date: 2, currency: 2,
           line_items (group mean): 2, every other field: 1}
fields_mean  = Σ weight × score / Σ weight          (fields with a value only)
completeness = present ÷ expected  (expected = validation_service.expected_fields(type))
validation   = {pass: 1.0, warn: 0.7, fail: 0.3}[report.status]
overall      = 0.60 × fields_mean + 0.25 × completeness + 0.15 × validation
label        = high ≥ 0.85 · medium ≥ 0.60 · low
needs_review = label == low or any KEY_FIELD (total_amount, vendor, invoice_number,
               invoice_date, currency) is ungrounded
review_fields = ungrounded or low fields, key fields first
```
`document_type == unknown` → `None`. No values at all → `fields_mean` = 0. All constants are
module-level so tests and ENGINEERING_NOTES quote one source.

### 3. Re-extraction with feedback (`structured_extraction`, PRD D1, D3)

- `MAX_ATTEMPTS = 2` stays the schema-retry limit inside `extract_structured_data` (0003
  unchanged); new `EXTRACTION_BUDGET = 3` is the total per extraction.
- `extract_structured_data(..., force)` now also writes `grounding = NULL` when it (re)writes
  the row, so a new extraction is never shown with an old report.
- **New `ground_extraction(db, llm, document_id) -> ExtractionRead`** (called by the tool):
  1. Load the row (`structured_data_missing` if none) and the text; if `row.grounding` is set,
     return it unchanged (idempotent, no LLM call).
  2. `report = guardrails.check_grounding(row.data, text.raw_text, text.method)`.
  3. While `report.ungrounded > 0` and `row.attempts + retries < EXTRACTION_BUDGET`:
     `bind_trace(purpose=GROUNDING_RETRY, prompt_version=v2)`; messages = system + document +
     the previous reply (assistant) + `prompts.grounding_retry_prompt(items)`; a schema-invalid
     reply counts as an attempt (`valid=False`) and is discarded; otherwise re-check and keep it
     if it has **fewer or equal** ungrounded values (ties → latest).
  4. Save `data` (kept attempt), `grounding` (`ExtractionGrounding` JSON), `attempts`
     (total calls), tokens (+ retries) in one commit; log `grounding checked` with counts.
- `prompts.py` → `PROMPT_VERSION = "structured_extraction.v2"`; new
  `grounding_retry_prompt(items)`: "These values were not found in the document text: `vendor`:
  'ABC Supply Sdn Bhd' … Copy each value exactly as printed, or use null if the document does
  not contain it. Do not change other values. Return the complete object." The system prompt is
  unchanged apart from the version.
- `ExtractionRead` / `ExtractionResponse` gain `grounding: ExtractionGrounding | None`.
- New `grounding_stats(db, since) -> GroundingStats` (sums of `grounding->report->checked`,
  `grounded`, extractions with `grounding_retries > 0`) for metrics, via `crud.py`.

### 4. Agent (`agent`, PRD D1, D4, D8)

- **Tool `check_grounding`** (no arguments), registered between `extract_structured_data` and
  `validate_invoice`. Guard: needs `ctx.structured` (`structured_data_missing`). Calls
  `structured_extraction_service.ground_extraction`, then sets `ctx.structured` (it may have
  changed), `ctx.grounding`. Returns to the model: `{checked, grounded, weak, ungrounded,
  inferred, retries, ungrounded_values: [{field, value}], changed_fields: [...]}` — never text.
- `_extract_structured_data` resets `ctx.grounding = None` and `ctx.confidence = None`.
- **Guard** in `_validate_invoice`: `ctx.grounding is None` → `ToolError("grounding_required",
  "Call check_grounding before validate_invoice.")`; `grounding_required` joins
  `RECOVERABLE_CODES`. After validation: `ctx.confidence = guardrails_service.score_confidence(
  ctx.structured, ctx.grounding.report, ctx.validation)`; the tool result adds
  `needs_review` and `review_fields`.
- **Summary** (`agent.summary.v2`): the payload gains `"review": [{field, reason}]`; the system
  prompt asks to name those fields and to say they should be verified. Coverage check:
  `missing_review(text, review_fields)` — the text must contain one of `verify / review /
  check / confirm` **and** a keyword per field (reusing `_FIELD_KEYWORDS`; `line_items[i].x` →
  "line i+1"). Missing ones join the existing retry message; the code fallback appends one
  sentence: "Please verify the vendor and the total: they could not be confirmed in the
  document text."
- **Agent prompt** `agent.document.v2`: the order gains step 3 `check_grounding`.
- `AgentResult.confidence: ConfidenceReport | None = None` (old results load as `None`).
  `_complete` also writes `overall_confidence` and `needs_review`.
- New `confidence_stats(db, since) -> ConfidenceStats` (completed runs with a score: count,
  average, needs-review count, count per label) for metrics.
- `AGENT_MAX_STEPS` default 8 → **10** (`config.py`, `.env.example`, README).

### 5. Small additive changes elsewhere

- `validation/service.py`: public `expected_fields(document_type) -> list[str]` (the keys of
  the existing `_REQUIRED` table). No rule changes.
- `observability`: `llm_calls.attempt`; `record_llm_call` stores it; `LLMSpan.attempt`;
  `crud.count_retries(db, since)` (rows with `attempt > 1`); `MetricsSummary.guardrails`.

### Storage — migration `0007_guardrails.py` (revision `"0007"`, down → `"0006"`, PRD D6)

```
extractions.grounding           JSONB NULL
agent_runs.overall_confidence   NUMERIC(4,3) NULL   CHECK (overall_confidence BETWEEN 0 AND 1)
agent_runs.needs_review         BOOLEAN NULL
llm_calls.attempt               INTEGER NOT NULL DEFAULT 1   CHECK (attempt >= 1)
```
Schema-only: existing rows keep `NULL` (D11) and `attempt = 1`.

### API (PRD D7, D10)

| Endpoint | Change |
|---|---|
| `GET /api/documents/{id}/result` | `+ confidence: ConfidenceReport \| null` |
| `GET /api/documents/{id}/extraction` | `+ grounding: ExtractionGrounding \| null` |
| `GET /api/documents/{id}/trace` | `LLMSpan + attempt` |
| `GET /api/metrics/summary` | `+ guardrails: {runs_scored, avg_confidence, by_label{high, medium, low}, needs_review, needs_review_rate, values_checked, values_grounded, grounding_rate, grounding_retry_extractions, transient_retries}` (same `?days=` window) |

### Frontend (PRD D9, D10)

- **Types / client**: `GroundingStatus`, `FieldConfidence`, `ConfidenceReport`,
  `AgentResult.confidence?: ConfidenceReport | null`, `LLMSpan.attempt`,
  `MetricsSummary.guardrails`. No new endpoint, no new query hook.
- **`lib/confidence.ts`** (pure, unit-tested): `confidenceOf(report, path)`,
  `labelMeta(label)` → `{text: "High", icon, tone}`, `reviewList(report)` → readable field
  names (reusing the field labels of `StructuredData`), `lineItemPath(i, column)`.
- **`components/ConfidenceBadge.tsx`**: `High` / `Medium` / `Low` with a distinct lucide icon
  each (`ShieldCheck`, `ShieldAlert`, `ShieldX`) + text, success / warning / danger tokens;
  tooltip with score (e.g. `0.92`) and reasons; a `compact` variant (icon only, text for screen
  readers and in the tooltip) for line-item cells. "Not found in document" marker for
  `ungrounded`, "Inferred from symbol" note for `inferred`.
- **`StructuredData.tsx` / `LineItemsTable.tsx`**: take `confidence: ConfidenceReport | null`;
  badge next to each value, a small "Show in text" button when the field has a span.
  Old results: one muted line "Confidence not available — reprocess to compute".
- **`ConfidenceSummary.tsx`**: overall chip (label + score) in the result header, and a
  **Needs review** `Alert` (warning) listing `review_fields` as buttons that jump to the text.
- **`RawTextSection.tsx`**: accepts `highlight: {start, end} | null`; opens itself if collapsed,
  renders the text in three parts with the match in a `<mark>` (token colours, works in dark
  mode), scrolls it into view and moves focus to it (`tabIndex=-1`) for keyboard users.
  `DocumentDetailPage` holds the `highlight` state.
- **Lanes / trace**: `roleOfTool("check_grounding") = "extraction"`, `toolLabel` "Check
  grounding"; `TraceTimeline` shows the purpose "Grounding retry" and an "attempt N" chip when
  `attempt > 1`.
- **Metrics page**: a "Guardrails" section — tiles for average confidence, needs review (% and
  count), grounding rate, grounding retries, transient retries, plus a high / medium / low split
  shown as a stacked bar with numbers and a legend (the `dataviz` skill is loaded before
  building it). Empty state when nothing is scored yet.
- Everything uses the 0006 design system, light + dark, 375 px, `tabular-nums` for scores.

## System Components

| Component | Responsibility |
|---|---|
| `app/core/errors.py` | `LLMError.retryable` / `retry_after` |
| `app/core/llm.py` | `_classify`, `_with_retries`, `_backoff`, `attempt` on records, `Purpose.GROUNDING_RETRY`, SDK retries off, FakeLLM through the same loop |
| `guardrails/matching.py` | Normalisation with offset map, page lookup, number / date / identifier / fuzzy / currency matchers |
| `guardrails/schema.py` | Grounding and confidence DTOs |
| `guardrails/service.py` | `check_grounding`, `score_confidence`, `ungrounded_items` |
| `structured_extraction` (service, crud, prompts, schema, model) | `ground_extraction`, budget, v2 prompt, `grounding` column, `grounding_stats` |
| `agent` (tools, prompts, schema, service, crud, model) | `check_grounding` tool + guard, confidence after validation, summary v2 coverage, run columns, `confidence_stats` |
| `validation/service.py` | `expected_fields` |
| `observability` (model, service, schema, crud) | `attempt` column and span field, retry count, `guardrails` metrics block |
| `migrations/versions/0007_guardrails.py` | The four columns |
| `frontend/src/lib/confidence.ts`, `components/ConfidenceBadge.tsx`, `features/detail/ConfidenceSummary.tsx` | Badges, chip, banner |
| `frontend/src/features/detail/*`, `features/metrics/MetricsPage.tsx`, `lib/agents.ts` | Wiring, "Show in text", lanes, metrics section |

## Processing Flow

```
run_document_agent
  extract_text ──────────────► document_texts (raw_text, method)
  extract_structured_data ───► _extract_with_retry (≤ 2 calls, schema) → extractions (grounding = NULL)
  check_grounding ───────────► ground_extraction
                                 check_grounding(data, raw_text, method)       ← code
                                 while ungrounded and calls < 3:
                                   llm.complete [purpose = grounding_retry]    ← each transport
                                   attempt → own ledger row (attempt 1..3, backoff between)
                                   re-check, keep the best
                                 save data + grounding (one commit)
  validate_invoice ──────────► guard: grounding_required until grounded
                               validate_invoice → score_confidence (code)
  convert_currency (optional)
  generate_summary ──────────► payload + review fields → coverage check (issues + review) → retry / append
  _complete ─────────────────► result {…, confidence}, overall_confidence, needs_review

GET /result      → AgentResult incl. confidence
GET /extraction  → … + grounding
GET /metrics     → … + guardrails (agent_runs, extractions, llm_calls.attempt)
```

## Dependencies

| Dependency | Purpose |
|---|---|
| `rapidfuzz` (backend, new) | Fast fuzzy partial / token-set matching with alignment (offsets for highlighting); MIT, wheels for 3.12 |
| None new (frontend) | Badges, highlight and the stacked bar are Tailwind + lucide (already used) |

## Implementation Phases

### Phase 1: Core retry seam
`LLMError` fields; `_classify`, `_with_retries`, `_backoff`, `_sleep`; SDK `max_retries=0`;
FakeLLM through the loop; `attempt` on `LLMCallRecord` and `llm.call`; `Purpose.GROUNDING_RETRY`.
Autouse test fixture that makes `_sleep` a no-op recorder. Tests: each status / exception maps
to the right code and retryability; retry until success; give up after `1 + max_retries`;
`Retry-After` honoured and capped; jitter within bounds (seeded); non-retryable raised at once;
one record per attempt with `attempt` 1..n.

### Phase 2: `guardrails` module
`matching.py`, `schema.py`, `service.py` and `rapidfuzz`. Table-driven unit tests per matcher
(both number conventions, `(50.00)`, `50` vs `50.00`, `1.234` both readings, date families incl.
Malay and ambiguous numeric → weak, identifiers with spaces / dashes, fuzzy above / below 85 and
80, address token-set, `RM` → inferred, OCR confusions on vision only, page / span offsets
round-trip to `raw_text`), then `check_grounding` on fixture texts and `score_confidence`
scenarios (clean PDF → high; ungrounded total → needs review; vision factor; validation error
and warning; unknown → None; empty document).

### Phase 3: Storage
Migration `0007`, model columns, `record_llm_call` stores `attempt`. Migration test (columns,
types, checks, head = `0007`, downgrade).

### Phase 4: Re-extraction
`ground_extraction`, budget, `grounding_retry_prompt`, prompt v2, `grounding = NULL` on
re-extract, `ExtractionRead` / `ExtractionResponse.grounding`, `grounding_stats`. Service tests
(FakeLLM): grounded first time → no LLM call; one ungrounded → one `grounding_retry` call with
feedback listing it; still ungrounded after the budget → kept and flagged; a worse retry is not
kept; a schema-invalid retry counts and is discarded; extraction that already used 2 calls gets
1 retry; idempotent second call; ledger rows carry `grounding_retry`.

### Phase 5: Agent
Tool, guard, `RECOVERABLE_CODES`, confidence after validation, summary v2 + `missing_review` +
fallback sentence, agent prompt v2, `AgentResult.confidence`, run columns, `confidence_stats`,
`AGENT_MAX_STEPS = 10`. Tests: happy path with grounding; the model calls `validate_invoice`
first → `grounding_required` → recovers; re-extract after grounding resets the guard; the run
result and columns hold the confidence; summary that omits a review field is retried, then
completed by code.

### Phase 6: API and metrics
`/result`, `/extraction`, `/trace` (attempt), `/metrics/summary` guardrails block. Router tests
(new keys present, old keys unchanged, pre-0008 rows → `null`), metrics on seeded data with
`?days=`, import-layering test extended to `guardrails` (no crud / model / FastAPI / DB imports).

### Phase 7: Frontend
Types, `lib/confidence.ts`, `ConfidenceBadge`, `ConfidenceSummary`, StructuredData / LineItems /
RawText changes, lanes + trace labels, Metrics section. Vitest: `confidence.ts` table tests;
badges render text + icon per label; banner lists review fields and "Show in text" highlights
and scrolls; old-result state; metrics guardrails section and its empty state; run with and
without `TZ=UTC`.

### Phase 8: Browser check and close-out
Run the DB, backend and frontend; process a text PDF and a scanned image (real OpenAI only in
this manual check), plus a reprocess; check the detail page (badges, banner, highlight) and
Metrics at desktop and 375 px, light and dark; fix issues. Full backend and frontend checks.
Update `docs/reference/folder-structure.md` (module, routes, schemas, database, wiring, config
default), `ENGINEERING_NOTES.md` (architecture, prompt design for v2 prompts, limitations,
production improvements; replace the "comes with B2" pointers), `README.md` (guardrails usage,
`AGENT_MAX_STEPS`), roadmap; decision log `0009` for any divergence; commit on the feature branch.

## Testing Strategy

- **Never the real OpenAI API**: `FakeLLM` everywhere; it now goes through the same retry loop,
  so transient-retry tests script `LLMError(..., retryable=True)` replies. Core tests that cover
  `_classify` build SDK exceptions with a fake `httpx.Response` (status, headers, body).
- **No waiting**: an autouse fixture replaces `llm._sleep` with a list-appender, so backoff
  values are asserted without sleeping; `random` is seeded where jitter is checked.
- **Fixtures**: small `raw_text` strings for a clean text-PDF invoice, a Malaysian invoice with
  Malay dates and `RM`, a vision transcription with OCR misreads, and an invoice with an invented
  vendor; matching `InvoiceData` objects.
- **Determinism**: grounding and confidence are pure — table-driven tests with exact expected
  statuses, offsets and scores.
- **Agent**: scripted tool-call sequences (FakeLLM `LLMResponse` with `tool_calls`) for the happy
  path, the skipped-grounding path and the summary-coverage path.
- **Frontend**: pure functions table-tested; component tests with `fetchMock` fixtures for a
  high-confidence result, a needs-review result, a pre-0008 result and empty guardrail metrics.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Grounding false negatives (formats we did not foresee) | Extra LLM calls, spurious "needs review" | `weak` never retries; budget caps calls at 3; fixtures cover the formats in the sample invoices; documented limitation |
| False positives for short numbers (`1`, `2`) or common words | An invented small value looks grounded | Documented limitation; line-item numbers are also covered by 0004's arithmetic checks |
| A retry makes the data worse | Lower quality saved | Keep the attempt with the fewest ungrounded values; schema-invalid retries are discarded |
| Our retry loop changes behaviour of every call | Regressions in 0002–0007 | Same exceptions surface after the last attempt; full suite runs; non-retryable codes raise at once |
| Longer worst-case run time (3 extraction calls × 3 transport attempts) | Slow failures | Bounded by config; waits capped; visible in the trace |
| The model loops on `grounding_required` | Step limit reached | Clear error message + prompt order; `AGENT_MAX_STEPS = 10`; test covers recovery |
| Stricter summary check | More summary retries | Same single retry + code-appended sentence as 0005 |
| `rapidfuzz` on long texts | CPU time | Normalised text computed once; ~50 values × 60k chars is milliseconds in rapidfuzz |
| Highlight offsets drift from the shown text | Wrong span highlighted | Offsets are into `raw_text` exactly as `GET /text` returns it; round-trip unit test |

## Roadmap Phase

**Phase:** Phase 3 — Bonus Tasks (B2).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0008-guardrails-prd.md` | Intent | Product goals and constraints this plan implements |
| `docs/plan/0003-structured-extraction-plan.md` | Plan | Retry loop and `extractions` this extends |
| `docs/plan/0005-agent-plan.md` | Plan | Tools, guards, summary coverage this extends |
| `docs/plan/0007-observability-plan.md` | Plan | `_observe`, ledger, metrics this extends |
| `docs/reference/folder-structure.md` | Reference | Structural placement of planned components |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this plan (next: 0009) |

## Open Questions

None — the PRD's decisions are final; details above are implementation choices within them.
