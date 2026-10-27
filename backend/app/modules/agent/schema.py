import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.guardrails.schema import ConfidenceLabel, ConfidenceReport
from app.modules.structured_extraction.schema import InvoiceData
from app.modules.validation.schema import ConversionResult, ValidationReport


class AgentMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


class RunTrigger(StrEnum):
    UPLOAD = "upload"
    REPROCESS = "reprocess"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class StepError(BaseModel):
    code: str
    message: str


class ToolStep(BaseModel):
    """One recorded tool call. ``result`` is exactly what the model was sent back."""

    index: int
    turn: int
    tool: str
    arguments: dict[str, Any]
    status: StepStatus
    result: dict[str, Any] | None = None
    error: StepError | None = None
    duration_ms: int
    started_at: datetime


class AgentResult(BaseModel):
    """The final result (brief Part 4) plus the optional conversion; ``GET /result``."""

    document_id: uuid.UUID
    structured_data: InvoiceData
    validation: ValidationReport
    conversion: ConversionResult | None
    summary: str
    # Per-field and overall confidence (feature 0008); null for unknown documents and for
    # results saved before 0008.
    confidence: ConfidenceReport | None = None


class AgentRunRead(BaseModel):
    """One ``agent_runs`` row without ``result`` (that has its own endpoint)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    mode: AgentMode
    trigger: RunTrigger
    status: RunStatus
    steps: list[ToolStep]
    summary: str | None
    error_code: str | None
    error: str | None
    model: str | None
    agent_prompt_version: str
    summary_prompt_version: str
    prompt_tokens: int
    completion_tokens: int
    started_at: datetime
    finished_at: datetime | None


class ConfidenceStats(BaseModel):
    """Confidence of completed runs in a window (feature 0008 metrics)."""

    runs_scored: int
    avg_confidence: float | None
    needs_review: int
    by_label: dict[ConfidenceLabel, int]


class RunStats(BaseModel):
    """Agent runs in a window and how long the completed ones took (feature 0007 metrics)."""

    total: int
    running: int
    completed: int
    failed: int
    avg_ms: int | None
    p50_ms: int | None
    p95_ms: int | None
