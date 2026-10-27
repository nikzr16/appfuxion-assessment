"""Guardrails: grounding check and confidence scoring (PRD 0008 D1, D2, D4).

Pure, deterministic code — no LLM, no database. ``check_grounding`` looks every non-null
value of an ``InvoiceData`` up in the document's own text; ``score_confidence`` combines that
with the 0004 validation report and schema completeness into per-field and overall scores.
The callers (``structured_extraction`` re-extraction, the agent's tools) store the results.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.guardrails import matching
from app.modules.guardrails.matching import DocumentText, Match
from app.modules.guardrails.schema import (
    ConfidenceComponents,
    ConfidenceLabel,
    ConfidenceReport,
    FieldConfidence,
    FieldGrounding,
    GroundingReport,
    GroundingStatus,
    ValueKind,
)
from app.modules.structured_extraction.schema import DocumentType, InvoiceData
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.validation import service as validation_service
from app.modules.validation.schema import Severity, ValidationReport, ValidationStatus

# -- What each field is (D2) -------------------------------------------------------------

_HEADER_KINDS: dict[str, ValueKind] = {
    "vendor": ValueKind.TEXT,
    "vendor_address": ValueKind.TEXT,
    "vendor_tax_id": ValueKind.IDENTIFIER,
    "customer_name": ValueKind.TEXT,
    "customer_address": ValueKind.TEXT,
    "invoice_number": ValueKind.IDENTIFIER,
    "invoice_date": ValueKind.DATE,
    "due_date": ValueKind.DATE,
    "payment_terms": ValueKind.TEXT,
    "currency": ValueKind.CURRENCY,
    "subtotal": ValueKind.NUMBER,
    "tax": ValueKind.NUMBER,
    "total_amount": ValueKind.NUMBER,
}
_LINE_KINDS: dict[str, ValueKind] = {
    "description": ValueKind.TEXT,
    "quantity": ValueKind.NUMBER,
    "unit_price": ValueKind.NUMBER,
    "amount": ValueKind.NUMBER,
}

# -- Confidence constants (D4) -----------------------------------------------------------

GROUNDING_SCORE: dict[GroundingStatus, float] = {
    GroundingStatus.GROUNDED: 1.0,
    GroundingStatus.INFERRED: 0.9,
    GroundingStatus.WEAK: 0.7,
    GroundingStatus.UNGROUNDED: 0.2,
}
ERROR_FACTOR = 0.5
WARNING_FACTOR = 0.8
VISION_FACTOR = 0.9

KEY_FIELDS = ("total_amount", "vendor", "invoice_number", "invoice_date", "currency")
FIELD_WEIGHTS: dict[str, float] = {
    "total_amount": 3,
    "vendor": 2,
    "invoice_number": 2,
    "invoice_date": 2,
    "currency": 2,
}
LINE_ITEMS_WEIGHT = 2.0
OTHER_WEIGHT = 1.0

FIELDS_SHARE = 0.60
COMPLETENESS_SHARE = 0.25
VALIDATION_SHARE = 0.15
VALIDATION_SCORE: dict[ValidationStatus, float] = {
    ValidationStatus.PASS: 1.0,
    ValidationStatus.WARN: 0.7,
    ValidationStatus.FAIL: 0.3,
}

HIGH_THRESHOLD = 0.85
MEDIUM_THRESHOLD = 0.60


# -- Grounding ---------------------------------------------------------------------------


def _values(data: InvoiceData) -> Iterator[tuple[str, ValueKind, Any]]:
    """(path, kind, value) for every value of ``data``, in schema order; nulls skipped."""
    yield "document_type", ValueKind.CLASSIFICATION, data.document_type.value
    for name, kind in _HEADER_KINDS.items():
        value = getattr(data, name)
        if value is not None:
            yield name, kind, value
    for index, item in enumerate(data.line_items):
        for name, kind in _LINE_KINDS.items():
            value = getattr(item, name)
            if value is not None:
                yield f"line_items[{index}].{name}", kind, value


def _display(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _find(doc: DocumentText, kind: ValueKind, value: Any) -> Match | None:
    if kind is ValueKind.NUMBER:
        return matching.find_number(doc, value)
    if kind is ValueKind.DATE:
        return matching.find_date(doc, value)
    if kind is ValueKind.IDENTIFIER:
        return matching.find_identifier(doc, value)
    if kind is ValueKind.CURRENCY:
        return matching.find_currency(doc, value)
    return matching.find_text(doc, value)


def check_grounding(data: InvoiceData, raw_text: str, method: ExtractionMethod) -> GroundingReport:
    """Look every non-null value of ``data`` up in ``raw_text`` (the full text, D2)."""
    doc = DocumentText(raw_text, method)
    fields: list[FieldGrounding] = []
    for path, kind, value in _values(data):
        shown = _display(value)
        if kind is ValueKind.CLASSIFICATION:
            fields.append(
                FieldGrounding(path=path, value=shown, kind=kind, status=GroundingStatus.SKIPPED)
            )
            continue
        found = _find(doc, kind, value)
        if found is None:
            fields.append(
                FieldGrounding(
                    path=path,
                    value=shown,
                    kind=kind,
                    status=GroundingStatus.UNGROUNDED,
                    note="Not found in the document text",
                )
            )
            continue
        fields.append(
            FieldGrounding(
                path=path,
                value=shown,
                kind=kind,
                status=found.status,
                match=found.kind,
                similarity=found.similarity,
                page=doc.page_at(found.start),
                start=found.start,
                end=found.end,
                note=found.note,
            )
        )

    def count(status: GroundingStatus) -> int:
        return sum(1 for f in fields if f.status is status)

    return GroundingReport(
        method=method,
        checked=len(fields) - count(GroundingStatus.SKIPPED),
        grounded=count(GroundingStatus.GROUNDED),
        weak=count(GroundingStatus.WEAK),
        ungrounded=count(GroundingStatus.UNGROUNDED),
        inferred=count(GroundingStatus.INFERRED),
        fields=fields,
    )


# -- Confidence --------------------------------------------------------------------------


def label_for(score: float) -> ConfidenceLabel:
    if score >= HIGH_THRESHOLD:
        return ConfidenceLabel.HIGH
    if score >= MEDIUM_THRESHOLD:
        return ConfidenceLabel.MEDIUM
    return ConfidenceLabel.LOW


def _applies(issue_field: str, path: str) -> bool:
    return path == issue_field or path.startswith((f"{issue_field}[", f"{issue_field}."))


def _grounding_reason(field: FieldGrounding) -> str:
    where = f" on page {field.page}" if field.page is not None else ""
    if field.status is GroundingStatus.GROUNDED:
        return f"Found in the document text{where}"
    if field.status is GroundingStatus.INFERRED:
        return f"{field.note or 'Inferred from a printed symbol'}{where}"
    if field.status is GroundingStatus.WEAK:
        if field.similarity is not None:
            return f"Close match ({field.similarity}/100){where}"
        return f"{field.note or 'Weak match'}{where}"
    return "Not found in the document text"


def _score_field(
    field: FieldGrounding, validation: ValidationReport, vision: bool
) -> FieldConfidence:
    score = GROUNDING_SCORE[field.status]
    reasons = [_grounding_reason(field)]
    issues = [issue for issue in validation.issues if _applies(issue.field, field.path)]
    if any(issue.severity is Severity.ERROR for issue in issues):
        score *= ERROR_FACTOR
    elif any(issue.severity is Severity.WARNING for issue in issues):
        score *= WARNING_FACTOR
    reasons.extend(
        f"Validation {issue.severity.value}: {issue.message}"
        for issue in issues
        if issue.severity is not Severity.INFO
    )
    if vision:
        score *= VISION_FACTOR
        reasons.append("Read from a scanned image (OCR)")
    score = round(score, 3)
    return FieldConfidence(
        path=field.path,
        score=score,
        label=label_for(score),
        grounding=field.status,
        page=field.page,
        start=field.start,
        end=field.end,
        reasons=reasons,
    )


def _weighted_mean(fields: dict[str, FieldConfidence]) -> float:
    total = 0.0
    weights = 0.0
    line_scores = [f.score for path, f in fields.items() if path.startswith("line_items[")]
    for path, field in fields.items():
        if path.startswith("line_items["):
            continue
        weight = FIELD_WEIGHTS.get(path, OTHER_WEIGHT)
        total += weight * field.score
        weights += weight
    if line_scores:
        total += LINE_ITEMS_WEIGHT * sum(line_scores) / len(line_scores)
        weights += LINE_ITEMS_WEIGHT
    return total / weights if weights else 0.0


def _completeness(data: InvoiceData) -> float:
    expected = validation_service.expected_fields(data.document_type)
    if not expected:
        return 1.0
    present = sum(1 for name in expected if getattr(data, name) not in (None, []))
    return present / len(expected)


def _review_order(path: str) -> tuple[int, int]:
    key = KEY_FIELDS.index(path) if path in KEY_FIELDS else len(KEY_FIELDS)
    return key, 0


def score_confidence(
    data: InvoiceData, grounding: GroundingReport, validation: ValidationReport
) -> ConfidenceReport | None:
    """Per-field and overall confidence (D4); ``None`` for ``unknown`` documents."""
    if data.document_type is DocumentType.UNKNOWN:
        return None
    vision = grounding.method is ExtractionMethod.VISION
    fields = {
        f.path: _score_field(f, validation, vision)
        for f in grounding.fields
        if f.status is not GroundingStatus.SKIPPED
    }
    components = ConfidenceComponents(
        fields=round(_weighted_mean(fields), 3),
        completeness=round(_completeness(data), 3),
        validation=VALIDATION_SCORE[validation.status],
    )
    overall = round(
        FIELDS_SHARE * components.fields
        + COMPLETENESS_SHARE * components.completeness
        + VALIDATION_SHARE * components.validation,
        3,
    )
    label = label_for(overall)
    flagged = [
        path
        for path, field in fields.items()
        if field.grounding is GroundingStatus.UNGROUNDED or field.label is ConfidenceLabel.LOW
    ]
    review_fields = sorted(flagged, key=_review_order)  # stable: schema order within groups
    needs_review = label is ConfidenceLabel.LOW or any(
        fields[path].grounding is GroundingStatus.UNGROUNDED
        for path in KEY_FIELDS
        if path in fields
    )
    return ConfidenceReport(
        overall=overall,
        label=label,
        needs_review=needs_review,
        review_fields=review_fields,
        components=components,
        fields=fields,
    )
