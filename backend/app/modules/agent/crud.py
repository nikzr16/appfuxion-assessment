import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.modules.agent.model import AgentRun
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
