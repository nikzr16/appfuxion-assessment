"""The Coordinator: multi-agent mode (PRD 0011). Plain Python, no LLM.

It runs the Extraction, Validation and Reporting agents in that order on the shared
``AgentRunner``. All three work on one ``DocumentToolContext``, so every tool guard (tables
before structured data, grounding before validation, vendor history and similar invoices
before the summary) holds across agents unchanged (D1). Each agent starts a fresh
conversation with a hand-off brief written by code (D2), sees only its own tools (D4) and
ends when code says its work is done (D5). The first agent that fails ends the run; the
agents after it never start (D6). Status and storage stay with the service.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.llm import Agent, LLMClient, TokenUsage
from app.core.logging import bind_trace
from app.modules.agent import prompts
from app.modules.agent.runner import AgentRunError, AgentRunner
from app.modules.agent.schema import AgentPart, RunStatus, ToolStep
from app.modules.agent.tools import (
    EXTRACTION_TOOLS,
    REPORTING_TOOLS,
    VALIDATION_TOOLS,
    DocumentToolContext,
    build_agent_tools,
    conversion_needed,
)
from app.modules.validation.schema import Severity

logger = logging.getLogger(__name__)

Progress = Callable[[list[ToolStep], list[AgentPart]], None]


@dataclass(frozen=True)
class AgentSpec:
    """One agent: who it is, what it is told, which tools it gets and when it is done."""

    agent: Agent
    name: str
    prompt_version: str
    system_prompt: Callable[[str], str]
    brief: Callable[[DocumentToolContext, str], str]
    tools: tuple[str, ...]
    max_steps: int
    done: Callable[[DocumentToolContext], bool]


def _extraction_brief(ctx: DocumentToolContext, content_type: str) -> str:
    return prompts.extraction_brief(str(ctx.document_id), content_type)


def _validation_brief(ctx: DocumentToolContext, _content_type: str) -> str:
    assert ctx.structured is not None and ctx.grounding is not None
    return prompts.validation_brief(
        document_type=ctx.structured.document_type.value,
        currency=ctx.structured.currency,
        base_currency=ctx.base_currency,
        checked=ctx.grounding.checked,
        grounded=ctx.grounding.grounded,
        ungrounded=ctx.grounding.ungrounded,
    )


def _reporting_brief(ctx: DocumentToolContext, _content_type: str) -> str:
    assert ctx.structured is not None and ctx.validation is not None
    severities = [issue.severity for issue in ctx.validation.issues]
    return prompts.reporting_brief(
        document_type=ctx.structured.document_type.value,
        status=ctx.validation.status.value,
        errors=severities.count(Severity.ERROR),
        warnings=severities.count(Severity.WARNING),
        converted=ctx.conversion is not None,
        needs_review=ctx.confidence.needs_review if ctx.confidence else None,
    )


def _validation_done(ctx: DocumentToolContext) -> bool:
    # A needed conversion must at least have been tried before the agent may stop (D5).
    return (
        ctx.validation is not None
        and ctx.history is not None
        and (ctx.conversion_tried or not conversion_needed(ctx))
    )


# Step limits per agent (D7): the happy paths take 4, 2-3 and 2 turns.
EXTRACTION = AgentSpec(
    agent=Agent.EXTRACTION,
    name="Extraction Agent",
    prompt_version=prompts.EXTRACTION_PROMPT_VERSION,
    system_prompt=prompts.extraction_system_prompt,
    brief=_extraction_brief,
    tools=EXTRACTION_TOOLS,
    max_steps=6,
    done=lambda ctx: ctx.grounding is not None,
)
VALIDATION = AgentSpec(
    agent=Agent.VALIDATION,
    name="Validation Agent",
    prompt_version=prompts.VALIDATION_PROMPT_VERSION,
    system_prompt=prompts.validation_system_prompt,
    brief=_validation_brief,
    tools=VALIDATION_TOOLS,
    max_steps=6,
    done=_validation_done,
)
REPORTING = AgentSpec(
    agent=Agent.REPORTING,
    name="Reporting Agent",
    prompt_version=prompts.REPORTING_PROMPT_VERSION,
    system_prompt=prompts.reporting_system_prompt,
    brief=_reporting_brief,
    tools=REPORTING_TOOLS,
    max_steps=4,
    done=lambda ctx: ctx.summary is not None,
)
AGENTS: tuple[AgentSpec, ...] = (EXTRACTION, VALIDATION, REPORTING)


@dataclass(frozen=True)
class CoordinatorOutcome:
    steps: list[ToolStep]
    parts: list[AgentPart]
    # Agent-loop turns only; the summary call's usage stays on the context, as in single mode.
    usage: TokenUsage
    model: str | None
    turns: int


class CoordinatorError(Exception):
    """An agent failed; carries everything recorded so far. ``message`` names the agent."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        steps: list[ToolStep],
        parts: list[AgentPart],
        usage: TokenUsage,
        model: str | None,
        turns: int,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.steps = steps
        self.parts = parts
        self.usage = usage
        self.model = model
        self.turns = turns


