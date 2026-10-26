import ast
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, LLMError, NotFoundError
from app.core.llm import FakeLLM, LLMResponse, TokenUsage
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.structured_extraction import prompts, service
from app.modules.structured_extraction.model import Extraction
from app.modules.structured_extraction.schema import DocumentType, InvoiceData
from app.modules.structured_extraction.service import StructuredExtractionError
from tests.modules.structured_extraction.conftest import MakeDocument, invoice

# A structured reply whose currency fails validation (the model kept the symbol).
INVALID_REPLY = invoice().model_dump_json().replace('"MYR"', '"RM"')


def _row_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Extraction)).scalar_one()


def _status(db: Session, document_id: uuid.UUID) -> DocumentStatus:
    db.expire_all()
    return documents_service.get_document(db, document_id).status


# -- Happy path -----------------------------------------------------------------------


def test_extracts_saves_and_returns_typed_data(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(invoice())

    result = service.extract_structured_data(db_session, fake_llm, document_id)

    assert result.document_id == document_id
    assert result.data == invoice()
    assert result.data.total_amount == Decimal("123.45")
    assert result.data.invoice_date == date(2025, 3, 4)
    assert result.model == "fake-model"
    assert result.prompt_version == prompts.PROMPT_VERSION
    assert result.attempts == 1
    assert (result.prompt_tokens, result.completion_tokens) == (10, 5)
    assert _row_count(db_session) == 1
    assert _status(db_session, document_id) == DocumentStatus.PROCESSING  # untouched


def test_the_call_uses_the_strict_schema_and_wraps_the_text(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    text = "--- Page 1 ---\nINVOICE INV-1\n\n--- Page 2 ---\nTotal RM 9.00"
    document_id = make_document(text)
    fake_llm.queue(invoice())

    service.extract_structured_data(db_session, fake_llm, document_id)

    [call] = fake_llm.calls
    assert call.response_format is InvoiceData
    assert call.temperature == 0
    assert call.vision is False
    assert call.messages[0] == {"role": "system", "content": prompts.SYSTEM_PROMPT}
    assert call.messages[1] == {"role": "user", "content": f"<document>\n{text}\n</document>"}


def test_money_is_stored_as_exact_decimal_strings(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(invoice(total_amount="1234567.89"))

    service.extract_structured_data(db_session, fake_llm, document_id)

    stored = db_session.execute(select(Extraction.data)).scalar_one()
    assert stored["total_amount"] == "1234567.89"
    assert stored["invoice_date"] == "2025-03-04"
    assert stored["due_date"] is None
    assert stored["line_items"][0]["unit_price"] == "10.00"


def test_unknown_document_type_is_a_saved_result(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document("Meeting notes: discuss the roadmap.")
    empty = {name: None for name in InvoiceData.model_fields if name != "document_type"}
    fake_llm.queue(
        InvoiceData.model_validate({**empty, "document_type": "unknown", "line_items": []})
    )

    result = service.extract_structured_data(db_session, fake_llm, document_id)

    assert result.data.document_type is DocumentType.UNKNOWN
    assert result.data.line_items == []
    assert _row_count(db_session) == 1


# -- Retry ----------------------------------------------------------------------------


def test_an_invalid_reply_is_retried_once_with_the_errors_fed_back(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(INVALID_REPLY, invoice())

    result = service.extract_structured_data(db_session, fake_llm, document_id)

    assert result.attempts == 2
    assert result.data.currency == "MYR"
    first, second = fake_llm.calls
    assert second.messages[:2] == first.messages
    feedback = second.messages[2]
    assert feedback["role"] == "user"
    assert "currency: Value error, must be a 3-letter ISO 4217 code" in feedback["content"]
    assert "(got: 'RM')" in feedback["content"]
    # Tokens of a rejected reply are not reported by the SDK; only the valid one counts.
    assert (result.prompt_tokens, result.completion_tokens) == (10, 5)


def test_a_reply_without_a_parsed_object_counts_as_an_invalid_attempt(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    empty = LLMResponse(content="", usage=TokenUsage(3, 1), model="fake-model", parsed=None)
    fake_llm.queue(empty, invoice())

    result = service.extract_structured_data(db_session, fake_llm, document_id)

    assert result.attempts == 2
    assert "no structured object" in fake_llm.calls[1].messages[2]["content"]
    assert (result.prompt_tokens, result.completion_tokens) == (13, 6)


def test_two_invalid_replies_raise_invalid_llm_output(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(INVALID_REPLY, INVALID_REPLY)

    with pytest.raises(StructuredExtractionError) as caught:
        service.extract_structured_data(db_session, fake_llm, document_id)

    assert caught.value.code == "invalid_llm_output"
    assert caught.value.status_code == 502
    assert "currency" in caught.value.message
    assert len(fake_llm.calls) == 2
    assert _row_count(db_session) == 0
    assert _status(db_session, document_id) == DocumentStatus.PROCESSING


def test_a_refusal_is_not_retried(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    refusal = LLMResponse(content=None, usage=TokenUsage(), model="m", refusal="I can't.")
    fake_llm.queue(refusal, invoice())

    with pytest.raises(StructuredExtractionError) as caught:
        service.extract_structured_data(db_session, fake_llm, document_id)

    assert caught.value.code == "llm_refused"
    assert len(fake_llm.calls) == 1
    assert _row_count(db_session) == 0
    assert _status(db_session, document_id) == DocumentStatus.PROCESSING


def test_an_api_failure_is_not_retried(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(LLMError("upstream down"), invoice())

    with pytest.raises(LLMError) as caught:
        service.extract_structured_data(db_session, fake_llm, document_id)

    assert caught.value.code == "llm_error"
    assert len(fake_llm.calls) == 1
    assert _row_count(db_session) == 0
    assert _status(db_session, document_id) == DocumentStatus.PROCESSING


def test_format_errors_names_the_field_and_truncates_the_value() -> None:
    lines = service._format_errors(
        [
            {"loc": ("line_items", 0, "amount"), "msg": "bad", "input": "x" * 200},
            {"loc": (), "msg": "no object"},
        ]
    )

    assert lines[0].startswith("line_items.0.amount: bad (got: 'xxx")
    assert lines[0].endswith("...)")
    assert len(lines[0]) < 120
    assert lines[1] == "reply: no object"


# -- Idempotence and force ------------------------------------------------------------


def test_second_call_returns_the_same_row_without_a_new_llm_call(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(invoice())

    first = service.extract_structured_data(db_session, fake_llm, document_id)
    second = service.extract_structured_data(db_session, fake_llm, document_id)

    assert second.id == first.id
    assert second.data == first.data
    assert len(fake_llm.calls) == 1


def test_force_re_extracts_and_replaces_the_row_in_place(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(invoice(), invoice(vendor="ACME (corrected)"))

    first = service.extract_structured_data(db_session, fake_llm, document_id)
    forced = service.extract_structured_data(db_session, fake_llm, document_id, force=True)

    assert forced.id == first.id
    assert forced.data.vendor == "ACME (corrected)"
    assert forced.updated_at > first.updated_at
    assert len(fake_llm.calls) == 2
    assert _row_count(db_session) == 1


# -- Prerequisites --------------------------------------------------------------------


def test_missing_text_is_409_text_not_extracted(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(raw_text=None)

    with pytest.raises(ConflictError) as caught:
        service.extract_structured_data(db_session, fake_llm, document_id)

    assert caught.value.code == "text_not_extracted"
    assert fake_llm.calls == []


def test_unknown_document_is_not_found(db_session: Session, fake_llm: FakeLLM) -> None:
    with pytest.raises(NotFoundError):
        service.extract_structured_data(db_session, fake_llm, uuid.uuid4())


# -- Long text ------------------------------------------------------------------------


def test_long_text_is_sent_as_head_and_tail(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    text = "H" * 45_000 + "M" * 10_000 + "T" * 15_000
    document_id = make_document(text)
    fake_llm.queue(invoice())

    service.extract_structured_data(db_session, fake_llm, document_id)

    sent = fake_llm.calls[0].messages[1]["content"]
    assert sent == (
        "<document>\n"
        + "H" * 45_000
        + "\n\n[... 10000 characters omitted ...]\n\n"
        + "T" * 15_000
        + "\n</document>"
    )


def test_text_at_the_limit_is_sent_unchanged() -> None:
    text = "x" * service.MAX_INPUT_CHARS
    assert service._fit_text(text) == text


# -- Transactions ---------------------------------------------------------------------


def test_no_database_transaction_is_open_during_the_llm_call(
    db_session: Session, make_document: MakeDocument
) -> None:
    in_transaction: list[bool] = []

    class ProbingLLM(FakeLLM):
        def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
            in_transaction.append(db_session.in_transaction())
            return super().complete(*args, **kwargs)

    document_id = make_document()
    service.extract_structured_data(db_session, ProbingLLM([INVALID_REPLY, invoice()]), document_id)

    assert in_transaction == [False, False]


# -- get_extraction -------------------------------------------------------------------


def test_get_extraction_returns_the_saved_row(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(invoice())
    saved = service.extract_structured_data(db_session, fake_llm, document_id)

    assert service.get_extraction(db_session, document_id) == saved


def test_get_extraction_while_processing_is_409_not_ready(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document()

    with pytest.raises(ConflictError) as caught:
        service.get_extraction(db_session, document_id)
    assert caught.value.code == "extraction_not_ready"


def test_get_extraction_for_a_failed_document_is_409_unavailable(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document()
    documents_service.mark_failed(db_session, document_id, "StructuredExtractionError: boom")
    db_session.commit()

    with pytest.raises(ConflictError) as caught:
        service.get_extraction(db_session, document_id)
    assert caught.value.code == "extraction_unavailable"
    assert "StructuredExtractionError: boom" in caught.value.message


def test_get_extraction_for_an_unknown_document_is_not_found(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        service.get_extraction(db_session, uuid.uuid4())


# -- Layering -------------------------------------------------------------------------


def test_module_never_imports_another_modules_crud_or_model() -> None:
    module_dir = Path(service.__file__).parent
    own = "app.modules.structured_extraction."
    offenders: list[str] = []
    for path in module_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = {node.module} | {f"{node.module}.{alias.name}" for alias in node.names}
            else:
                continue
            offenders += [
                f"{path.name}: {name}"
                for name in names
                if name.startswith("app.modules.")
                and not name.startswith(own)
                and name.rsplit(".", 1)[-1] in ("crud", "model")
            ]
    assert offenders == []


def test_service_does_not_import_fastapi() -> None:
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "fastapi" not in source
