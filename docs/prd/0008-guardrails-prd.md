# 0008 Guardrails PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Make every extracted value **checkable and trustworthy**: detect values the model may have
invented (a **grounding check** against the document's own text), give each field and each
document a **confidence score**, and **retry** what is worth retrying — transient API errors
with backoff, and extractions whose values are not found in the text with targeted feedback.
This is the brief's guardrails bonus (B2: hallucination detection, confidence scoring,
retry). It closes the 0003–0007 limitations that point here: "whether a value really appears
in the text comes with B2", "re-ask for the fields that failed", "retry in our own seam so
each attempt is its own span".

## Goals

- A **deterministic grounding check** (code, no LLM): every non-null extracted value —
  header fields and every line-item cell — is looked up in `raw_text` with rules per value
  kind (numbers, dates, identifiers, free text, currency) and gets a status: `grounded`,
  `weak`, `ungrounded`, `inferred` or `skipped`, plus where it was found (page, character
  span).
- **Re-extraction with feedback** when a value is ungrounded: the model is told which values
  were not found and asked to copy them as printed or use `null`, inside one bounded attempt
  budget shared with 0003's schema retry.
- **Confidence per field and per document** (0–1 number + `high` / `medium` / `low` label)
  from three parts: grounding, validation issues (0004) and schema completeness — plus a
  **`needs_review`** flag.
- **Transient-error retries in our own seam** (`app/core/llm.py`): backoff with jitter on
  rate limits, timeouts, connection errors and 5xx, each attempt its own ledger row (0007).
- Every new LLM call goes through `app/core/llm.py` with a `Purpose` label, so it shows in
  the 0007 ledger, trace and metrics.
- Results persisted (Alembic migration) and exposed **additively** on existing endpoints;
  the brief's result shape stays intact.
- UI: confidence badges and grounding markers on the document detail page, a "needs review"
  banner, "show in text" highlighting, and guardrail numbers on the Metrics page.
- Tests use `FakeLLM`; never the real OpenAI API.

## Non-Goals

- An LLM judge ("ask a second model whether this is right") — grounding is deterministic
  code, in the spirit of Domain Rule 5.
- Model logprobs as a confidence signal (see D4) — a production improvement.
- Changing 0004's validation rules or issue catalogue (see D8).
- Changing the document status lifecycle (`processing → completed | failed`).
- Table / layout extraction and multimodal extraction — **B5 (0009)**.
- Retrieval, vendor history, the Query Agent — **B3 (0010)**.
- Extraction / Validation / Reporting agents and the Coordinator — **B4 (0011)**.
- Human correction of fields (editing values in the UI), authentication.

## Scope

| In Scope | Out of Scope |
|---|---|
| `backend/app/modules/guardrails/`: `service.py` + `schema.py` (pure, like `validation`; more layers only if justified) | A guardrails table of its own (D6) |
| Grounding check, confidence scoring, `needs_review` | LLM-as-judge, logprobs |
| `check_grounding` agent tool + code guard before `validate_invoice`; re-extraction with grounding feedback; prompt bumps | Re-asking only the failed fields with a partial schema (D3) |
| Transient-error retry with backoff + jitter in `app/core/llm.py`; SDK retries off | A job queue / retry of whole failed runs |
| Migration: grounding on `extractions`, confidence on `agent_runs`, `attempt` on `llm_calls` | Rewriting old rows (D11) |
| Additive fields on `GET /extraction`, `GET /result`, `GET /metrics/summary` | A new guardrails endpoint (D7) |
| Summary mentions fields that need review (0005 keyword check reused) | New 0004 issue codes (D8) |
| Detail page: badges, banner, "show in text"; Metrics page: guardrails block | Editing fields, a review queue |
| Tests with `FakeLLM` on real Postgres; frontend Vitest | Real OpenAI calls in tests |
| README, ENGINEERING_NOTES 0008 sections, folder-structure reference | — |

## User Stories

1. **As a reviewer of an invoice**, I want each field to show how sure the system is and
   whether its value was found in the document, so that I know which values to double-check.
2. **As a reviewer**, I want to click a field and see where it appears in the raw text, so
   that I can verify it in seconds.
