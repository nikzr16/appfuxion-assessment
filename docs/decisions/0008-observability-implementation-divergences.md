# 0008 - Observability implementation details that differ from the 0007 plan

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

Implementing `docs/plan/0007-observability-plan.md`, testing it and checking the UI in the
browser against a running backend changed a few details the PRD or plan had named or only
sketched. None changes the PRD's decisions D1–D14, the ledger's columns or the two routes.

## Decision

1. **Error code of a rejected structured reply.** PRD D3 calls it `invalid_llm_output`. The
   ledger stores the exception's own code, and the LLM client raises `LLMOutputError` with
   code `llm_invalid_output` (0003 later turns it into its own `invalid_llm_output` domain
   error). So the ledger row says `llm_invalid_output`; it is the same event.
2. **`bind_trace` doubles as a decorator.** The plan showed `with bind_trace(...)` blocks in
   each caller. The single-purpose helpers (`_transcribe_pages`, `_extract_with_retry`, the
   summary tool's `_complete`) are decorated instead (`@bind_trace(purpose=…,
   prompt_version=…)`), which needs no re-indentation and keeps the label next to the function
   it describes. The runner and the agent service use `with` blocks as planned.
3. **Embeddings default to the `embedding` purpose.** An unlabelled `embed` call is recorded as
   `embedding` without a warning (there is only one kind of embedding call); only an
   unlabelled chat call becomes `unknown` with a warning. A call that fails with something
   other than an `AppError` (e.g. `FakeLLM` running out of replies) is recorded with
   `internal_error`.
4. **Trace card additions.** Besides the planned totals strip and timeline, the card shows a
   "Tokens by purpose" row (from `by_purpose`, already in the response) and a legend for the
   bar colours (tool step / LLM call / failed). The planning turns are shown as one line above
   the lanes inside the Agent activity card, rather than in its header, where they did not fit
   next to the run status at phone width.
5. **Timeline colours are new tokens.** The tool and LLM bars use `--series-tool` /
   `--series-llm` (indigo / orange, separate values for dark mode), not the existing accent
   and info tokens: the palette validator failed accent + info on normal-vision separation
   (ΔE 14.8 light, 12.6 dark). The chosen pair passes every check in both themes.
6. **Layout fixes from the browser check.** At 375 px, step labels and tile hints wrap
   instead of truncating, and the cost tile spans both columns. On the Metrics page the two
   usage tables are stacked full width (side by side at 1280 px they needed a horizontal
   scroll), number cells do not wrap, and below `sm` each table becomes a stacked list.
7. **Price table source.** OpenAI's pricing page no longer lists the 4.1 / 4o families, so the
   prices were checked on each model's page (`developers.openai.com/api/docs/models/<model>`)
   on 2026-10-27; all seven match the table. That page marks `gpt-4.1-mini`, the default
   `OPENAI_MODEL`, as deprecated (recorded as a limitation).
8. **Small read helpers in earlier modules.** As planned, `documents` gained
   `count_by_status` (+ an internal `DocumentCounts` DTO) and `agent` gained `run_stats`,
   `completed_run_ids` and a `RunStats` DTO, which is also part of the `MetricsSummary`
   response. The runner gained an optional `prompt_version` argument.

## Reason

1, 3 and 8 follow from recording each exception's own code and reading other modules only
through their services. 2 keeps the label changes to one line per caller. 4–6 came from using
the page at desktop and phone width in both themes. 5 came from running the dataviz palette
validator instead of eyeballing the colours. 7 is where the prices are published today.

## Impact

- [ ] Workflow doc updated
- [x] Reference doc updated (`docs/reference/folder-structure.md`: tree, routes, schemas, `llm_calls`, wiring)
- [ ] No upstream doc update needed
