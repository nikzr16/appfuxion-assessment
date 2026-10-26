"""``AgentRunner``: the OpenAI tool-calling loop every agent in the project shares.

The runner knows nothing about documents. An agent is a system prompt plus a list of
``Tool``s; the runner asks the model which tool to call, runs it, sends the (short) result
back, and repeats until the caller's ``done`` check passes or the step limit is reached.
Every tool call is recorded as a ``ToolStep``. Message contents are never logged or stored.

One *step* is one model turn (one ``LLMClient.complete`` call), whatever number of tool
calls that turn requests.
"""

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.errors import AppError, LLMError
from app.core.llm import LLMClient, Message, Purpose, TokenUsage, ToolCall
from app.core.logging import bind_trace
from app.modules.agent.schema import StepError, StepStatus, ToolStep

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    """A function the model may call. ``handler`` returns JSON-safe data for the model."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: ToolHandler

    def definition(self) -> dict[str, Any]:
        """The OpenAI ``tools`` entry (strict function calling)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
                "strict": True,
            },
        }


NO_ARGUMENTS: Mapping[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


class ToolError(Exception):
    """A tool could not do its job. Recoverable errors go back to the model; fatal ones
    end the run."""

    def __init__(self, code: str, message: str, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fatal = fatal


@dataclass(frozen=True)
class RunOutcome:
    steps: list[ToolStep]
    usage: TokenUsage
    model: str | None
    turns: int


class AgentRunError(Exception):
    """The run failed; carries what happened so far so the caller can record it."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        steps: list[ToolStep],
        usage: TokenUsage,
        model: str | None,
        turns: int,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.steps = steps
        self.usage = usage
        self.model = model
        self.turns = turns


class AgentRunner:
    def __init__(
        self,
        llm: LLMClient,
        tools: Sequence[Tool],
        *,
        max_steps: int,
        temperature: float = 0,
        prompt_version: str | None = None,
    ) -> None:
        self._llm = llm
        self._prompt_version = prompt_version
        self._tools = {tool.name: tool for tool in tools}
        self._definitions = [tool.definition() for tool in tools]
        self._max_steps = max_steps
        self._temperature = temperature

    def run(
        self,
        messages: Sequence[Message],
        *,
        done: Callable[[], bool],
        on_step: Callable[[ToolStep], None] | None = None,
    ) -> RunOutcome:
        """Loop until ``done()`` is true after a tool call; raise ``AgentRunError`` otherwise."""
        conversation: list[Message] = list(messages)
        steps: list[ToolStep] = []
        usage = TokenUsage()
        model: str | None = None

        def fail(code: str, message: str, turns: int) -> AgentRunError:
            return AgentRunError(code, message, steps=steps, usage=usage, model=model, turns=turns)

        for turn in range(1, self._max_steps + 1):
            try:
                with bind_trace(purpose=Purpose.AGENT_LOOP, prompt_version=self._prompt_version):
                    response = self._llm.complete(
                        conversation, tools=self._definitions, temperature=self._temperature
                    )
            except LLMError as exc:
                raise fail(exc.code, exc.message, turn) from exc
            usage = usage + response.usage
            model = response.model
            if not response.tool_calls:
                raise fail(
                    "agent_incomplete",
                    "The agent stopped calling tools before it finished.",
                    turn,
                )
            conversation.append(_assistant_message(response.content, response.tool_calls))

            for call in response.tool_calls:
                step, fatal = self._call(call, index=len(steps), turn=turn)
                steps.append(step)
                if on_step is not None:
                    on_step(step)
                payload = step.result if step.error is None else {"error": step.error.model_dump()}
                conversation.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(payload)}
                )
                if fatal and step.error is not None:
                    raise fail(step.error.code, step.error.message, turn)
                if done():
                    return RunOutcome(steps=steps, usage=usage, model=model, turns=turn)

        raise fail(
            "agent_max_steps",
            f"The agent did not finish within {self._max_steps} steps.",
            self._max_steps,
        )

    def _call(self, call: ToolCall, *, index: int, turn: int) -> tuple[ToolStep, bool]:
        """Run one tool call; returns the recorded step and whether its error is fatal."""
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        arguments: dict[str, Any] = {}
        result: dict[str, Any] | None = None
        error: ToolError | None = None
        try:
            parsed = json.loads(call.arguments or "{}")
            if not isinstance(parsed, dict):
                raise ToolError("invalid_arguments", "Tool arguments must be a JSON object.")
            arguments = parsed
            tool = self._tools.get(call.name)
            if tool is None:
                raise ToolError("unknown_tool", f"There is no tool named {call.name!r}.")
            # LLM calls made inside the tool are linked to this step in the ledger (0007).
            with bind_trace(step_index=index):
                result = tool.handler(arguments)
        except json.JSONDecodeError:
            error = ToolError("invalid_arguments", "Tool arguments are not valid JSON.")
        except ToolError as exc:
            error = exc
        except AppError as exc:  # a tool that did not classify its error: treat as fatal
            error = ToolError(exc.code, exc.message, fatal=True)
        except Exception as exc:
            logger.exception("agent tool crashed", extra={"tool": call.name})
            error = ToolError("internal_error", f"{type(exc).__name__}: {exc}", fatal=True)

        duration_ms = round((time.perf_counter() - started) * 1000)
        logger.info(
            "agent tool call",
            extra={
                "tool": call.name,
                "status": "error" if error else "ok",
                "error_code": error.code if error else None,
                "duration_ms": duration_ms,
            },
        )
        step = ToolStep(
            index=index,
            turn=turn,
            tool=call.name,
            arguments=arguments,
            status=StepStatus.ERROR if error else StepStatus.OK,
            result=result,
            error=StepError(code=error.code, message=error.message) if error else None,
            duration_ms=duration_ms,
            started_at=started_at,
        )
        return step, bool(error and error.fatal)


def _assistant_message(content: str | None, tool_calls: Sequence[ToolCall]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in tool_calls
        ],
    }
