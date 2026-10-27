# 0009 - Guardrails implementation details that differ from the 0008 plan

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

Implementing `docs/plan/0008-guardrails-plan.md`, testing it, running real documents through
it and checking the UI in the browser at desktop and 375 px (light and dark) changed a few
details the plan had sketched. None changes the PRD's decisions D1–D12, the stored columns or
the API fields.

## Decision

1. **Free-text matching.** The plan named `token_set_ratio` for addresses. Addresses use the
   same path as other free text instead: an exact match on a punctuation-insensitive view
   (which already absorbs the model's ", " between printed lines), then `partial_ratio`
   with alignment. `token_set_ratio` gives no span to highlight. A third exact pass on a
   letters-and-digits-only view was added before the fuzzy pass, so letter-spaced headings
   (`K E D A I  M A J U`) are `grounded`, not `weak` or `ungrounded`; found while testing real
   documents.
2. **OCR look-alikes in identifiers.** The plan allowed "one OCR confusion" on vision text.
   The matcher folds every look-alike (`O/0`, `I/l/|/1`, `S/5`, `B/8`) on both sides and
   reports a match as `weak` (never `grounded`). Counting single substitutions would need an
   edit-distance search for little gain; `weak` already lowers the score and shows the doubt.
3. **Scores are floats in JSON.** Field and overall scores are 0–1 floats rounded to 3
   decimals in the API (they are not money); `agent_runs.overall_confidence` stores the same
   value as `NUMERIC(4,3)`. The UI shows them as percentages (`0.917` → `92%`).
4. **`Retry-After` is capped at 60 s** (`RETRY_AFTER_CAP_SECONDS`) so a far-future hint cannot
   stall a background run; the jittered backoff cap stays 20 s as planned.
5. **Agent tool results.** `validate_invoice` also returns `needs_review` and `review_fields`
   to the model, and a new `extract_structured_data` call resets the run's grounding,
   confidence *and* validation (validation must run again on the new data). The summary's
   review list is capped at 6 fields (`MAX_REVIEW_FIELDS`, key fields first) so the appended
   fallback sentence stays short.
6. **High confidence is an icon.** The plan put a `High` / `Medium` / `Low` pill on every
   field. In the browser, 15 green pills drowned out the ones that matter and squeezed the
   narrow two-column field grid. `High` is shown as the distinct shield-check icon (label and
   reasons in the tooltip and for screen readers); `Medium` and `Low` keep the text pill. The
   badge sits after the value and wraps under it, never shrinking the value. Line-item cells
   use the icon for every level, as planned.
7. **Chart colours for the confidence split.** The Metrics page's high / medium / low bar uses
   three new tokens (`--conf-high`, `--conf-medium`, `--conf-low`), not the status tokens: the
   light-mode warning and danger tokens failed the adjacent-segment separation check (ΔE 4.9
   CVD, 9.1 normal vision). The new steps pass the dataviz validator in both themes (dark CVD
   6.5 is in the floor band, so the bar also has a 2 px gap, icons, labels and counts in the
   legend, and a tooltip per segment).
8. **Agent test fixture.** The agent and observability tests' default document is now a PDF
   that prints the values of their `invoice()` fixture (`tests/modules/agent/conftest.py`),
   so `check_grounding` finds them and makes no LLM call; the old sample PDF stays for the
   text-extraction tests.

## Reason

Each change came from a test, a real document or the visual check, and keeps the PRD's intent
(deterministic grounding, bounded retries, doubt made visible, never colour alone) with less
code or a clearer screen.

## Impact

- [x] Reference doc updated (`docs/reference/folder-structure.md`)
- [x] ENGINEERING_NOTES.md 0008 sections describe the shipped behaviour
- [ ] No upstream doc update needed
