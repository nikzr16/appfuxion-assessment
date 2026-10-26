# [Feature] Workflow

> **Type:** Workflow | **Must stay current:** Yes -- update when behavior changes

<!-- AI Context
Role: This document describes how the system behaves *today*.
Use it as the authoritative source for current processing flows, stage
sequencing, error handling, and runtime defaults. When writing or modifying
code, the behavior described here is the specification.
This document must be updated before a coding session ends whenever behavior,
flow, or error handling changes. If it conflicts with a PRD or plan, this
document reflects reality; record the divergence in the decision log.
-->

## Purpose

_What this workflow accomplishes and when it runs._

## Trigger

_What initiates this workflow (API call, scheduled job, event, etc.)._

## Preconditions

- ...

## Stages

<!-- Use markdown sections for simple linear flows. For complex multi-branch
workflows, a pseudo-YAML code block may be clearer -- see the extractor
workflow doc for an example of that format. -->

### 1. [Stage Name]

**Input:** ...
**Actions:** ...
**Output:** ...
**On failure:** ...

## Error States

| Error | Cause | Handling |
|---|---|---|
| | | |

## Defaults

| Setting | Default |
|---|---|
| | |

## Behavioral Constraints

_Mode restrictions, policy rules, or invariants that apply across stages but don't belong to a single stage definition._

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/prd/[feature]-prd.md` | Intent | Product goals this workflow fulfills |
| `docs/plan/[feature]-plan.md` | Plan | Architecture this workflow implements |
| `docs/reference/folder-structure.md` | Reference | File locations of workflow components |
| `docs/decisions/NNNN-*.md` | Decision log | Deviations from original plan captured here |
