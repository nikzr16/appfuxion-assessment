# 0005 - Validation implementation details that differ from the 0004 plan

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

Implementing `docs/plan/0004-validation-plan.md` settled a few message and formatting details
the plan only sketched. None changes the PRD's decisions D1-D12, the issue codes, the
severities, the report or conversion shapes, or the error codes.

## Decision

1. **`x` instead of `×` in messages.** The line message reads "Line 1: quantity 2 x unit
   price 25.00 = 50.00 MYR, …". Ruff's `RUF001` rejects the ambiguous `×` character in
   strings, and plain ASCII is safer for the summary prompt and logs.
2. **Missing-field messages carry hints.** The plan said a fixed `"<Label> is missing."`.
   Dates add "(it may have been printed in an ambiguous day/month format)", the currency adds
   "(the symbol may be ambiguous, e.g. a bare $)", and empty line items read "No line items
   were found." The hints point at 0003's deliberate `null`s so the summary can explain them.
3. **Money is shown with at least the currency's minor units, and more when the value has
   them.** The plan's `f"{value:,.{n}f}"` would print `3 x 3.3333 = 9.9999` as `10.00`, hiding
   why a line was checked. The currency code is added to results, not to every operand
   ("Subtotal 100.00 + tax 6.00 = 106.00 MYR, …").
4. **Message variants.** Without tax the totals message is "Subtotal X does not match the
   total Y (difference D)". Without a subtotal, the line-sum message also gives the amount
   before tax ("the total is 106.00 MYR (100.00 MYR before tax)"), since either would have
   passed.
5. **`is_iso_currency` checks the three-letter shape first**, before the `EXCLUDED_CODES`
   and `pycountry` lookups, so empty or odd input (`""`, `"RM"`, `"MYRR"`) is a plain `False`.
6. **The ISO data was verified, not just copied.** The minor-unit exceptions and the excluded
   codes were checked against the official ISO 4217 list one (SIX, published 2026-09-17), and
   `pycountry`'s 178 codes matched that list exactly. `ISO_4217_AS_OF` records the list date.
7. **Test layout.** Five files instead of the plan's three: `test_validate_invoice.py`,
   `test_convert_currency.py`, `test_currencies.py` (data + lookups), `test_schema.py` and
   `test_layering.py` (no other module except `structured_extraction.schema`; no
   DB / LLM / storage / FastAPI imports). The module has 100% line coverage.
8. **README not changed.** Setup is unchanged (`uv sync` installs `pycountry`) and there is
   no new endpoint to show.

## Reason

Each change makes a message clearer or a check stricter, without touching the contract that
0005 and 0006 depend on (codes, fields, severities, `expected` / `actual`).

## Impact

- [ ] Workflow doc updated
- [x] Reference doc updated (`docs/reference/folder-structure.md`)
- [x] No upstream doc update needed
