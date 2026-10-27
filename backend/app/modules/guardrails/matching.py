"""Pure matchers that look one extracted value up in a document's text (PRD 0008 D2).

``DocumentText`` prepares the text once (page markers masked, NFKC + case-fold + collapsed
whitespace, number tokens, compact and loose views); each ``find_*`` function returns a
``Match`` with offsets into the **original** ``raw_text`` or ``None``. Nothing here knows
about ``InvoiceData``; the service decides which matcher a field uses.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cached_property

from rapidfuzz import fuzz

from app.modules.guardrails.schema import GroundingStatus, MatchKind
from app.modules.text_extraction.schema import ExtractionMethod

PAGE_MARKER = re.compile(r"^--- Page (\d+) ---$", re.MULTILINE)

# Fuzzy similarity (0-100) that still counts as a ``weak`` match for free text.
FUZZY_THRESHOLD = {ExtractionMethod.PDF_PARSER: 85, ExtractionMethod.VISION: 80}
# Shorter free-text values must match exactly (fuzzy scores mean little on 1-3 characters).
MIN_FUZZY_CHARS = 4

# Characters an OCR / vision model commonly confuses with digits (case-folded).
_OCR_DIGITS = str.maketrans({"o": "0", "i": "1", "l": "1", "|": "1", "s": "5", "b": "8"})

_MONTHS: dict[int, tuple[str, ...]] = {
    # English full and short names, then Malay full and short names (longest first).
    1: ("january", "januari", "jan"),
    2: ("february", "februari", "feb"),
    3: ("march", "mac", "mar"),
    4: ("april", "apr"),
    5: ("may", "mei"),
    6: ("june", "jun"),
    7: ("july", "julai", "jul"),
    8: ("august", "ogos", "aug", "ogs"),
    9: ("september", "sept", "sep"),
    10: ("october", "oktober", "oct", "okt"),
    11: ("november", "nov"),
    12: ("december", "disember", "dec", "dis"),
}

# Printed symbols / words per ISO code, case-folded (mirrors the 0003 prompt's table).
CURRENCY_SYMBOLS: dict[str, tuple[str, ...]] = {
    "MYR": ("rm", "ringgit"),
    "SGD": ("s$",),
    "IDR": ("rp", "rupiah"),
    "THB": ("฿", "baht"),
    "PHP": ("₱", "php", "philippine peso"),
    "VND": ("₫", "đ", "dong"),
    "BND": ("b$",),
    "KHR": ("៛", "riel"),
    "LAK": ("₭", "kip"),
    "MMK": ("ks", "kyat"),
    "USD": ("us$",),
    "EUR": ("€",),
    "GBP": ("£",),
    "INR": ("₹",),
    "KRW": ("₩",),
    "HKD": ("hk$",),
    "TWD": ("nt$",),
    "AUD": ("a$", "au$"),
    "NZD": ("nz$",),
    "CAD": ("c$", "ca$"),
    "CNY": ("cn¥", "rmb", "元"),
    "JPY": ("jp¥", "円"),
    "CHF": ("chf", "fr."),
    "AED": ("aed", "د.إ"),
    "SAR": ("sar", "﷼"),
}

_NUMBER = re.compile(r"\d[\d.,']*\d|\d")
_SPACED_NUMBER = re.compile(r"(?<![\d.,])\d{1,3}(?: \d{3})+(?:[.,]\d+)?(?![\d])")
_OCR_NUMBER = re.compile(r"(?<![a-z])[\doilsb|][\doilsb|.,']*[\doilsb|](?![a-z])")


@dataclass(frozen=True)
class Match:
    status: GroundingStatus
    kind: MatchKind
    start: int
    end: int
    similarity: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class _View:
    """A transformed copy of the text with each character's offset in ``raw_text``."""

    text: str
    offsets: tuple[int, ...]

    def span(self, start: int, end: int) -> tuple[int, int]:
        return self.offsets[start], self.offsets[end - 1] + 1


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _view(raw: str, keep: str = "space") -> _View:
    """Normalise ``raw`` char by char, remembering where each output char came from.

    ``keep="space"``: NFKC + case-fold, whitespace runs become one space.
    ``keep="loose"``: as ``space`` but punctuation also becomes a space.
    ``keep="compact"``: letters and digits only (identifiers).
    """
    chars: list[str] = []
    offsets: list[int] = []
    for index, raw_char in enumerate(raw):
        for char in _fold(raw_char):
            if keep == "compact":
                if not char.isalnum():
                    continue
            elif char.isspace() or (keep == "loose" and not char.isalnum()):
                if not chars or chars[-1] == " ":
                    continue
                char = " "
            chars.append(char)
            offsets.append(index)
    return _View("".join(chars), tuple(offsets))


