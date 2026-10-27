import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.modules.agent.schema import AgentMode, RunStats, RunStatus, RunTrigger, StepStatus

CallStatus = Literal["ok", "error"]


class UsageTotals(BaseModel):
    """LLM usage of a set of ledger rows. ``cost_usd`` is ``None`` when none was priced."""

    llm_calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Decimal | None = None
    # False when some rows used a model missing from the price table (cost is a lower bound).
    cost_complete: bool = True


class GroupTotals(UsageTotals):
    """``UsageTotals`` of one purpose, agent or model."""

    key: str
    avg_latency_ms: int = 0


# -- Trace (GET /documents/{id}/trace, PRD 0007 D6) ------------------------------------


class TraceRun(BaseModel):
    run_id: uuid.UUID
    mode: AgentMode
    trigger: RunTrigger
    status: RunStatus
    error_code: str | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    # Upload runs only: from the upload to the start of the run.
    queue_ms: int | None
    # ``None`` while the run is still going.
    processing_ms: int | None
    # The 0005 run-level totals (agent loop + summary), shown for runs before the ledger.
    run_prompt_tokens: int
    run_completion_tokens: int


class ToolSpan(BaseModel):
    kind: Literal["tool"] = "tool"
    step_index: int
    turn: int
    tool: str
    status: StepStatus
    error_code: str | None
    started_at: datetime
    offset_ms: int
    duration_ms: int


class LLMSpan(BaseModel):
    kind: Literal["llm"] = "llm"
    id: uuid.UUID
    # The tool step this call was made in; ``None`` for agent-loop turns.
    step_index: int | None
    purpose: str
    agent: str | None
    model: str
    prompt_version: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: Decimal | None
    status: CallStatus
    error_code: str | None
    started_at: datetime
    offset_ms: int
    duration_ms: int
    # 1 = first try; 2+ = a transient-error retry of the same call (feature 0008).
    attempt: int = 1


Span = Annotated[ToolSpan | LLMSpan, Field(discriminator="kind")]


class DocumentTrace(BaseModel):
    document_id: uuid.UUID
    uploaded_at: datetime
    run: TraceRun | None
    # False when the run has no ledger rows (it ran before feature 0007).
    llm_calls_recorded: bool
    totals: UsageTotals
    by_purpose: list[GroupTotals]
    by_agent: list[GroupTotals]
    spans: list[Span]
    prices_as_of: date


# -- Metrics (GET /metrics/summary, PRD 0007 D7) ---------------------------------------


class DocumentMetrics(BaseModel):
    total: int
    processing: int
    completed: int
    failed: int
    # completed / (completed + failed); ``None`` when nothing has finished.
    success_rate: float | None


class LLMMetrics(UsageTotals):
    error_rate: float | None
    # Over completed runs that have ledger rows (runs before 0007 are left out).
    documents_with_usage: int
    avg_tokens_per_document: int | None
    avg_cost_per_document: Decimal | None


class GuardrailMetrics(BaseModel):
    """Extraction quality in the window (feature 0008 metrics, PRD D10)."""

    runs_scored: int
    avg_confidence: float | None
    by_label: dict[str, int]
    needs_review: int
    # needs_review / runs_scored; ``None`` when nothing is scored yet.
    needs_review_rate: float | None
    values_checked: int
    values_grounded: int
    # values_grounded / values_checked; ``None`` when nothing was checked.
    grounding_rate: float | None
    grounding_retry_extractions: int
    # Ledger rows that were a transient-error retry (attempt > 1).
    transient_retries: int


class VisionMetrics(BaseModel):
    """Tables, layout and vision use in the window (feature 0009 metrics, PRD D12)."""

    # Newest layout analysis per document made in the window.
    layouts_analysed: int
    documents_with_line_item_table: int
    tables_found: int
    # Line items of extractions in the window, by where they came from.
    line_items_from_table: int
    line_items_from_model: int
    # from_table / (from_table + from_model); ``None`` when there are no line items.
    line_items_table_share: float | None
    # Successful vision page calls (one per page) and multimodal extraction calls.
    pages_via_vision: int
    multimodal_calls: int


class MetricsSummary(BaseModel):
    window_days: int | None
    since: datetime | None
    generated_at: datetime
    # The earliest ledger row; token and cost figures cover only what came after it.
    ledger_since: datetime | None
    documents: DocumentMetrics
    runs: RunStats
    llm: LLMMetrics
    by_model: list[GroupTotals]
    by_purpose: list[GroupTotals]
    guardrails: GuardrailMetrics
    vision: VisionMetrics
    prices_as_of: date
