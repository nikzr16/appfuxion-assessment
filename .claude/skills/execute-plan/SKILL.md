---
name: execute-plan
description: Systematically carries out a task step by step with verification at each step, in any domain (code, writing, research, data, ops, config). Works from an explicit plan when one exists, or directly from the request. Use when building, changing, or producing something.
---
# Execute Plan

Carry out work systematically, one step at a time, verifying each step before
moving on. This skill is **domain-agnostic** and self-contained: it works whether
the task is code, prose, data, research, configuration, or operations, and
whether or not a formal plan document exists.

## When to Use

- Producing or changing an artifact of any kind.
- Executing steps from a plan, task list, or issue.
- Running the `execute` step of a workflow or the ad-hoc route.

## Inputs (use whatever is available)

- An explicit plan / task breakdown, if one was provided.
- Otherwise, the user's request plus the current state of the workspace.
- Relevant existing material and conventions (read on demand, not all up front).

If requirements are ambiguous, resolve the smallest next unknown by reading the
relevant file — don't stall, and don't invent scope that wasn't asked for.

## Execution Loop

1. **Scope** — restate the goal and list the concrete steps in dependency order.
   For a small change this may be a single step.
2. **Do the work** — for each step:
   - Read what you're about to change and its immediate context.
   - Produce complete, finished output — no placeholders or "TODO later".
   - Follow the domain's conventions (style, format, structure) already in use.
   - Handle failure/edge cases; never hardcode secrets or environment-specific values.
3. **Verify** — run the domain's natural check after each step (a build, tests,
   a linter, a dry run, a re-read for factual/logical consistency). Fix what you
   broke before moving on.
4. **Confirm** — check the step's acceptance criteria (or the request's intent)
   are actually met.
5. **Repeat** in order, respecting dependencies.

## Definition of Done

- [ ] Output complete and consistent with the domain's conventions
- [ ] Failure/edge cases handled; no hardcoded secrets/config
- [ ] Verified by the domain's natural check (tests, build, review, dry run…)
- [ ] Acceptance criteria / request intent satisfied
- [ ] Supporting docs or notes updated where behavior/content changed

## Pitfalls to Avoid

- ❌ Placeholders or unfinished sections left behind
- ❌ Skipping verification
- ❌ Adding scope that wasn't requested
- ❌ Ignoring failure/edge cases or hardcoding values
- ❌ Loading the whole workspace up front instead of on demand
