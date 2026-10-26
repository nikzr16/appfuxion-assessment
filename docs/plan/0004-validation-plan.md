# 0004 Validation Implementation Plan

> **Type:** Plan | **Must stay current:** No -- record divergences in decision log, rewrite only during re-planning

<!-- AI Context
Role: This document describes *how* to build the feature, not *what* or *why*.
Read the corresponding PRD first for intent and constraints, then use this plan
to guide implementation order, component boundaries, and technical decisions.
Do not rewrite this document during coding. If the implementation diverges from
this plan, add an entry to the decision log instead. Only rewrite during a
deliberate re-planning session.
-->

## Overview

Add the pure `validation` module: `schema.py` (enums, DTOs, the typed conversion error),
`currencies.py` (data only: minor-unit exceptions, excluded ISO codes, the dated USD rate
snapshot) and `service.py` (`validate_invoice`, `convert_currency`). No router, crud, model,
migration or LLM call (PRD D1). One new runtime dependency, `pycountry`, answers "is this a
real ISO 4217 code?" (PRD D8). Nothing is wired into the pipeline: the 0005 agent tools will
call the two service functions.

## Technical Approach

### Layers
`schema.py`, `currencies.py`, `service.py`. The module imports only
`app.modules.structured_extraction.schema` (`InvoiceData`, `LineItem`, `DocumentType`),
`app.core.errors` (`AppError`) and `pycountry`. No DB, storage, LLM or FastAPI import.

### Service API
```python
def validate_invoice(data: InvoiceData, *, today: date | None = None) -> ValidationReport
def convert_currency(amount: Decimal, from_currency: str, to_currency: str) -> ConversionResult
def is_iso_currency(code: str) -> bool        # pycountry lookup minus EXCLUDED_CODES
def minor_units(code: str | None) -> int      # exceptions table, else 2; None/invalid → 2
```
`is_iso_currency` and `minor_units` are public because 0005 (and later 0006 via the API) may
need them to format amounts; they are small and pure.

### Schema (`schema.py`, PRD D2, D9, D10, D11)
```python
class Severity(StrEnum):         ERROR="error" · WARNING="warning" · INFO="info"
class ValidationStatus(StrEnum): PASS="pass" · WARN="warn" · FAIL="fail"
class IssueCode(StrEnum):        # PRD D10, in this order
    MISSING_FIELD · NOT_FINANCIAL_DOCUMENT · INVALID_CURRENCY · SUBTOTAL_TAX_MISMATCH ·
    TAX_INCLUDED · LINE_ITEMS_SUM_MISMATCH · LINE_ITEMS_INCOMPLETE · LINE_AMOUNT_MISMATCH ·
    NEGATIVE_AMOUNT · DUE_BEFORE_INVOICE · DATE_IN_FUTURE · DATE_TOO_OLD

class ValidationIssue(BaseModel):            # frozen
    field: str                               # "total_amount", "line_items[2].amount"
    code: IssueCode
    severity: Severity
    message: str
    expected: Decimal | None = None          # exact; JSON decimal string
    actual: Decimal | None = None

class ValidationReport(BaseModel):           # frozen
    status: ValidationStatus
    issues: list[ValidationIssue]

class ConversionResult(BaseModel):           # frozen
    original_amount: Decimal
    from_currency: str
    to_currency: str
    rate: Decimal                            # 1 from_currency = rate to_currency, 10 sig. digits
    converted_amount: Decimal                # quantised to to_currency minor units
    rate_date: date
    source: str

class CurrencyConversionError(AppError):     # 422, default code "unsupported_currency"
```
`model_dump(mode="json")` writes every `Decimal` as a string and dates as ISO strings
(Pydantic v2 default), so both DTOs go straight into a tool result or JSONB. `field`
shadows nothing on `BaseModel`; a schema test pins the JSON shape.