def run_agents(
    ctx: DocumentToolContext,
    llm: LLMClient,
    content_type: str,
    *,
    on_progress: Progress | None = None,
    agents: tuple[AgentSpec, ...] = AGENTS,
) -> CoordinatorOutcome:
    """Run the agents in order on one shared context; raise ``CoordinatorError`` on the first
    failure. ``on_progress`` sees the steps after each tool call and the parts after each
    agent, so the caller can keep ``GET /runs`` live."""
    steps: list[ToolStep] = []
    parts: list[AgentPart] = []
    usage = TokenUsage()
    model: str | None = None
    turns = 0

    def step_done(step: ToolStep) -> None:
        if on_progress is not None:
            on_progress([*steps, step], parts)

    for spec in agents:
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        summary_before = ctx.summary_usage
        runner = AgentRunner(
            llm,
            build_agent_tools(ctx, spec.tools),
            max_steps=spec.max_steps,
            prompt_version=spec.prompt_version,
            tool_choice="required",
            agent=spec.agent.value,
            step_offset=len(steps),
            turn_offset=turns,
        )
        messages = [
            {"role": "system", "content": spec.system_prompt(ctx.base_currency)},
            {"role": "user", "content": spec.brief(ctx, content_type)},
        ]
        logger.info("agent started", extra={"agent": spec.agent.value})
        try:
            with bind_trace(agent=spec.agent.value):
                outcome = runner.run(
                    messages, done=lambda spec=spec: spec.done(ctx), on_step=step_done
                )
        except AgentRunError as exc:
            steps += exc.steps
            usage = usage + exc.usage
            model = exc.model or model
            turns += exc.turns
            parts.append(
                _part(
                    spec,
                    RunStatus.FAILED,
                    exc.turns,
                    exc.steps,
                    exc.usage,
                    ctx,
                    summary_before,
                    started_at,
                    exc.code,
                )
            )
            _log_agent(spec, RunStatus.FAILED, exc.code, exc.turns, len(exc.steps), started)
            if on_progress is not None:
                on_progress(steps, parts)
            raise CoordinatorError(
                exc.code,
                f"{spec.name}: {exc.message}",
                steps=steps,
                parts=parts,
                usage=usage,
                model=model,
                turns=turns,
            ) from exc

        steps += outcome.steps
        usage = usage + outcome.usage
        model = outcome.model or model
        turns += outcome.turns
        parts.append(
            _part(
                spec,
                RunStatus.COMPLETED,
                outcome.turns,
                outcome.steps,
                outcome.usage,
                ctx,
                summary_before,
                started_at,
                None,
            )
        )
        _log_agent(spec, RunStatus.COMPLETED, None, outcome.turns, len(outcome.steps), started)
        if on_progress is not None:
            on_progress(steps, parts)

    return CoordinatorOutcome(steps=steps, parts=parts, usage=usage, model=model, turns=turns)


def _part(
    spec: AgentSpec,
    status: RunStatus,
    turns: int,
    steps: list[ToolStep],
    loop_usage: TokenUsage,
    ctx: DocumentToolContext,
    summary_before: TokenUsage,
    started_at: datetime,
    error_code: str | None,
) -> AgentPart:
    # The summary call is made inside the Reporting Agent's tool, so its tokens are that
    # agent's too: the parts then add up to the run's 0005 totals.
    summary = ctx.summary_usage
    return AgentPart(
        agent=spec.agent.value,
        status=status,
        prompt_version=spec.prompt_version,
        turns=turns,
        steps=len(steps),
        prompt_tokens=loop_usage.prompt_tokens
        + summary.prompt_tokens
        - summary_before.prompt_tokens,
        completion_tokens=(
            loop_usage.completion_tokens
            + summary.completion_tokens
            - summary_before.completion_tokens
        ),
        started_at=started_at,
        finished_at=datetime.now(UTC),
        error_code=error_code,
    )


def _log_agent(
    spec: AgentSpec,
    status: RunStatus,
    error_code: str | None,
    turns: int,
    steps: int,
    started: float,
) -> None:
    logger.info(
        "agent finished",
        extra={
            "agent": spec.agent.value,
            "status": status.value,
            "error_code": error_code,
            "turns": turns,
            "steps": steps,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
