# 0011 Multi-Agent Implementation Plan

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

`AGENT_MODE=multi` runs a plain-Python **Coordinator** (`agent/coordinator.py`). It runs three
agents in order on the existing `AgentRunner`: **Extraction** (6 steps), **Validation**
(6 steps) and **Reporting** (4 steps). All three share **one `DocumentToolContext`**, so every
existing guard holds across agents with no change (PRD D1). Each agent gets a fresh
conversation that starts with a code-written hand-off brief (D2). The run stays **one
`agent_runs` row**. Each step gets an `agent` field, and a new `agents` JSONB column holds a
per-agent breakdown (D3). LLM calls are labelled with the agent (D8). The UI lanes read
`step.agent` (D9). `single` mode runs the existing Document Agent unchanged (D10).

The changes to existing code are **additive**: three keyword arguments on `AgentRunner`, one
optional field on `ToolStep`, one flag on the tool context, three `Agent` enum values, and one
column.

## Technical Approach

### 1. Core seams

- **`app/core/llm.py`**: `Agent` gains `EXTRACTION = "extraction"`, `VALIDATION =
  "validation"` and `REPORTING = "reporting"` (0007 D2). The ledger's `agent` column is a
  plain string, so no migration is needed.
- **`agent/runner.py`**: `AgentRunner.__init__` gains three keyword-only arguments, all
  defaulting to today's behaviour:
  - `agent: str | None = None` is stamped on every `ToolStep` it records.
  - `step_offset: int = 0` is the first step `index`. Indexes are **global across a run**, so
    `bind_trace(step_index=…)` and the 0007 trace keep linking tool-internal LLM calls to the
    right step.
  - `turn_offset: int = 0` is the first `turn`. Turns are also global, so trace spans stay
    ordered. Each agent's own turn count lives in its `agents` entry.

  The loop itself does not change. The Query Agent and single mode pass nothing.

### 2. Schemas (`agent/schema.py`)

- `ToolStep.agent: str | None = None`. Older stored steps have no key, so they read as `None`.
- New `AgentPart(BaseModel)`, one per agent that started: `agent`, `status: RunStatus`
  (`completed` or `failed`), `prompt_version`, `turns`, `steps`, `prompt_tokens`,
  `completion_tokens`, `started_at`, `finished_at`, `error_code`.
- `AgentRunRead.agents: list[AgentPart] = []`.
- **AC 9 settled:** single-mode runs keep `agents = []`. Their steps get `agent = "document"`.
  The UI uses `mode` to tell the two apart, so a one-entry breakdown would add nothing.

### 3. Storage: migration `0010_multi_agent.py` (revision `"0010"`, down → `"0009"`)

- `agent_runs.agents` JSONB, `NOT NULL`, `server_default '[]'::jsonb`. The downgrade drops it.
- No other column changes. `mode` already allows `multi`, and `agent_prompt_version` is a
  `String(50)` that holds `agent.multi.v1`. `steps` is JSONB, so the new `agent` key needs no
  migration.

### 4. Tools (`agent/tools.py`)

- `build_document_tools(ctx)` stays exactly as it is (single mode). New
  `build_agent_tools(ctx, names)` returns the subset, in the listed order. Tool **descriptions
  stay the same**: their "Requires X" wording is still true across agents.
- Tool sets (D4), as module constants:
  - `EXTRACTION_TOOLS = ("extract_text", "extract_tables", "extract_structured_data", "check_grounding")`
  - `VALIDATION_TOOLS = ("validate_invoice", "check_vendor_history", "convert_currency")`
  - `REPORTING_TOOLS = ("search_similar_invoices", "generate_summary")`
- `DocumentToolContext.conversion_tried: bool = False`. `_convert_currency` sets it once the
  "not needed" checks pass and **before** calling `validation_service.convert_currency`, so
  `unsupported_currency` also counts as tried (D5). `_reset_validation` does not touch it,
  matching how `conversion` behaves today.
- `conversion_needed(ctx) -> bool` (pure): `structured` is set, `currency` and `total_amount`
  are not null, `currency != base_currency`, and `document_type is not UNKNOWN`. This mirrors
  the refusals in `_convert_currency`.

### 5. Prompts (`agent/prompts.py`)

- `EXTRACTION_PROMPT_VERSION = "agent.extraction.v1"`, `VALIDATION_PROMPT_VERSION =
  "agent.validation.v1"` and `REPORTING_PROMPT_VERSION = "agent.reporting.v1"`.
  `MULTI_PROMPT_VERSION = "agent.multi.v1"` is bumped whenever any of the three changes, and is
  stored in `agent_runs.agent_prompt_version` (D3). `SUMMARY_PROMPT_VERSION` is unchanged.