def normalise_value(value: str, keep: str = "space") -> str:
    return _view(value, keep).text.strip()


def _readings(token: str) -> set[Decimal]:
    """Every plausible value of a printed number under both separator conventions."""
    token = token.replace("'", "").strip(".,")
    if not token:
        return set()
    readings: list[str] = []
    dots, commas = token.count("."), token.count(",")
    if dots and commas:
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
        thousands = "," if decimal_sep == "." else "."
        readings.append(token.replace(thousands, "").replace(decimal_sep, "."))
    elif dots or commas:
        sep = "." if dots else ","
        groups = token.split(sep)
        if len(groups) == 2:
            readings.append(f"{groups[0]}.{groups[1]}")  # decimal separator
            if len(groups[1]) == 3:
                readings.append("".join(groups))  # thousands separator
        else:
            if all(len(group) == 3 for group in groups[1:]):
                readings.append("".join(groups))
            readings.append("".join(groups[:-1]) + "." + groups[-1])
    else:
        readings.append(token)
    values: set[Decimal] = set()
    for reading in readings:
        try:
            values.add(Decimal(reading).normalize())
        except InvalidOperation:
            continue
    return values


@dataclass(frozen=True)
class _Number:
    values: frozenset[Decimal]
    start: int
    end: int
    ocr: bool


class DocumentText:
    """One document's text, prepared for repeated lookups."""

    def __init__(self, raw_text: str, method: ExtractionMethod) -> None:
        self.raw = raw_text
        self.method = method
        self._pages = [(m.start(), int(m.group(1))) for m in PAGE_MARKER.finditer(raw_text)]
        # Markers are masked with spaces (same length) so "Page 2" never matches a 2.
        self._masked = PAGE_MARKER.sub(lambda m: " " * len(m.group(0)), raw_text)

    @property
    def is_vision(self) -> bool:
        return self.method is ExtractionMethod.VISION

    def page_at(self, offset: int) -> int:
        page = 1
        for start, number in self._pages:
            if start > offset:
                break
            page = number
        return page

    @cached_property
    def spaced(self) -> _View:
        return _view(self._masked, "space")

    @cached_property
    def loose(self) -> _View:
        return _view(self._masked, "loose")

    @cached_property
    def compact(self) -> _View:
        return _view(self._masked, "compact")

    @cached_property
    def numbers(self) -> list[_Number]:
        view = self.spaced
        found: list[_Number] = []
        for pattern in (_NUMBER, _SPACED_NUMBER):
            for m in pattern.finditer(view.text):
                values = _readings(m.group(0).replace(" ", ""))
                if values:
                    start, end = view.span(m.start(), m.end())
                    found.append(_Number(frozenset(values), start, end, ocr=False))
        if self.is_vision:
            for m in _OCR_NUMBER.finditer(view.text):
                token = m.group(0)
                if not any(c.isdigit() for c in token) or token.isdigit():
                    continue
                if not any(c in "oilsb|" for c in token):
                    continue
                values = _readings(token.translate(_OCR_DIGITS))
                if values:
                    start, end = view.span(m.start(), m.end())
                    found.append(_Number(frozenset(values), start, end, ocr=True))
        found.sort(key=lambda n: (n.ocr, n.start))
        return found


# -- Matchers -----------------------------------------------------------------------------


def find_number(doc: DocumentText, value: Decimal) -> Match | None:
    """Equal value under either separator convention; sign ignored ("(50.00)" = -50)."""
    target = abs(value).normalize()
    for number in doc.numbers:
        if target in number.values:
            if number.ocr:
                return Match(
                    GroundingStatus.WEAK,
                    MatchKind.OCR,
                    number.start,
                    number.end,
                    note="Matched after correcting likely OCR misreads",
                )
            return Match(GroundingStatus.GROUNDED, MatchKind.NUMBER, number.start, number.end)
    return None


def _date_patterns(day: date) -> list[tuple[re.Pattern[str], bool]]:
    """(pattern, ambiguous) pairs for every printed form of ``day``."""
    d = rf"0?{day.day}"
    m = rf"0?{day.month}"
    y = rf"(?:{day.year}|{day.year % 100:02d})"
    sep = r"(?P<s>[/\-. ])"
    numeric_ambiguous = day.day <= 12 and day.month <= 12 and day.day != day.month
    names = "|".join(_MONTHS[day.month])
    ordinal = r"(?:st|nd|rd|th)?"
    gap = r"[\s\-/.,]*"
    patterns = [
        (rf"(?<!\d){day.year}{sep}{m}(?P=s){d}(?!\d)", False),  # ISO / Y-M-D
        (rf"(?<!\d){d}{sep}{m}(?P=s){y}(?!\d)", numeric_ambiguous),  # D/M/Y
        (rf"(?<!\d){m}{sep}{d}(?P=s){y}(?!\d)", numeric_ambiguous),  # M/D/Y
        (rf"(?<!\w){d}{ordinal}{gap}(?:{names})\.?{gap}'?{y}(?!\d)", False),
        (rf"(?<!\w)(?:{names})\.?{gap}{d}{ordinal}{gap}'?{y}(?!\d)", False),
    ]
    return [(re.compile(pattern), ambiguous) for pattern, ambiguous in patterns]


