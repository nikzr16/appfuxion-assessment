"""The Document Agent: runs the tools on one document, records the run, owns its status."""

import logging
import time
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import ConflictError
from app.core.llm import LLMClient, TokenUsage
from app.core.logging import bind_document_id
from app.core.storage import Storage
from app.modules.agent import crud, prompts
from app.modules.agent.model import AgentRun
from app.modules.agent.runner import AgentRunError, AgentRunner, RunOutcome
from app.modules.agent.schema import (
    AgentMode,
    AgentResult,
    AgentRunRead,
    RunStatus,
    RunTrigger,
    ToolStep,
)
from app.modules.agent.tools import DocumentToolContext, build_document_tools
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus, DocumentUploadResponse

logger = logging.getLogger(__name__)


def run_document_agent(
    document_id: uuid.UUID,
    *,
    llm: LLMClient,
    storage: Storage,
    trigger: RunTrigger = RunTrigger.UPLOAD,
    force: bool = False,
    today: date | None = None,
) -> None:
    """Background task: process one document with the Document Agent (PRD 0005).

    Opens its own session. Expected failures (tool errors, step limit, LLM errors) end with
    the run and the document ``failed`` and are not raised; anything unexpected propagates
    so ``documents.service.run_pipeline`` can still mark the document ``failed``.
    """
    settings = get_settings()
    db = SessionLocal()
    try:
        with bind_document_id(str(document_id)):
            mode = _resolve_mode(settings.agent_mode)
            source = documents_service.get_document_source(db, document_id)
            stale = crud.fail_running(
                db,
                document_id,
                error_code="run_abandoned",
                error="A newer run started before this one finished.",
            )
            if stale:
                logger.warning("closed stale running agent runs", extra={"count": stale})
            run = crud.create_run(
                db,
                document_id=document_id,
                mode=mode.value,
                trigger=trigger.value,
                model=settings.openai_model,
                agent_prompt_version=prompts.AGENT_PROMPT_VERSION,
                summary_prompt_version=prompts.SUMMARY_PROMPT_VERSION,
            )
            db.commit()
            logger.info(
                "agent run started",
                extra={"run_id": str(run.id), "mode": mode.value, "trigger": trigger.value},
            )
            _execute(db, run, llm, storage, source.content_type, force=force, today=today)
    finally:
        db.close()


def _execute(
    db: Session,
    run: AgentRun,
    llm: LLMClient,
    storage: Storage,
    content_type: str,
    *,
    force: bool,
    today: date | None,
) -> None:
    settings = get_settings()
    started = time.perf_counter()
    ctx = DocumentToolContext(
        db=db,
        llm=llm,
        storage=storage,
        document_id=run.document_id,
        base_currency=settings.base_currency,
        force=force,
        today=today,
    )
    runner = AgentRunner(llm, build_document_tools(ctx), max_steps=settings.agent_max_steps)
    messages = [
        {"role": "system", "content": prompts.agent_system_prompt(settings.base_currency)},
        {"role": "user", "content": prompts.agent_user_prompt(str(run.document_id), content_type)},
    ]
    recorded: list[ToolStep] = []

    def save_step(step: ToolStep) -> None:
        # Keeps GET /runs live while the run is going; the tools commit their own rows too.
        recorded.append(step)
        crud.set_steps(db, run.id, _dump_steps(recorded))
        db.commit()

    try:
        outcome = runner.run(messages, done=lambda: ctx.summary is not None, on_step=save_step)
    except AgentRunError as exc:
        db.rollback()
        usage = exc.usage + ctx.summary_usage
        crud.finish_run(
            db,
            run.id,
            values={
                "status": RunStatus.FAILED.value,
                "steps": _dump_steps(exc.steps),
                "error_code": exc.code,
                "error": exc.message,
                "model": exc.model or run.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            },
        )
        documents_service.mark_failed(db, run.document_id, f"{exc.code}: {exc.message}")
        db.commit()
        _log_finished(RunStatus.FAILED, exc.code, len(exc.steps), exc.turns, usage, started)
        return

    _complete(db, run, ctx, outcome)
    usage = outcome.usage + ctx.summary_usage
    _log_finished(RunStatus.COMPLETED, None, len(outcome.steps), outcome.turns, usage, started)


def _complete(db: Session, run: AgentRun, ctx: DocumentToolContext, outcome: RunOutcome) -> None:
    """Save the result and complete the run and the document in one transaction (D8)."""
    assert ctx.structured is not None and ctx.validation is not None and ctx.summary is not None
    result = AgentResult(
        document_id=run.document_id,
        structured_data=ctx.structured,
        validation=ctx.validation,
        conversion=ctx.conversion,
        summary=ctx.summary,
    )
    usage = outcome.usage + ctx.summary_usage
    crud.finish_run(
        db,
        run.id,
        values={
            "status": RunStatus.COMPLETED.value,
            "steps": _dump_steps(outcome.steps),
            "result": result.model_dump(mode="json"),
            "summary": ctx.summary,
            "model": outcome.model or run.model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
        },
    )
    documents_service.mark_completed(db, run.document_id)
    db.commit()


def start_reprocess(db: Session, document_id: uuid.UUID) -> DocumentUploadResponse:
    """Put the document back to ``processing``; the caller schedules the run (D10)."""
    document = documents_service.restart_processing(db, document_id)
    db.commit()
    return DocumentUploadResponse(document_id=document.document_id, status=document.status)


def get_result(db: Session, document_id: uuid.UUID) -> AgentResult:
    """The final result of the latest completed run (D9); never runs anything."""
    document = documents_service.get_document(db, document_id)
    if document.status == DocumentStatus.PROCESSING:
        raise ConflictError(
            "The document is still processing; its result is not ready yet.",
            code="result_not_ready",
        )
    run = crud.latest_completed(db, document_id)
    if document.status == DocumentStatus.FAILED or run is None or run.result is None:
        message = "No result is available for this document."
        if document.error:
            message = f"{message} Processing failed: {document.error}"
        raise ConflictError(message, code="result_unavailable")
    return AgentResult.model_validate(run.result)


def list_runs(db: Session, document_id: uuid.UUID) -> list[AgentRunRead]:
    """Every run of the document, newest first, with its tool-call log (D11)."""
    documents_service.get_document(db, document_id)  # 404 when unknown
    return [AgentRunRead.model_validate(run) for run in crud.list_by_document(db, document_id)]


def _resolve_mode(configured: str) -> AgentMode:
    """PRD D13: ``multi`` is not available until B4, so it runs the single agent."""
    if configured == AgentMode.MULTI:
        logger.warning(
            "multi-agent mode is not available until B4; running the single Document Agent"
        )
    return AgentMode.SINGLE


def _dump_steps(steps: list[ToolStep]) -> list[dict[str, object]]:
    return [step.model_dump(mode="json") for step in steps]


def _log_finished(
    status: RunStatus,
    error_code: str | None,
    steps: int,
    turns: int,
    usage: TokenUsage,
    started: float,
) -> None:
    logger.info(
        "agent run finished",
        extra={
            "status": status.value,
            "error_code": error_code,
            "steps": steps,
            "turns": turns,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
