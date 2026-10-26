---
name: analyze-requirements
description: Default first-pass analysis that turns a raw user request into a standardized Requirement Brief — extracting intent, resolving the smallest blocking unknowns, and mapping the need onto the harness's real capabilities (agents, skills, registered workflows) and execution tier. Use at the start of any non-trivial request, before routing or building.
allowed-tools: Read, Grep, Glob
---

# Analyze Requirements

Convert a raw request into a **Requirement Brief**: a compact, standardized
contract that captures *what the user actually wants* and *how it maps to what
this harness can actually do*. This is the default front door for any
non-trivial request — run it before the orchestrator routes or an agent builds.

Use the canonical terms from `.claude/GLOSSARY.md`: **workflow**, **route**,
**step**, **agent**, **skill**, **execution tier** (Trivial / Fast lane / Full).

## When to Use

- Any request that isn't a trivial one-liner (see Tier T below).
- Before the `orchestrator` selects a route, or before `execute-plan` starts.
- Whenever intent is ambiguous, multi-file, or spans systems.

Skip it for trivial edits (~≤15 lines / single file) — those run directly.

## Cost & Efficiency Contract (read first)

This skill is deliberately lean. Obey the budgets so analysis never costs more
than the work itself:

- **Context budget:** ≤6 files read, ≤10 tool uses in the first pass. Read on
  demand — never load the whole codebase up front.
- **One clarifying round, max.** Batch every open question into a single ask.
  If a question is answerable by reading one file, read it instead of asking.
- **Stop-and-ask** only when a genuine blocker remains after the budget is
  spent (scope, destructive action, or irreducible ambiguity).
- **Right-size the output.** The brief scales with the tier — a Fast-lane brief
  is a few lines; a Full brief fills every section.

## Process (modular — run each stage, keep each short)

### 1. Capture intent

Restate the request in one or two sentences: the **goal** (outcome the user
wants) and the **why** (motivation), separated from the **how** (any solution
the user proposed — record it, but don't assume it's the only path).

### 2. Extract requirements

List them as discrete, testable items, tagged by type:

- `[FR]` functional — observable behavior the result must exhibit.
- `[NFR]` non-functional — performance, security, cost, UX, compatibility.
- `[CON]` constraint — tech stack, files/systems in scope, deadlines, "don't
  touch X".
- `[ASM]` assumption — anything you inferred rather than were told (flag these).

### 3. Resolve unknowns (bounded)

For each gap, pick exactly one action: **read** (a specific file resolves it),
**assume** (low-risk default — record as `[ASM]`), or **ask** (blocking, no safe
default). Collect all `ask` items into one batched question and stop only if any
remain.

### 4. Map to harness capabilities

Match the requirements against what actually exists — never invent capability:

1. Read **`.claude/workflows/registry.yml`** and score `enabled` routes by
   `match.intent` overlap. Name the best route, or state "no route matches → the
   orchestrator's domain-agnostic ad-hoc route (`executor` → `executor`
   self-review)".
2. Identify which **agents** (`.claude/agents/`) and **skills**
   (`.claude/skills/`) the work needs. If a required capability is missing, say
   so explicitly and note that a new workflow/agent/skill would be needed.

### 5. Classify the execution tier (cost control)

Pick the smallest tier that satisfies the requirements:

| Tier | Trigger | Handling |
|------|---------|----------|
| **T — Trivial** | ~≤15 lines, single file, no risk | Run directly; no orchestrator, no brief needed. |
| **F — Fast lane** | small / low-risk multi-file | `execute → review + test`; drop `mandatory: false` steps. |
| **U — Full** | feature / high-risk / cross-module / migration, or explicit full-pipeline request | Run all steps. |

Justify the choice in one line. When two tiers are plausible, choose the cheaper
one and name the single factor that would escalate it.

### 6. Define acceptance criteria

2–5 checkable statements that make "done" objective and testable. Each should
map back to an `[FR]`/`[NFR]` from stage 2.

## Output: the Requirement Brief (standardized contract)

Emit exactly this structure so every downstream agent consumes the same shape.
Omit a section only by writing `- none`.

```md
## Requirement Brief

**Goal:** <one sentence>
**Why:** <motivation, or "not stated">

**Requirements:**
- [FR] ...
- [NFR] ...
- [CON] ...
- [ASM] ...

**Open questions (blocking):**
- <batched question(s), or "none">

**Capability map:**
- Route: <registry route id | "ad-hoc (no match)">
- Agents: <list>
- Skills: <list>
- Gaps: <missing capability, or "none">

**Execution tier:** <T | F | U> — <one-line justification>

**Acceptance criteria:**
- [ ] ...
```

## Hard Rules

- **Never invent capabilities.** Every agent/skill/route named must already
  exist under `.claude/`; missing ones go under **Gaps**.
- **One clarifying round.** Batch questions; prefer reading over asking.
- **Right-size to the tier.** Don't produce a Full brief for a Fast-lane task.
- **Separate intent from solution.** Record the user's proposed "how", but map
  requirements to the goal, not to an assumed implementation.
- **This skill is read-only.** It analyzes and hands off — it does not build.
