"""The value matchers behind the grounding check (PRD 0008 D2)."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.guardrails.matching import (
    CURRENCY_SYMBOLS,
    DocumentText,
    find_currency,
    find_date,
    find_identifier,
    find_number,
    find_text,
)
from app.modules.guardrails.schema import GroundingStatus, MatchKind
from app.modules.structured_extraction import prompts as extraction_prompts
from app.modules.text_extraction.schema import ExtractionMethod

PDF = ExtractionMethod.PDF_PARSER
VISION = ExtractionMethod.VISION


def doc(text: str, method: ExtractionMethod = PDF) -> DocumentText:
    return DocumentText(text, method)


def matched(document: DocumentText, match: object) -> str:
    assert match is not None
    return document.raw[match.start : match.end]  # type: ignore[attr-defined]


# -- Numbers ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Total 1,234.56", "1234.56"),
        ("Total 1.234,56", "1234.56"),
        ("Total 1 234,56", "1234.56"),
        ("Total 1'234.56", "1234.56"),
        ("Total RM1,234.56", "1234.56"),
        ("Total $12.30", "12.3"),
        ("Total 50", "50.00"),
        ("Total 50.00", "50"),
        ("Discount (50.00)", "-50.00"),
        ("Discount -50.00", "-50"),
        ("Total 1.234", "1234"),  # thousands reading
        ("Total 1.234", "1.234"),  # decimal reading
        ("Total 12,5", "12.5"),
        ("Amount 1,234,567.89", "1234567.89"),
    ],
)
def test_numbers_match_by_value_under_both_conventions(text: str, value: str) -> None:
    found = find_number(doc(text), Decimal(value))
    assert found is not None and found.status is GroundingStatus.GROUNDED


def test_numbers_report_the_printed_span() -> None:
    document = doc("Subtotal 100.00\nTotal 1,259.56")
    assert matched(document, find_number(document, Decimal("1259.56"))) == "1,259.56"


@pytest.mark.parametrize("value", ["99.99", "1259.65", "12.35"])
def test_absent_numbers_are_not_found(value: str) -> None:
    assert find_number(doc("Total 1,259.56 and 12.30"), Decimal(value)) is None


def test_page_markers_never_match_a_number() -> None:
    assert find_number(doc("--- Page 2 ---\nNo amounts here"), Decimal("2")) is None


def test_ocr_confusions_are_weak_and_only_on_vision_text() -> None:
    text = "Total RM l2.5O"
    vision = find_number(doc(text, VISION), Decimal("12.50"))
    assert vision is not None
    assert (vision.status, vision.kind) == (GroundingStatus.WEAK, MatchKind.OCR)
    assert find_number(doc(text, PDF), Decimal("12.50")) is None


def test_a_clean_token_wins_over_an_ocr_reading() -> None:
    found = find_number(doc("Sub l2.50 Total 12.50", VISION), Decimal("12.50"))
    assert found is not None and found.status is GroundingStatus.GROUNDED


# -- Dates ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Date: 2025-03-14",
        "Date: 14/03/2025",
        "Date: 14-3-25",
        "Date: 03/14/2025",
        "Date: 14.03.2025",
        "Date: 14 March 2025",
        "Date: 14th Mar 2025",
        "Date: 14-Mar-2025",
        "Date: March 14, 2025",
        "Date: Mar. 14 2025",
        "Tarikh: 14 Mac 2025",
        "Tarikh: 14 MAC 2025",
    ],
)
def test_unambiguous_date_forms_are_grounded(text: str) -> None:
    found = find_date(doc(text), date(2025, 3, 14))
    assert found is not None and found.status is GroundingStatus.GROUNDED


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Tarikh: 1 Ogos 2025", date(2025, 8, 1)),
        ("Tarikh: 5 Disember 2025", date(2025, 12, 5)),
        ("Tarikh: 9 Mei 2025", date(2025, 5, 9)),
        ("Tarikh: 30 Okt 2025", date(2025, 10, 30)),
    ],
)
def test_malay_month_names(text: str, value: date) -> None:
    found = find_date(doc(text), value)
    assert found is not None and found.status is GroundingStatus.GROUNDED


def test_ambiguous_numeric_date_is_weak() -> None:
    found = find_date(doc("Due: 03/04/2025"), date(2025, 4, 3))
    assert found is not None
    assert found.status is GroundingStatus.WEAK
    assert found.note == "Only found in an ambiguous day/month format"


def test_same_day_and_month_is_not_ambiguous() -> None:
    found = find_date(doc("Due: 04/04/2025"), date(2025, 4, 4))
    assert found is not None and found.status is GroundingStatus.GROUNDED


def test_an_unambiguous_form_elsewhere_wins_over_an_ambiguous_one() -> None:
    found = find_date(doc("Due: 03/04/2025 (3 April 2025)"), date(2025, 4, 3))
    assert found is not None and found.status is GroundingStatus.GROUNDED


@pytest.mark.parametrize("text", ["Date: 14/03/2024", "Date: 4/03/2025", "Ref 214/03/2025"])
def test_other_dates_do_not_match(text: str) -> None:
    assert find_date(doc(text), date(2025, 3, 14)) is None


# -- Identifiers ------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["INV-2025-0042", "inv 2025 0042", "INV/2025/0042"])
def test_identifiers_ignore_case_spaces_and_punctuation(value: str) -> None:
    document = doc("Invoice No: INV-2025-0042\n")
    found = find_identifier(document, value)
    assert found is not None and found.status is GroundingStatus.GROUNDED
    assert matched(document, found) == "INV-2025-0042"


def test_one_wrong_digit_is_not_an_identifier_match() -> None:
    assert find_identifier(doc("Invoice No: INV-2025-0042"), "INV-2025-0043") is None


def test_vision_identifiers_fold_ocr_look_alikes_as_weak() -> None:
    found = find_identifier(doc("Inv N0: lNV-OO42", VISION), "INV-0042")
    assert found is not None and found.status is GroundingStatus.WEAK
    assert find_identifier(doc("Inv N0: lNV-OO42", PDF), "INV-0042") is None


# -- Free text --------------------------------------------------------------------------


def test_text_exact_ignoring_case_whitespace_and_punctuation() -> None:
    document = doc("ABC SUPPLY SDN. BHD.\nNo. 12, Jalan Ampang,\n50450 Kuala Lumpur")
    vendor = find_text(document, "ABC Supply Sdn Bhd")
    address = find_text(document, "No. 12, Jalan Ampang, 50450 Kuala Lumpur")
    assert vendor is not None and vendor.status is GroundingStatus.GROUNDED
    assert address is not None and address.status is GroundingStatus.GROUNDED
    assert matched(document, address) == "No. 12, Jalan Ampang,\n50450 Kuala Lumpur"


def test_letter_spaced_headings_still_match_exactly() -> None:
    document = doc("K E D A I   M A J U   E N T E R P R I S E\nInvoice 12")
    found = find_text(document, "Kedai Maju Enterprise")
    assert found is not None and found.status is GroundingStatus.GROUNDED
    assert matched(document, found) == "K E D A I   M A J U   E N T E R P R I S E"


def test_close_text_is_weak_with_its_similarity() -> None:
    found = find_text(doc("Sold by ABC SUPPLY SDN BHD, Kuala Lumpur"), "ABC Suply Sdn Bhd")
    assert found is not None
    assert (found.status, found.kind) == (GroundingStatus.WEAK, MatchKind.FUZZY)
    assert found.similarity is not None and 85 <= found.similarity < 100


def test_unrelated_text_is_not_found() -> None:
    assert find_text(doc("ABC SUPPLY SDN BHD"), "XYZ Trading Company") is None


def test_vision_text_gets_a_lower_fuzzy_threshold() -> None:
    text = "Vendor: Kedai Runcit Ahmad Bersaudara"
    value = "Kedei Runct Ahmd Bersodara"
    vision = find_text(doc(text, VISION), value)
    assert vision is not None and 80 <= (vision.similarity or 0) < 85
    assert find_text(doc(text, PDF), value) is None


def test_short_text_must_match_exactly() -> None:
    assert find_text(doc("Vendor: ABD"), "ABC") is None


# -- Currency ---------------------------------------------------------------------------


def test_printed_iso_code_is_grounded() -> None:
    found = find_currency(doc("Total (MYR) 10.00"), "MYR")
    assert found is not None and found.status is GroundingStatus.GROUNDED


@pytest.mark.parametrize(
    ("text", "code"),
    [("Total RM 10.00", "MYR"), ("Total RM10.00", "MYR"), ("S$ 5.00", "SGD"), ("€5", "EUR")],
)
def test_symbol_is_inferred(text: str, code: str) -> None:
    found = find_currency(doc(text), code)
    assert found is not None and found.status is GroundingStatus.INFERRED
    assert found.note and "Inferred from the printed symbol" in found.note


@pytest.mark.parametrize(
    ("text", "code"),
    [("Total $10.00", "USD"), ("Form 10.00", "MYR"), ("US$ 10.00", "SGD")],
)
def test_ambiguous_or_absent_currency_is_not_found(text: str, code: str) -> None:
    assert find_currency(doc(text), code) is None


def test_symbol_table_covers_every_code_in_the_extraction_prompt() -> None:
    prompt_codes = {
        code for code in CURRENCY_SYMBOLS if f"-> {code}" in extraction_prompts.SYSTEM_PROMPT
    }
    assert prompt_codes == set(CURRENCY_SYMBOLS)


# -- Pages ------------------------------------------------------------------------------


def test_page_numbers_come_from_the_markers() -> None:
    document = doc("--- Page 1 ---\nHeader\n--- Page 2 ---\nTotal 99.00")
    found = find_number(document, Decimal("99"))
    assert found is not None and document.page_at(found.start) == 2
    assert doc("No markers at all").page_at(5) == 1