3. **As a reviewer**, I want a clear "needs review" banner (and a sentence in the summary)
   when key values could not be confirmed, so that a doubtful document never looks final.
4. **As an operator**, I want short API outages and rate limits to be retried with backoff,
   and to see each retry in the trace, so that runs fail less and failures are explainable.
5. **As an operator**, I want guardrail numbers on the Metrics page (average confidence,
   share needing review, grounding rate, retries), so that I can see extraction quality over
   time.

## Product Decisions

> **Status: final.** D1–D12 agreed with the user on 2026-10-27: D1 changed to a separate
> `check_grounding` agent tool that code prevents the model from skipping (user's choice);
> D2–D12 as recommended.

| # | Decision (recommended) | Rationale |
|---|---|---|
| D1 | **Grounding is a separate agent tool, `check_grounding`, that the model cannot skip** (user's choice). New order: `extract_text` → `extract_structured_data` → **`check_grounding`** → `validate_invoice` → (`convert_currency`) → `generate_summary`. **Code guard:** `validate_invoice` refuses (recoverable `grounding_required`) until `check_grounding` has succeeded in this run *for the current extraction* (a new `extract_structured_data` call resets it). Because `generate_summary` already requires `validate_invoice` (0005 D2) and a run only completes with a summary, **every completed run has been grounded**. The tool calls the pure `guardrails.service.check_grounding(data, raw_text, method)`; when values are ungrounded it runs the re-extraction with feedback (D3) through `structured_extraction.service`, re-checks, and saves the kept attempt with its grounding report. It returns a short result to the model (counts + ungrounded field names and values, never the raw text). The tool description and the agent prompt (bumped to `agent.v2`) state the order. `check_grounding` belongs to the **Extraction** lane in the UI. `AGENT_MAX_STEPS` default goes from 8 to **10** (the happy path gains one turn). Confidence (D4) is computed by code **right after `validate_invoice`** (it needs the validation report), so `generate_summary` can use it. | A visible tool shows grounding as its own step in the trace and agent lanes, and maps directly onto B4's Extraction Agent ("extraction + grounding / retry"). The guard chain (summary → validation → grounding) turns "please don't skip it" into a rule the code enforces, the same way 0005 guards the summary. Keeping it out of `validate_invoice` keeps "is the document consistent?" (0004) apart from "did the model copy it faithfully?" (B2). |
| D2 | **Matching rules, per value kind.** The text is NFKC-normalised, case-folded and whitespace-collapsed first. **Numbers** (money, quantities): every number-like token in the text is parsed under both conventions (`1,234.56`, `1.234,56`, `1 234,56`), currency symbols stripped, `(50.00)` / `-50.00` compared by absolute value; a match is equal `Decimal` value (`50` = `50.00`). **Dates:** candidate printed forms are generated from the ISO date (D/M/Y and M/D/Y, separators `/ - . space`, 2- and 4-digit years, padded or not, English **and Malay** month names / abbreviations, ISO); a match only through an ambiguous numeric form (day and month both ≤ 12 and different) is `weak`. **Identifiers** (`invoice_number`, `vendor_tax_id`): exact after removing spaces, `- / .` and case — no fuzzy match (one wrong digit is a wrong invoice). **Free text** (vendor, customer, addresses, payment terms, line descriptions): exact normalised substring → `grounded`; else fuzzy best-window similarity (**`rapidfuzz`**, new dependency) ≥ 85 → `weak`; below → `ungrounded`. **Currency:** `grounded` if the ISO code is printed, `inferred` if only a symbol that maps to it is printed (`RM` → MYR, shared table with the 0003 prompt), else `ungrounded`. **`document_type`:** `skipped` (a classification, not a printed value). **Null values:** not checked. **Vision (OCR) text:** fuzzy threshold 80 instead of 85, and digits may match through common OCR confusions (`O/0`, `I/l/1`, `S/5`, `B/8`) as `weak`. Each match stores page and span. | Values are printed in many formats; normalising each kind is what makes "appears in the text" meaningful without false alarms. Identifiers must be exact; names and descriptions tolerate small differences. Vision text has misreads, so it gets slightly looser rules — but only to `weak`, never to `grounded`. |
| D3 | **An ungrounded value triggers a re-extraction of the whole object with feedback; the budget is shared.** One budget of **3 extraction calls** per extraction (first + 2 retries) covers both reasons: schema-invalid replies (retried inside `extract_structured_data`, as in 0003) and ungrounded values (retried by `check_grounding` with whatever budget is left; `weak` does not trigger a retry). The feedback lists each ungrounded value ("`vendor`: 'ABC Supply Sdn Bhd' was not found in the document; copy it as printed or use null"). Grounding-triggered calls use a new **`Purpose.GROUNDING_RETRY`** (schema retries keep `structured_extraction`). When the budget is spent, the **attempt with the fewest ungrounded values** is kept (ties → the latest) and remaining ungrounded values are **kept and flagged, not nulled**. Prompt bump to `structured_extraction.v2`. | Re-asking the whole object reuses 0003's single code path and schema; the document text dominates the tokens either way, so a partial re-ask would save little. A shared budget bounds cost (≤ 3 calls). Keeping-but-flagging respects that the checker is heuristic (OCR, formatting); nulling a true value would lose data, while the flag + low confidence + banner make the doubt visible. |
| D4 | **Confidence: a 0–1 score and a label, from code (no logprobs).** **Per field:** grounding (`grounded` 1.0, `inferred` 0.9, `weak` 0.7, `ungrounded` 0.2) × validation (an `error` issue on the field × 0.5, a `warning` × 0.8) × source (vision text × 0.9). Null fields have no score ("not found"). **Overall:** 0.60 × weighted field mean (total 3; vendor, invoice number, invoice date, currency, line items as one group 2; others 1) + 0.25 × completeness (expected fields present, per document type, from 0004's required-field table) + 0.15 × validation (pass 1.0, warn 0.7, fail 0.3). **Labels:** `high` ≥ 0.85, `medium` ≥ 0.60, `low` < 0.60. **`needs_review`** = overall `low` **or** any key field (total, vendor, invoice number, invoice date, currency) `ungrounded`. `unknown` documents get no confidence. Each score keeps its **reasons** ("found on page 1", "fuzzy match 88", "validation warning"). | A transparent formula anyone can recompute beats an opaque number; labels are what people read, the number is there for sorting and metrics. Logprobs are awkward to map onto JSON fields and FakeLLM has none — a production improvement. |
| D5 | **Transient retries move from the SDK into our seam.** `OpenAILLMClient` sets the SDK's `max_retries=0` and retries itself: **retryable** = connection errors, timeouts, 408, 409, 429 (except `insufficient_quota`), 5xx; **not retryable** = other 4xx, refusals, invalid output (that is D3's job). **Exponential backoff with full jitter** (base 1 s, cap 20 s), honouring `Retry-After`; attempts = `1 + OPENAI_MAX_RETRIES` (existing setting, default 2). **Each attempt is its own ledger row** with a new `attempt` number (1, 2, 3) and a specific error code (`llm_rate_limited`, `llm_timeout`, `llm_unavailable`, else `llm_error`). FakeLLM goes through the same retry path (tests use a no-wait sleep). | Matches the brief's "retry with backoff" and the 0007 production improvement: today SDK retries are invisible (one row, longer latency). Jitter avoids synchronised retries; reusing `OPENAI_MAX_RETRIES` adds no new config. |
| D6 | **Storage on existing records, one migration.** `extractions.grounding` (JSONB, nullable: the report + per-attempt history: reason and ungrounded fields); `agent_runs` gets `overall_confidence` (`NUMERIC(4,3)`, nullable) and `needs_review` (BOOLEAN, nullable) for metrics, while the full confidence report lives in the run's `result` JSON (`AgentResult.confidence`); `llm_calls.attempt` (INT, default 1). **History:** each run keeps its own confidence (and per-field grounding inside it); `extractions` stays one row per document, replaced on reprocess (0003 D9). | Grounding describes an extraction, confidence describes a run's result — they live where they belong, with no new table and no join. Two scalar columns keep metrics queries simple; run history already exists through `agent_runs`. |
| D7 | **API: additive fields only.** `GET /result` adds `confidence` (`overall`, `label`, `needs_review`, `components`, `fields{path: score, label, grounding status, page, span, reasons}`) — the brief's keys are untouched. `GET /extraction` adds `grounding` and the attempt history. `GET /metrics/summary` adds a `guardrails` block (D10). No new endpoint. | The UI already loads `/result`; one extra key keeps the client simple and the brief's shape intact. A separate endpoint would duplicate data that belongs to the result. |
| D8 | **Grounding is not a validation issue; the summary mentions fields that need review; status unchanged.** 0004's catalogue and `ValidationReport` stay as they are. The summary input gains the `low` / `ungrounded` fields; 0005's keyword check also requires them ("verify"/"review" + the field), with the same retry-once + code-appended sentence fallback. The document still ends `completed`; doubt is shown through `needs_review`. | Validation answers "is the document consistent?"; grounding answers "did we read it faithfully?" — mixing them would blur both. Reusing 0005's coverage mechanism guarantees the summary warns the reader. A new status would ripple through 0001–0007 for little gain. |
| D9 | **UI on the detail page.** (a) A **confidence badge** on every field in Structured data and every line-item cell: `High` / `Medium` / `Low` with an icon + text (never colour alone), score and reasons in a tooltip; ungrounded values get a "Not found in document" marker. (b) An **overall confidence chip** in the result header and a **"Needs review"** banner listing the fields to check. (c) **"Show in text"** on a grounded field scrolls the Raw text section to the match and highlights it. Status palette tokens (success / warning / danger), light + dark, 375 px. Old results without confidence show "Confidence not available — reprocess to compute". | Badges where the values are is the 0006 D17 promise; the banner makes doubt impossible to miss; "show in text" turns grounding into a one-click proof for a reviewer. |
| D10 | **Metrics: a small guardrails block.** `/metrics/summary` and the Metrics page add: average overall confidence, share of documents needing review, grounding rate (grounded ÷ checked values), extractions that needed a grounding retry, and transient retries (ledger rows with `attempt > 1`). Same `?days=` window. | Cheap on top of D6's columns and the ledger; shows whether quality changes over time. |
| D11 | **No backfill.** Extractions and runs from before 0008 keep `null` grounding / confidence; the UI says "reprocess to compute" (same pattern as 0007 D8). | Keeps the migration schema-only; reprocessing one document gives it full guardrails. (Alternative: a one-off deterministic backfill command — no LLM cost, but more code for old demo data.) |
| D12 | **Scope guard confirmed:** B5 (vision tables / layout), B3 (retrieval, Query Agent), B4 (multi-agent, Coordinator) and authentication stay out of 0008. | Keeps 0008 to the brief's guardrails bonus. |

## Constraints

- Layering: router → service → crud → model; `service.py` never imports FastAPI.
- Cross-module: modules import each other's `service` / `schema` only. `guardrails` is pure
  (no DB): it imports `structured_extraction.schema` and `validation.schema`; callers
  (`structured_extraction`, `agent`) import `guardrails.service`.
- All OpenAI access stays in `app/core/llm.py`; every new call has a `Purpose` and a
  `prompt_version`. Retries never change what a successful call returns.
- Grounding and confidence are deterministic code — same input, same output; no LLM.
- The guard chain `generate_summary` → `validate_invoice` → `check_grounding` is enforced
  by code, not by the prompt alone.
- Domain Rule 4 ("never invent values") still holds: retries may only replace a value with
  one copied from the document or with `null`.
- Bounded cost: at most 3 extraction calls per extraction and `1 + OPENAI_MAX_RETRIES`
  attempts per call.
- Money as `Decimal`; UUID v4 PKs; timezone-aware timestamps; errors use the shared
  `{error: {code, message}}` shape; routes under `/api`.
- Frontend: one typed API client, TanStack Query, Tailwind tokens, light + dark, 375 px;
  status never shown by colour alone.

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | Grounding marks values `grounded` / `weak` / `ungrounded` / `inferred` / `skipped` per D2 for: both number conventions, parentheses negatives, `50` vs `50.00`, each date format family incl. Malay months, ambiguous numeric dates (`weak`), identifiers (exact only), fuzzy text above / below threshold, `RM` → MYR (`inferred`), vision OCR confusions (`weak`); page and span are correct | unit tests |
| 2 | An ungrounded value makes `check_grounding` re-extract with feedback listing it (Purpose `grounding_retry`); a schema-invalid reply still retries as in 0003; the total never exceeds 3 calls per extraction; the attempt with the fewest ungrounded values is saved and remaining ones are flagged, not nulled | service tests (FakeLLM) |
| 2b | `validate_invoice` before `check_grounding` (or after a new `extract_structured_data`) returns the recoverable `grounding_required`; a scripted run that tries to skip grounding still ends grounded or does not complete | agent tests (FakeLLM) |
| 3 | Per-field and overall confidence, labels and `needs_review` match D4 for scripted cases (clean PDF → high; ungrounded total → needs review; vision text; validation error); `unknown` documents get none | unit tests |
| 4 | Transient errors (429, 5xx, timeout, connection) are retried with backoff + jitter up to `1 + OPENAI_MAX_RETRIES` attempts, `Retry-After` honoured; non-retryable errors are not; each attempt writes its own ledger row with `attempt` and a specific error code; SDK retries are off | core tests |
| 5 | `GET /result` includes `confidence`, `GET /extraction` includes `grounding` and attempt history; all existing keys unchanged; pre-0008 rows return `null` | router tests |
| 6 | The summary mentions every `needs review` field (keyword check, retry, appended sentence fallback) | service test |
| 7 | `/metrics/summary` returns the guardrails block for seeded data and respects `?days=` | service + router tests |
| 8 | `alembic upgrade head` adds `extractions.grounding`, `agent_runs.overall_confidence` / `needs_review`, `llm_calls.attempt` | migration test |
| 9 | `guardrails` imports no other module's `crud` / `model` and nothing from FastAPI or the DB | import test |
| 10 | Detail page shows field and line-item badges (icon + text), the overall chip, the needs-review banner, "show in text" highlighting and the "reprocess to compute" state; Metrics page shows the guardrails block | Vitest + browser check (desktop + 375 px, light + dark) |
| 11 | `ruff check`, `ruff format --check`, `pytest`, `npm run lint`, `typecheck`, `test` (also with `TZ=UTC`), `build` pass; CI green | CI run |

## Roadmap Phase

**Phase:** Phase 3 — Bonus Tasks (B2, after B1 so every retry and re-extraction is traced).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0008-guardrails-plan.md` | Plan | Implementation path (written after this PRD is final) |
| `docs/prd/0002-text-extraction-prd.md` | Intent | `raw_text`, page markers, `pdf_parser` / `vision` method |
| `docs/prd/0003-structured-extraction-prd.md` | Intent | `InvoiceData`, the retry loop (D5) this extends, `extractions` |
| `docs/prd/0004-validation-prd.md` | Intent | `ValidationReport`, required-field table used for completeness |
| `docs/prd/0005-agent-prd.md` | Intent | Tools, summary coverage check (D3), `GET /result` |
| `docs/prd/0006-frontend-prd.md` | Intent | Detail page sections prepared for badges (D17) |
| `docs/prd/0007-observability-prd.md` | Intent | `llm_calls` ledger, `Purpose` labels, metrics |
| `docs/reference/folder-structure.md` | Reference | Structural placement of the module |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this PRD |

## Open Questions

None — D1–D12 agreed with the user on 2026-10-27 (grounding as a separate
`check_grounding` agent tool, enforced by a code guard before `validate_invoice`;
per-kind matching rules with `rapidfuzz`, Malay month names and looser OCR rules for
vision text; whole-object re-extraction with feedback inside a shared 3-call budget, best
attempt kept, ungrounded values flagged not nulled; 0–1 confidence + high / medium / low
labels from grounding, validation and completeness, no logprobs, `needs_review` flag;
transient retries in our seam with backoff + jitter, one ledger row per attempt; storage on
`extractions`, `agent_runs`, `llm_calls`; additive API fields; grounding not a validation
issue, summary mentions fields to review, status unchanged; badges, banner and "show in
text" on the detail page; a guardrails block on Metrics; no backfill; B5 / B3 / B4 / auth
out of scope).
