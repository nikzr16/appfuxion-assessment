---
name: generate-workflow
description: Create and generate new orchestration workflows for the .claude harness. Scaffolds a workflow YAML from the template, validates it, and registers it in registry.yml. Use when the user asks to create, generate, add, or edit a workflow, cycle, pipeline, route, or the registry.
allowed-tools: Read, Write, Edit, Bash
---

# Generate Workflow

Guide the user to create a runnable **workflow** for the orchestration harness. A
workflow is **one YAML file** in `.claude/workflows/` plus **one route** in
`.claude/workflows/registry.yml`. No orchestrator code changes are needed.

Canonical terms live in `.claude/GLOSSARY.md` — **workflow** is the noun;
"cycle"/"pipeline" are human synonyms only (fine as `match.intent` keywords).

## Quick Start

Copy this checklist and track progress:

```
Workflow Progress:
- [ ] Step 1: Gather intent (keywords + ordered steps + gates)
- [ ] Step 2: Scaffold {id}.yml from the template
- [ ] Step 3: Validate the new file (must exit 0)
- [ ] Step 4: Register the route in registry.yml (upsert)
- [ ] Step 5: Re-validate the full config (must exit 0)
- [ ] Step 6: Report the route, file path, and validator output
```

## Step 1: Gather Intent

Ask (or infer) these before writing anything:

- **Trigger keywords** → `match.intent` (the words that route a request here).
- **Ordered steps** → each step's `agent` and optional `skill`.
- **Gates** → any step whose next step depends on a verdict. Prefer explicit
  no-op/blocked tokens for expensive follow-ups, e.g.
  `CHANGED`/`NOOP`/`BLOCK`, `PASS`/`WARN`/`BLOCK`, or `APPROVE`/`REVISE`.

Every step's `agent` and `skill` must **already exist** under `.claude/agents/`
and `.claude/skills/`. If a needed capability is missing, say so — do not invent
a route that cannot run.

For project-specific behavior, create namespaced project capabilities
(`proj.<agent>`, `proj-<skill>`, `proj-<workflow>.yml`) in the downstream project.
Do not add domain-specific skills or workflows to the reusable core template;
record reusable structure in this skill and domain detail in project knowledge.

## Step 2: Scaffold

Copy `.claude/workflows/_template.yml` to `.claude/workflows/{id}.yml` and fill
in `match`, `steps`, and any gates. Use the template's shape:

```yaml
name: My Workflow
description: One-line summary of what this workflow accomplishes.

match:
  intent: [keyword, another-keyword]
  priority: 50

steps:
  # `executor` is the generic worker bundled with the harness. Swap in your own
  # domain-specific agents once you add them under .claude/agents/.
  - id: build
    type: agent                 # optional; `agent` is the default step type
    agent: executor             # required for agent steps; must exist under .claude/agents/
    skill: execute-plan         # optional; must exist under .claude/skills/
    action: Do the first thing.
    mandatory: true

  - id: review
    agent: executor
    action: Review the output of `build`. Emit VERDICT APPROVE when no follow-up is needed, or REVISE when `build` must run again.
    requires: [build]
    verdict_contract: ["APPROVE", "REVISE"]   # exact tokens the agent emits
    max_retries: 2
    on_complete:
      APPROVE: { next: done }
      REVISE: { next: build }

  - id: done
    agent: executor
    action: Finalize once review approves.
    requires: [review]
```

**Step types** (`type`, default `agent`): use `type: manual` for a step that
**escalates to the user** (decision/approval) instead of spawning an agent.

Rules for gated steps: every `on_complete` **requires** a `verdict_contract`
(the exact `VERDICT: <token>` tokens the step's agent emits) and `max_retries`.
Route `NOOP`, clean `PASS`, and terminal `BLOCK` paths to `done` when no further
workflow step should run.

## Step 3: Validate (incremental)

Run the validator on the new file only. Proceed **only on exit 0**:

```bash
python .claude/skills/validate-config/scripts/validate_config.py .claude/workflows/{id}.yml
```

Never register a file that fails validation.

## Step 4: Register (upsert)

Add an `enabled` route to `.claude/workflows/registry.yml`. If a route with the
same `id` already exists, **edit it in place** — never duplicate:

```yaml
routes:
  - id: my-workflow
    workflow: my-workflow.yml
    description: What this workflow does
    match: { intent: [keyword, another-keyword], priority: 50 }
    enabled: true
```

## Step 5: Re-validate (full)

Run the validator with no argument and expect exit 0:

```bash
python .claude/skills/validate-config/scripts/validate_config.py
```

## Step 6: Report

Report the new/updated route, the workflow file path, and the validator output.

## Hard Rules

- **Validate before registering.** Only exit 0 proceeds.
- **Upsert, never duplicate** a route id in `registry.yml`.
- **Recursion guard:** a workflow step may never spawn `orchestrator` or
  `workflow-author`.
- **Only real capabilities:** every `agent`/`skill` referenced must already exist.
- **Project-specific stays project-specific:** document domain structure in
  project knowledge and use `proj.*`/`proj-*` namespaced files, not core files.
- **Skip no-op work:** use conditional gates so clean/no-op paths do not trigger
  unnecessary review, regeneration, knowledge updates, or broad validation.
- `_`-prefixed files (e.g. `_template.yml`) are non-routable templates — never add
  them to `registry.yml`.
