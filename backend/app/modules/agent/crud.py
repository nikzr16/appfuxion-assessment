import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, case, func, select, update
from sqlalchemy.orm import Session

from app.modules.agent.model import AgentRun, QueryConversation, QueryRun
from app.modules.agent.schema import RunStatus


def create_run(
    db: Session,
    *,
    document_id: uuid.UUID,
    mode: str,
    trigger: str,
    model: str | None,
    agent_prompt_version: str,
    summary_prompt_version: str,
) -> AgentRun:
    """Insert a ``running`` run and flush; the caller commits."""
    run = AgentRun(
        document_id=document_id,
        mode=mode,
        trigger=trigger,
        status=RunStatus.RUNNING.value,
        steps=[],
        model=model,
        agent_prompt_version=agent_prompt_version,
        summary_prompt_version=summary_prompt_version,
    )
    db.add(run)
    db.flush()
    return run


def get(db: Session, run_id: uuid.UUID) -> AgentRun | None:
    return db.get(AgentRun, run_id)


def set_steps(db: Session, run_id: uuid.UUID, steps: list[dict[str, Any]]) -> None:
    """Replace the run's step log and flush; the caller commits."""
    db.execute(update(AgentRun).where(AgentRun.id == run_id).values(steps=steps))
    db.flush()


def finish_run(db: Session, run_id: uuid.UUID, *, values: dict[str, Any]) -> None:
    """Close a run (status, result or error, tokens) and flush; the caller commits."""
    db.execute(
        update(AgentRun).where(AgentRun.id == run_id).values(**values, finished_at=func.now())
    )
    db.flush()


def fail_running(db: Session, document_id: uuid.UUID, *, error_code: str, error: str) -> int:
    """Mark every ``running`` run of the document ``failed``; returns how many changed."""
    result = db.execute(
        update(AgentRun)
        .where(AgentRun.document_id == document_id, AgentRun.status == RunStatus.RUNNING.value)
        .values(
            status=RunStatus.FAILED.value,
            error_code=error_code,
            error=error,
            finished_at=func.now(),
        )
    )
    db.flush()
    return result.rowcount


