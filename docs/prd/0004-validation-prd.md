# 0004 Validation PRD

> **Type:** Intent | **Must stay current:** No -- record divergences in decision log

<!-- AI Context
Role: This document captures product intent, not implementation detail.
Use it to understand *what* the feature should do and *why*, then consult the
implementation plan and workflow docs for *how*.
Do not rewrite this document during coding. If implementation diverges from
the intent described here, add an entry to the decision log instead.
-->

## Purpose

Check an extracted `InvoiceData` (0003) with plain, deterministic code — missing fields,
totals, dates, currency — and report what is wrong, so the agent (0005) can mention every
problem in its summary. Also convert an amount between currencies with a static, dated rate
table. This is brief Part 5: Validation Tool. The LLM never does this arithmetic.

## Goals

- One pure function, `validate_invoice(data: InvoiceData, *, today: date | None = None) ->
  ValidationReport`, that never calls a database, the network or an LLM, and gives the same
  report for the same input (and the same `today`). This is the function the 0005 agent's
  `validate_invoice` tool wraps.
- A `ValidationReport` with a `status` (`pass | warn | fail`) and a list of `issues`
  (`field`, `code`, `severity`, `message`) from a **stable, documented code catalogue** that
  the UI (0006) and the summary prompt (0005) can rely on. It serialises to plain JSON.
