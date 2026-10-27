# 0012 - A tax-ID vendor match also needs a similar vendor name

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

PRD 0010 D4 says two documents have the same vendor when their normalised tax IDs are equal,
or their normalised names are equal and they do not have different tax IDs, with "no fuzzy
match". Decision 0011 ("Observed, not changed") recorded what this did to the real data: four
sample vendors print one SST number (the sample PDFs come from one template), so Acme
Trading, Acme Office Supplies, BrightLane Logistics and CloudNine Hosting formed one vendor
history, and the Query Agent quoted CloudNine Hosting's total as "the highest Acme Trading
total". A misread buyer tax ID would do the same. The user chose to fix this before 0011.

## Decision

A tax-ID match now also needs a **similar vendor name** when both documents have a name.

- `rules.similar_vendor_names(a, b)`: rapidfuzz `token_set_ratio` of the two normalised
  names, at least `VENDOR_NAME_MIN_SIMILARITY` = **80**. A missing name never vetoes.
  Token-set means one name may contain the other ("acme" / "acme trading" = 100), and
  extraction typos still pass ("acme trading" / "acme trdaing" = 92), while different vendors
  fail ("acme trading" / "acme office supplies" = 50, "brightlane logistics" = 31).
- The check runs in Python, before the SQL: `crud.vendor_names_for_tax` lists the distinct
  name keys under the tax ID, the similar ones go into `Filters.vendor_tax_names`, and
  `crud.vendor_condition` accepts a tax-ID row only with one of those names or no name. So
  `find`, `count` and the vector search keep their SQL limits and counts; no new extension
  (pg_trgm) or migration.
- It applies wherever a **document's own vendor** is matched: `check_vendor_history`
  (duplicate, outlier, new vendor) and `vendor_history` for a document or invoice number
  (the detail page and the Query Agent).
- It does **not** apply to a vendor **typed as search text** (`search_invoices`,
  `get_vendor_history` with a vendor): that text is one value used as both name and tax ID,
  so comparing it with itself would make a typed tax ID match nothing. A typed tax ID still
  returns every invoice under it.
- The name rule is unchanged: the same normalised name with different tax IDs is still two
  vendors. The fuzzy score only **narrows** a match; it never joins two vendors that D4
  would keep apart.

## Reason

D4 wanted exact, explainable matching because a duplicate warning on the wrong vendor is
worse than a missed one. A shared tax ID across clearly different names is that wrong
warning (and a wrong "highest total" in Ask AI). Using fuzzy matching only as a veto keeps
D4's promise: every match is still explained as "by tax ID" or "by name", and nothing new is
merged. The cost is that a vendor that really changed its trading name under one tax ID now
starts a new history; that is the safer mistake.

## Impact

- [x] Tests: `test_similar_vendor_names` (rules), `test_a_shared_tax_id_needs_a_similar_vendor_name`,
      `test_vendor_history_keeps_vendors_that_share_a_tax_id_apart`, and the existing tax-ID
      test now uses a similar name
- [x] Checked on the development data: Acme Trading's history has only its own 5 invoices;
      BrightLane Logistics and Acme Office Supplies have their own
- [x] ENGINEERING_NOTES.md 0010 sections (vendor identity, limitations, production
      improvements) updated
- [x] No API, schema, migration, config or UI change (`docs/reference/folder-structure.md`
      unchanged); vendor-history issues already stored on earlier runs stay as they were
      until the document is reprocessed
