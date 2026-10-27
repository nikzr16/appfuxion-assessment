"""check_grounding and score_confidence (PRD 0008 D2, D4)."""

from datetime import date
from typing import Any

import pytest

from app.modules.guardrails import service
from app.modules.guardrails.schema import ConfidenceLabel, GroundingStatus
from app.modules.structured_extraction.schema import InvoiceData
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.validation import service as validation_service

TODAY = date(2025, 4, 1)

INVOICE_TEXT = """--- Page 1 ---
ABC SUPPLY SDN. BHD.
No. 12, Jalan Ampang, 50450 Kuala Lumpur
SST No: W10-1808-32000123
Invoice No: INV-2025-0042
Tarikh: 4 Mac 2025          Due: 3 April 2025
Bill to: Kedai Runcit Ahmad
Qty  Description          Unit price   Amount
2    Printer paper A4     12.50        25.00
1    Toner cartridge      75.00        75.00
--- Page 2 ---
Subtotal                 RM 100.00
SST 6%                       6.00
Total                    RM 106.00
Terms: Net 30
"""


def line(description: str, quantity: str, unit_price: str, amount: str) -> dict[str, str]:
    return {
        "description": description,
        "quantity": quantity,
        "unit_price": unit_price,
        "amount": amount,
    }


def make_invoice(**overrides: Any) -> InvoiceData:
    data: dict[str, Any] = {
        "document_type": "invoice",
        "vendor": "ABC Supply Sdn Bhd",
        "vendor_address": "No. 12, Jalan Ampang, 50450 Kuala Lumpur",
        "vendor_tax_id": "W10-1808-32000123",
        "customer_name": "Kedai Runcit Ahmad",
        "customer_address": None,
        "invoice_number": "INV-2025-0042",
        "invoice_date": "2025-03-04",
        "due_date": "2025-04-03",
        "payment_terms": "Net 30",
        "currency": "MYR",
        "subtotal": "100.00",
        "tax": "6.00",
        "total_amount": "106.00",
        "line_items": [
            {
                "description": "Printer paper A4",
                "quantity": "2",
                "unit_price": "12.50",
                "amount": "25.00",
            },
            {
                "description": "Toner cartridge",
                "quantity": "1",
                "unit_price": "75.00",
                "amount": "75.00",
            },
        ],
    }
    data.update(overrides)
    return InvoiceData.model_validate(data)


def ground(data: InvoiceData, method: ExtractionMethod = ExtractionMethod.PDF_PARSER):
    return service.check_grounding(data, INVOICE_TEXT, method)


def score(data: InvoiceData, method: ExtractionMethod = ExtractionMethod.PDF_PARSER):
    report = ground(data, method)
    validation = validation_service.validate_invoice(data, today=TODAY)
    return service.score_confidence(data, report, validation)


# -- Grounding ----------------------------------------------------------------------------


def test_a_faithful_extraction_is_fully_grounded() -> None:
    report = ground(make_invoice())
    statuses = {f.path: f.status for f in report.fields}

    assert statuses["document_type"] is GroundingStatus.SKIPPED
    assert statuses["currency"] is GroundingStatus.INFERRED  # "RM" printed, not "MYR"
    assert report.ungrounded == 0 and report.weak == 0
    assert report.checked == len(report.fields) - 1
    assert report.grounded == report.checked - 1
    assert report.method is ExtractionMethod.PDF_PARSER


def test_spans_point_into_raw_text_and_pages_follow_markers() -> None:
    fields = {f.path: f for f in ground(make_invoice()).fields}

    total = fields["total_amount"]
    assert INVOICE_TEXT[total.start : total.end] == "106.00"  # type: ignore[misc]
    assert total.page == 2
    vendor = fields["vendor"]
    assert INVOICE_TEXT[vendor.start : vendor.end] == "ABC SUPPLY SDN. BHD"  # type: ignore[misc]
    assert vendor.page == 1
    assert fields["line_items[1].description"].page == 1


def test_null_values_are_not_checked() -> None:
    report = ground(make_invoice(customer_address=None, due_date=None))
    paths = {f.path for f in report.fields}
    assert "customer_address" not in paths and "due_date" not in paths


def test_invented_values_are_ungrounded() -> None:
    report = ground(
        make_invoice(vendor="XYZ Trading Company", total_amount="160.00", invoice_number="INV-9")
    )
    ungrounded = {f.path for f in report.ungrounded_fields()}
    assert ungrounded == {"vendor", "total_amount", "invoice_number"}
    assert all(f.note == "Not found in the document text" for f in report.ungrounded_fields())
    assert {f.value for f in report.ungrounded_fields()} == {
        "XYZ Trading Company",
        "160.00",
        "INV-9",
    }


