---
name: validate-config
description: Validates the .claude harness configuration (agents, skills, workflows, registry) as real code. Use before registering a new workflow, during final verification, or on any request to validate the .claude config.
allowed-tools: Bash, Read
---

# validate-config

Deterministic validator for the harness configuration. This is the one hard,
code-enforced guarantee in the harness — routing and gating are otherwise
model-driven (orchestrator prompt-adherence).

## When to run

- **Pre-register gate** — `workflow-author` runs it before adding a route to `registry.yml`.
- **Final verification** — after building or editing harness files.
- **On request** — any "validate the .claude config" ask.

## How to run

Full-config scan (verification / CI):

```bash
python .claude/skills/validate-config/scripts/validate_config.py
```

Incremental (fast path while authoring a single workflow):

```bash
python .claude/skills/validate-config/scripts/validate_config.py .claude/workflows/<id>.yml
```

## What it checks

- Agent + skill frontmatter is present and parseable; required fields exist.
- Agent `skills:` refs resolve to real skills.
- `registry.yml` routes point at existing, routable workflow files; `fallback` is valid.
- Each workflow step's `agent` / `skill` resolves.
- **Recursion guard:** no step spawns `orchestrator` or `workflow-author`.
- **Verdict contract:** every gated step (`on_complete`) declares a `verdict_contract` token list.
- **Core-lock (reuse guard):** every file in `.claude/CORE.manifest` must match its
  recorded checksum — a full scan **errors** if the shared core drifts. Non-core
  capabilities that aren't namespaced (`proj.*` agent, `proj-*` skill/workflow)
  produce a warning.
- `_`-prefixed workflows (e.g. `_template.yml`) are skipped everywhere.

## Core-lock (keeping the harness reusable across projects)

The stock harness is **checksum-locked** so project work can't silently change it.
Put project-specific work in **namespaced** capabilities (`proj.*` / `proj-*`),
never by editing a core file. Only harness maintainers regenerate the manifest
after an intentional core change:

```bash
python .claude/skills/validate-config/scripts/validate_config.py --update-core-manifest
```

## Reading results (G-F exit policy)

- **Exit 0** — no errors (warnings may still print; they are informational and never block).
- **Exit 1** — one or more ERRORS; do not register/ship until resolved.
- **Exit 2** — environment problem (e.g. PyYAML missing).
