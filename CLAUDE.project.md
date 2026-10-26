# Project Context

This file is the project-specific context layer for this repository.

The reusable harness policy lives in `CLAUDE.md`; keep this file focused on the
actual product, codebase, team conventions, and commands for the project created
from the harness.

When guidance conflicts:
- Project behavior, domain rules, architecture, and commands in this file take
  precedence for project work.
- Harness routing, capability placement, and validation rules in `CLAUDE.md`
  still apply.

> **Template:** replace every `_italic placeholder_` below when you start a new
> project from this harness. Delete sections that don't apply.

## Project Overview

_One or two paragraphs: what the product is, who uses it, and the core problem it solves._

## Tech Stack

- **Frontend:** _framework, language, styling_
- **Backend:** _language, framework, runtime_
- **Storage:** _database / files / external services_
- **Packaging:** _package managers and lockfiles_
- **Deployment:** _how and where it runs_

## Repository Layout

Full structural reference: `docs/reference/folder-structure.md` (create it from
`docs/templates/reference-template.md`; keep it current when structure, routes,
schemas, or config change).

- **`_path/`** — _what lives here_
- **`docs/`** — docs-first source of truth: `docs/product-roadmap.md`,
  `docs/prd/`, `docs/plan/`, `docs/reference/`, `docs/decisions/`. `docs/draft/` is the
  user's personal scratch space — never read or act on it unless explicitly referenced.

## Commands

| Purpose | Command | Notes |
|---------|---------|-------|
| Install deps | _command_ | |
| Run locally | _command_ | |
| Build | _command_ | |
| Test | _command_ | |

## Code Conventions

1. **Docs-first:** Read `docs/product-roadmap.md` and the relevant PRD/plan before feature
   work; follow `docs/documentation-standard.md` for doc maintenance and the session-close
   checklist.
2. _Add project conventions here (imports, typing, module layout, naming, …)._

## Domain Rules

1. _Business rules, invariants, and data definitions the code must respect._

## Environment And Secrets

- _Which `.env` files exist, what they configure, and where their `.example` copies live._

## Testing And Definition Of Done

- _Test command(s) that must pass for touched code._
- Treat tests as part of implementation, not a follow-up task.
- Never rewrite intent docs (PRDs/plans) during coding — record divergences in
  `docs/decisions/` instead.
- After a coding task, run the session-close checklist in `docs/documentation-standard.md`
  and keep `docs/reference/` in sync with structural changes.
- Mark a roadmap item `shipped` only when its deliverables and acceptance criteria are
  fully implemented and passing.

## Operational Notes

- _Anything an agent should know to operate safely: generated data not to delete,
  boundaries between components, where metrics/logs live, etc._
