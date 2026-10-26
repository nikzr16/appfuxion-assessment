# 0002 - Documents implementation details that differ from the 0001 plan

> **Date:** 2026-10-26 | **Status:** Accepted

<!-- AI Context
Role: This is an append-only record of a single implementation divergence.
Each entry captures why the deviation happened and what it affects.
Never edit an existing decision log entry. To reverse a previous decision,
create a new entry that references the original. After adding an entry,
check the impact checklist below and update affected workflow or reference
docs before the session ends.
-->

## Context

Implementing `docs/plan/0001-documents-plan.md` surfaced a few small details the plan
did not pin down. None changes the API contract or the PRD's decisions.

## Decision

1. **`run_pipeline` opens a DB session only when the hook raises**, not up front as the
   plan describes. The hook manages its own session (0005), so the wrapper needs one only
   to call `mark_failed`.
2. **Status helpers flush but never commit.** `service.mark_completed` /
   `service.mark_failed` leave the commit to the caller (`run_pipeline` commits its own
   failure update). 0005 may only import `documents.service`, not its `crud`, so this is
   what lets it save results and completion in one transaction.
3. **`create_document` returns a `DocumentRead`**; the router builds the
   `{document_id, status}` response from it.
4. **Name cleaning edge cases:** `.pdf` becomes `pdf` (leading dots stripped, as planned),
   and an "extension" longer than 100 bytes is treated as part of the stem when trimming.
5. **Log field `stored_filename`** instead of `filename`, because `filename` is a reserved
   `LogRecord` attribute.
6. **Storage tests omit a backslash path-escape case**, because `\` is a legal filename
   character on Linux (CI) and the test would behave differently per platform. Service
   tests still cover client names containing `\`.

## Reason

Each choice is the smallest one that keeps behaviour correct on both Windows and Linux
and keeps 0005's integration point simple.

## Impact

- [ ] Workflow doc updated
- [x] Reference doc updated (`docs/reference/folder-structure.md`)
- [x] No upstream doc update needed