### Data (`currencies.py`, PRD D8, D11) — constants only, no functions
```python
ISO_4217_AS_OF = "ISO 4217 amendment list, <date of the list the exceptions follow>"
DEFAULT_MINOR_UNITS = 2
MINOR_UNITS: dict[str, int] = {
    # 0 dp
    "BIF": 0, "CLP": 0, "DJF": 0, "GNF": 0, "ISK": 0, "JPY": 0, "KMF": 0, "KRW": 0,
    "PYG": 0, "RWF": 0, "UGX": 0, "UYI": 0, "VND": 0, "VUV": 0, "XAF": 0, "XOF": 0, "XPF": 0,
    # 3 dp
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
    # 4 dp
    "CLF": 4, "UYW": 4,
}
EXCLUDED_CODES = frozenset({"XAU", "XAG", "XPT", "XPD", "XDR", "XSU", "XUA",
                            "XBA", "XBB", "XBC", "XBD", "XTS", "XXX"})
RATES_AS_OF: date = date(...)                # from the snapshot's time_last_update_utc
RATES_SOURCE = "ExchangeRate-API open access (https://www.exchangerate-api.com), USD base"
RATES_PER_USD: dict[str, Decimal] = {"USD": Decimal("1"), "MYR": Decimal("..."), ...}  # 25
```
**Snapshot (once, during Phase 1):** `GET https://open.er-api.com/v6/latest/USD`, copy the
25 PRD D11 currencies as `Decimal("…")` string literals exactly as published, and the date of
`time_last_update_utc`. A comment says how to refresh it (re-run the request, replace the
literals and the date, re-run the tests). No code fetches rates at runtime.

### `validate_invoice` algorithm
```
today = today or date.today()
if data.document_type is UNKNOWN:
    return report([issue(document_type, NOT_FINANCIAL_DOCUMENT, WARNING)])   # D3: nothing else
currency_ok = data.currency is not None and is_iso_currency(data.currency)
tol = Decimal(1).scaleb(-minor_units(data.currency if currency_ok else None))   # D4
issues  = _required_fields(data)              # D3
issues += _currency(data)                     # D8
issues += _dates(data, today)                 # D7
issues += _negatives(data)                    # D6
issues += _totals(data, tol)                  # D5 (a)
issues += _line_items(data, tol)              # D5 (c) per line, then (b) sum
return ValidationReport(status=_roll_up(issues), issues=issues)               # D2
```
The order of the helpers is the report order (PRD D9); inside a helper, fields follow
`InvoiceData` order and lines follow their index. All comparisons are
`abs(a - b) > tol` on exact `Decimal`s; nothing is rounded except text in messages.

| Helper | Rule (PRD) | Issue |
|---|---|---|
| `_required_fields` | Table below (D3); empty `line_items` → `field="line_items"` | `missing_field` with the table's severity |
| `_currency` | `currency` set and not `is_iso_currency` | `invalid_currency` error |
| `_dates` | both dates set and `due_date < invoice_date` | `due_before_invoice` error (field `due_date`) |
| | `invoice_date > today + 1 day` | `date_in_future` warning |
| | `invoice_date < today − 10 years` (Feb 29 → Feb 28) | `date_too_old` info |
| `_negatives` | `subtotal`, `tax`, `total_amount` < 0 (in that order) | `negative_amount` warning, `actual` = value |
| `_totals` | `subtotal` and `total_amount` set. With `tax`: `subtotal + tax ≈ total` passes; else `subtotal ≈ total` (and `tax ≠ 0`) → `tax_included` info; else mismatch. Without `tax`: `subtotal ≈ total` or mismatch | `subtotal_tax_mismatch` warning, field `total_amount`, `expected` = subtotal (+ tax), `actual` = total |
| `_line_items` (c) | per line with `quantity`, `unit_price`, `amount` all set: `quantity × unit_price ≈ amount` | `line_amount_mismatch` warning, field `line_items[i].amount`, `expected` = q × p, `actual` = amount |
| `_line_items` (b) | lines present; any `amount` null → one `line_items_incomplete` info ("2 of 7 lines have no amount; the line total was not checked") and stop. Else `s = Σ amount`: vs `subtotal` if set; else vs `total` or `total − tax` (either passes); neither set → skip | `line_items_sum_mismatch` warning, field `line_items`, `expected` = s, `actual` = subtotal or total |

**Required fields (D3):**

| Field | invoice | receipt |
|---|---|---|
| `vendor` | error | error |
| `invoice_number` | warning | — |
| `invoice_date` | warning | warning |
| `due_date` | info | — |
| `currency` | warning | warning |
| `total_amount` | error | error |
| `line_items` (empty) | info | info |

