"""Query Agent (PRD 0010 D8): answers, memory, citations, number checks, failures, routes."""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import LLMError, NotFoundError
from app.core.llm import FakeLLM
from app.core.storage import LocalStorage
from app.modules.agent import prompts, service
from app.modules.agent.model import QueryRun
from app.modules.agent.query import QueryFailedError
from app.modules.agent.schema import QueryRequest, RunStatus
from app.modules.observability.model import LlmCall
from tests.modules.agent.conftest import tool_turn
from tests.modules.retrieval.seed import seed_invoice

SEARCH_KEYS = (
    "text",
    "vendor",
    "invoice_number",
    "date_from",
    "date_to",
    "currency",
    "min_total",
    "max_total",
    "document_type",
    "limit",
)


def search(**arguments: Any) -> Any:
    return tool_turn(("search_invoices", {key: arguments.get(key) for key in SEARCH_KEYS}))


def history(**arguments: Any) -> Any:
    keys = ("document_id", "invoice_number", "vendor", "date_from", "date_to")
    return tool_turn(("get_vendor_history", {key: arguments.get(key) for key in keys}))


def answer(text: str, cited: list[str] | None = None, answerable: bool = True) -> Any:
    return tool_turn(
        (
            "submit_answer",
            {"answer": text, "cited_document_ids": cited or [], "answerable": answerable},
        )
    )


@pytest.fixture
def invoices(db_session: Session, storage: LocalStorage) -> list[uuid.UUID]:
    return [
        seed_invoice(db_session, storage, index=1, invoice_number="A1", total_amount="100.00"),
        seed_invoice(db_session, storage, index=2, invoice_number="A2", total_amount="300.00"),
        seed_invoice(db_session, storage, index=3, vendor="Other", invoice_number="B1"),
    ]


def _ask(db: Session, fake: FakeLLM, question: str = "How much did we pay ABC?", **kw: Any) -> Any:
    return service.ask(db, fake, QueryRequest(question=question, **kw))


@pytest.mark.usefixtures("llm_recorder")
def test_a_question_is_answered_with_citations_and_verified_numbers(
    db_session: Session, invoices: list[uuid.UUID]
) -> None:
    first, second, _ = (str(i) for i in invoices)
    fake = FakeLLM(
        [
            search(vendor="ABC Supplies"),
            answer("ABC Supplies billed MYR 400.00 over 2 invoices.", [second, first]),
        ]
    )

    response = _ask(db_session, fake)

    assert response.status is RunStatus.COMPLETED and response.turn == 1
    assert response.answer == "ABC Supplies billed MYR 400.00 over 2 invoices."
    assert response.answerable is True and response.numbers_verified is True
    assert [str(c.document_id) for c in response.citations] == [second, first]
    assert response.citations[0].invoice_number == "A2"
    assert [s.tool for s in response.steps] == ["search_invoices", "submit_answer"]
    assert response.usage.prompt_tokens == 20
    assert all(call.tool_choice == "required" for call in fake.calls)
    search_result = response.steps[0].result
    assert search_result is not None and search_result["totals"]["sum"] == "400.00"

    rows = db_session.execute(select(LlmCall)).scalars().all()
    assert {(r.agent, r.purpose, r.query_run_id) for r in rows} == {
        ("query", "agent_loop", response.turn_id)
    }
    assert all(r.document_id is None and r.run_id is None for r in rows)
    assert rows[0].prompt_version == prompts.QUERY_PROMPT_VERSION


def test_a_follow_up_sees_earlier_turns_and_a_new_chat_does_not(
    db_session: Session, invoices: list[uuid.UUID]
) -> None:
    first = _ask(db_session, FakeLLM([answer("There are 3 invoices.")]), "How many invoices?")
    fake = FakeLLM([answer("Still 3.")])

    second = _ask(db_session, fake, "And now?", conversation_id=first.conversation_id)

    assert second.conversation_id == first.conversation_id and second.turn == 2
    messages = fake.calls[0].messages
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "How many invoices?"
    assert messages[2]["content"].startswith("There are 3 invoices.\n[Cited documents: none]")
    fresh = FakeLLM([answer("Hello.")])
    _ask(db_session, fresh, "Hi there")
    assert [m["role"] for m in fresh.calls[0].messages] == ["system", "user"]


