# Documentation Standard

Every file in `docs/` belongs to one of six types. Each type has a freshness rule that determines when it must be updated.

## Document Types and Freshness Rules

| Type | Purpose | Must Stay Current | Update When |
|---|---|---|---|
| **Roadmap** | Phase sequencing, PRD registry, cross-feature priorities | Yes | New PRD added, phase graduates, priorities shift |
| **Intent** (PRD) | Product goals, constraints, scope | No | Product direction changes |
| **Plan** | Implementation path, phasing, architecture | No (after coding starts) | Deliberate re-planning session |
| **Workflow** | How the system works today | Yes | Behavior, flow, or error handling changes |
| **Reference** | Structural facts (files, routes, schemas, config) | Yes | Files, modules, routes, or schemas change |
| **Decision log** | Deviations from the plan | Append-only | Implementation diverges, bug forces redesign, assumption invalidated |

Key rules:

- The roadmap is the top-level sequencing document. When a new PRD is created, register it in the roadmap under the appropriate phase.
- Intent docs and plans are not rewritten during coding. Record divergences in the decision log.
- Workflow and reference docs must be updated before the coding session ends when behavior or structure changes.
- Decision log entries are never edited. Reverse a decision by adding a new entry.

## Naming Convention

Name documents as `[feature]-[type].md` where type matches the document's role:

| Suffix | Document Type |
|---|---|
| `-prd.md` | Intent (PRD) |
| `-plan.md` | Plan |
| `-workflow.md` | Workflow |

The product roadmap is `product-roadmap.md` (one per project). Reference docs live in `docs/reference/` with descriptive names such as `folder-structure.md`. Decision log entries use `NNNN-short-title.md`.

A feature may have a combined Intent/Plan document or separate PRD and plan files. The templates support the split approach.

## Document Inventory

| Document | Type |
|---|---|
| `docs/product-roadmap.md` | Roadmap |
| `docs/documentation-standard.md` | Standard |
| `docs/*-workflow.md` | Workflow |
| `docs/prd/*.md` | Intent (PRD) |
| `docs/plan/*.md` | Plan |
| `docs/reference/*.md` | Reference |
| `docs/decisions/*.md` | Decision log |
| `docs/templates/*.md` | Templates |

## Folder Layout

```text
docs/
├── product-roadmap.md
├── documentation-standard.md
├── [feature]-workflow.md
├── prd/
├── plan/
├── reference/
├── decisions/
├── draft/
└── templates/
```

`docs/` stays at the repository root so it can document every part of the codebase.
`docs/draft/` is personal scratch space — agents never read or act on it unless explicitly referenced.

## Session-Close Checklist

Run at the end of every substantial coding session.

- [ ] New PRD created? Register it in the product roadmap under the correct phase.
- [ ] Feature shipped or phase graduated? Update the roadmap status.
- [ ] Behavior changed? Update the workflow doc.
- [ ] Files, routes, or schemas changed? Update the reference doc.
- [ ] Diverged from the plan? Add a decision log entry.
- [ ] Design trade-off made? Add a decision log entry.
- [ ] Scan the workflow doc: does it match what the code does today?