**Roll-up (D2):** any `error` → `fail`; else any `warning` → `warn`; else `pass`.

**Messages:** complete sentences built by code. Money is formatted with
`f"{value:,.{n}f}"` where `n` = the currency's minor units (2 when unknown) and the code
appended when valid, e.g. `"Subtotal 100.00 + tax 6.00 = 106.00 MYR, but the total is
108.00 MYR (difference 2.00 MYR)."`. Quantity and unit price are shown as printed
(`normalize()`d). Lines are named 1-based ("Line 3"). A missing date's message adds "(it may
have been printed in an ambiguous day/month format)". Missing-field messages are a fixed
`"<Label> is missing."` per field.

**Never raises (D9):** every helper only reads non-null values it checked; `Decimal`
arithmetic on any finite `InvoiceData` value (Pydantic already rejects NaN/inf) cannot raise
under the default context (results are rounded to 28 significant digits, which is far
beyond any tolerance). A test feeds extreme values (`1E+20`, `1E-10`, negative zero) to pin
this.

### `convert_currency` algorithm (PRD D11)
```
src, dst = from_currency.strip().upper(), to_currency.strip().upper()
if not isinstance(amount, Decimal) or not amount.is_finite():
    raise CurrencyConversionError(code="invalid_amount")
for code in (src, dst): if code not in RATES_PER_USD:
    raise CurrencyConversionError(code="unsupported_currency",
          message=f"{code} is not in the rate table (as of {RATES_AS_OF}). Supported: ...")
exact = Decimal(1) if src == dst else RATES_PER_USD[dst] / RATES_PER_USD[src]   # prec 28
try:
    converted = (amount * exact).quantize(Decimal(1).scaleb(-minor_units(dst)), ROUND_HALF_UP)
except InvalidOperation:                     # result too large for 28 digits
    raise CurrencyConversionError(code="invalid_amount")
rate = exact rounded to 10 significant digits (localcontext(prec=10), +exact)
return ConversionResult(original_amount=amount, from_currency=src, to_currency=dst,
                        rate=rate, converted_amount=converted,
                        rate_date=RATES_AS_OF, source=RATES_SOURCE)
```
The converted amount uses the exact cross rate; the reported `rate` is rounded for display
only (documented in the docstring). Negative amounts convert normally (credit notes).

### Errors
| Code | Status | Class | Raised when |
|---|---|---|---|
| `unsupported_currency` | 422 | `CurrencyConversionError(AppError)` in `validation/schema.py` | a code is not in `RATES_PER_USD` (including invalid / lower-case garbage) |
| `invalid_amount` | 422 | same | amount not a finite `Decimal`, or the result overflows 28 digits |

`validate_invoice` raises nothing.

### Logging
None in `validate_invoice` (pure, called often, the agent run records the report in 0005).
`convert_currency` logs nothing either; its errors carry the reason. 0005 logs tool calls.

## System Components

| Component | Responsibility |
|---|---|
| `modules/validation/__init__.py` | Package marker (empty, like the other modules) |
| `modules/validation/schema.py` | `Severity`, `ValidationStatus`, `IssueCode`, `ValidationIssue`, `ValidationReport`, `ConversionResult`, `CurrencyConversionError` |
| `modules/validation/currencies.py` | `MINOR_UNITS`, `DEFAULT_MINOR_UNITS`, `EXCLUDED_CODES`, `ISO_4217_AS_OF`, `RATES_PER_USD`, `RATES_AS_OF`, `RATES_SOURCE` |
| `modules/validation/service.py` | `validate_invoice`, `convert_currency`, `is_iso_currency`, `minor_units` + private check helpers |
| `backend/pyproject.toml`, `backend/uv.lock` | add `pycountry` |

No change to `app/main.py`, `app/models.py`, migrations or config.

## Processing Flow

```
(0005 validate_invoice tool / tests) ── validate_invoice(InvoiceData, today?) ──▶ service
  unknown ─────────────────────────────▶ report(warn, [not_financial_document])
  required → currency → dates → negatives → totals → line items
  roll-up: error → fail · warning → warn · else pass ──▶ ValidationReport (never raises)

(0005 convert_currency tool / tests) ── convert_currency(amount, from, to) ──▶ service
  bad amount ─────────────────▶ 422 invalid_amount
  code not in rate table ─────▶ 422 unsupported_currency
  cross rate via USD → half-up to target minor units ──▶ ConversionResult (rate_date, source)
```

