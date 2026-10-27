# 0013 - Multi-agent implementation details that differ from the 0011 PRD and plan

> **Date:** 2026-10-27 | **Status:** Accepted

<!-- AI Context
Role: This is an append-only record of a single implementation divergence.
Each entry captures why the deviation happened and what it affects.
Never edit an existing decision log entry. To reverse a previous decision,
create a new entry that references the original. After adding an entry,
check the impact checklist below and update affected workflow or reference
docs before the session ends.
-->

## Context

PRD 0011 D9 said the Metrics page "by agent" grouping would show the new agents "with no
code change", and plan §9 added a "By agent" table "with no API change". While writing the
plan, it turned out the Metrics page renders only "By model" and "By purpose". During coding
it also turned out that `GET /metrics/summary` has no `by_agent` field: only the
per-document trace (`GET /documents/{id}/trace`) groups by agent. The user approved the
table together with the plan.

## Decision

1. **`GET /metrics/summary` gains an additive `by_agent: GroupTotals[]`** (same shape as
   `by_model` / `by_purpose`). `observability.crud.group_totals` accepts `by="agent"` and
   groups on `coalesce(agent, 'unknown')`, as the trace already does. The Metrics page shows
   it as a "By agent" table with readable names (`document` → Document Agent, `extraction` →
   Extraction Agent, …, `unknown` → "Outside an agent"). The frontend type marks the field
   optional, so an older backend still renders.
2. **The live-progress write reuses `crud.set_steps`.** The plan named a new
   `crud.set_progress`. Instead, `set_steps` takes an optional `agents` list and writes both
   columns in one update. This avoids two near-identical functions.
3. **Lane wording.** The Validation lane is now described as "Checks totals, dates, currency
   and vendor history; converts the total", and the Reporting lane as "Finds similar invoices
   and writes the summary". This matches the tools each agent really has (0010 added them;
   the 0006 text predates them). A lane whose agent never started keeps the "Not reached"
   badge and says "The run stopped before this agent started."

## Reason

The user asked for per-agent cost on the Metrics page. Without a backend field the page
could only show the latest document's numbers. One additive field reuses the existing
grouping query and response shape, so the risk stays small, and no client breaks. The other
two items are naming and wording only.

## Impact

- [x] Tests: `test_metrics_summary_aggregates_documents_runs_and_the_ledger` (by_agent),
      `test_metrics_summary` router test, `MetricsPage.test.tsx` "By agent" region
- [x] `docs/reference/folder-structure.md` lists the new `by_agent` field
- [x] No migration and no config change for these items
