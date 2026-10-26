# General Harness

A reusable, hands-off **agent-orchestration harness** for Claude Code with a
**docs-first** workflow. Start any new project from this template: you describe the
work in plain language, and the harness routes it to the right agent and workflow.
You don't need to tag an `@agent` or a skill.

## What's Inside

```text
.
├── CLAUDE.md               # Generic harness policy (routing, tiers, guardrails) — core
├── CLAUDE.project.md       # Project context layer — fill this in per project
├── .mcp.json               # MCP servers (empty by default)
├── .claude/
│   ├── agents/             # orchestrator, executor, workflow-author, mcp-connector
│   ├── skills/             # analyze-requirements, execute-plan, author/generate-workflow,
│   │                       # mcp-connector, validate-config (+ validator script)
│   ├── workflows/          # _template.yml, README.md, registry.yml (ships routeless)
│   ├── hooks/              # session_start.py — onboarding + opt-in core auto-pull
│   ├── GLOSSARY.md         # Single source of truth for names
│   ├── CORE.manifest       # Checksum lock over the shared core files
│   └── settings.json       # Registers the SessionStart hook
└── docs/                   # Docs-first source of truth
    ├── documentation-standard.md
    ├── product-roadmap.md  # Starts as the roadmap template — fill it in
    ├── prd/  plan/  reference/  decisions/
    ├── draft/              # Personal scratch space; agents ignore it
    └── templates/          # PRD, plan, workflow, reference, roadmap, decision-log
```

## How Requests Are Routed

| Request shape | What happens |
|---|---|
| Trivial (about 15 lines or fewer, one file) | Runs directly, without the orchestrator |
| Build / implement / change / fix | **orchestrator** picks a route from `registry.yml`, or uses the built-in ad-hoc route (`executor` → self-review) |
| Mentions a workflow / cycle / pipeline / route | **workflow-author** scaffolds, validates, and registers it |
| Mentions an MCP server / connector | **mcp-connector** adds it to `.mcp.json` |

See [CLAUDE.md](CLAUDE.md) for the full policy and
[.claude/workflows/README.md](.claude/workflows/README.md) for the workflow format.

## Docs-First Workflow

1. Set the product direction in `docs/product-roadmap.md`.
2. For each feature, write `docs/prd/[feature]-prd.md`, then `docs/plan/[feature]-plan.md`,
   starting from `docs/templates/`.
3. Implement against the PRD and plan. When the code diverges from the plan, add an entry
   to `docs/decisions/NNNN-title.md`. Don't rewrite the PRD or plan to match.
4. Keep the workflow and reference docs current, and run the session-close checklist in
   [docs/documentation-standard.md](docs/documentation-standard.md).

## Starting A New Project From This Harness

1. Copy or clone this repo into the new project.
2. Fill in [CLAUDE.project.md](CLAUDE.project.md) and `docs/product-roadmap.md`.
3. Add project-only capabilities under namespaced names so they never collide with core:
   - agent → `.claude/agents/proj.<name>.md`
   - skill → `.claude/skills/proj-<name>/SKILL.md`
   - workflow → `.claude/workflows/proj-<name>.yml`, plus a route in `registry.yml`
4. Validate after any change under `.claude/`:

   ```bash
   python .claude/skills/validate-config/scripts/validate_config.py
   ```

5. (Optional) To receive core updates, add this harness as the `upstream` remote. The
   SessionStart hook then refreshes core files automatically:

   ```bash
   git remote add upstream <this-harness-repo-url>
   ```

**Never edit a core file** (the files listed in `.claude/CORE.manifest`) to change project
behavior. Add a `proj.*` / `proj-*` capability instead. If a core file drifts, the validator
reports a core-lock error. Harness maintainers who deliberately change core should
regenerate the lock with `--update-core-manifest`.