## Dependencies

| Dependency | Purpose |
|---|---|
| `pycountry` (runtime, LGPL-2.1-only, no transitive deps; current 26.2.16) | ISO 4217 code lookup (`pycountry.currencies.get(alpha_3=...)`) |
| ExchangeRate-API open access (one-time manual fetch, not a runtime dependency) | Source of the dated rate snapshot; attribution kept in `RATES_SOURCE` |

## Implementation Phases

### Phase 1: Dependency and data
`uv add pycountry`. Fetch the snapshot once and write `currencies.py`. Tests in
`tests/modules/validation/test_currencies.py`: every rate-table code is a valid ISO code and
has a positive `Decimal` rate; `USD` is exactly 1; the 25 PRD codes are all present;
`RATES_AS_OF` is a `date`; `is_iso_currency` (`MYR` yes, `ABC` / `XAU` / `XTS` no, `XAF`
yes); `minor_units` (JPY 0, MYR 2, KWD 3, CLF 4, `None` 2).

### Phase 2: Schema
`schema.py` + `tests/modules/validation/test_schema.py`: report and conversion result
round-trip through `model_dump(mode="json")` → `model_validate` unchanged; `Decimal`s are
JSON strings (`"106.00"`), dates ISO; enum values are the PRD strings; issue keys are
exactly `{field, code, severity, message, expected, actual}`.

### Phase 3: `validate_invoice`
`service.py` checks + `tests/modules/validation/test_validate_invoice.py` (table-driven, see
Testing Strategy).

### Phase 4: `convert_currency`
`tests/modules/validation/test_convert_currency.py` (table-driven).

### Phase 5: Close-out
`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` green (DB via
`docker compose --env-file .env -f db/docker-compose.yml up -d`, since the shared conftest
needs it). Update `docs/reference/folder-structure.md` (module files, DTOs, the issue code
catalogue with severities, error codes, rate-table date and source, `pycountry`); append
0004 to `ENGINEERING_NOTES.md` (architecture, limitations — static rates, no
discount/shipping fields, tax-inclusive heuristic — and production improvements); README
only if setup changes (it does not: `uv sync` picks up `pycountry`); decision log
`docs/decisions/0005-…` for any divergence; roadmap stays `in progress` until you confirm
the merge; commit on `feature/0004-validation`.

## Testing Strategy

- **No DB, no LLM in the tests themselves**: plain function calls. (The shared session
  conftest still connects to Postgres; that is unchanged.)
- **Fixture** (`tests/modules/validation/conftest.py`): `make_invoice(**overrides)` — a
  complete, consistent MYR invoice: lines `2 × 25.00 = 50.00` and `1 × 50.00 = 50.00`,
  subtotal `100.00`, tax `6.00`, total `106.00`, invoice date `2026-10-01`, due
  `2026-10-31`, vendor and number set; `TODAY = date(2026, 10, 26)`. Line overrides via a
  `lines=[...]` argument. Built with `InvoiceData.model_validate` so tests use real DTOs.
- **`test_validate_invoice.py`** (each row: overrides → expected list of
  `(code, severity, field)`, plus status):
  - clean invoice → `pass`, `[]` (AC 1)
  - D3: each missing field for invoice and receipt (severity per table); receipt without
    number / due date → no issue; empty lines → info; `unknown` → exactly one
    `not_financial_document` even when other fields are set (AC 2)
  - roll-up: error → `fail`, warning only → `warn`, info only → `pass` (AC 3)
  - D5 (a): `total 108.00` → mismatch with `expected 106.00`, `actual 108.00`, message
    contains `106.00`, `108.00`, `2.00`; tax-inclusive (`subtotal 106`, `tax 6`, `total
    106`) → `tax_included` info; no tax → subtotal vs total (AC 4)
  - D5 (b): sum vs subtotal; no subtotal → vs total or total − tax; one null amount →
    `line_items_incomplete` and no sum issue (AC 5)
  - D5 (c): `2 × 25.00 ≠ 49.00` → `line_amount_mismatch` at `line_items[0].amount`, message
    says "Line 1"; unit price with 4 dp (`3 × 3.3333 = 9.9999` vs `10.00`) passes (AC 6)
  - D4 tolerance: MYR 0.01 off passes / 0.02 fails; JPY 1 off passes / 2 fails; KWD 0.001
    passes / 0.002 fails; null currency uses 0.01 (AC 7)
  - D6: negative line amount (discount) → no issue; negative total → `negative_amount`
    with `actual` (AC 8)
  - D7: due before invoice → error; invoice date `2026-10-28` → `date_in_future`,
    `2026-10-27` → nothing; `2016-10-25` → `date_too_old`, `2016-10-26` → nothing; `today`
    injected (AC 9)
  - D8: `ABC`, `XAU`, `XTS` → `invalid_currency`; `XAF` → none (AC 10)
  - issue order is deterministic (same input twice → identical report); extreme values
    never raise; report survives JSON round-trip (AC 11)
