"""The agent's guardrails: check_grounding tool, its guard, confidence and summary (PRD 0008)."""

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.llm import FakeLLM
from app.modules.agent import prompts, service
from app.modules.agent.model import AgentRun
from app.modules.agent.schema import RunStatus
from app.modules.agent.tools import field_name, missing_review
from tests.modules.agent.conftest import (
    SUMMARY,
    MakeDocument,
    invoice,
    text_turn,
    tool_turn,
)

RunAgent = Callable[..., None]


def _run(db: Session, document_id: uuid.UUID) -> AgentRun:
    db.expire_all()
    return db.query(AgentRun).filter(AgentRun.document_id == document_id).one()


def test_validate_before_grounding_is_refused_and_the_run_recovers(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(
        [
            tool_turn("extract_text"),
            tool_turn("extract_tables"),
            tool_turn("extract_structured_data"),
            invoice(),
            tool_turn("validate_invoice"),
            tool_turn("check_grounding"),
            tool_turn("validate_invoice"),
            tool_turn("generate_summary"),
            SUMMARY,
        ]
    )

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    refused = run.steps[3]
    assert (refused["tool"], refused["status"]) == ("validate_invoice", "error")
    assert refused["error"]["code"] == "grounding_required"
    assert [s["tool"] for s in run.steps[4:]] == [
        "check_grounding",
        "validate_invoice",
        "generate_summary",
    ]


def test_a_run_that_never_grounds_cannot_complete(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(
        [
            tool_turn("extract_text"),
            tool_turn("extract_tables"),
            tool_turn("extract_structured_data"),
            invoice(),
            tool_turn("validate_invoice"),
            tool_turn("generate_summary"),
            text_turn("I am done."),
        ]
    )

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.FAILED
    assert run.result is None


def test_a_new_extraction_must_be_grounded_again(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(
        [
            tool_turn("extract_text"),
            tool_turn("extract_tables"),
            tool_turn("extract_structured_data"),
            invoice(),
            tool_turn("check_grounding"),
            tool_turn("extract_structured_data"),  # idempotent: no LLM call
            tool_turn("validate_invoice"),
            tool_turn("check_grounding"),
            tool_turn("validate_invoice"),
            tool_turn("generate_summary"),
            SUMMARY,
        ]
    )

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    assert run.steps[5]["error"]["code"] == "grounding_required"


def test_an_invented_total_is_re_extracted_and_the_run_is_confident(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(
        [
            tool_turn("extract_text"),
            tool_turn("extract_tables"),
            tool_turn("extract_structured_data"),
            invoice(total_amount="132.45"),
            tool_turn("check_grounding"),
            invoice(),  # the grounding retry copies the printed total
            tool_turn("validate_invoice"),
            tool_turn("generate_summary"),
            SUMMARY,
        ]
    )

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    grounding_step = run.steps[3]["result"]
    assert grounding_step["retries"] == 1
    assert grounding_step["ungrounded"] == 0
    assert grounding_step["changed_fields"] == ["total_amount"]
    result = service.get_result(db_session, document_id)
    assert str(result.structured_data.total_amount) == "123.45"
    assert result.confidence is not None and result.confidence.needs_review is False


def test_an_unconfirmed_vendor_needs_review_and_the_summary_says_so(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    invented = invoice(vendor="Globex Trading Company")
    document_id = make_document()
    fake = FakeLLM(
        [
            tool_turn("extract_text"),
            tool_turn("extract_tables"),
            tool_turn("extract_structured_data"),
            invented,
            tool_turn("check_grounding"),
            invented,
            invented,
            tool_turn("validate_invoice"),
            tool_turn("generate_summary"),
            SUMMARY,  # does not ask to verify the vendor -> retried
            SUMMARY,  # still not -> code appends the sentence
        ]
    )

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    assert run.needs_review is True
    assert run.overall_confidence is not None
    result = service.get_result(db_session, document_id)
    assert result.confidence is not None
    assert result.confidence.review_fields == ["vendor"]
    assert result.structured_data.vendor == "Globex Trading Company"  # flagged, not nulled
    summary_payload = fake.calls[-2].messages[1]["content"]
    assert '"review": [{"field": "vendor"' in summary_payload
    retry = fake.calls[-1].messages[-1]["content"]
    assert "verify these fields: vendor" in retry
    assert result.summary.endswith(prompts.review_sentence(["vendor"]))


def test_a_summary_that_asks_to_verify_the_field_is_accepted() -> None:
    text = "Invoice from Globex. Please verify the vendor name against the document."
    assert missing_review(text, ["vendor"]) == []
    assert missing_review("Invoice from Globex.", ["vendor"]) == ["vendor"]
    assert missing_review("Please check line 2.", ["line_items[1].amount"]) == []
    assert missing_review("Please check the total.", ["vendor", "total_amount"]) == ["vendor"]
    assert missing_review("Anything", []) == []


def test_field_names_are_readable() -> None:
    names: dict[str, Any] = {
        "total_amount": "total amount",
        "vendor_tax_id": "vendor tax id",
        "line_items[0].unit_price": "line 1 unit price",
    }
    assert {path: field_name(path) for path in names} == names
    assert prompts.review_sentence(["vendor"]) == (
        "Please verify the vendor: it could not be confirmed in the document text."
    )
    assert prompts.review_sentence(["vendor", "total amount", "currency"]) == (
        "Please verify the vendor, total amount and currency: they could not be confirmed in "
        "the document text."
    )


def test_confidence_stats_summarise_scored_runs(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    from tests.modules.agent.conftest import happy_script

    run_agent(make_document(), FakeLLM(happy_script()))
    run_agent(make_document(), FakeLLM([text_turn("no")]))  # failed: not scored

    stats = service.confidence_stats(db_session)

    assert stats.runs_scored == 1
    assert stats.avg_confidence is not None and stats.avg_confidence > 0.85
    assert stats.needs_review == 0
    assert stats.by_label == {"high": 1, "medium": 0, "low": 0}


def test_extraction_before_extract_tables_is_refused_and_the_run_recovers(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(
        [
            tool_turn("extract_text"),
            tool_turn("extract_structured_data"),  # skips extract_tables (feature 0009)
            tool_turn("extract_tables"),
            tool_turn("extract_structured_data"),
            invoice(),
            tool_turn("check_grounding"),
            tool_turn("validate_invoice"),
            tool_turn("generate_summary"),
            SUMMARY,
        ]
    )

    run_agent(document_id, fake)

    run = _run(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    refused = run.steps[1]
    assert (refused["tool"], refused["status"]) == ("extract_structured_data", "error")
    assert refused["error"]["code"] == "tables_required"