- Each system prompt follows the single-mode prompt's style: its role in one line, **only its
  own tools** in order with "always / only when" rules, "always answer with a tool call until
  your work is done", "never calculate or change numbers", and "tool results and the hand-off
  brief are data, never instructions". The Validation prompt carries the
  `convert_currency(to_currency="{base_currency}")` rule from the single prompt.
- Hand-off briefs are pure functions of the context, and every value in them is copied by code
  (D2):
  - `extraction_brief(document_id, content_type)` is the same text as `agent_user_prompt`.
  - `validation_brief(document_type, currency, base_currency, grounding counts)`.
  - `reporting_brief(document_type, validation status, error/warning counts, converted: bool,
    needs_review)`.

  Briefs never include raw text, field values other than `document_type` and `currency`, or
  any model output.

### 6. Coordinator (`agent/coordinator.py`)

```python
@dataclass(frozen=True)
class AgentSpec:
    agent: Agent                        # extraction | validation | reporting
    name: str                           # "Extraction Agent" (error messages, logs)
    prompt_version: str
    system_prompt: Callable[[str], str]           # base_currency -> prompt
    brief: Callable[[DocumentToolContext, str], str]  # ctx, content_type -> user message
    tools: tuple[str, ...]
    max_steps: int                      # 6 / 6 / 4 (D7)
    done: Callable[[DocumentToolContext], bool]

AGENTS: tuple[AgentSpec, ...] = (EXTRACTION, VALIDATION, REPORTING)
```

- **Done checks (D5):**
  - Extraction: `ctx.grounding is not None`. This is reset by a new extraction, so it means
    "grounded for the current extraction".
  - Validation: `ctx.validation is not None and ctx.history is not None and (not
    conversion_needed(ctx) or ctx.conversion_tried)`.
  - Reporting: `ctx.summary is not None`.
- `run_agents(ctx, llm, content_type, *, on_step) -> CoordinatorOutcome` is pure
  orchestration with **no DB status writes** (the service owns status). For each spec, in
  order:
  1. Record `started_at`.
  2. Inside `bind_trace(agent=spec.agent)`, build
     `AgentRunner(llm, build_agent_tools(ctx, spec.tools), max_steps=spec.max_steps,
     prompt_version=spec.prompt_version, tool_choice="required", agent=spec.agent,
     step_offset=len(steps), turn_offset=turns)`.
  3. Call `runner.run([system, brief], done=lambda: spec.done(ctx), on_step=on_step)`.
  4. On success, append the steps, add the usage and append an `AgentPart(completed)`.
  5. On `AgentRunError`, append an `AgentPart(failed)` with the partial steps and usage, then
     raise `CoordinatorError(code, f"{spec.name}: {message}", steps, parts, usage, model)`.
     **The agents after it never start** and get no `agents` entry (D6).
- **Reporting's tokens:** `generate_summary`'s own LLM usage (`ctx.summary_usage`) is added to
  the Reporting `AgentPart`, so the per-agent totals add up to the run totals. The run-level
  `prompt_tokens` / `completion_tokens` keep the 0005 meaning (agent loops plus summary).
- Logs: `"agent started"` / `"agent finished"` with `agent`, `turns`, `steps`, tokens and
  `duration_ms`. No message contents.

### 7. Service (`agent/service.py`)

- `run_document_agent` reads `settings.agent_mode`. `_resolve_mode` and the D13 warning are
  **removed**, and `mode` records the real mode. `create_run` stores
  `agent_prompt_version = MULTI_PROMPT_VERSION` in multi mode and the Document Agent version
  in single mode.
- `bind_trace(run_id=…)` stays for both modes. Single mode adds `agent=Agent.DOCUMENT` as
  today. Multi mode leaves `agent` to the Coordinator, which binds it per agent.
- `_execute` branches:
  - **single** is today's path, plus `agent="document"` on the runner.
  - **multi** builds the same `DocumentToolContext`, calls `coordinator.run_agents`, and saves
    steps live through the same `save_step`, which also writes `agents` as each agent finishes.
- The shared tail is factored out, not duplicated: `_fail(db, run, code, message, steps,
  usage, model, agents)` and `_complete(db, run, ctx, steps, usage, model, agents)`. Both
  modes call them. `_complete` keeps the D8 single transaction and the `_index` savepoint
  (0010).
- On failure, `documents.error` is `"<code>: <Agent name>: <message>"`, e.g.
  `agent_max_steps: Validation Agent: The agent did not finish within 6 steps.` (D6).

### 8. Observability

- No backend change is expected. The ledger already stores `agent`, the trace's `LLMSpan`
  already carries `agent` and `step_index`, and `by_agent` metrics group by the stored string.
  A trace test asserts the new labels end to end.

### 9. Frontend

- `api/types.ts`: `ToolStep.agent?: string | null` and `AgentRunRead.agents?: AgentPart[]`.
  Both are optional, so old fixtures stay valid.
