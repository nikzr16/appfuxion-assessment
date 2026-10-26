"""Token ledger, document traces and product metrics (PRD 0007).

``record_llm_call`` is the recorder ``app.main`` registers with ``app.core.llm``: every LLM
call becomes one ``llm_calls`` row, written in its own session so that recording can never
fail or roll back a document run. The read side builds a run's trace from the agent run's
tool steps plus its ledger rows, and the metrics summary from aggregates.
"""

import logging
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Row
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.errors import NotFoundError
from app.core.llm import LLMCallRecord
from app.modules.agent import service as agent_service
from app.modules.agent.schema import AgentRunRead, RunTrigger
from app.modules.documents import service as documents_service
from app.modules.observability import crud, pricing
from app.modules.observability.model import LlmCall
from app.modules.observability.schema import (
    DocumentMetrics,
    DocumentTrace,
    GroupTotals,
    LLMMetrics,
    LLMSpan,
    MetricsSummary,
    Span,
    ToolSpan,
    TraceRun,
    UsageTotals,
)

logger = logging.getLogger(__name__)


# -- Recording (PRD D1, D3-D5) -------------------------------------------------------


def record_llm_call(record: LLMCallRecord) -> None:
    """Write one ledger row in its own short transaction. Never raises."""
    labels = record.labels
    db = SessionLocal()
    try:
        crud.insert(
            db,
            document_id=_as_uuid(labels.document_id),
            run_id=_as_uuid(labels.run_id),
            step_index=labels.step_index,
            agent=labels.agent,
            purpose=labels.purpose or "unknown",
            kind=record.kind,
            model=record.model,
            prompt_version=labels.prompt_version,
            prompt_tokens=record.usage.prompt_tokens,
            completion_tokens=record.usage.completion_tokens,
            cost_usd=pricing.estimate_cost(record.model, record.usage),
            latency_ms=record.latency_ms,
            status=record.status,
            error_code=record.error_code,
            started_at=record.started_at,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("llm.call not recorded", exc_info=True)
    finally:
        db.close()


def _as_uuid(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# -- Trace (PRD D6, D8) ----------------------------------------------------------------


def get_trace(
    db: Session, document_id: uuid.UUID, run_id: uuid.UUID | None = None
) -> DocumentTrace:
    """The latest run's trace, or the run ``run_id`` of this document."""
    document = documents_service.get_document(db, document_id)  # 404 when unknown
    runs = agent_service.list_runs(db, document_id)  # newest first
    run = _pick_run(runs, run_id)
    rows = list(crud.list_for_run(db, run.id)) if run is not None else []
    return DocumentTrace(
        document_id=document.document_id,
        uploaded_at=document.created_at,
        run=_trace_run(run, document.created_at) if run is not None else None,
        llm_calls_recorded=bool(rows),
        totals=_usage(rows),
        by_purpose=_groups(rows, lambda row: row.purpose),
        by_agent=_groups(rows, lambda row: row.agent or "unknown"),
        spans=_spans(run, rows) if run is not None else [],
        prices_as_of=pricing.PRICES_AS_OF,
    )


def _pick_run(runs: Sequence[AgentRunRead], run_id: uuid.UUID | None) -> AgentRunRead | None:
    if run_id is None:
        return runs[0] if runs else None
    for run in runs:
        if run.id == run_id:
            return run
    raise NotFoundError(f"Run not found for this document: {run_id}", code="run_not_found")


def _trace_run(run: AgentRunRead, uploaded_at: datetime) -> TraceRun:
    queue_ms = None
    if run.trigger == RunTrigger.UPLOAD:
        queue_ms = max(0, _ms(run.started_at - uploaded_at))
    processing_ms = None
    if run.finished_at is not None:
        processing_ms = max(0, _ms(run.finished_at - run.started_at))
    return TraceRun(
        run_id=run.id,
        mode=run.mode,
        trigger=run.trigger,
        status=run.status,
        error_code=run.error_code,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
        queue_ms=queue_ms,
        processing_ms=processing_ms,
        run_prompt_tokens=run.prompt_tokens,
        run_completion_tokens=run.completion_tokens,
    )


def _spans(run: AgentRunRead, rows: Iterable[LlmCall]) -> list[Span]:
    """Tool steps and LLM calls in start order; a step sorts before the calls made in it."""

    def offset(started_at: datetime) -> int:
        return max(0, _ms(started_at - run.started_at))

    keyed: list[tuple[datetime, int, Span]] = [
        (
            step.started_at,
            0,
            ToolSpan(
                step_index=step.index,
                turn=step.turn,
                tool=step.tool,
                status=step.status,
                error_code=step.error.code if step.error else None,
                started_at=step.started_at,
                offset_ms=offset(step.started_at),
                duration_ms=step.duration_ms,
            ),
        )
        for step in run.steps
    ]
    keyed += [
        (
            row.started_at,
            1,
            LLMSpan(
                id=row.id,
                step_index=row.step_index,
                purpose=row.purpose,
                agent=row.agent,
                model=row.model,
                prompt_version=row.prompt_version,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.prompt_tokens + row.completion_tokens,
                cost_usd=row.cost_usd,
                status="error" if row.status == "error" else "ok",
                error_code=row.error_code,
                started_at=row.started_at,
                offset_ms=offset(row.started_at),
                duration_ms=row.latency_ms,
            ),
        )
        for row in rows
    ]
    keyed.sort(key=lambda item: (item[0], item[1]))
    return [span for _, _, span in keyed]


def _usage(rows: Sequence[LlmCall]) -> UsageTotals:
    prompt = sum(row.prompt_tokens for row in rows)
    completion = sum(row.completion_tokens for row in rows)
    costs = [row.cost_usd for row in rows if row.cost_usd is not None]
    return UsageTotals(
        llm_calls=len(rows),
        failed_calls=sum(1 for row in rows if row.status == "error"),
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cost_usd=_cost_total(costs, calls=len(rows)),
        cost_complete=len(costs) == len(rows),
    )


def _groups(rows: Sequence[LlmCall], key: Callable[[LlmCall], str]) -> list[GroupTotals]:
    """Usage per key, in the order each key first appears (i.e. timeline order)."""
    grouped: dict[str, list[LlmCall]] = {}
    for row in rows:
        grouped.setdefault(key(row), []).append(row)
    return [
        GroupTotals(
            key=name,
            avg_latency_ms=round(sum(r.latency_ms for r in members) / len(members)),
            **_usage(members).model_dump(),
        )
        for name, members in grouped.items()
    ]


# -- Metrics (PRD D7) ------------------------------------------------------------------


def get_metrics(
    db: Session, *, days: int | None = None, now: datetime | None = None
) -> MetricsSummary:
    """Live aggregates over all time, or the last ``days`` days."""
    generated_at = now or datetime.now(UTC)
    since = generated_at - timedelta(days=days) if days is not None else None

    counts = documents_service.count_by_status(db, since=since)
    finished = counts.completed + counts.failed
    documents = DocumentMetrics(
        total=counts.processing + counts.completed + counts.failed,
        processing=counts.processing,
        completed=counts.completed,
        failed=counts.failed,
        success_rate=counts.completed / finished if finished else None,
    )

    totals = _usage_row(crud.totals(db, since=since))
    per_run = crud.per_run_totals(db, agent_service.completed_run_ids(db, since=since))
    llm = LLMMetrics(
        **totals.model_dump(),
        error_rate=totals.failed_calls / totals.llm_calls if totals.llm_calls else None,
        documents_with_usage=len(per_run),
        avg_tokens_per_document=(
            round(sum(int(r.tokens) for r in per_run) / len(per_run)) if per_run else None
        ),
        avg_cost_per_document=(
            _round_cost(sum((Decimal(r.cost_usd) for r in per_run), Decimal(0)) / len(per_run))
            if per_run
            else None
        ),
    )
    return MetricsSummary(
        window_days=days,
        since=since,
        generated_at=generated_at,
        ledger_since=crud.earliest_started_at(db),
        documents=documents,
        runs=agent_service.run_stats(db, since=since),
        llm=llm,
        by_model=[_group_row(r) for r in crud.group_totals(db, by="model", since=since)],
        by_purpose=[_group_row(r) for r in crud.group_totals(db, by="purpose", since=since)],
        prices_as_of=pricing.PRICES_AS_OF,
    )


def _usage_row(row: Row[Any]) -> UsageTotals:
    prompt, completion = int(row.prompt_tokens), int(row.completion_tokens)
    calls, unpriced = int(row.calls), int(row.unpriced)
    cost = Decimal(row.cost_usd) if row.cost_usd is not None else None
    return UsageTotals(
        llm_calls=calls,
        failed_calls=int(row.failed),
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cost_usd=cost if cost is not None else (Decimal(0) if calls == 0 else None),
        cost_complete=unpriced == 0,
    )


def _group_row(row: Row[Any]) -> GroupTotals:
    return GroupTotals(
        key=row.key,
        avg_latency_ms=round(float(row.avg_latency_ms)),
        **_usage_row(row).model_dump(),
    )


# -- Helpers ---------------------------------------------------------------------------


def _ms(delta: timedelta) -> int:
    return round(delta.total_seconds() * 1000)


def _cost_total(costs: Sequence[Decimal], *, calls: int) -> Decimal | None:
    """Sum of known costs; ``0`` with no calls; ``None`` when calls exist but none is priced."""
    if not costs:
        return Decimal(0) if calls == 0 else None
    return sum(costs, Decimal(0))


def _round_cost(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))