def test_memory_keeps_the_last_ten_completed_turns(db_session: Session) -> None:
    conversation = None
    for n in range(12):
        response = _ask(
            db_session,
            FakeLLM([answer(f"Answer {n}.")]),
            f"Question {n}?",
            conversation_id=conversation,
        )
        conversation = response.conversation_id
    fake = FakeLLM([answer("Done.")])
    _ask(db_session, fake, "Last one?", conversation_id=conversation)
    questions = [m["content"] for m in fake.calls[0].messages if m["role"] == "user"]
    assert questions == [f"Question {n}?" for n in range(2, 12)] + ["Last one?"]


def test_citations_keep_only_documents_the_tools_returned_in_this_chat(
    db_session: Session, invoices: list[uuid.UUID]
) -> None:
    first, _, other = (str(i) for i in invoices)
    turn1 = _ask(db_session, FakeLLM([search(invoice_number="A1"), answer("Found A1.", [first])]))
    fake = FakeLLM([answer("A1 and B1.", [first, other, str(uuid.uuid4()), first])])

    turn2 = _ask(db_session, fake, "Which ones?", conversation_id=turn1.conversation_id)

    # ``first`` was seen in turn 1; ``other`` and the random ID were never returned.
    assert [str(c.document_id) for c in turn2.citations] == [first]


def test_numbers_not_in_tool_results_get_one_retry_then_are_flagged(
    db_session: Session, invoices: list[uuid.UUID]
) -> None:
    fake = FakeLLM(
        [
            search(vendor="ABC Supplies"),
            answer("They billed about MYR 450.00."),
            answer("They billed about MYR 450.00."),
        ]
    )

    response = _ask(db_session, fake)

    assert response.numbers_verified is False
    assert response.answer == "They billed about MYR 450.00."
    retry = response.steps[1]
    assert retry.error is not None and retry.error.code == "numbers_not_found"
    assert "450" in retry.error.message


def test_a_corrected_answer_after_the_retry_is_verified(
    db_session: Session, invoices: list[uuid.UUID]
) -> None:
    fake = FakeLLM(
        [
            search(vendor="ABC Supplies"),
            answer("Roughly 450."),
            answer("They billed MYR 400.00 in total."),
        ]
    )
    assert _ask(db_session, fake).numbers_verified is True


def test_an_off_topic_question_gets_the_fixed_refusal(db_session: Session) -> None:
    fake = FakeLLM([answer("Paris.", answerable=False)])

    response = _ask(db_session, fake, "What is the capital of France?")

    assert response.answerable is False
    assert response.answer == prompts.QUERY_REFUSAL and response.citations == []


def test_the_context_document_is_given_to_the_agent_and_can_be_compared(
    db_session: Session, invoices: list[uuid.UUID]
) -> None:
    second = invoices[1]
    fake = FakeLLM(
        [
            history(document_id=str(second)),
            answer("A2 is MYR 300.00, MYR 200.00 above the median of the others.", [str(second)]),
        ]
    )

    response = _ask(db_session, fake, "Compare this invoice", document_id=second)

    context = fake.calls[0].messages[1]
    assert context["role"] == "system" and '"invoice_number": "A2"' in context["content"]
    target = response.steps[0].result["target"]  # type: ignore[index]
    assert target["diff_vs_median"] == "200.00" and target["rank"] == 1
    assert response.numbers_verified is True
    assert [str(c.document_id) for c in response.citations] == [str(second)]
    stored = db_session.get(QueryRun, response.turn_id)
    assert stored is not None and stored.document_id == second


def test_an_unknown_vendor_is_a_recoverable_tool_error_with_candidates(
    db_session: Session, invoices: list[uuid.UUID]
) -> None:
    fake = FakeLLM([history(vendor="ABC Supply Co"), answer("I could not find that vendor.")])
    response = _ask(db_session, fake)
    error = response.steps[0].error
    assert error is not None and error.code == "vendor_not_found"
    assert "ABC Supplies Sdn Bhd" in error.message