def latest_completed(db: Session, document_id: uuid.UUID) -> AgentRun | None:
    return db.execute(
        select(AgentRun)
        .where(
            AgentRun.document_id == document_id,
            AgentRun.status == RunStatus.COMPLETED.value,
        )
        .order_by(AgentRun.started_at.desc(), AgentRun.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_by_document(db: Session, document_id: uuid.UUID) -> Sequence[AgentRun]:
    """Newest first."""
    return (
        db.execute(
            select(AgentRun)
            .where(AgentRun.document_id == document_id)
            .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        )
        .scalars()
        .all()
    )


def _since(query: Select[Any], since: datetime | None) -> Select[Any]:
    return query if since is None else query.where(AgentRun.started_at >= since)


def count_by_status(db: Session, *, since: datetime | None = None) -> dict[str, int]:
    query = select(AgentRun.status, func.count()).group_by(AgentRun.status)
    return dict(db.execute(_since(query, since)).all())


def completed_duration_stats(
    db: Session, *, since: datetime | None = None
) -> tuple[float | None, float | None, float | None]:
    """Average, p50 and p95 duration of completed runs in milliseconds."""
    duration_ms = func.extract("epoch", AgentRun.finished_at - AgentRun.started_at) * 1000
    query = select(
        func.avg(duration_ms),
        func.percentile_cont(0.5).within_group(duration_ms),
        func.percentile_cont(0.95).within_group(duration_ms),
    ).where(AgentRun.status == RunStatus.COMPLETED.value, AgentRun.finished_at.is_not(None))
    avg, p50, p95 = db.execute(_since(query, since)).one()
    return (
        float(avg) if avg is not None else None,
        float(p50) if p50 is not None else None,
        float(p95) if p95 is not None else None,
    )


def completed_ids(db: Session, *, since: datetime | None = None) -> Sequence[uuid.UUID]:
    query = select(AgentRun.id).where(AgentRun.status == RunStatus.COMPLETED.value)
    return db.execute(_since(query, since)).scalars().all()


def confidence_totals(
    db: Session, *, since: datetime | None, high: float, medium: float
) -> tuple[int, Decimal | None, int, dict[str, int]]:
    """Scored completed runs: count, average, needs-review count and count per label."""
    scored = AgentRun.overall_confidence.is_not(None)
    label = case(
        (AgentRun.overall_confidence >= high, "high"),
        (AgentRun.overall_confidence >= medium, "medium"),
        else_="low",
    )
    base = select(
        func.count(),
        func.avg(AgentRun.overall_confidence),
        func.count().filter(AgentRun.needs_review.is_(True)),
    ).where(AgentRun.status == RunStatus.COMPLETED.value, scored)
    count, average, review = db.execute(_since(base, since)).one()
    per_label = (
        select(label, func.count())
        .where(AgentRun.status == RunStatus.COMPLETED.value, scored)
        .group_by(label)
    )
    labels = dict(db.execute(_since(per_label, since)).all())
    return count, average, review, labels


def issue_code_counts(
    db: Session, codes: Sequence[str], *, since: datetime | None
) -> dict[str, int]:
    """Completed runs whose ``result.validation.issues`` contain each code (feature 0010)."""
    counts: dict[str, int] = {}
    for code in codes:
        contains = AgentRun.result["validation"]["issues"].contains([{"code": code}])
        query = select(func.count()).where(AgentRun.status == RunStatus.COMPLETED.value, contains)
        counts[code] = db.execute(_since(query, since)).scalar_one()
    return counts


# -- Query Agent (feature 0010) -------------------------------------------------------------


def create_conversation(db: Session) -> QueryConversation:
    conversation = QueryConversation()
    db.add(conversation)
    db.flush()
    return conversation


def lock_conversation(db: Session, conversation_id: uuid.UUID) -> QueryConversation | None:
    """The conversation row, locked until commit so two turns never take one number."""
    return db.execute(
        select(QueryConversation).where(QueryConversation.id == conversation_id).with_for_update()
    ).scalar_one_or_none()


def get_conversation(db: Session, conversation_id: uuid.UUID) -> QueryConversation | None:
    return db.get(QueryConversation, conversation_id)


def touch_conversation(db: Session, conversation_id: uuid.UUID) -> None:
    db.execute(
        update(QueryConversation)
        .where(QueryConversation.id == conversation_id)
        .values(updated_at=func.now())
    )


def next_turn(db: Session, conversation_id: uuid.UUID) -> int:
    last = db.execute(
        select(func.max(QueryRun.turn)).where(QueryRun.conversation_id == conversation_id)
    ).scalar_one()
    return (last or 0) + 1


def create_query_run(db: Session, **values: Any) -> QueryRun:
    run = QueryRun(status=RunStatus.RUNNING.value, citations=[], steps=[], **values)
    db.add(run)
    db.flush()
    return run


def finish_query_run(db: Session, run_id: uuid.UUID, *, values: dict[str, Any]) -> QueryRun:
    db.execute(
        update(QueryRun)
        .where(QueryRun.id == run_id)
        .values(finished_at=func.clock_timestamp(), **values)
    )
    db.flush()
    run = db.get(QueryRun, run_id)
    assert run is not None
    db.refresh(run)
    return run


def list_turns(db: Session, conversation_id: uuid.UUID) -> Sequence[QueryRun]:
    return (
        db.execute(
            select(QueryRun)
            .where(QueryRun.conversation_id == conversation_id)
            .order_by(QueryRun.turn)
        )
        .scalars()
        .all()
    )


def recent_completed_turns(
    db: Session, conversation_id: uuid.UUID, *, limit: int
) -> list[QueryRun]:
    """The last ``limit`` completed turns, oldest first."""
    rows = (
        db.execute(
            select(QueryRun)
            .where(
                QueryRun.conversation_id == conversation_id,
                QueryRun.status == RunStatus.COMPLETED.value,
            )
            .order_by(QueryRun.turn.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(reversed(rows))


def query_totals(
    db: Session, *, since: datetime | None
) -> tuple[int, int, int, int, int, float | None]:
    """(conversations, questions, failed, unanswerable, unverified, avg ms of completed)."""
    duration_ms = func.extract("epoch", QueryRun.finished_at - QueryRun.started_at) * 1000
    completed = QueryRun.status == RunStatus.COMPLETED.value
    query = select(
        func.count(func.distinct(QueryRun.conversation_id)),
        func.count(),
        func.count().filter(QueryRun.status == RunStatus.FAILED.value),
        func.count().filter(completed, QueryRun.answerable.is_(False)),
        func.count().filter(completed, QueryRun.numbers_verified.is_(False)),
        func.avg(duration_ms).filter(completed),
    )
    if since is not None:
        query = query.where(QueryRun.started_at >= since)
    conversations, questions, failed, unanswerable, unverified, avg = db.execute(query).one()
    return (
        conversations,
        questions,
        failed,
        unanswerable,
        unverified,
        float(avg) if avg is not None else None,
    )
