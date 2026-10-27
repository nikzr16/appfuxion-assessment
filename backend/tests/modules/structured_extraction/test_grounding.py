"""ground_extraction: grounding check + re-extraction with feedback (PRD 0008 D1, D3)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, LLMError
from app.core.llm import FakeLLM, LLMCallRecord, LLMResponse, TokenUsage, register_llm_recorder
from app.modules.guardrails.schema import GroundingStatus
from app.modules.structured_extraction import crud, prompts, service
from app.modules.structured_extraction.service import EXTRACTION_BUDGET
from tests.modules.structured_extraction.conftest import MakeDocument, invoice


@pytest.fixture
def records() -> Iterator[list[LLMCallRecord]]:
    seen: list[LLMCallRecord] = []
    register_llm_recorder(seen.append)
    yield seen
    register_llm_recorder(None)


def extracted(
    db: Session, fake: FakeLLM, make_document: MakeDocument, *replies: object
) -> uuid.UUID:
    document_id = make_document()
    fake.queue(*replies)  # type: ignore[arg-type]
    service.extract_structured_data(db, fake, document_id)
    return document_id


def test_a_grounded_extraction_needs_no_llm_call(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = extracted(db_session, fake_llm, make_document, invoice())
    calls = len(fake_llm.calls)

    result = service.ground_extraction(db_session, fake_llm, document_id)

    assert len(fake_llm.calls) == calls
    assert result.grounding is not None
    report = result.grounding.report
    assert report.ungrounded == 0
    assert result.grounding.kept_attempt == 1 and result.grounding.grounding_retries == 0
    assert [(a.attempt, a.reason, a.valid) for a in result.grounding.attempts] == [
        (1, "initial", True)
    ]
    assert result.attempts == 1
    assert {f.path: f.status for f in report.fields}["currency"] is GroundingStatus.INFERRED


def test_an_ungrounded_value_is_re_asked_with_feedback_and_replaced(
    db_session: Session,
    fake_llm: FakeLLM,
    make_document: MakeDocument,
    records: list[LLMCallRecord],
) -> None:
    document_id = extracted(
        db_session, fake_llm, make_document, invoice(vendor="Globex Trading Company")
    )
    fake_llm.queue(invoice())

    result = service.ground_extraction(db_session, fake_llm, document_id)

    retry = fake_llm.calls[-1]
    assert retry.messages[-2]["role"] == "assistant"
    assert "Globex Trading Company" in retry.messages[-2]["content"]
    assert retry.messages[-1]["content"] == prompts.grounding_retry_prompt(
        [("vendor", "Globex Trading Company")]
    )
    assert records[-1].labels.purpose == "grounding_retry"
    assert records[-1].labels.prompt_version == prompts.PROMPT_VERSION

    assert result.data.vendor == "ACME Supplies Sdn Bhd"
    assert result.attempts == 2
    assert result.prompt_tokens == 20 and result.completion_tokens == 10  # both calls
    assert result.grounding is not None
    assert result.grounding.kept_attempt == 2 and result.grounding.grounding_retries == 1
    assert [(a.reason, a.ungrounded) for a in result.grounding.attempts] == [
        ("initial", ["vendor"]),
        ("grounding", []),
    ]
    saved = crud.get_by_document(db_session, document_id)
    assert saved is not None and saved.data["vendor"] == "ACME Supplies Sdn Bhd"


def test_still_ungrounded_after_the_budget_is_kept_and_flagged(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    invented = invoice(total_amount="999.00")
    document_id = extracted(db_session, fake_llm, make_document, invented)
    fake_llm.queue(invented, invented)

    result = service.ground_extraction(db_session, fake_llm, document_id)

    assert result.attempts == EXTRACTION_BUDGET
    assert str(result.data.total_amount) == "999.00"  # flagged, not nulled
    assert result.grounding is not None
    assert result.grounding.grounding_retries == 2
    assert result.grounding.kept_attempt == 3  # ties go to the latest
    assert [f.path for f in result.grounding.report.ungrounded_fields()] == ["total_amount"]


def test_a_worse_retry_is_not_kept(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = extracted(db_session, fake_llm, make_document, invoice(vendor="Globex Ltd"))
    worse = invoice(vendor="Globex Ltd", invoice_number="INV-0000-999", total_amount="1.00")
    fake_llm.queue(worse, worse)

    result = service.ground_extraction(db_session, fake_llm, document_id)

    assert result.data.vendor == "Globex Ltd"
    assert result.data.invoice_number == "INV-2025-001"
    assert result.grounding is not None and result.grounding.kept_attempt == 1


def test_schema_retries_already_spent_leave_one_grounding_retry(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = extracted(
        db_session, fake_llm, make_document, '{"not": "an invoice"}', invoice(vendor="Globex Ltd")
    )
    fake_llm.queue(invoice(vendor="Globex Ltd"))

    result = service.ground_extraction(db_session, fake_llm, document_id)

    assert result.attempts == EXTRACTION_BUDGET
    assert result.grounding is not None
    assert [(a.attempt, a.reason, a.valid) for a in result.grounding.attempts] == [
        (1, "initial", False),
        (2, "schema", True),
        (3, "grounding", True),
    ]
    assert fake_llm.replies == type(fake_llm.replies)()  # nothing else was asked


def test_an_invalid_or_refused_retry_is_discarded_and_counts(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = extracted(db_session, fake_llm, make_document, invoice(vendor="Globex Ltd"))
    refusal = LLMResponse(content=None, usage=TokenUsage(), model="fake-model", refusal="no")
    fake_llm.queue('{"broken": true}', refusal)

    result = service.ground_extraction(db_session, fake_llm, document_id)

    assert result.data.vendor == "Globex Ltd"
    assert result.grounding is not None
    assert [(a.reason, a.valid) for a in result.grounding.attempts] == [
        ("initial", True),
        ("grounding", False),
        ("grounding", False),
    ]
    assert result.grounding.kept_attempt == 1


def test_grounding_is_idempotent_and_reset_by_a_forced_extraction(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = extracted(db_session, fake_llm, make_document, invoice())
    first = service.ground_extraction(db_session, fake_llm, document_id)
    again = service.ground_extraction(db_session, fake_llm, document_id)
    assert again.grounding == first.grounding

    fake_llm.queue(invoice())
    service.extract_structured_data(db_session, fake_llm, document_id, force=True)
    row = crud.get_by_document(db_session, document_id)
    assert row is not None and row.grounding is None


def test_an_api_failure_during_a_retry_propagates_and_saves_nothing(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = extracted(db_session, fake_llm, make_document, invoice(vendor="Globex Ltd"))
    fake_llm.queue(LLMError("down"))

    with pytest.raises(LLMError):
        service.ground_extraction(db_session, fake_llm, document_id)
    db_session.rollback()
    row = crud.get_by_document(db_session, document_id)
    assert row is not None and row.grounding is None


def test_grounding_needs_an_extraction(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    with pytest.raises(ConflictError) as caught:
        service.ground_extraction(db_session, fake_llm, make_document())
    assert caught.value.code == "structured_data_missing"


def test_grounding_stats_sum_the_reports(
    db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    clean = extracted(db_session, fake_llm, make_document, invoice())
    service.ground_extraction(db_session, fake_llm, clean)
    retried = extracted(db_session, fake_llm, make_document, invoice(vendor="Globex Ltd"))
    fake_llm.queue(invoice())
    service.ground_extraction(db_session, fake_llm, retried)
    extracted(db_session, fake_llm, make_document, invoice())  # not grounded: not counted

    stats = service.grounding_stats(db_session)

    assert stats.extractions == 2
    assert stats.values_checked > 0 and stats.values_grounded == stats.values_checked - 2
    assert stats.grounding_retry_extractions == 1
