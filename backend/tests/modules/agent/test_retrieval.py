"""Document Agent + retrieval (PRD 0010 D3, D5, D6): vendor history, similar invoices and
indexing at the end of the run."""

import json
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import LLMError
from app.core.llm import FakeLLM
from app.modules.agent.model import AgentRun
from app.modules.agent.schema import RunStatus, RunTrigger
from app.modules.documents import service as documents_service
from app.modules.observability.model import LlmCall
from app.modules.retrieval import crud as retrieval_crud
from tests.modules.agent.conftest import (
    SUMMARY,
    MakeDocument,
    happy_script,
    invoice,
    tool_turn,
    unknown_document,
)

RunAgent = Callable[..., None]
DUPLICATE_SUMMARY = f"{SUMMARY} Its invoice number INV-2025-001 was already used."


def _run(db: Session, document_id: uuid.UUID) -> AgentRun:
    db.expire_all()
    return db.execute(
        select(AgentRun)
        .where(AgentRun.document_id == document_id)
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    ).scalar_one()


@pytest.mark.usefixtures("llm_recorder")
def test_a_completed_run_indexes_the_document_with_the_tools_vector(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(happy_script())

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    row = retrieval_crud.get_by_document(db_session, document_id)
    assert row is not None and row.run_id == run.id and row.embedding is not None
    assert row.vendor_name_key == "acme supplies" and row.invoice_number_key == "INV2025001"
    assert row.needs_review is False
    assert len(fake.embed_calls) == 1 and fake.embed_calls[0] == [row.card]
    embeddings = (
        db_session.execute(select(LlmCall).where(LlmCall.kind == "embedding")).scalars().all()
    )
    assert [(e.purpose, e.run_id, e.step_index) for e in embeddings] == [("embedding", run.id, 6)]
    history, similar = run.steps[5], run.steps[6]
    assert history["tool"] == "check_vendor_history" and history["result"]["earlier_invoices"] == 0
    assert [i["code"] for i in history["result"]["issues"]] == ["new_vendor"]
    assert similar["result"] == {"available": True, "reused_embedding": False, "items": []}
    assert [i["code"] for i in run.result["validation"]["issues"]][-1] == "new_vendor"


def test_the_same_invoice_again_is_a_duplicate_and_the_summary_must_say_so(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    run_agent(make_document(), FakeLLM(happy_script()))
    second = make_document()
    # The first summary misses the warning: one retry, then the fixed summary.
    fake = FakeLLM([*happy_script(), DUPLICATE_SUMMARY])

    run_agent(second, fake)

    run = _run(db_session, second)
    assert run.status == RunStatus.COMPLETED
    validation = run.result["validation"]
    assert validation["status"] == "warn"
    assert [i["code"] for i in validation["issues"]][-1] == "duplicate_invoice_number"
    assert run.summary == DUPLICATE_SUMMARY
    summary_input = json.loads(fake.calls[-2].messages[1]["content"])
    assert [s["invoice_number"] for s in summary_input["similar_invoices"]] == ["INV-2025-001"]
    assert run.result["confidence"]["components"]["validation"] == 0.7
    similar = next(s for s in run.steps if s["tool"] == "search_similar_invoices")
    assert similar["result"]["items"][0]["similarity"] == pytest.approx(1.0)


def test_skipping_the_history_check_or_the_similar_search_is_refused_and_recovered(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    script = [
        tool_turn("extract_text"),
        tool_turn("extract_tables"),
        tool_turn("extract_structured_data"),
        invoice(),
        tool_turn("check_grounding"),
        tool_turn("validate_invoice"),
        tool_turn("generate_summary"),
        tool_turn("search_similar_invoices"),
        tool_turn("check_vendor_history"),
        tool_turn("generate_summary"),
        tool_turn("search_similar_invoices"),
        tool_turn("generate_summary"),
        SUMMARY,
    ]

    run_agent(document_id, FakeLLM(script))

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    errors = [s["error"]["code"] for s in run.steps if s["error"]]
    assert errors == ["history_check_required", "history_check_required", "similar_search_required"]


def test_an_embedding_failure_still_completes_and_indexes_without_a_vector(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(happy_script(), max_retries=0)
    fake.embed_error = LLMError("down", code="llm_unavailable")

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    similar = next(s for s in run.steps if s["tool"] == "search_similar_invoices")
    assert similar["result"]["available"] is False
    row = retrieval_crud.get_by_document(db_session, document_id)
    assert row is not None and row.embedding is None and row.embedding_model is None


def test_a_reprocess_with_the_same_card_reuses_the_vector(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM(happy_script()))
    documents_service.restart_processing(db_session, document_id)
    db_session.commit()
    fake = FakeLLM(happy_script())

    run_agent(document_id, fake, trigger=RunTrigger.REPROCESS, force=True)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    assert fake.embed_calls == []
    row = retrieval_crud.get_by_document(db_session, document_id)
    assert row is not None and row.run_id == run.id and row.embedding is not None
    # Its own earlier version is not history: still a first-time vendor, no duplicate.
    assert [i["code"] for i in run.result["validation"]["issues"]][-1] == "new_vendor"


def test_an_unknown_document_is_not_indexed(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(happy_script(unknown_document())[:-1])

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    assert retrieval_crud.get_by_document(db_session, document_id) is None
    assert fake.embed_calls == []
    history = next(s for s in run.steps if s["tool"] == "check_vendor_history")
    assert history["result"]["skipped"] is True


def test_an_indexing_failure_never_fails_the_run(
    db_session: Session,
    make_document: MakeDocument,
    run_agent: RunAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.retrieval import service as retrieval_service

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(retrieval_service, "index_document", broken)
    document_id = make_document()

    run_agent(document_id, FakeLLM(happy_script()))

    assert _run(db_session, document_id).status == RunStatus.COMPLETED
    assert documents_service.get_document(db_session, document_id).status == "completed"
    assert retrieval_crud.get_by_document(db_session, document_id) is None
