---
name: author-workflow
description: Scaffolds a new workflow YAML from the template, validates it, and registers it in registry.yml only on a passing validation. Use when explicitly asked to add or edit a workflow, cycle, pipeline, route, or the registry.
allowed-tools: Read, Write, Edit, Bash
---

# author-workflow

Create or edit a **workflow** declaratively — no changes to the `orchestrator`. A
workflow is one YAML file plus one `registry.yml` route. (Canonical terms live in
`.claude/GLOSSARY.md`; "cycle"/"pipeline" are human synonyms only.)

## Procedure

1. **Gather intent** — the trigger keywords (`match.intent`), the ordered steps
   (`agent` + optional `skill`), and any gate verdicts. For expensive follow-ups,
   prefer conditional verdicts such as `CHANGED`/`NOOP`/`BLOCK`,
   `PASS`/`WARN`/`BLOCK`, or `APPROVE`/`REVISE` so clean paths can skip work.
2. **Scaffold** — copy `.claude/workflows/_template.yml` to
   `.claude/workflows/{id}.yml`. Fill `match`, `steps`, and gates. Every gated
   step (`on_complete`) needs a `verdict_contract` token list and `max_retries`.
3. **Validate (incremental)** — run:

   ```bash
   python .claude/skills/validate-config/scripts/validate_config.py .claude/workflows/{id}.yml
   ```

   Proceed only on **exit 0**. Never register a file that fails validation.
4. **Register (G-E upsert)** — if a route with `{id}` already exists in
   `registry.yml`, update it in place (never duplicate). Otherwise append a new
   `enabled: true` route.
5. **Re-validate (full)** — run the validator with no argument; expect exit 0.
6. **Report** — the new/updated route, the file path, and validator output.

## Rules

- Each step's `agent` and `skill` must already exist under `.claude/agents/` and
  `.claude/skills/`. If a step needs a capability that no agent/skill provides,
  say so — do not invent a route that cannot run.
- If the workflow is project-specific, namespace it as `proj-<id>.yml`, use
  project agents (`proj.<name>`) and skills (`proj-<name>`), and keep the domain
  behavior in project knowledge or project capabilities rather than core files.
- For no-op paths, route to `done` instead of running review, regeneration,
  knowledge updates, or broad validation without a concrete reason.
- **Recursion guard:** a workflow step may never spawn `orchestrator` or
  `workflow-author`.
- Files prefixed `_` are non-routable templates; never add them to `registry.yml`.