- Messages are complete English sentences that already contain the numbers (e.g. "Subtotal
  100.00 + tax 6.00 = 106.00, but the total is 108.00 (difference 2.00)"), so the summary
  can repeat them without doing any maths.
- One pure function, `convert_currency(amount, from_currency, to_currency) ->
  ConversionResult`, backed by a static rate table with a visible "as of" date and source.
  This is the function the 0005 agent's `convert_currency` tool wraps.

## Non-Goals

- Duplicate invoice numbers, vendor history and amount outliers — B3 (`check_vendor_history`).
- Grounding (does each value appear in the raw text?) and confidence scores — B2.
- Re-extracting or correcting data; validation only reports.
- Live exchange rates or rate history.
- Registering the agent tools and the "summary refuses until validation has run" guard — 0005.
- Storing reports — 0005 stores the report as part of the agent run (see D1).

## Scope

| In Scope | Out of Scope |
|---|---|
| `backend/app/modules/validation/` — pure module (files per D1) | Router, crud, model, migration (D1) |
| `validate_invoice` + `ValidationReport` / `ValidationIssue` | Agent tool wrappers and JSON-schema tool definitions (0005) |
| `convert_currency` + `ConversionResult` + static, dated rate table | Live / historical rates |
| ISO 4217 validity via `pycountry` + minor-units table (D8) | Locale-aware number formatting for the UI (0006) |
| Table-driven pure unit tests (no DB, no OpenAI) | Vendor / duplicate / outlier checks (B3) |

## User Stories

1. **As a user**, I want to be told when an invoice's numbers do not add up, a required
   field is missing, the due date is before the invoice date or the currency is not real,
   so that I do not pay or file a wrong document.
2. **As a user**, I want a single pass / warn / fail status, so that I can see at a glance
   whether the document needs a closer look.
3. **As the 0005 agent**, I want a JSON report whose messages already contain the numbers,
   so that my summary can mention every issue without calculating anything.
4. **As the 0006 UI**, I want stable issue codes and field paths, so that I can highlight
   the exact field (including a single line item).
5. **As a user**, I want an amount converted to another currency with the rate date shown,
   so that I can compare documents in different currencies and know how current the rate is.

## Product Decisions

> **Status: final.** D1–D12 agreed with the user on 2026-10-26.
> D1–D6, D11, D12 as recommended; the user chose a `date_too_old` info note (D7), the
> `pycountry` dependency for ISO 4217 (D8) and `expected` / `actual` fields on each issue
> (D9); D10 gains `date_too_old`.

| # | Decision (recommended) | Rationale |
|---|---|---|
| D1 | **Module shape: pure, no persistence, no endpoint.** `validation/` holds `service.py` (the two functions), `schema.py` (DTOs + the typed error) and **`currencies.py`** (data only: the ISO 4217 table and the rate table). No `router`, `crud`, `model` or migration. It imports only `structured_extraction.schema`. The report is stored by 0005 inside the agent run and shown through its `GET /documents/{id}/result`. | The project rule says a pure module is `service` + `schema`; ~180 currency codes and a dated rate table are reviewable data, not logic, so one extra data-only file keeps `service.py` readable. A debug endpoint would add a router and tests for something 0005's result already exposes. |
| D2 | **Severity model.** Three issue severities: **`error`** (the data is impossible or unusable), **`warning`** (probably wrong or incomplete — a person should look), **`info`** (worth knowing; does not affect the status). Roll-up: any `error` → **`fail`**; else any `warning` → **`warn`**; else **`pass`** (info only, or no issues). | One clear rule the UI and the summary can explain. `info` lets us record notes (e.g. "tax treated as included") without making a clean document look bad. |
| D3 | **Required fields by `document_type`.** **invoice:** `vendor`, `total_amount` → error; `invoice_number`, `invoice_date`, `currency` → warning; `due_date` → info; empty `line_items` → info. **receipt:** `vendor`, `total_amount` → error; `invoice_date`, `currency` → warning; empty `line_items` → info; `invoice_number` and `due_date` not required. **unknown:** run **no** other checks; report one **warning** `not_financial_document`. All use code `missing_field` except the `unknown` case. | Without vendor and total the document cannot be paid, filed or compared, so that is a fail. A null date or currency is often 0003 being honest (ambiguous `03/04/2025`, bare `$`), so it is a warning, not a fail. Receipts commonly lack a number and never have a due date. An `unknown` document is not a broken invoice; checking its (null) fields would only produce noise. |
| D4 | **Tolerance: one minor unit of the document's currency** (MYR/USD 0.01, JPY/KRW/VND 1, KWD/BHD 0.001), from the ISO table (D8). Null or invalid currency → 0.01. Compare exact `Decimal` values: mismatch when `abs(a − b) > tolerance`. **No rounding** inside checks. | Printed amounts are already rounded to minor units, so their sums should match to within one unit; a fixed 0.01 would be too strict for JPY-style rounding and too loose for 3-decimal currencies. Exact decimals avoid float noise. |
| D5 | **Arithmetic checks** (each runs only when all its inputs are non-null; a missing input is already reported by D3, so a skipped check adds no issue). (a) **Totals:** `subtotal + tax ≈ total` → else **warning** `subtotal_tax_mismatch`. If `subtotal ≈ total` instead (tax-inclusive pricing), pass with **info** `tax_included`. With `subtotal` but no `tax`: `subtotal ≈ total`. (b) **Line sum:** sum of line `amount`s ≈ `subtotal` when present; else ≈ `total − tax` or `total` (either passes) → else **warning** `line_items_sum_mismatch`. If any line has a null `amount`, skip (b) and add one **info** `line_items_incomplete`. (c) **Per line:** `quantity × unit_price ≈ amount` → else **warning** `line_amount_mismatch` (field `line_items[i].amount`). Messages include both numbers and the difference. | All arithmetic mismatches are **warnings, not errors**, because `InvoiceData` has no discount, shipping or cash-rounding fields: a correct invoice with "Shipping 15.00" or "Rounding −0.02" in its totals block would otherwise *fail*. The message names the difference so a person (and the summary) can judge. Accepting tax-inclusive layouts avoids a false warning on most Southeast Asian receipts. |
| D6 | **Negative amounts.** Line-level negatives (`quantity`, `unit_price`, `amount`) are **allowed with no issue** (discounts, returns). A negative `total_amount`, `subtotal` or `tax` → **warning** `negative_amount` ("looks like a credit note or refund"). | 0003 keeps negatives as printed on purpose. Discount and return lines are normal; a negative headline amount is legitimate for credit notes but unusual enough to point out. |
| D7 | **Dates.** `due_date < invoice_date` → **error** `due_before_invoice` (any document type, when both are set). `invoice_date` more than 1 day after `today` → **warning** `date_in_future` (`today` defaults to `date.today()`, injectable for tests; 1-day slack covers time zones). `invoice_date` more than **10 years** before `today` → **info** `date_too_old` (user's choice). Null dates are handled by D3 (the message notes the date may have been printed in an ambiguous format). | A due date before the issue date is impossible. A future date usually means a misread year (0003 maps two-digit years to 20xx, so "99" becomes 2099), which this catches. Old invoices are legitimately uploaded from archives, so age is only a note (info), never a warning. |
| D8 | **Currency validity via `pycountry`** (user's choice): a code is valid when `pycountry.currencies` knows it **and** it is not a fund, precious metal or test code (`XAU`, `XAG`, `XPT`, `XPD`, `XDR`, `XSU`, `XUA`, `XBA`–`XBD`, `XTS`, `XXX`); real `X` currencies (`XAF`, `XOF`, `XCD`, `XPF`) stay valid. Invalid → **error** `invalid_currency`. Null → D3. `pycountry` has **no minor units**, so `currencies.py` holds a small **minor-units exception table** (default 2; 0 dp e.g. JPY, KRW, VND, CLP, ISK, XAF, XOF; 3 dp e.g. BHD, IQD, JOD, KWD, LYD, OMR, TND; 4 dp CLF, UYW), dated to the ISO list it follows. Whether a currency is in the *rate* table is not a validation concern. | A maintained dependency tracks ISO 4217 changes (from Debian's `iso-codes`) instead of a hand-copied list. `pycountry` is LGPL-2.1, used unmodified as a library, which fits a public repo; it adds no transitive dependencies. A code that is not a real currency is certainly wrong, hence error. |
| D9 | **Report contract.** `ValidationReport {status, issues[]}`; `ValidationIssue {field, code, severity, message, expected, actual}`. `field` is a JSON path into `InvoiceData` (`total_amount`, `line_items[2].amount`, 0-based; messages say "Line 3"). **`expected` / `actual`** (user's choice) are optional **decimal strings** set on the numeric issues so the UI can show the numbers without parsing the message: for the three mismatch codes `expected` = the value computed by code, `actual` = the printed value; for `negative_amount` only `actual`; `null` on every other issue. They hold the **exact** values (not rounded); the message formats them to the currency's minor units. Issues are ordered by check order, then line index, so the report is deterministic. Codes and severities are `StrEnum`s. `validate_invoice` **never raises** for any valid `InvoiceData` — every problem is an issue. | Field paths let the UI highlight one line item; structured numbers let it show "expected 106.00 · printed 108.00" without regex. Determinism makes table-driven tests and summaries stable. "Never raises" means the agent always gets a report it can summarise. |
| D10 | **Issue code catalogue** (stable; adding a code is fine, renaming one is a breaking change): `missing_field`, `not_financial_document`, `invalid_currency`, `subtotal_tax_mismatch`, `tax_included`, `line_items_sum_mismatch`, `line_items_incomplete`, `line_amount_mismatch`, `negative_amount`, `due_before_invoice`, `date_in_future`, `date_too_old`. Each code has a fixed severity except `missing_field`, whose severity comes from D3. Documented in the module and in `docs/reference/`. | One list that 0005's prompt and 0006's UI can depend on. |
| D11 | **`convert_currency(amount: Decimal, from_currency: str, to_currency: str) -> ConversionResult`.** **Rates** in `currencies.py`: units of each currency per **1 USD** (base USD), with `RATES_AS_OF` (date) and `RATES_SOURCE`. **Currencies:** the 25 in 0003's symbol table — MYR, SGD, IDR, THB, PHP, VND, BND, KHR, LAK, MMK, USD, EUR, GBP, INR, KRW, HKD, TWD, AUD, NZD, CAD, CNY, JPY, CHF, AED, SAR. **Snapshot:** fetched **once** at implementation time from one public source that covers all 25 (ExchangeRate-API open access, `open.er-api.com`, USD base; attribution required) and pasted as `Decimal` literals; refreshing it is a manual code change. **Maths:** cross rate = `to_per_usd / from_per_usd` at full `Decimal` precision; converted amount rounded **half-up** to the target's minor units. Same currency → rate 1, amount rounded to minor units. Codes are upper-cased; negative amounts allowed. **Result:** `{original_amount, from_currency, to_currency, rate, converted_amount, rate_date, source}`; money and rate are decimal strings in JSON; `rate` reported to 10 significant digits. **Errors:** an unknown/unsupported code or a non-finite amount raises **`CurrencyConversionError`** (an `AppError`, 422) with code **`unsupported_currency`** or **`invalid_amount`**; the 0005 tool turns it into a tool error the agent can read. | USD base is how public tables publish rates, and any pair is one division. The 25 currencies are exactly those 0003 can produce from symbols. One source keeps the snapshot consistent; the date and source travel with every result so the "static, dated table" limitation is visible to the user, not hidden. Half-up is the commercial rounding convention on invoices. A typed error (not a silent `null`) tells the agent exactly why a conversion failed. |
| D12 | **Scope guard.** Duplicate invoice numbers, vendor history, outliers and spend anomalies are **B3** (`check_vendor_history`); grounding and confidence are **B2**. 0004 checks one document against itself only. | Those checks need stored history (DB) or the raw text, which a pure tool does not have. |

## Constraints

- Pure module: no DB session, no `Storage`, no `LLM`, no FastAPI import, no I/O at call time
  (`pycountry`'s bundled data is read once and cached).
- One new runtime dependency: `pycountry` (D8). No other new dependency.
- Cross-module: import only `structured_extraction.schema` (`InvoiceData`, `LineItem`,
  `DocumentType`); never its `service`, `crud` or `model`.
- Money is `Decimal` end to end; no `float` anywhere in the module.
- The report and the conversion result must be JSON-serialisable with
  `model_dump(mode="json")` (0005 sends them to the model as tool results and stores them in
  JSONB).
- Deterministic: same input (and `today`) → same output, same issue order.
- Error responses (if one ever reaches HTTP) use the shared `{error: {code, message}}` shape.

## Acceptance Criteria

| # | Criterion | Verifiable By |
|---|---|---|
| 1 | A complete, consistent invoice → `status = pass`, no issues | unit test |
| 2 | Each D3 missing-field rule produces `missing_field` with the right field and severity for `invoice` and `receipt`; `unknown` → exactly one `not_financial_document` warning | table-driven unit test |
| 3 | Roll-up: any error → `fail`; warnings only → `warn`; info only → `pass` | unit test |
| 4 | `subtotal + tax ≠ total` → `subtotal_tax_mismatch` warning whose message contains both values and the difference, with `expected` = subtotal + tax and `actual` = total as decimal strings; tax-inclusive layout → `tax_included` info and no mismatch | table-driven unit test |
| 5 | Line sum checked against subtotal, else `total − tax` or `total`; a null line amount → `line_items_incomplete` info and no sum check | table-driven unit test |
| 6 | `quantity × unit_price ≠ amount` → `line_amount_mismatch` with field `line_items[i].amount` | unit test |
| 7 | Tolerance follows minor units: a 0.01 difference passes in MYR, a 1 difference passes in JPY, a 0.002 difference fails in KWD | table-driven unit test |
| 8 | Negative line amounts → no issue; negative total / subtotal / tax → `negative_amount` warning | unit test |
| 9 | Due before invoice → `due_before_invoice` error; invoice date > today + 1 → `date_in_future` warning; invoice date > 10 years before today → `date_too_old` info (all with injected `today`) | unit test |
| 10 | Unknown 3-letter code (e.g. `ABC`) and excluded codes (e.g. `XAU`, `XTS`) → `invalid_currency` error; `XAF` passes; minor units are 0 for JPY, 2 for MYR, 3 for KWD | unit test |
| 11 | `validate_invoice` never raises on any `InvoiceData`, and the report survives `model_dump(mode="json")` → `model_validate` unchanged | unit test |
| 12 | `convert_currency` converts a known pair with the expected rate and half-up rounding to target minor units (e.g. → JPY has 0 dp); same currency → rate 1; result carries `rate_date` and `source`; lower-case codes accepted | table-driven unit test |
| 13 | Unsupported currency → `CurrencyConversionError` `unsupported_currency`; NaN / infinite amount → `invalid_amount` | unit test |
| 14 | Every currency in the rate table is in the ISO table; every rate is a positive `Decimal` | unit test |
| 15 | `validation` imports nothing from another module except `structured_extraction.schema` | import test |
| 16 | `ruff check`, `ruff format --check`, `pytest` pass; CI green | CI run |

## Roadmap Phase

**Phase:** Phase 1 — Core Pipeline (brief Parts 1–5)

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this PRD |
| `docs/plan/0004-validation-plan.md` | Plan | Implementation path (written after this PRD is final) |
| `docs/prd/0003-structured-extraction-prd.md` | Intent | `InvoiceData` contract this module consumes |
| `docs/decisions/0004-structured-extraction-implementation-divergences.md` | Decision log | How 0003 was actually built (e.g. trailing zeros not kept) |
| `docs/reference/folder-structure.md` | Reference | Structural placement of the module |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this PRD |

## Open Questions

None — D1–D12 agreed with the user on 2026-10-26 (pure module + `currencies.py`,
  no storage, no endpoint; error / warning / info roll-up; lenient required fields, `unknown`
  → one warning; tolerance of one minor unit; arithmetic mismatches as warnings with
  tax-inclusive accepted; only headline negatives warn; due-before-invoice error, future
  warning, too-old info; `pycountry` + minor-units table; issues carry `expected` / `actual`;
  12-code catalogue; USD-based one-time rate snapshot from ExchangeRate-API, half-up rounding,
  typed 422 error; B2 / B3 checks out of scope).
