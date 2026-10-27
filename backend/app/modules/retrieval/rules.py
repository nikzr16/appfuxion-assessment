"""Pure helpers of the retrieval module (PRD 0010 D2, D4, D5): normalisation, the invoice
card, history statistics and the vendor-history rules. No database, no LLM.
"""

import hashlib
import re
import statistics
import unicodedata
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from rapidfuzz import fuzz

from app.modules.retrieval.schema import CARD_VERSION, HistoryStats
from app.modules.structured_extraction.schema import InvoiceData

# Line descriptions in the card: at most this many items and characters.
CARD_MAX_ITEMS = 30
CARD_MAX_ITEM_CHARS = 2000
# Amount outlier (D5): smallest history, box-plot fence factor, smallest gap from the median.
OUTLIER_MIN_HISTORY = 5
OUTLIER_IQR_FACTOR = Decimal("1.5")
OUTLIER_MIN_GAP = Decimal("0.25")
# A tax-ID match also needs vendor names at least this similar (rapidfuzz token-set ratio,
# 0-100; decision 0012): one tax ID on invoices from different vendors is an extraction error.
VENDOR_NAME_MIN_SIMILARITY = 80

_CENT = Decimal("0.01")
# Removed from the end of a normalised vendor name, repeatedly ("abc sdn bhd" -> "abc").
_LEGAL_SUFFIXES = (
    "sdn bhd",
    "sdn",
    "bhd",
    "berhad",
    "ltd",
    "limited",
    "pte",
    "plc",
    "inc",
    "llc",
    "co",
    "corp",
    "corporation",
    "company",
    "gmbh",
)
_NON_WORD = re.compile(r"[^\w]+")
_TAX_SEPARATORS = re.compile(r"[\s\-./]+")
_NOT_ALNUM = re.compile(r"[^0-9A-Z]+")
# "1,250.00", "1250", "12.5": thousands separators only in groups of three.
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# Integers this small (counts, ordinals, months) never fail the number check (D8).
FREE_INTEGER_MAX = 12


# -- Normalisation (D4) ---------------------------------------------------------------------


def normalise_tax_id(value: str | None) -> str | None:
    if not value:
        return None
    key = _TAX_SEPARATORS.sub("", value).upper()
    return key or None


def normalise_vendor_name(value: str | None) -> str | None:
    if not value:
        return None
    text = unicodedata.normalize("NFKC", value).lower().replace("&", " and ")
    text = " ".join(_NON_WORD.sub(" ", text).replace("_", " ").split())
    changed = True
    while changed and text:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if text == suffix:
                break
            if text.endswith(" " + suffix):
                text = text[: -len(suffix) - 1].rstrip()
                changed = True
                break
    return text or None


def similar_vendor_names(a: str | None, b: str | None) -> bool:
    """Whether two normalised vendor names can belong to one vendor; a missing name never
    vetoes. Token-set ratio, so "acme" and "acme trading" match (one name contains the other).
    """
    if a is None or b is None:
        return True
    return fuzz.token_set_ratio(a, b) >= VENDOR_NAME_MIN_SIMILARITY


def normalise_invoice_number(value: str | None) -> str | None:
    if not value:
        return None
    key = _NOT_ALNUM.sub("", unicodedata.normalize("NFKC", value).upper())
    return key or None


# -- Card (D2) --------------------------------------------------------------------------------


def build_card(data: InvoiceData) -> str:
    """The short, deterministic text that is embedded for one document."""
    lines = [f"Document type: {data.document_type.value}"]
    if data.vendor:
        tax = f" (tax ID: {data.vendor_tax_id})" if data.vendor_tax_id else ""
        lines.append(f"Vendor: {data.vendor}{tax}")
    if data.invoice_number:
        lines.append(f"Invoice number: {data.invoice_number}")
    dates = []
    if data.invoice_date:
        dates.append(f"Invoice date: {data.invoice_date.isoformat()}")
    if data.due_date:
        dates.append(f"Due date: {data.due_date.isoformat()}")
    if dates:
        lines.append(". ".join(dates))
    if data.total_amount is not None:
        currency = f" {data.currency}" if data.currency else ""
        lines.append(f"Total: {data.total_amount}{currency}")
    descriptions = [
        " ".join(item.description.split())
        for item in data.line_items[:CARD_MAX_ITEMS]
        if item.description and item.description.strip()
    ]
    if descriptions:
        lines.append(f"Items: {'; '.join(descriptions)[:CARD_MAX_ITEM_CHARS]}")
    return "\n".join(lines)


def card_hash(card: str, model: str | None) -> str:
    return hashlib.sha256(f"{CARD_VERSION}\n{card}\n{model or ''}".encode()).hexdigest()


# -- Statistics (D5) --------------------------------------------------------------------------


def money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, ROUND_HALF_UP)


def history_stats(
    totals: Sequence[Decimal], *, count: int, skipped: Sequence[str], base_currency: str
) -> HistoryStats:
    """Sum, range, mean, quartiles and box-plot fences of totals in the base currency."""
    stats = HistoryStats(
        base_currency=base_currency,
        count=count,
        with_total=len(totals),
        skipped_currencies=sorted(set(skipped)),
    )
    if not totals:
        return stats
    ordered = sorted(totals)
    if len(ordered) == 1:
        q1 = median = q3 = ordered[0]
    else:
        q1, median, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    iqr = q3 - q1
    return stats.model_copy(
        update={
            "sum": money(sum(ordered, Decimal(0))),
            "min": money(ordered[0]),
            "max": money(ordered[-1]),
            "mean": money(sum(ordered, Decimal(0)) / len(ordered)),
            "median": money(median),
            "q1": money(q1),
            "q3": money(q3),
            "low_fence": money(q1 - OUTLIER_IQR_FACTOR * iqr),
            "high_fence": money(q3 + OUTLIER_IQR_FACTOR * iqr),
        }
    )


def is_outlier(total: Decimal, stats: HistoryStats) -> bool:
    """Outside the fences and at least 25 % away from the median, with enough history."""
    if stats.with_total < OUTLIER_MIN_HISTORY or stats.median is None or stats.median <= 0:
        return False
    assert stats.low_fence is not None and stats.high_fence is not None
    outside = total < stats.low_fence or total > stats.high_fence
    return outside and abs(total - stats.median) >= OUTLIER_MIN_GAP * stats.median


def format_money(value: Decimal, currency: str | None) -> str:
    text = f"{money(value):,.2f}"
    return f"{currency} {text}" if currency else text


# -- Numbers in answers (D8) ------------------------------------------------------------------


def _canonical(token: str) -> str:
    value = Decimal(token.replace(",", ""))
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def number_tokens(text: str) -> set[str]:
    """Every number in ``text`` in a canonical form (``1,250.00`` and ``1250`` are equal)."""
    return {_canonical(match) for match in _NUMBER.findall(text)}


def unverified_numbers(answer: str, known: set[str]) -> list[str]:
    """Numbers in ``answer`` that appear in none of ``known``, small integers excepted."""
    missing = []
    for token in sorted(number_tokens(answer)):
        if token in known:
            continue
        if token.isdigit() and int(token) <= FREE_INTEGER_MAX:
            continue
        missing.append(token)
    return missing