def find_date(doc: DocumentText, value: date) -> Match | None:
    """A printed form of the date; only an ambiguous numeric form gives ``weak``."""
    view = doc.spaced
    weak: Match | None = None
    for pattern, ambiguous in _date_patterns(value):
        found = pattern.search(view.text)
        if found is None:
            continue
        start, end = view.span(found.start(), found.end())
        if not ambiguous:
            return Match(GroundingStatus.GROUNDED, MatchKind.DATE, start, end)
        weak = weak or Match(
            GroundingStatus.WEAK,
            MatchKind.DATE,
            start,
            end,
            note="Only found in an ambiguous day/month format",
        )
    return weak


def find_identifier(doc: DocumentText, value: str) -> Match | None:
    """Exact after dropping spaces and punctuation; vision may fold OCR look-alikes."""
    needle = normalise_value(value, "compact")
    if not needle:
        return None
    view = doc.compact
    index = view.text.find(needle)
    if index >= 0:
        start, end = view.span(index, index + len(needle))
        return Match(GroundingStatus.GROUNDED, MatchKind.IDENTIFIER, start, end)
    if doc.is_vision:
        index = view.text.translate(_OCR_DIGITS).find(needle.translate(_OCR_DIGITS))
        if index >= 0:
            start, end = view.span(index, index + len(needle))
            return Match(
                GroundingStatus.WEAK,
                MatchKind.OCR,
                start,
                end,
                note="Matched after correcting likely OCR misreads",
            )
    return None


def find_text(doc: DocumentText, value: str) -> Match | None:
    """Exact (normalised) substring, else a close fuzzy match above the threshold."""
    for keep, view in (("space", doc.spaced), ("loose", doc.loose)):
        needle = normalise_value(value, keep)
        if not needle:
            return None
        index = view.text.find(needle)
        if index >= 0:
            start, end = view.span(index, index + len(needle))
            return Match(GroundingStatus.GROUNDED, MatchKind.EXACT, start, end)
    # Letter-spaced headings ("K E D A I  M A J U") and odd punctuation: letters and digits
    # only, still an exact match.
    compact = normalise_value(value, "compact")
    if len(compact) >= MIN_FUZZY_CHARS and (index := doc.compact.text.find(compact)) >= 0:
        start, end = doc.compact.span(index, index + len(compact))
        return Match(GroundingStatus.GROUNDED, MatchKind.EXACT, start, end)
    needle = normalise_value(value, "loose")
    if len(needle) < MIN_FUZZY_CHARS or not doc.loose.text:
        return None
    aligned = fuzz.partial_ratio_alignment(needle, doc.loose.text)
    similarity = round(aligned.score)
    if similarity < FUZZY_THRESHOLD[doc.method] or aligned.dest_end <= aligned.dest_start:
        return None
    start, end = doc.loose.span(aligned.dest_start, aligned.dest_end)
    return Match(
        GroundingStatus.WEAK, MatchKind.FUZZY, start, end, similarity=similarity, note=None
    )


def _symbol_pattern(symbol: str) -> re.Pattern[str]:
    after = r"(?![a-z])" if symbol[-1].isalpha() else ""
    return re.compile(rf"(?<![a-z]){re.escape(symbol)}{after}")


def find_currency(doc: DocumentText, code: str) -> Match | None:
    """The ISO code as printed (grounded) or a symbol that maps to it (inferred)."""
    view = doc.spaced
    found = re.search(rf"(?<![a-z]){re.escape(code.casefold())}(?![a-z])", view.text)
    if found:
        start, end = view.span(found.start(), found.end())
        return Match(GroundingStatus.GROUNDED, MatchKind.EXACT, start, end)
    for symbol in CURRENCY_SYMBOLS.get(code.upper(), ()):
        found = _symbol_pattern(symbol).search(view.text)
        if found:
            start, end = view.span(found.start(), found.end())
            return Match(
                GroundingStatus.INFERRED,
                MatchKind.SYMBOL,
                start,
                end,
                note=f"Inferred from the printed symbol '{doc.raw[start:end]}'",
            )
    return None
