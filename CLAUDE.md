# Agentic Factory Runtime Policy

This repository uses `.claude/` agent, skill, and workflow files.

## Project Context

Project-specific policy and context live in @CLAUDE.project.md. Read it in full
when working in a project created from this harness. It layers on top of this
generic harness policy while leaving harness routing and capability placement
rules in this file intact.

## Session Start (persona + onboarding)

You are the guide for this Orchestral Harness template. At the start of a
session, if the user has NOT given a concrete task, greet them with a brief
(<=5 lines) orientation, then offer to help:
- what this repo is (a hands-off agent-orchestration harness),
- how to use it (just describe the work; mention a "workflow/cycle" to author one),
- that trivial edits run directly and everything else routes through the orchestrator.

Give this brief only once per session (skip it once real work starts). If the
user opens with a concrete task, skip the greeting and just do the work.

## Locations

| Path | Content |
|------|---------|
| `.claude/workflows/` | Workflow definitions and execution gates |
| `.claude/agents/` | Agent system prompts and routing |
| `.claude/skills/` | Skill playbooks and task protocols |

**Placement is load-bearing.** The `validate-config` script and the orchestrator
only discover capabilities under `.claude/` (skills at `.claude/skills/*/SKILL.md`,
agents at `.claude/agents/*.md`, workflows at `.claude/workflows/*.yml`). Never
place a harness skill/agent/workflow in `.cursor/skills/` or anywhere outside
`.claude/` — it will be silently invisible. After any change under `.claude/`, run
`python .claude/skills/validate-config/scripts/validate_config.py` and require exit 0.

## Reuse Across Projects (core vs project separation)

This harness is meant to be reused in every project. To keep the shared
**core** identical and updatable everywhere while each project adds its own
capabilities, core and project files coexist in the same flat `.claude/` folders
(placement is load-bearing) but are separated by **naming + a checksum lock**:

- **Core** (shared, locked): the stock agents (`orchestrator`, `executor`,
  `workflow-author`, `mcp-connector`), stock skills, `_template.yml`,
  `GLOSSARY.md`, the hook, and the validator. Listed in `.claude/CORE.manifest`.
- **Project capability** (yours, free): namespaced so it can never collide with
  or overwrite core —
  - agent → `.claude/agents/proj.<name>.md`
  - skill → `.claude/skills/proj-<name>/SKILL.md`
  - workflow → `.claude/workflows/proj-<name>.yml` (+ a route in `registry.yml`)
- **Never edit a core file** to change project behavior; add a `proj.*` / `proj-*`
  capability instead. The validator **errors** (core-lock) if any core file drifts.
- `registry.yml` and `CLAUDE.project.md` are the intended per-project edit points.
- If a skill or workflow is not reusable harness behavior, keep it out of core:
  document the domain structure in `CLAUDE.project.md` or
  `docs/project-knowledge.md`, then create namespaced `proj.*` / `proj-*`
  capabilities only in the downstream project that needs them.

**Getting core updates (git upstream model).** Each project keeps this template
as a git remote and merges core forward:

```bash
git remote add upstream <this-harness-repo-url>   # once, per project
git fetch upstream
git merge upstream/main                            # pulls core updates
```

Because project files are namespaced (`proj.*`/`proj-*`) and core filenames are
reserved, `git merge` updates core cleanly and never touches project
capabilities. Only harness maintainers change core, then run
`--update-core-manifest` (see the `validate-config` skill) and commit upstream.

**Auto-pull on session start (opt-in).** The `SessionStart` hook
(`.claude/hooks/session_start.py`) can refresh core automatically *before any
orchestration*, so projects stay current with zero manual steps. It is
deliberately conservative:

- **Activates only when a core source is configured** — an `upstream` remote (so
  the template repo itself, which has none, safely no-ops), or `HARNESS_CORE_URL`.
- **Updates only core paths** (from `CORE.manifest`) via `git checkout <src> --`;
  never touches project (`proj.*`) files, so it can't conflict.
- **Re-locks** by regenerating `CORE.manifest`, then reports the update in the
  session's onboarding note (the pulled core lands **staged, not committed** —
  review and commit it; committing also silences the note).
- **Fails safe/silent** (no git, offline, timeout, no source) and is fully
  disableable.

Config via env vars: `HARNESS_CORE_REMOTE` (default `upstream`),
`HARNESS_CORE_BRANCH` (default `main`), `HARNESS_CORE_URL` (fetch directly from a
URL when no remote is set), `HARNESS_NO_CORE_SYNC=1` (disable). Run it manually
to test: `python .claude/hooks/session_start.py --sync-core`.

To enable in a downstream project: `git remote add upstream <this-harness-repo-url>`
— that's it; the next session refreshes core.

