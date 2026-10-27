import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Row, Select, func, select
from sqlalchemy.orm import Session

from app.modules.observability.model import LlmCall


def insert(db: Session, **values: Any) -> LlmCall:
    """Add one ledger row and flush; the caller commits."""
    row = LlmCall(**values)
    db.add(row)
    db.flush()
    return row


def list_for_run(db: Session, run_id: uuid.UUID) -> Sequence[LlmCall]:
    """The run's calls in the order they started."""
    return (
        db.execute(
            select(LlmCall).where(LlmCall.run_id == run_id).order_by(LlmCall.started_at, LlmCall.id)
        )
        .scalars()
        .all()
    )


def _usage_columns() -> tuple[Any, ...]:
    return (
        func.count().label("calls"),
        func.count().filter(LlmCall.status == "error").label("failed"),
        func.coalesce(func.sum(LlmCall.prompt_tokens), 0).label("prompt_tokens"),
        func.coalesce(func.sum(LlmCall.completion_tokens), 0).label("completion_tokens"),
        func.sum(LlmCall.cost_usd).label("cost_usd"),
        func.count().filter(LlmCall.cost_usd.is_(None)).label("unpriced"),
        func.coalesce(func.avg(LlmCall.latency_ms), 0).label("avg_latency_ms"),
    )


def _since(query: Select[Any], since: datetime | None) -> Select[Any]:
    return query if since is None else query.where(LlmCall.started_at >= since)


def totals(db: Session, *, since: datetime | None = None) -> Row[Any]:
    """One row: calls, failed, prompt_tokens, completion_tokens, cost_usd, unpriced,
    avg_latency_ms."""
    return db.execute(_since(select(*_usage_columns()), since)).one()


def group_totals(
    db: Session, *, by: Literal["model", "purpose", "agent"], since: datetime | None = None
) -> Sequence[Row[Any]]:
    """``totals`` per model, purpose or agent (column ``key``), most tokens first."""
    columns = {
        "model": LlmCall.model,
        "purpose": LlmCall.purpose,
        # Calls made outside any agent have no label, as in the trace (feature 0011).
        "agent": func.coalesce(LlmCall.agent, "unknown"),
    }
    column = columns[by]
    tokens = func.sum(LlmCall.prompt_tokens + LlmCall.completion_tokens)
    query = (
        select(column.label("key"), *_usage_columns())
        .group_by(column)
        .order_by(tokens.desc(), column)
    )
    return db.execute(_since(query, since)).all()


def per_run_totals(db: Session, run_ids: Sequence[uuid.UUID]) -> Sequence[Row[Any]]:
    """Tokens and known cost per run, for the runs that have ledger rows."""
    if not run_ids:
        return []
    query = (
        select(
            LlmCall.run_id,
            func.sum(LlmCall.prompt_tokens + LlmCall.completion_tokens).label("tokens"),
            func.coalesce(func.sum(LlmCall.cost_usd), Decimal(0)).label("cost_usd"),
            func.count().filter(LlmCall.cost_usd.is_(None)).label("unpriced"),
        )
        .where(LlmCall.run_id.in_(run_ids))
        .group_by(LlmCall.run_id)
    )
    return db.execute(query).all()


def earliest_started_at(db: Session) -> datetime | None:
    return db.execute(select(func.min(LlmCall.started_at))).scalar_one()


def count_retries(db: Session, *, since: datetime | None = None) -> int:
    """Ledger rows that were a transient-error retry (feature 0008)."""
    query = select(func.count()).select_from(LlmCall).where(LlmCall.attempt > 1)
    return int(db.execute(_since(query, since)).scalar_one())


def count_calls(
    db: Session, *, purpose: str, since: datetime | None = None, ok_only: bool = False
) -> int:
    """Ledger rows with this purpose (feature 0009 metrics)."""
    query = select(func.count()).select_from(LlmCall).where(LlmCall.purpose == purpose)
    if ok_only:
        query = query.where(LlmCall.status == "ok")
    return int(db.execute(_since(query, since)).scalar_one())


def avg_cost_per_query_run(db: Session, *, since: datetime | None = None) -> Decimal | None:
    """Average summed cost of the Query Agent's turns (feature 0010 metrics)."""
    per_run = (
        select(func.sum(LlmCall.cost_usd).label("cost"))
        .where(LlmCall.query_run_id.is_not(None))
        .group_by(LlmCall.query_run_id)
    )
    per_run = _since(per_run, since).subquery()
    value = db.execute(select(func.avg(per_run.c.cost))).scalar_one()
    return Decimal(value) if value is not None else None
