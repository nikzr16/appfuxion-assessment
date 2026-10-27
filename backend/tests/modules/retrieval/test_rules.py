from decimal import Decimal

import pytest

from app.modules.retrieval import rules
from tests.modules.retrieval.seed import invoice_data


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ABC Supplies Sdn. Bhd.", "abc supplies"),
        ("abc supplies SDN BHD", "abc supplies"),
        ("ABC Supplies", "abc supplies"),
        ("ABC  Supplies (M) Sdn Bhd", "abc supplies m"),
        ("Tan & Sons Trading Co.", "tan and sons trading"),
        ("Acme Corp Ltd", "acme"),
        ("Berhad", "berhad"),
        ("  ", None),
        (None, None),
    ],
)
def test_vendor_names_normalise(raw: str | None, expected: str | None) -> None:
    assert rules.normalise_vendor_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("c 1234-5678.90", "C1234567890"),
        ("SST/W10-1808-32000123", "SSTW10180832000123"),
        ("", None),
    ],
)
def test_tax_ids_normalise(raw: str, expected: str | None) -> None:
    assert rules.normalise_tax_id(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("INV-1042", "INV1042"), ("inv 1042", "INV1042"), ("#INV1042", "INV1042"), ("0042", "0042")],
)
def test_invoice_numbers_normalise(raw: str, expected: str) -> None:
    assert rules.normalise_invoice_number(raw) == expected


def test_the_card_lists_the_key_fields_in_a_fixed_order() -> None:
    data = invoice_data(
        vendor_tax_id="C123",
        due_date="2026-02-15",
        line_items=[
            {"description": "Printer  toner", "quantity": None, "unit_price": None, "amount": None},
            {"description": "A4 paper", "quantity": None, "unit_price": None, "amount": None},
        ],
    )
    assert rules.build_card(data) == (
        "Document type: invoice\n"
        "Vendor: ABC Supplies Sdn Bhd (tax ID: C123)\n"
        "Invoice number: INV-1001\n"
        "Invoice date: 2026-01-15. Due date: 2026-02-15\n"
        "Total: 1000.00 MYR\n"
        "Items: Printer toner; A4 paper"
    )


def test_the_card_omits_missing_values_and_caps_the_items() -> None:
    items = [
        {"description": f"Item {n}", "quantity": None, "unit_price": None, "amount": None}
        for n in range(40)
    ]
    data = invoice_data(vendor=None, invoice_number=None, invoice_date=None, line_items=items)
    card = rules.build_card(data)
    assert "Vendor" not in card and "Invoice number" not in card and "date" not in card
    assert "Item 29" in card and "Item 30" not in card


def test_the_card_hash_changes_with_the_card_and_the_model() -> None:
    assert rules.card_hash("a", "m1") == rules.card_hash("a", "m1")
    assert rules.card_hash("a", "m1") != rules.card_hash("b", "m1")
    assert rules.card_hash("a", "m1") != rules.card_hash("a", "m2")


def _stats(*totals: str) -> object:
    return rules.history_stats(
        [Decimal(t) for t in totals], count=len(totals), skipped=[], base_currency="MYR"
    )


def test_history_stats_use_inclusive_quartiles_and_box_plot_fences() -> None:
    stats = _stats("100", "200", "300", "400", "500")
    assert (stats.min, stats.q1, stats.median, stats.q3, stats.max) == (
        Decimal("100.00"),
        Decimal("200.00"),
        Decimal("300.00"),
        Decimal("400.00"),
        Decimal("500.00"),
    )
    assert stats.low_fence == Decimal("-100.00") and stats.high_fence == Decimal("700.00")
    assert stats.sum == Decimal("1500.00") and stats.mean == Decimal("300.00")


def test_history_stats_handle_one_and_no_totals() -> None:
    one = _stats("80")
    assert one.median == one.q1 == one.q3 == Decimal("80.00")
    none = rules.history_stats([], count=2, skipped=["XAU", "XAU"], base_currency="MYR")
    assert none.median is None and none.with_total == 0 and none.skipped_currencies == ["XAU"]


def test_an_outlier_needs_five_totals_the_fences_and_a_25_percent_gap() -> None:
    five = _stats("100", "105", "110", "115", "120")
    assert rules.is_outlier(Decimal("500"), five)
    assert rules.is_outlier(Decimal("10"), five)
    assert not rules.is_outlier(Decimal("118"), five)
    assert not rules.is_outlier(Decimal("500"), _stats("100", "105", "110", "115"))
    # Identical history: the fences are zero-width, but small changes are not flagged.
    same = _stats("100", "100", "100", "100", "100")
    assert not rules.is_outlier(Decimal("110"), same)
    assert rules.is_outlier(Decimal("130"), same)


def test_number_tokens_are_canonical() -> None:
    assert rules.number_tokens("RM 1,250.00 vs 1250 and 12.50% on 2026-09-02") == {
        "1250",
        "12.5",
        "2026",
        "9",
        "2",
    }


def test_unverified_numbers_ignore_small_integers_and_known_values() -> None:
    known = rules.number_tokens('{"sum": "3750.00", "count": 3}')
    assert rules.unverified_numbers("3 invoices, MYR 3,750.00 in total", known) == []
    assert rules.unverified_numbers("about 4,000 or 1250.5", known) == ["1250.5", "4000"]
