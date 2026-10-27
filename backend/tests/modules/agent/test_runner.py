"""AgentRunner with toy tools: no database, scripted FakeLLM only."""

import json
from typing import Any

import pytest

from app.core.errors import AppError, LLMError
from app.core.llm import FakeLLM, LLMResponse, TokenUsage, ToolCall
from app.modules.agent.runner import NO_ARGUMENTS, AgentRunError, AgentRunner, Tool, ToolError
from app.modules.agent.schema import StepStatus
from tests.modules.agent.conftest import text_turn, tool_turn


class Recorder:
    """Toy tools: ``echo`` returns its arguments; ``finish`` sets ``done``."""

    def __init__(self) -> None:
        self.finished = False
        self.calls: list[str] = []

    def tools(self, **extra: Any) -> list[Tool]:
        tools = [
            Tool("echo", "Echo the arguments.", _object({"text": {"type": "string"}}), self._echo),
            Tool("finish", "Finish.", NO_ARGUMENTS, self._finish),
        ]
        tools += [Tool(name, name, NO_ARGUMENTS, handler) for name, handler in extra.items()]
        return tools

    def _echo(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("echo")
        return {"echo": arguments.get("text")}

    def _finish(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append("finish")
        self.finished = True
        return {"ok": True}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _run(fake: FakeLLM, recorder: Recorder, max_steps: int = 5, **extra: Any) -> Any:
    runner = AgentRunner(fake, recorder.tools(**extra), max_steps=max_steps)
    return runner.run(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        done=lambda: recorder.finished,
    )


def test_tool_definitions_are_strict_functions() -> None:
    definition = Recorder().tools()[1].definition()
    assert definition == {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish.",
            "parameters": dict(NO_ARGUMENTS),
            "strict": True,
        },
    }


def test_runs_tools_until_done_and_records_every_step() -> None:
    recorder = Recorder()
    fake = FakeLLM([tool_turn(("echo", {"text": "hi"})), tool_turn("finish")])

    outcome = _run(fake, recorder)

    assert recorder.calls == ["echo", "finish"]
    assert outcome.turns == 2
    assert outcome.usage == TokenUsage(20, 10)
    assert outcome.model == "fake-model"
    first, second = outcome.steps
    assert (first.index, first.turn, first.tool) == (0, 1, "echo")
    assert first.arguments == {"text": "hi"}
    assert first.status is StepStatus.OK
    assert first.result == {"echo": "hi"}
    assert first.error is None
    assert first.duration_ms >= 0
    assert (second.index, second.turn, second.tool) == (1, 2, "finish")


def test_tool_choice_is_sent_only_when_the_runner_sets_it() -> None:
    fake = FakeLLM([tool_turn("finish")])
    _run(fake, Recorder())
    assert fake.calls[0].tool_choice is None

    recorder = Recorder()
    fake = FakeLLM([tool_turn("finish")])
    AgentRunner(fake, recorder.tools(), max_steps=2, tool_choice="required").run(
        [{"role": "user", "content": "go"}], done=lambda: recorder.finished
    )
    assert fake.calls[0].tool_choice == "required"


def test_every_call_sends_the_tools_at_temperature_zero_and_the_tool_results_back() -> None:
    recorder = Recorder()
    first_turn = tool_turn(("echo", {"text": "hi"}))
    fake = FakeLLM([first_turn, tool_turn("finish")])

    _run(fake, recorder)

    assert all(call.temperature == 0 for call in fake.calls)
    assert all(
        [t["function"]["name"] for t in call.tools or []] == ["echo", "finish"]
        for call in fake.calls
    )
    second = fake.calls[1].messages
    assistant, tool_message = second[2], second[3]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == first_turn.tool_calls[0].id
    assert assistant["tool_calls"][0]["function"]["name"] == "echo"
    assert tool_message == {
        "role": "tool",
        "tool_call_id": first_turn.tool_calls[0].id,
        "content": json.dumps({"echo": "hi"}),
    }


def test_a_recoverable_error_goes_back_to_the_model_and_the_loop_continues() -> None:
    def refuse(_args: dict[str, Any]) -> dict[str, Any]:
        raise ToolError("not_yet", "Call echo first.")

    recorder = Recorder()
    fake = FakeLLM([tool_turn("refuse"), tool_turn("finish")])

    outcome = _run(fake, recorder, refuse=refuse)

    step = outcome.steps[0]
    assert step.status is StepStatus.ERROR
    assert step.result is None
    assert step.error is not None and step.error.code == "not_yet"
    assert json.loads(fake.calls[1].messages[-1]["content"]) == {
        "error": {"code": "not_yet", "message": "Call echo first."}
    }
    assert recorder.finished


@pytest.mark.parametrize(
    ("handler_error", "code"),
    [
        (ToolError("broken", "Cannot go on.", fatal=True), "broken"),
        (AppError("Unclassified.", code="something_bad"), "something_bad"),
        (RuntimeError("boom"), "internal_error"),
    ],
)
def test_a_fatal_error_ends_the_run_at_once(handler_error: Exception, code: str) -> None:
    def explode(_args: dict[str, Any]) -> dict[str, Any]:
        raise handler_error

    fake = FakeLLM([tool_turn("explode", "finish"), tool_turn("finish")])

    with pytest.raises(AgentRunError) as caught:
        _run(fake, Recorder(), explode=explode)

    assert caught.value.code == code
    assert len(fake.calls) == 1  # no further LLM call
    assert [step.tool for step in caught.value.steps] == ["explode"]  # finish never ran
    assert caught.value.usage == TokenUsage(10, 5)


@pytest.mark.parametrize(
    ("name", "arguments", "code"),
    [
        ("echo", "{not json", "invalid_arguments"),
        ("echo", "[1, 2]", "invalid_arguments"),
        ("missing_tool", "{}", "unknown_tool"),
    ],
)
def test_bad_calls_are_recoverable(name: str, arguments: str, code: str) -> None:
    bad = LLMResponse(
        content=None,
        usage=TokenUsage(10, 5),
        model="fake-model",
        tool_calls=(ToolCall(id="call_bad", name=name, arguments=arguments),),
    )
    recorder = Recorder()
    fake = FakeLLM([bad, tool_turn("finish")])

    outcome = _run(fake, recorder)

    assert outcome.steps[0].error is not None
    assert outcome.steps[0].error.code == code
    assert recorder.finished


def test_a_reply_without_tool_calls_is_agent_incomplete() -> None:
    fake = FakeLLM([tool_turn(("echo", {"text": "a"})), text_turn("All done!")])

    with pytest.raises(AgentRunError) as caught:
        _run(fake, Recorder())

    assert caught.value.code == "agent_incomplete"
    assert len(caught.value.steps) == 1


def test_the_step_limit_counts_model_turns() -> None:
    fake = FakeLLM([tool_turn(("echo", {"text": "a"})) for _ in range(4)])

    with pytest.raises(AgentRunError) as caught:
        _run(fake, Recorder(), max_steps=3)

    assert caught.value.code == "agent_max_steps"
    assert len(fake.calls) == 3
    assert caught.value.turns == 3


def test_done_stops_before_the_rest_of_the_turn() -> None:
    recorder = Recorder()
    fake = FakeLLM([tool_turn("finish", ("echo", {"text": "late"}))])

    outcome = _run(fake, recorder)

    assert recorder.calls == ["finish"]
    assert len(outcome.steps) == 1


def test_an_llm_failure_ends_the_run_with_its_code() -> None:
    fake = FakeLLM([tool_turn(("echo", {"text": "a"})), LLMError("OpenAI is down")])

    with pytest.raises(AgentRunError) as caught:
        _run(fake, Recorder())

    assert caught.value.code == "llm_error"
    assert caught.value.message == "OpenAI is down"
    assert len(caught.value.steps) == 1


def test_on_step_sees_each_step_as_it_happens() -> None:
    recorder = Recorder()
    seen: list[str] = []
    runner = AgentRunner(
        FakeLLM([tool_turn(("echo", {"text": "a"}), "finish")]), recorder.tools(), max_steps=2
    )

    runner.run([], done=lambda: recorder.finished, on_step=lambda step: seen.append(step.tool))

    assert seen == ["echo", "finish"]
