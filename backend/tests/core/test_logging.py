import json
import logging

from app.core.logging import (
    JsonFormatter,
    TraceLabels,
    bind_document_id,
    bind_trace,
    document_id_var,
    trace_labels,
)


def format_record(**extra: object) -> dict[str, object]:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonFormatter().format(record))


def test_json_formatter_emits_core_fields_and_extras() -> None:
    payload = format_record(model="gpt-x", prompt_tokens=3)

    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "t"
    assert payload["model"] == "gpt-x"
    assert payload["prompt_tokens"] == 3
    assert "document_id" not in payload


def test_document_id_context_var_is_attached_and_reset() -> None:
    with bind_document_id("doc_abc"):
        assert format_record()["document_id"] == "doc_abc"
    assert document_id_var.get() is None
    assert "document_id" not in format_record()


def test_trace_labels_are_attached_nested_and_reset() -> None:
    with bind_document_id("doc_1"), bind_trace(run_id="run_1", agent="document"):
        with bind_trace(purpose="summary", step_index=0):
            payload = format_record()
            assert trace_labels().step_index == 0
        outer = format_record()

    assert payload["run_id"] == "run_1"
    assert payload["agent"] == "document"
    assert payload["purpose"] == "summary"
    assert payload["step_index"] == 0
    assert "purpose" not in outer and outer["run_id"] == "run_1"
    assert trace_labels() == TraceLabels()


def test_bind_trace_leaves_labels_it_is_not_given() -> None:
    with bind_trace(run_id="run_1"), bind_trace(purpose="agent_loop"):
        assert trace_labels().run_id == "run_1"
        with bind_trace(run_id=None):
            assert trace_labels().run_id is None
        assert trace_labels().run_id == "run_1"
