# Product Roadmap

> **Type:** Roadmap | **Must stay current:** Yes -- update when phases, features, or priorities change

<!-- AI Context
Role: This is the top-level sequencing document for the entire product.
It defines development phases, maps PRDs to phases, and captures the
rationale for ordering. Use it to understand *what is being built when*
and *why that order was chosen*.

When a new PRD is created, register it here under the appropriate phase.
When a feature ships or a phase graduates, update the status columns.
When priorities shift, update phase assignments and record the reasoning
in the Prioritization Log below.

Individual PRDs hold feature-level detail. This document holds the
cross-feature ordering logic. Do not duplicate PRD content here.
-->

## Product Vision

_One to three sentences describing the long-term direction of the product._

## Phasing Strategy

_How phases are defined: by user base milestones, capability tiers, infrastructure readiness, or a combination. Explain the graduation logic._

## Phases

### Phase 1: [Name]

**Trigger:** _What starts this phase (e.g. project kickoff, first deployment)._
**Graduation criteria:** _What must be true before moving to Phase 2._

| PRD | Module | Status | Notes |
|---|---|---|---|
| `docs/[feature]-prd.md` | `src/[module]/` | draft / in-progress / shipped | |

### Phase 2: [Name]

**Trigger:** _What starts this phase (e.g. Phase 1 shipped, N active users)._
**Graduation criteria:** _What must be true before moving to Phase 3._

| PRD | Module | Status | Notes |
|---|---|---|---|
| | | | |

### Phase 3: [Name]

**Trigger:** _What starts this phase._
**Graduation criteria:** _What must be true before moving to Phase 4._

| PRD | Module | Status | Notes |
|---|---|---|---|
| | | | |

## Cross-Cutting Concerns

_Capabilities that span multiple phases rather than belonging to a single PRD (e.g. auth, observability, CI/CD, infrastructure). Track their progression here._

| Concern | Introduced In | Matured In | Current State |
|---|---|---|---|
| | | | |

## PRD Registry

_Master list of all PRDs and their phase assignment. Duplicates the per-phase tables into one flat view for quick lookup._

| PRD | Phase | Module | Status |
|---|---|---|---|
| | | | |

## Prioritization Log

_When a feature moves between phases or priorities shift, record the change and reasoning here. Entries are append-only._

| Date | Change | Reason |
|---|---|---|
| | | |

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/documentation-standard.md` | Standard | Governs how all docs are maintained |
| `docs/reference/folder-structure.md` | Reference | Structural placement of modules |
| `docs/decisions/NNNN-*.md` | Decision log | Deviations that may affect roadmap |
