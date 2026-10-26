# 0006 - Agent implementation details that differ from the 0005 plan

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

Implementing `docs/plan/0005-agent-plan.md` changed a few details the plan had fixed or only
sketched. None changes the PRD's decisions D1–D16, the routes, the result shape, the table's
columns or the error codes.

## Decision

1. **`BASE_CURRENCY` is checked for its shape only.** The plan said the setting must be a
   currency in the 0004 rate table (a start-up error otherwise). `app/core/config.py` only
   checks that it is three letters (strip, upper-case). An unsupported base currency surfaces
   as a recoverable `unsupported_currency` tool error when the agent tries to convert.
2. **The whole PDF render holds the lock.** The plan wanted the JPEG preparation outside the
   pypdfium2 lock "where practical". The PIL image returned by `to_pil()` shares memory with
   the pdfium bitmap until it is prepared, so `_prepare_image` stays inside the lock.
3. **Crud names.** `crud.append_step` became `crud.set_steps` (the service rewrites the whole
   step list after each tool call; the list is tiny), and `crud.fail_stale_running` became
   `crud.fail_running` (it returns how many runs it closed).
4. **Tests disable the pipeline by registration, not by a dependency override.** The global
   autouse fixture calls `register_pipeline_runner(None)` and agent tests opt in with
   `agent_pipeline`. The plan's override-based default would have been undone by the 0001
   tests that pop their own override; with registration those tests needed no change other
   than one renamed test.
5. **An `AppError` that a tool did not classify is fatal with its own code.** The plan only
   covered non-`AppError` exceptions (`internal_error`). The runner now also turns an
   unclassified `AppError` into a fatal step with that error's code; the document tools
   classify every error themselves, so this only protects future agents.
6. **An empty summary gets its own retry message.** The plan treated an empty reply as
   "missing every issue". The retry now says "Your reply was empty …" instead of listing
   issues (a clean document has none to list); an empty reply after the retry is still the
   fatal `invalid_llm_output`.
7. **The run's `model` starts as `OPENAI_MODEL`** and is replaced by the model that actually
   answered the agent loop when the run ends, so a run that fails before its first reply
   still records which model was configured.

## Reason

Each change keeps the layering rules (core never imports a feature module), avoids a
use-after-free risk in pdfium, or makes the tests and logs simpler without changing behaviour
the PRD defines.

## Impact

- [ ] Workflow doc updated
- [x] Reference doc updated (`docs/reference/folder-structure.md` describes the final names)
- [ ] No upstream doc update needed