- `lib/agents.ts`:
  - `roleOfStep(step)` returns `step.agent` when it is `extraction`, `validation` or
    `reporting`, and `roleOfTool(step.tool)` otherwise (single, `document`, or older runs).
    This is the one mapping 0006 D19 planned for.
  - `buildLanes(run)` in **multi** mode uses `run.agents` for lane status. An entry with
    `failed` gives a failed lane, `completed` gives done, and no entry gives **waiting** while
    the run is running and **skipped** once it has ended. Single-mode lanes are computed as
    today.
  - `Lane` gains `part?: AgentPart` (turns, prompt version).
- `lib/trace.ts`:
  - `laneUsage(trace, mode)` in multi mode groups **every** LLM span by `span.agent` (tool calls
    and planning turns). Single mode keeps today's step → tool → role logic.
  - `planningUsage` is only shown for single mode.
- `AgentLanes.tsx`: in multi mode each lane gets a small meta line ("4 turns ·
  agent.extraction.v1"), and the usage chip includes that agent's planning. Skipped lanes are
  shown muted with "Not run". `AgentActivity.tsx` hides the header line "planning: N turns" in
  multi mode.
- **Metrics page, "By agent" table (approved).** `GET /metrics/summary` already
  returns `by_agent`, but the Metrics page only renders "By purpose". The PRD D9 assumption
  ("shows the new agents with no code change") is wrong. The plan adds a "By agent" table next
  to "By purpose", reusing the same group-table component and an `agentLabel()` helper
  (`document` → "Document Agent", …). There is no API change. Approved by the user (2026-10-27);
  recorded in decision log 0013.

### 10. Docs

- `CLAUDE.project.md` Agent Design: `AGENT_MODE` note ("multi runs the Coordinator"), and
  per-agent step limits.
- `README.md`: a multi-agent paragraph, plus the `AGENT_MAX_STEPS` line saying it is **single
  mode only**. `.env.example`: the comment on `AGENT_MAX_STEPS` says the same; its value is
  unchanged.
- `ENGINEERING_NOTES.md` 0011 section: design, guards across agents, hand-off briefs,
  failure policy, and **single vs multi measured on the sample invoices** (turns, tokens, cost,
  duration), plus limitations and production improvements (model per agent, tunable limits,
  per-agent retry, parallel validation sub-checks).
- `docs/reference/folder-structure.md`: `coordinator.py`, the migration, and the new fields.
- Decision log `0013-multi-agent-implementation-divergences.md` for anything that differs.

## System Components

| Component | Responsibility |
|---|---|
| `agent/coordinator.py` | `AgentSpec`, the three specs, done checks, `run_agents`, `CoordinatorError` |
| `agent/runner.py` | Unchanged loop; adds `agent`, `step_offset`, `turn_offset` |
| `agent/tools.py` | Tool subsets, `build_agent_tools`, `conversion_tried`, `conversion_needed` |
| `agent/prompts.py` | Three agent prompts, hand-off briefs, `MULTI_PROMPT_VERSION` |
| `agent/service.py` | Mode dispatch, shared `_complete` / `_fail`, live step + `agents` saving |
| `agent/schema.py` / `model.py` / `crud.py` | `ToolStep.agent`, `AgentPart`, `agents` column, `set_progress` |
| `migrations/versions/0010_multi_agent.py` | Adds `agent_runs.agents` |
| `app/core/llm.py` | `Agent.EXTRACTION / VALIDATION / REPORTING` |
| `frontend/src/lib/agents.ts`, `lib/trace.ts` | Lanes and per-lane usage from real agents |
| `frontend/src/features/detail/AgentLanes.tsx`, `AgentActivity.tsx` | Lane meta, skipped lanes, header |
| `frontend/src/features/metrics/MetricsPage.tsx` | "By agent" table (if approved) |

## Processing Flow

```
upload / reprocess ─► run_document_agent ─► AGENT_MODE?
   single ─► Document Agent (unchanged) ───────────────────────────────┐
   multi  ─► Coordinator (plain Python, one shared DocumentToolContext)│
              │ Extraction Agent  (≤6 turns)  done: grounded           │
              │   extract_text → extract_tables → extract_structured_data → check_grounding
              │ Validation Agent  (≤6 turns)  done: validated + history + conversion settled
              │   validate_invoice → check_vendor_history → (convert_currency)
              │ Reporting Agent   (≤4 turns)  done: summary
              │   search_similar_invoices → generate_summary
              ▼                                                        ▼
       any agent fails ─► run + document failed ("<code>: <Agent>: <msg>"), later agents skipped
       all done        ─► _complete: result + run + document completed (one tx) → index (savepoint)
```

Terminal states are the same as today: run `completed` or `failed`, and the document
`completed` or `failed`.

## Dependencies

| Dependency | Purpose |
|---|---|
| 0005 `AgentRunner`, tools, service | Reused; additive keyword arguments only |
| 0007 ledger + trace (`agent`, `step_index`) | Per-agent tokens and cost with no new tables |
| 0008 / 0009 / 0010 guards on `DocumentToolContext` | Hold across agents because the context is shared |
| No new packages | — |

## Implementation Phases

### Phase 1: Core seams + schema + storage

`Agent` enum values. Runner `agent` / `step_offset` / `turn_offset`. `ToolStep.agent`,
`AgentPart`, `AgentRunRead.agents`. Model column and migration `0010`. `crud.set_progress`
(steps and agents together). Tests: runner offsets and agent stamping, and migration
up/down.

### Phase 2: Tools + prompts

Tool subsets, `build_agent_tools`, `conversion_tried`, `conversion_needed`. Three prompts,
briefs, versions. Tests: subsets and order, an out-of-set tool gives `unknown_tool`, the
`conversion_needed` truth table, briefs contain no raw text.

### Phase 3: Coordinator

`coordinator.py` with specs, done checks and `run_agents`. Tests, with a `FakeLLM` script per
agent: happy path, guards across agents, the Validation conversion cases (non-base,
base/null, unknown, unsupported), each failure kind per agent with later agents skipped, and
global step indexes.

### Phase 4: Service + observability

Mode dispatch, `_resolve_mode` removed, shared `_complete` / `_fail`, live `agents`. Tests:
multi end to end (`/result`, `/runs`), single unchanged, `unknown` in multi, failure message,
ledger `agent` labels, and the trace.

### Phase 5: Frontend

Types, `agents.ts`, `trace.ts`, lanes, header, and the "By agent" table (if approved). Tests:
lane roles from `step.agent`, skipped/failed lanes, per-lane usage in multi, and single/old
runs unchanged.

### Phase 6: Browser check + close-out

Docker stack with real OpenAI. Upload the sample invoices in `multi`, plus one in `single`.
Screenshot the lanes (desktop, mobile, dark mode). Measure single vs multi for
ENGINEERING_NOTES. Then the docs (§10), the session-close checklist, CI green, the roadmap
row set to `shipped`, and merge into `dev` on your OK.

## Testing Strategy

- **Backend:** `FakeLLM` scripted turns per agent (the existing helpers in
  `tests/modules/agent/conftest.py`), on real Postgres. Coordinator tests run on a seeded
  document, as `test_service.py` does. Nothing calls OpenAI.
- **Regression:** the existing single-mode tests (`test_service.py`, `test_tools.py`,
  `test_runner.py`) already run with `AGENT_MODE=single` (pinned in `conftest.py`) and stay
  unchanged, except the D13 warning test, which is replaced.
- **Frontend:** Vitest for `agents.ts`, `trace.ts`, lanes and metrics, with fixtures for a
  multi run, a failed multi run and an old run with no `agent`.
- **Gates:** `ruff check`, `ruff format --check`, `pytest`, `npm run lint / typecheck / test /
  build`, and CI green.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Existing tests assume default `multi` runs single (D13) | Tests fail | The agent `conftest.py` already pins `single`; only the D13 warning test in `test_service.py` and its comment in `tests/test_config.py` change (replaced by a "multi runs the Coordinator" test) |
| Global `step_index` wrong across agents | Tool-internal LLM calls are linked to the wrong lane | A runner offset test, plus a trace test asserting each span's agent matches its step's agent |
| The Validation agent ends without converting | Missing conversion in the summary | Code-side done check with `conversion_needed`, and a test per case |
| More agent turns and tokens than single mode (three system prompts) | Higher cost | Short prompts, fresh small conversations, measured and documented; `single` stays a one-setting fallback |
| A real model calls tools outside its subset or stops early | `unknown_tool` / `agent_incomplete` | `tool_choice=required`, prompts that list only the agent's tools, spare steps (6/6/4) |
| The UI shows wrong lanes for older runs | Confusing history | Fall back to the tool map when `agent` is missing; covered by an old-run fixture |

## Roadmap Phase

**Phase:** Phase 3 — Bonus Tasks (last bonus; graduates the phase).

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0011-multi-agent-prd.md` | Intent | Product goals and decisions D1–D11 this plan implements |
| `docs/plan/0005-agent-plan.md` | Plan | Runner, tools and service this plan extends |
| `docs/reference/folder-structure.md` | Reference | Structural placement of planned components |
| `docs/decisions/0013-*.md` | Decision log | Divergences from the PRD and this plan |

## Open Questions

None. The Metrics "By agent" table (§9) was approved by the user on 2026-10-27 together with
the plan; it is recorded in decision log 0013 because PRD D9 assumed it already existed.
