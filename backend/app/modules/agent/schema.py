import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    # The agent that made the call: ``document`` (single mode), ``extraction`` / ``validation``
    # / ``reporting`` (multi mode, feature 0011); ``None`` on runs saved before 0011.
    agent: str | None = None
    tool: str
    arguments: dict[str, Any]
    status: StepStatus
    result: dict[str, Any] | None = None
    error: StepError | None = None
    duration_ms: int
    started_at: datetime


class AgentPart(BaseModel):
    """One agent of a multi-agent run (PRD 0011 D3); only agents that started have one."""

    agent: str
    status: RunStatus
    prompt_version: str
    turns: int
    steps: int
    # Agent-loop turns plus, for Reporting, the summary call (the 0005 run-level meaning).
    prompt_tokens: int
    completion_tokens: int
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None


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
    # Per-agent breakdown in multi mode; ``[]`` in single mode (PRD 0011 D3).
    agents: list[AgentPart] = []
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


# -- Query Agent (feature 0010) -------------------------------------------------------------

QUESTION_MIN_CHARS = 3
QUESTION_MAX_CHARS = 500


class QueryRequest(BaseModel):
    question: str = Field(min_length=QUESTION_MIN_CHARS, max_length=QUESTION_MAX_CHARS)
    conversation_id: uuid.UUID | None = None
    # The document the user is looking at, so "this invoice" can be resolved.
    document_id: uuid.UUID | None = None

    @field_validator("question", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class Citation(BaseModel):
    document_id: uuid.UUID
    filename: str
    vendor: str | None
    invoice_number: str | None
    invoice_date: date | None
    total_amount: Decimal | None
    currency: str | None
    needs_review: bool | None


class QueryUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    embedding_tokens: int


class QueryTurn(BaseModel):
    turn_id: uuid.UUID
    turn: int
    question: str
    document_id: uuid.UUID | None
    status: RunStatus
    answer: str | None
    answerable: bool | None
    numbers_verified: bool | None
    citations: list[Citation]
    steps: list[ToolStep]
    error_code: str | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None


class QueryResponse(QueryTurn):
    conversation_id: uuid.UUID
    usage: QueryUsage


class ConversationRead(BaseModel):
    conversation_id: uuid.UUID
    created_at: datetime
    turns: list[QueryTurn]


class QuerySuggestions(BaseModel):
    indexed_documents: int
    questions: list[str]


class QueryStats(BaseModel):
    conversations: int
    questions: int
    questions_failed: int
    questions_unanswerable: int
    questions_unverified: int
    avg_question_ms: int | None


class IssueCounts(BaseModel):
    """Completed runs whose validation contains each vendor-history code (metrics)."""

    duplicate_flags: int
    outlier_flags: int
    new_vendor_flags: int