- **`test_convert_currency.py`**: USD → MYR equals `RATES_PER_USD["MYR"]` × amount, rounded
  half-up to 2 dp; MYR → JPY has 0 dp; cross rate MYR → SGD equals `SGD / MYR`; half-up on
  an exact `.5` boundary (constructed from table values); same currency → rate 1 and
  amount quantised; `"myr"` accepted; negative amount converts; result has `rate_date ==
  RATES_AS_OF` and `source == RATES_SOURCE`; `rate` has ≤ 10 significant digits (AC 12);
  `ABC` / valid-but-unsupported `KWD` → `unsupported_currency`; `Decimal("NaN")`,
  `Decimal("Infinity")`, a float → `invalid_amount` (AC 13). Expected values are computed
  in the test from the table, so a rate refresh does not break the tests.
- **`test_layering.py`** (or a test in `test_validate_invoice.py`): AST scan of
  `app/modules/validation/*.py` — the only `app.modules.*` import is
  `app.modules.structured_extraction.schema`; no `sqlalchemy`, `fastapi`, `openai`,
  `app.core.db`, `app.core.llm`, `app.core.storage` import (AC 15).
- Never the real OpenAI API; no network in tests.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Discount, shipping or cash-rounding lines exist only in the totals block (`InvoiceData` has no fields for them) | False `subtotal_tax_mismatch` / `line_items_sum_mismatch` on a correct invoice | Warnings, not errors (PRD D5); the message states the difference so the summary can say "possibly shipping or discount"; documented limitation |
| Tax-inclusive heuristic hides a real error (`subtotal = total`, tax forgotten) | A wrong invoice passes with an info note | Rare; the `tax_included` info still appears in the report and the summary |
| Static rates go stale | Converted amounts drift from today's value | `rate_date` and `source` are in every result; documented limitation; refresh is a one-file change |
| `pycountry`'s ISO data lags or changes a code | A new currency is reported as invalid (or vice versa) | Pinned via `uv.lock`; the test suite pins the codes we rely on; upgrade is a lock bump |
| `pycountry` has no minor units | Wrong tolerance for a currency missing from the exception table | Default 2 is right for most currencies; the exception list follows ISO 4217 and is tested |
| ExchangeRate-API terms require attribution | Licence issue in a public repo | `RATES_SOURCE` names it; carried in every result and in ENGINEERING_NOTES / README limitations |
| `date.today()` makes the date checks time-dependent | Flaky tests | `today` is injectable; tests always pass it |
| 0005 prompt relies on message wording | Summary quality changes if messages change | Codes and fields are the stable contract (PRD D10); messages may improve freely |

## Roadmap Phase

**Phase:** Phase 1 — Core Pipeline (brief Parts 1–5)

## Related Documents

| Document | Type | Relationship |
|---|---|---|
| `docs/product-roadmap.md` | Roadmap | Phase assignment and sequencing for this plan |
| `docs/prd/0004-validation-prd.md` | Intent | Product goals and decisions (D1–D12) this plan implements |
| `docs/prd/0003-structured-extraction-prd.md` | Intent | `InvoiceData` contract consumed here |
| `docs/reference/folder-structure.md` | Reference | Structural placement of planned components |
| `docs/decisions/NNNN-*.md` | Decision log | Divergences from this plan |

## Open Questions

None.
