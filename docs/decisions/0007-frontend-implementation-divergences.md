# 0007 - Frontend implementation details that differ from the 0006 plan

> **Date:** 2026-10-27 | **Status:** Accepted

<!-- AI Context
Role: This is an append-only record of a single implementation divergence.
Each entry captures why the deviation happened and what it affects.
Never edit an existing decision log entry. To reverse a previous decision,
create a new entry that references the original. After adding an entry,
check the impact checklist below and update affected workflow or reference
docs before the session ends.
-->

## Context

Implementing `docs/plan/0006-frontend-plan.md` and checking the UI in the browser against a
running backend changed a few details the plan had fixed or only sketched. None changes the
PRD's decisions D1–D19, the backend contracts or the routes beyond the planned
`GET /api/config`.

## Decision

1. **Uploads start with an explicit button.** Dropped or picked files are listed in the queue
   ("Ready") and sent when the user presses **Upload N files**, instead of starting on drop.
   The user can review the list, see client-side rejections and remove files first; adding
   more files to the same batch works. Everything else in D4 is as planned (≤ 5 files, two at
   a time, list on success, stay on any rejection).
2. **Additions for clarity (no new API).** After a successful batch the list shows a
   dismissible "N documents uploaded" notice and marks the new rows **New** (passed in the
   navigation state); the summary's Total shows the converted base-currency total
   ("≈ MYR 6,503.76") when there is a conversion; the layout has a skip link and a short
   "extracted by AI, verify important values" footer.
3. **The 0000 `HealthBadge` is restyled for the header.** It is now a compact dot + word
   ("Online" / "Degraded" / "Offline"; the word is hidden on phones) with the full sentence in
   the `title` and for screen readers. Its tests were updated to the new wording.
4. **The failed run's error is shown once.** The failed panel shows the document's error; the
   Agent activity card does not repeat it (the failing step still shows its own error code).
5. **File layout.** `buttonClasses` lives in `components/ui/buttonClasses.ts` and the
   announcer hook in `components/ui/announce.ts` (React Fast Refresh needs component files to
   export only components); `EmptyState` gained `pageHeading` so a page that is only an empty
   state (not found) has one visible `<h1>` instead of a hidden duplicate.
6. **Two layout fixes found in the browser check.** Grids use `grid-cols-1` (`minmax(0, 1fr)`)
   and their columns `min-w-0`, and table scroll containers are `relative`: without them the
   line-items table and the screen-reader-only text inside its cells widened the page at phone
   width.
7. **Poppins is imported per subset** (`@fontsource/poppins/latin-400.css` …) so the build
   ships only the Latin files, as D18 says; the package's default entry bundles every subset.
8. **Dev-server config for the desktop preview.** `.claude/launch.json` defines the backend
   (`uv run --directory backend uvicorn …`, port 8000) and frontend (`npm --prefix frontend
   run dev`, port 5173) servers used for the browser check. It is tooling, not a harness
   capability; `validate_config.py` still passes.
9. **Vitest audit warnings are unchanged.** `npm audit` still reports the Vitest advisories
   recorded in decision 0001 (dev-only; the upgrade to ≥ 4.1.12 is blocked by npm). The new
   runtime dependencies add no advisories.

## Reason

Each change came from using the UI (1–4, 6), from lint or accessibility checks (5), or from
matching the PRD more exactly (7). An explicit Upload button is the safer interaction when
several files are dropped at once and each upload starts paid processing.

## Impact

- [ ] Workflow doc updated
- [x] Reference doc updated (`docs/reference/folder-structure.md`: frontend tree, `/api/config`, `ClientConfig`, dependencies)
- [ ] No upstream doc update needed
