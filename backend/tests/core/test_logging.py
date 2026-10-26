import json
import logging

from app.core.logging import JsonFormatter, bind_document_id, document_id_var


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