## Terminology

`.claude/GLOSSARY.md` is the single source of truth for names. Key terms:
**workflow** (canonical noun; "cycle"/"pipeline" are human synonyms only),
**route**, **step**, **gated step**, **verdict contract**, **agent**, **skill**.

## Default Operating Mode

Use the **Lean profile** by default:
- Prefer direct execution for small, targeted changes.
- Invoke heavyweight agents only when user intent or task complexity requires them.
- Load context files on demand, not all at once.

Escalate to **Full profile** only for:
- Full specification creation and validation
- Full phase implementation and verification
- Explicit user request for full pipeline behavior

**Profiles map to the orchestrator's execution tiers** (see `.claude/GLOSSARY.md`):
- **Lean profile** → **Trivial** tier (run directly, no orchestrator) or
  **Fast lane** tier (`execute → review + test`).
- **Full profile** → **Full** tier (all workflow steps run).

## Orchestral Harness (generic, hands-off routing)

The user should never have to name an agent, skill, or workflow. Route by
request shape:

- **Trivial** (~≤15 lines / single file) → execute directly (Lean profile); no orchestrator.
- **Multi-file or "build / implement / change / fix a feature or bug"** → delegate to
  the **`orchestrator`** agent. It reads `.claude/workflows/registry.yml`, selects the
  matching workflow, and runs it end-to-end with enforced gates. With no workflow
 registered yet, it uses its built-in, domain-agnostic ad-hoc route
 (`executor` → `executor` self-review).
- **Explicit "workflow / cycle / pipeline / route / registry" mention** → delegate to
  the **`workflow-author`** agent (scaffold → validate → register).
- **Explicit "MCP / MCP server / MCP connector / tool server" mention** → delegate to
  the **`mcp-connector`** agent (add/configure/validate a server in the repo-root
  `.mcp.json`).
- **Compound ("author then run")** → `workflow-author` first, then hand the new route
  to the `orchestrator`.

**Rules:**
- Auto-delegate. Do not ask "which agent/skill/workflow?" — infer it from the request.
- Skills load themselves (each agent preloads its own via the `skills:` frontmatter).
- Only pause for the user at genuine decision points: a gate blocker needing a
  product/scope decision, destructive actions, or ambiguous requirements.
- Announce the current step briefly as you go so the flow is visible.
- The one deterministic check is the `validate-config` script; run it after editing
  `.claude/` config.

## Invocation Guardrails

- Do not run the full cycle for routine one-line fixes; prefer direct Lean execution.
- Use an independent verification/self-review pass by risk level:
 - High risk / cross-module / migration: required
 - Small contained fix: optional
- Prefer stage-based / on-demand context loading for implementation and verification tasks.
- Prefer conditional workflow gates for expensive follow-ups. Steps that may be
  unnecessary should emit explicit verdicts (`NOOP`, `CHANGED`, `PASS`, `WARN`,
  `BLOCK`, `APPROVE`, `REVISE`) and route clean/no-op paths to `done`.

## Tool Relevance Filter

Before invoking a heavyweight specialist tool/agent, enforce:
- Relevance check: does this tool directly improve the requested outcome?
- Scope check: for narrow tasks, avoid unrelated specialists.
- Justification check: include a one-line reason category:
  - `error-diagnosis`
  - `phase-completion`
  - `spec-production`
  - `security-review`

If a tool does not pass relevance + scope checks, skip invocation.

## Exploration Efficiency Policy

- Default to `quick_discovery` for exploratory requests.
- Budget for quick exploration:
  - Max parallel explore agents: 1
  - Max tool uses per pass: 10
  - Max files read in initial pass: 6
- If quick pass is insufficient, stop and ask before deepening unless the user explicitly requested a deep dive.
- Deep exploration is allowed only for unresolved ambiguity or high-risk investigation, with max 2 parallel explore agents.

## Query-Shape Routing

- Needle query (specific symbol/file/path): use direct `ReadFile`/`rg`/`Glob`; avoid explore subagents.
- Scoped architecture query (single subsystem): one explore agent, quick pass first.
- Cross-system query: two-phase flow (quick pass, then gated deep pass if needed).

## Stop-And-Ask Escalation

If exploration exceeds budget thresholds (agent count, tool uses, repeated reads):
- Pause exploration.
- Return concise findings so far.
- Ask user whether to continue with deeper investigation.

## Token Optimization Metrics

Track these after rollout:
- Average tokens for non-phase tasks (target: reduce by 40%+)
- Number of heavy-skill invocations on small fixes (target: <= 1)
- Number of completion reports generated outside phase completion (target: near zero unless requested)

Weekly tuning knobs:
- `phase completion threshold`
- `high-risk task` criteria
- Lean vs Full profile overrides
