# Workflows — the orchestral harness

A hands-off orchestration layer over the `.claude/` agents and skills. The user
describes an outcome in plain language; the **orchestrator** agent routes it to a
workflow and runs that workflow end-to-end, spawning specialist agents in a
fixed, gated sequence. No `@agent` or skill tagging. New workflows are added
declaratively — one YAML file + one registry entry — with **no change to the
orchestrator**.

> **Terminology:** `.claude/GLOSSARY.md` is the source of truth for what things
> are called. **workflow** is the canonical noun ("cycle"/"pipeline" are human
> synonyms only).

> **How this executes:** this is *not* a compiled engine. `registry.yml`, the
> workflow YAMLs, and fields like `match`, `on_complete`, and `max_retries` are
> conventions the `orchestrator` (an LLM) reads and follows via its prompt. The
> only deterministic guarantee is the `validate-config` **script**.

## Files

| File | Role |
|------|------|
| `registry.yml` | Routing source of truth: `id`, `workflow`, `description`, `match.intent`, `priority`, `enabled`, plus `fallback: adhoc`. Ships with **no routes** — every request uses the ad-hoc fallback until you author a workflow. |
| `_template.yml` | Copy-to-create a new workflow. `_`-prefixed files are **non-routable**. |

No concrete workflow ships by default; author one with the `workflow-author`
agent (or by hand from `_template.yml`). Agents live in `.claude/agents/`;
skills in `.claude/skills/`. The `validate-config` skill bundles the validator
script.

## Routing (selection algorithm)

1. User names a workflow/route explicitly → use it.
2. Otherwise score each `enabled` route by `match.intent` overlap with the
   request; highest wins (ties → `priority`, then list order).
3. No positive match → built-in, domain-agnostic **ad-hoc** route (`executor` → `executor` self-review).
4. Registry missing/malformed → ad-hoc + a note in the summary.
5. `_`-prefixed files are ignored everywhere.

## Workflow schema

```yaml
name: Human-readable name
description: What this workflow accomplishes.
match:
  intent: [keyword, ...]     # routing keywords
  priority: 50               # higher wins ties
steps:
  - id: unique-step-id
    type: agent|manual       # optional; default `agent`. `manual` escalates to the user
    agent: agent-name        # required for `agent` steps; must exist under .claude/agents/
    skill: skill-name        # optional; must exist under .claude/skills/
    action: "What to do"
    requires: [step-id, ...] # dependencies
    parallel_with: [step-id] # run concurrently
    input: "path"            # supports {project-name}, {NN}, {slug}
    output: "path"
    mandatory: true|false    # false → fast lane may skip it
    # Gated step: on_complete REQUIRES a verdict_contract + max_retries
    verdict_contract: ["APPROVE", "REVISE"]
    max_retries: 3
    on_complete:
      APPROVE: { next: other-step }
      REVISE: { next: this-or-earlier-step }
```

### Step types

Every step has a `type` (default **`agent`**):

- **`agent`** — the orchestrator spawns `agent` (optionally using `skill`) to do the work.
- **`manual`** — the orchestrator **pauses and escalates to the user** (a decision,
  approval, or destructive action). No `agent`; use `action` to state what's needed.

### Verdict contract

Any gated step declares the exact tokens its agent returns. The agent **must emit
a machine-checkable final line**, e.g. `VERDICT: REVISE`, and the orchestrator
branches on it. A verdict outside the contract, or a missing verdict line, is
treated as a failure (see robustness rules).

### Conditional gates for efficiency

Use gates to avoid expensive follow-up work when the previous step proves it is
unnecessary. Common patterns:

- `CHANGED | NOOP | BLOCK` for generation, sync, or knowledge-update steps.
- `PASS | WARN | BLOCK` for preflight checks before implementation.
- `APPROVE | REVISE` for review loops.

Route clean/no-op paths to `done`, and route only the changed or blocked paths to
review, regeneration, broad validation, or a manual decision. The chosen
`on_complete` branch is the active path; unrelated later steps should not run
just because their `requires` are satisfied.

### Robustness rules (orchestrator prompt)

- **G-A hard-failure** — on agent error/timeout/`maxTurns`/unrecognized verdict:
  retry once, then stop with a partial summary.
- **G-C placeholder resolution** — `{project-name}` from repo/`docs/`; `{NN}` =
  highest existing `docs/specs/phase-*` or `01`; ad-hoc uses scratch paths
  (`docs/plans/adhoc-{slug}-*`).
- **G-D parallel join** — wait for all `parallel_with`; pass only if all succeed;
  re-run any failed step via its own agent, capped by `max_retries`.
- **Recursion guard** — no step may spawn `orchestrator` or `workflow-author`.

## Authoring a custom workflow

Two ways, both without touching the orchestrator:

- **Ask the AI:** "add a `<name>` workflow that does X → Y → Z" — the
  `workflow-author` agent scaffolds and registers it.
- **By hand:** copy `_template.yml` to `.claude/workflows/{id}.yml`, fill `match`
  + `steps` (each `agent`/`skill` must exist; gated steps need a verdict
  contract), run the validator, then add an `enabled` route to `registry.yml`.

**Project vs core:** a workflow that belongs to this project (not the shared
harness) must be namespaced `proj-<id>.yml` so it stays separate from the
checksum-locked core. Same for its agents (`proj.*`) and skills (`proj-*`). See
"Reuse across projects" in `../../CLAUDE.md`.

Project-specific workflows and skills should not be promoted into the reusable
core template. Keep reusable structure here, and record domain-specific
instructions in project knowledge (`CLAUDE.project.md`, `docs/project-knowledge.md`,
or namespaced `proj-*` capabilities created inside the downstream project).

## Validation (the one deterministic check)

```bash
python .claude/skills/validate-config/scripts/validate_config.py            # full scan
python .claude/skills/validate-config/scripts/validate_config.py <file>     # single workflow
```

Checks frontmatter validity, agent `skills:` refs, registry → workflow
resolution, step `agent`/`skill` resolution, `fallback` value, the recursion
guard, and verdict-contract presence on gated steps. Skips `_*.yml`. Exits
non-zero on **errors only** (warnings are informational).
