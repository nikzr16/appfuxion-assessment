"""Grounding and confidence DTOs (PRD 0008 D2, D4, D6).

Pure data: the reports are stored by their owners — grounding on ``extractions.grounding``
(``ExtractionGrounding``), confidence inside ``agent_runs.result`` (``ConfidenceReport``).
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from app.modules.text_extraction.schema import ExtractionMethod


class GroundingStatus(StrEnum):
    """Whether a value was found in the document text."""

    GROUNDED = "grounded"  # found as printed (after normalisation)
    WEAK = "weak"  # close match, ambiguous date form or OCR correction
    UNGROUNDED = "ungrounded"  # not found: possibly invented
    INFERRED = "inferred"  # currency derived from a printed symbol (RM -> MYR)
    SKIPPED = "skipped"  # not a printed value (document_type)


class ValueKind(StrEnum):
    NUMBER = "number"
    DATE = "date"
    IDENTIFIER = "identifier"
    TEXT = "text"
    CURRENCY = "currency"
    CLASSIFICATION = "classification"


class MatchKind(StrEnum):
    EXACT = "exact"
    NUMBER = "number"
    DATE = "date"
    IDENTIFIER = "identifier"
    FUZZY = "fuzzy"
    SYMBOL = "symbol"
    OCR = "ocr"


class FieldGrounding(BaseModel):
    """One checked value. ``start`` / ``end`` are offsets into ``raw_text`` as stored."""

    path: str
    value: str
    kind: ValueKind
    status: GroundingStatus
    match: MatchKind | None = None
    similarity: int | None = None
    page: int | None = None
    start: int | None = None
    end: int | None = None
    note: str | None = None


class GroundingReport(BaseModel):
    """Every non-null value of one ``InvoiceData``, in schema order."""

    method: ExtractionMethod
    checked: int
    grounded: int
    weak: int
    ungrounded: int
    inferred: int
    fields: list[FieldGrounding]

    def ungrounded_fields(self) -> list[FieldGrounding]:
        return [f for f in self.fields if f.status is GroundingStatus.UNGROUNDED]


class GroundingAttempt(BaseModel):
    """One extraction call of a grounded extraction (PRD D3)."""

    attempt: int
    reason: Literal["initial", "schema", "grounding"]
    valid: bool
    ungrounded: list[str]


class ExtractionGrounding(BaseModel):
    """What ``extractions.grounding`` holds: the kept attempt's report and the history."""

    report: GroundingReport
    kept_attempt: int
    grounding_retries: int
    attempts: list[GroundingAttempt]
    checked_at: datetime


class ConfidenceLabel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FieldConfidence(BaseModel):
    path: str
    score: float
    label: ConfidenceLabel
    grounding: GroundingStatus
    page: int | None = None
    start: int | None = None
    end: int | None = None
    reasons: list[str]


class ConfidenceComponents(BaseModel):
    fields: float
    completeness: float
    validation: float


class ConfidenceReport(BaseModel):
    """Per-field and overall confidence of one run's result (``AgentResult.confidence``)."""

    overall: float
    label: ConfidenceLabel
    needs_review: bool
    review_fields: list[str]
    components: ConfidenceComponents
    fields: dict[str, FieldConfidence]