def test_the_step_limit_fails_the_turn_and_keeps_the_row(db_session: Session) -> None:
    fake = FakeLLM([search(text=None)] * 6)

    with pytest.raises(QueryFailedError) as caught:
        _ask(db_session, fake)

    assert caught.value.status_code == 502 and "agent_max_steps" in caught.value.message
    run = db_session.execute(select(QueryRun)).scalar_one()
    assert run.status == RunStatus.FAILED and run.error_code == "agent_max_steps"
    assert len(run.steps) == 6


def test_an_llm_error_fails_the_turn_with_its_code(db_session: Session) -> None:
    with pytest.raises(LLMError) as caught:
        _ask(db_session, FakeLLM([LLMError("down", code="llm_error")]))
    assert caught.value.code == "llm_error"
    run = db_session.execute(select(QueryRun)).scalar_one()
    assert run.status == RunStatus.FAILED


def test_unknown_conversation_and_document_are_404(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        _ask(db_session, FakeLLM(), conversation_id=uuid.uuid4())
    with pytest.raises(NotFoundError):
        _ask(db_session, FakeLLM(), document_id=uuid.uuid4())
    assert db_session.execute(select(QueryRun)).first() is None


def test_suggestions_come_from_the_index(db_session: Session, storage: LocalStorage) -> None:
    empty = service.query_suggestions(db_session)
    assert empty.indexed_documents == 0 and len(empty.questions) == 3
    document_id = seed_invoice(db_session, storage, index=1)
    seed_invoice(db_session, storage, index=2, vendor="Other Shop", invoice_number="Z")
    seed_invoice(db_session, storage, index=3, invoice_number="Y")
    result = service.query_suggestions(db_session, document_id)
    assert result.indexed_documents == 3
    assert result.questions[:3] == [
        "Compare this invoice with previous ABC Supplies Sdn Bhd invoices",
        "How much have we spent with ABC Supplies Sdn Bhd in total?",
        "Show the latest invoices from Other Shop",
    ]


def test_metrics_helpers_count_questions_and_flags(
    db_session: Session, invoices: list[uuid.UUID]
) -> None:
    _ask(db_session, FakeLLM([answer("Paris.", answerable=False)]), "Capital of France?")
    with pytest.raises(QueryFailedError):
        _ask(db_session, FakeLLM([search()] * 6))
    stats = service.query_stats(db_session)
    assert (stats.conversations, stats.questions, stats.questions_failed) == (2, 2, 1)
    assert stats.questions_unanswerable == 1 and stats.avg_question_ms is not None


# -- Routes ------------------------------------------------------------------------------


def test_post_query_and_get_conversation(
    client: TestClient, fake_llm: FakeLLM, invoices: list[uuid.UUID]
) -> None:
    fake_llm.queue(search(vendor="Other"), answer("Other has 1 invoice.", [str(invoices[2])]))

    response = client.post("/api/query", json={"question": "  What about Other?  "})

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "What about Other?" and body["status"] == "completed"
    assert body["citations"][0]["invoice_number"] == "B1"
    assert body["citations"][0]["total_amount"] == "1000.00"
    conversation = client.get(f"/api/conversations/{body['conversation_id']}")
    assert conversation.status_code == 200
    assert [t["answer"] for t in conversation.json()["turns"]] == ["Other has 1 invoice."]
    assert client.get(f"/api/conversations/{uuid.uuid4()}").status_code == 404


@pytest.mark.parametrize("question", ["", "  a ", "x" * 501])
def test_post_query_validates_the_question(client: TestClient, question: str) -> None:
    response = client.post("/api/query", json={"question": question})
    assert response.status_code == 422


def test_post_query_reports_a_failed_turn_as_502(client: TestClient, fake_llm: FakeLLM) -> None:
    fake_llm.queue(*[search()] * 6)
    response = client.post("/api/query", json={"question": "Loop forever"})
    assert response.status_code == 502 and response.json()["error"]["code"] == "query_failed"


def test_get_suggestions(client: TestClient, invoices: list[uuid.UUID]) -> None:
    response = client.get("/api/query/suggestions", params={"document_id": str(invoices[0])})
    assert response.status_code == 200
    assert response.json()["questions"][0].startswith("Compare this invoice")
