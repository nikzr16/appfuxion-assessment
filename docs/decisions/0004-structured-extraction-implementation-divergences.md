# 0004 - Structured extraction implementation details that differ from the 0003 plan

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

Implementing `docs/plan/0003-structured-extraction-plan.md` surfaced a few details the plan
did not pin down and one place where the PRD's wording was stronger than the library's
behaviour. None changes the API contract, the error codes, the table or the PRD's decisions
D1-D12.

## Decision

1. **Trailing zeros of money are not kept.** PRD D2 says values "keep the precision printed".
   Pydantic reads the JSON number `5.00` into `Decimal("5")` (while `0.1` and `12.3456` stay
   exact), so the *value* is always exact but the printed formatting (`5.00`) is not. The
   schema test asserts value equality and that JSON output is a decimal string, never a float.
   Accepted: no check or calculation depends on trailing zeros; the UI can format to the
   currency's minor units.
2. **The blank-to-null validator wraps the whole optional type.** The plan sketched
   `Text | None` with a `BeforeValidator` on `str`; Pydantic then ran the validator only
   inside the `str` branch, so `"   "` became `None` and failed the `str` check. The alias is
   `Text = Annotated[str | None, BeforeValidator(...)]` and fields are typed `Text`. The strict
   schema is unchanged (`anyOf [string, null]`).
3. **A reply with no parsed object (and no refusal) counts its tokens.** Unlike a reply that
   fails validation inside the SDK, such a reply does return usage, so it is added to
   `prompt_tokens` / `completion_tokens`. Only replies rejected by validation stay uncounted
   (the limitation recorded in `ENGINEERING_NOTES.md`).
4. **`StructuredExtractionError`'s message lists the first three feedback lines** after the
   last attempt (e.g. `currency: Value error, must be a 3-letter ISO 4217 code ...`), so the
   document's `error` column explains the failure without the logs.
5. **`LLMOutputError`'s message names the schema** (`"The model's structured reply did not
   match InvoiceData."`); the error list is in its `errors` attribute. The real client logs it
   at `WARNING` with the error count (not `ERROR`, since the caller may retry).
6. **Test layout.** `conftest.py` holds `make_document(raw_text=SAMPLE_TEXT)` (saves the text
   row through `text_extraction.crud`, a test-only shortcut so any text, including 70,000
   characters, can be set up without building a PDF) and an `invoice(**overrides)` builder.
   Beyond the plan's list, tests also cover the feedback line format and truncation, a
   test for `text_extraction.service.find_text` in the 0002 suite, and the
   `get_extraction` 404. The layering guard rejects any other module's `crud` / `model`, not
   only those of `documents`.
7. **README not changed.** It does not list endpoints beyond the upload ones, and the new
   route answers 409 until 0005 wires extraction, so there is nothing to demonstrate yet.

## Reason

Each choice is the smallest one that matches how Pydantic and the OpenAI SDK really behave
(1, 2, 3) or makes failures easier to explain (4, 5), without touching the agreed API or data
model.

## Impact

- [ ] Workflow doc updated
- [x] Reference doc updated (`docs/reference/folder-structure.md`)
- [x] No upstream doc update needed
