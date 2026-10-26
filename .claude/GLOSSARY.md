# Harness Glossary — canonical terminology

Single source of truth for what we call things. Every doc, prompt, agent, and
skill in this repo uses these terms so the agent and the user stay in sync. When
in doubt, this file wins.

## Canonical terms

| Term | Definition | Do **not** call it |
|------|------------|--------------------|
| **harness** | The whole hands-off orchestration system under `.claude/`. | "factory", "engine" |
| **registry** | `registry.yml` — the routing source of truth the orchestrator reads. | "manifest", "index" |
| **route** | One registered entry in the registry (`id`, `workflow`, `match`, `enabled`) that points to a workflow file. | "mapping" |
| **workflow** | The YAML file in `.claude/workflows/` defining an ordered sequence of steps. **Canonical noun.** | see synonyms note below |
| **step** | One unit inside a workflow (`id`, `agent`/`type`, `action`, deps, gates). | "stage", "task" |
| **gated step** (**gate**) | A step with `on_complete` that branches on a returned verdict. | "checkpoint" |
| **verdict contract** | `verdict_contract` — the exact tokens a gated step's agent may emit as its final `VERDICT: <token>` line. | "return codes" |
| **agent** | A specialist worker defined under `.claude/agents/`. | "bot", "worker" |
| **skill** | A reusable playbook under `.claude/skills/` (each has a `SKILL.md`). | "plugin", "recipe" |
| **orchestrator** | The router agent that selects a route and runs its steps. Never does the work itself. | "controller" |
| **workflow-author** | The privileged agent that scaffolds, validates, and registers workflows. | "generator" |
| **mcp-connector** | The privileged agent that adds/configures MCP servers in the repo-root `.mcp.json`. | "integration", "plugin" |
| **MCP connector** | One entry under `mcpServers` in `.mcp.json` (Claude Code's project MCP config) that connects the harness to an MCP server. | "MCP plugin", "integration" |
| **ad-hoc route** | The built-in, domain-agnostic fallback used when no route matches (`executor` → `executor` self-review). | "default flow" |
| **executor** | The generic, domain-agnostic worker agent the ad-hoc route spawns to do (and self-review) the work. | "worker", "generalist" |
| **core** | The reusable, shared harness itself — its stock agents, skills, workflow template, glossary, hook, and validator. Identical across every project and checksum-locked. | "base", "defaults" |
| **project capability** | An agent/skill/workflow that belongs to one project, not the shared harness. Lives in the same flat folders as core but is **namespaced** (`proj.*` agent, `proj-*` skill/workflow). | "custom agent/skill" |
| **core-lock** | The validator's hard check that every file in `CORE.manifest` matches its recorded checksum, so project work can never mutate the shared core. | "freeze", "guard" |
| **CORE.manifest** | `.claude/CORE.manifest` — the checksum allowlist of core files. Regenerated only by harness maintainers via `--update-core-manifest`. | "lockfile" |

### "workflow" vs "cycle" vs "pipeline"

**workflow** is the only canonical noun. `cycle` and `pipeline` are **human
synonyms** — acceptable in a user's request and as `match.intent` keywords, but
never used as the primary term in docs, prompts, schema, or file/field names.

## Profiles vs execution tiers (both kept, mapped)

Two related but distinct concepts:

- **Profile** — the operator-level mode the *main agent* runs in (from `CLAUDE.md`):
  **Lean** (default) or **Full**.
- **Execution tier** — the *orchestrator's* per-request run size:
  **Trivial**, **Fast lane**, or **Full**.

Explicit mapping:

| Profile | Execution tier(s) | Behavior |
|---------|-------------------|----------|
| **Lean** | Trivial, Fast lane | Trivial (~≤15 lines / 1 file) runs directly, no orchestrator. Small/low-risk multi-file → Fast lane (`execute → review + test`, drop `mandatory: false` steps). |
| **Full** | Full | Feature / high-risk / cross-module, or explicit full-pipeline request → all steps run. |

## Step types

Every step declares a `type` (default **`agent`** if omitted):

| `type` | Meaning | Required fields |
|--------|---------|-----------------|
| `agent` | The orchestrator spawns `agent` to do the work. | `agent` (must exist under `.claude/agents/`) |
| `manual` | The orchestrator **pauses and escalates to the user** (decision, approval, destructive action). | no `agent`; use `action` to state what's needed |

## Spelling & tokens

- Config **value** is `adhoc` (e.g. `fallback: adhoc`); in prose write **ad-hoc**.
- Placeholder tokens resolved at run time: `{project-name}`, `{NN}`, `{slug}`.
- `_`-prefixed files (e.g. `_template.yml`) are **non-routable** templates —
  never referenced by a route.