def test_unknown_document_only_has_a_skipped_type() -> None:
    data = InvoiceData.model_validate(
        {
            **dict.fromkeys(InvoiceData.model_fields),
            "document_type": "unknown",
            "line_items": [],
        }
    )
    report = service.check_grounding(data, "A recipe for nasi lemak", ExtractionMethod.PDF_PARSER)
    assert report.checked == 0 and len(report.fields) == 1


# -- Confidence ---------------------------------------------------------------------------


def test_a_clean_pdf_invoice_is_high_confidence() -> None:
    report = score(make_invoice())
    assert report is not None
    assert report.label is ConfidenceLabel.HIGH and report.overall >= 0.95
    assert report.needs_review is False and report.review_fields == []
    assert report.fields["vendor"].score == 1.0
    assert report.fields["currency"].score == 0.9  # inferred
    assert report.fields["vendor"].reasons == ["Found in the document text on page 1"]
    assert report.components.completeness == 1.0
    assert report.components.validation == 1.0


def test_an_ungrounded_key_field_needs_review() -> None:
    report = score(make_invoice(total_amount="160.00"))
    assert report is not None
    total = report.fields["total_amount"]
    assert total.grounding is GroundingStatus.UNGROUNDED
    assert total.label is ConfidenceLabel.LOW
    assert total.reasons[0] == "Not found in the document text"
    assert report.needs_review is True
    assert report.review_fields[0] == "total_amount"


def test_an_ungrounded_minor_field_is_listed_but_does_not_force_review() -> None:
    report = score(make_invoice(payment_terms="Net 60"))
    assert report is not None
    assert report.review_fields == ["payment_terms"]
    assert report.needs_review is False


def test_validation_issues_lower_the_fields_they_apply_to() -> None:
    # due before invoice date -> error on due_date; line amounts still sum to subtotal
    report = score(make_invoice(due_date="2025-03-01"))
    assert report is not None
    due = report.fields["due_date"]
    assert due.score == pytest.approx(0.2 * 0.5)  # ungrounded (1 March is not printed) x error
    assert any(reason.startswith("Validation error:") for reason in due.reasons)
    assert report.components.validation == 0.3


def test_vision_text_scales_every_field() -> None:
    report = score(make_invoice(), ExtractionMethod.VISION)
    assert report is not None
    assert report.fields["vendor"].score == 0.9
    assert "Read from a scanned image (OCR)" in report.fields["vendor"].reasons


def test_line_items_count_as_one_weighted_group() -> None:
    clean = score(make_invoice())
    lines = make_invoice().model_dump(mode="json")["line_items"]
    lines[0]["description"] = "Laser printer, colour"
    bad = score(make_invoice(line_items=lines))
    assert clean is not None and bad is not None
    assert bad.fields["line_items[0].description"].grounding is GroundingStatus.UNGROUNDED
    # one of 8 line values at 0.2 drags the group mean to 0.9; weight 2 of 18
    assert bad.components.fields == pytest.approx(clean.components.fields - 2 * 0.1 / 18, abs=0.002)


def test_missing_expected_fields_lower_completeness() -> None:
    report = score(make_invoice(invoice_number=None, currency=None))
    assert report is not None
    assert report.components.completeness == pytest.approx(5 / 7, abs=0.001)


def test_overall_formula_and_labels() -> None:
    report = score(make_invoice(total_amount="160.00", vendor="XYZ Trading Company"))
    assert report is not None
    c = report.components
    assert report.overall == pytest.approx(
        round(0.6 * c.fields + 0.25 * c.completeness + 0.15 * c.validation, 3)
    )
    assert service.label_for(0.85) is ConfidenceLabel.HIGH
    assert service.label_for(0.849) is ConfidenceLabel.MEDIUM
    assert service.label_for(0.6) is ConfidenceLabel.MEDIUM
    assert service.label_for(0.599) is ConfidenceLabel.LOW


def test_unknown_documents_have_no_confidence() -> None:
    data = InvoiceData.model_validate(
        {**dict.fromkeys(InvoiceData.model_fields), "document_type": "unknown", "line_items": []}
    )
    report = service.check_grounding(data, "text", ExtractionMethod.PDF_PARSER)
    validation = validation_service.validate_invoice(data, today=TODAY)
    assert service.score_confidence(data, report, validation) is None


def test_scores_are_deterministic() -> None:
    assert score(make_invoice()) == score(make_invoice())
