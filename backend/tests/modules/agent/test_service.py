"""Document Agent runs end to end on real Postgres with a scripted FakeLLM."""

import ast
import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.modules.agent as agent_module
import app.modules.documents as documents_module
from app.core.config import get_settings
from app.core.errors import ConflictError, LLMError, NotFoundError
from app.core.llm import FakeLLM
from app.modules.agent import crud, prompts, service, tools
from app.modules.agent.model import AgentRun
from app.modules.agent.schema import AgentMode, RunStatus, RunTrigger, StepStatus
from app.modules.documents import service as documents_service
from app.modules.documents.schema import DocumentStatus
from app.modules.text_extraction import service as text_extraction_service
from app.modules.text_extraction.service import TextExtractionError
from tests.modules.agent.conftest import (
    SUMMARY,
    MakeDocument,
    happy_script,
    invoice,
    text_turn,
    tool_turn,
    unknown_document,
)
from tests.modules.text_extraction import samples

RunAgent = Callable[..., None]


def _runs(db_session: Session, document_id: uuid.UUID) -> list[AgentRun]:
    db_session.expire_all()
    return list(
        db_session.execute(
            select(AgentRun)
            .where(AgentRun.document_id == document_id)
            .order_by(AgentRun.started_at)
        ).scalars()
    )


def _document(db_session: Session, document_id: uuid.UUID) -> Any:
    db_session.expire_all()
    return documents_service.get_document(db_session, document_id)


# -- Happy path -----------------------------------------------------------------------


def test_a_scripted_run_completes_the_run_and_the_document(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(happy_script())

    run_agent(document_id, fake)

    assert not fake.replies
    assert _document(db_session, document_id).status == DocumentStatus.COMPLETED
    (run,) = _runs(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    assert (run.mode, run.trigger) == ("single", "upload")
    assert run.model == "fake-model"
    assert run.agent_prompt_version == prompts.AGENT_PROMPT_VERSION
    assert run.summary_prompt_version == prompts.SUMMARY_PROMPT_VERSION
    assert run.summary == SUMMARY
    assert run.error_code is None and run.finished_at is not None
    # 4 agent turns + 1 summary call; the structured-extraction call is counted on its own row
    assert (run.prompt_tokens, run.completion_tokens) == (50, 25)
    assert run.result == {
        "document_id": str(document_id),
        "structured_data": invoice().model_dump(mode="json"),
        "validation": run.result["validation"],
        "conversion": None,
        "summary": SUMMARY,
    }
    assert run.result["validation"]["status"] == "pass"


def test_every_tool_call_is_recorded_without_raw_text(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM(happy_script()))

    (run,) = _runs(db_session, document_id)
    assert [step["tool"] for step in run.steps] == [
        "extract_text",
        "extract_structured_data",
        "validate_invoice",
        "generate_summary",
    ]
    for index, step in enumerate(run.steps):
        assert step["index"] == index
        assert step["turn"] == index + 1
        assert step["status"] == StepStatus.OK
        assert step["arguments"] == {}
        assert step["error"] is None
        assert step["duration_ms"] >= 0
        assert step["started_at"]
    assert set(run.steps[0]["result"]) == {"method", "page_count", "characters"}
    assert run.steps[3]["result"] == {"summary": SUMMARY}
    stored = json.dumps(run.steps)
    assert all(line not in stored for line in samples.INVOICE_LINES)


def test_the_agent_gets_its_prompts_tools_and_no_document_text(
    make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(happy_script())

    run_agent(document_id, fake)

    agent_calls = [call for call in fake.calls if call.tools]
    assert len(agent_calls) == 4
    first = agent_calls[0]
    assert first.temperature == 0
    assert first.messages == [
        {"role": "system", "content": prompts.agent_system_prompt("MYR")},
        {
            "role": "user",
            "content": prompts.agent_user_prompt(str(document_id), "application/pdf"),
        },
    ]
    sent = json.dumps([call.messages for call in agent_calls])
    assert all(line not in sent for line in samples.INVOICE_LINES)


def test_multi_mode_logs_the_b4_warning_and_runs_single(
    db_session: Session,
    make_document: MakeDocument,
    run_agent: RunAgent,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(get_settings(), "agent_mode", "multi")
    document_id = make_document()

    with caplog.at_level(logging.WARNING, logger="app.modules.agent.service"):
        run_agent(document_id, FakeLLM(happy_script()))

    assert any("not available until B4" in r.getMessage() for r in caplog.records)
    assert _runs(db_session, document_id)[0].mode == AgentMode.SINGLE


def test_single_mode_logs_no_b4_warning(
    make_document: MakeDocument, run_agent: RunAgent, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.modules.agent.service"):
        run_agent(make_document(), FakeLLM(happy_script()))

    assert not any("B4" in r.getMessage() for r in caplog.records)


# -- The model's choices ----------------------------------------------------------------


def test_a_summary_before_validation_is_refused_and_the_run_recovers(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(
        [
            tool_turn("extract_text"),
            tool_turn("extract_structured_data"),
            invoice(),
            tool_turn("generate_summary"),
            tool_turn("validate_invoice"),
            tool_turn("generate_summary"),
            SUMMARY,
        ]
    )

    run_agent(document_id, fake)

    (run,) = _runs(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    refused = run.steps[2]
    assert (refused["tool"], refused["status"]) == ("generate_summary", "error")
    assert refused["error"]["code"] == "validation_required"
    assert [step["tool"] for step in run.steps[3:]] == ["validate_invoice", "generate_summary"]


def test_a_foreign_currency_total_is_converted_into_the_result(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(
        [
            tool_turn("extract_text"),
            tool_turn("extract_structured_data"),
            invoice(currency="USD"),
            tool_turn("validate_invoice"),
            tool_turn(("convert_currency", {"to_currency": "MYR"})),
            tool_turn("generate_summary"),
            SUMMARY,
        ]
    )

    run_agent(document_id, fake)

    (run,) = _runs(db_session, document_id)
    assert run.status == RunStatus.COMPLETED
    conversion = run.result["conversion"]
    assert (conversion["from_currency"], conversion["to_currency"]) == ("USD", "MYR")
    summary_input = json.loads(fake.calls[-1].messages[1]["content"])
    assert summary_input["conversion"] == conversion


def test_an_unknown_document_completes_with_the_fixed_summary(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(happy_script(unknown_document())[:-1])  # no summary LLM reply

    run_agent(document_id, fake)

    assert _document(db_session, document_id).status == DocumentStatus.COMPLETED
    (run,) = _runs(db_session, document_id)
    assert run.summary == prompts.UNKNOWN_SUMMARY
    assert [i["code"] for i in run.result["validation"]["issues"]] == ["not_financial_document"]


# -- Failures ---------------------------------------------------------------------------


def test_a_fatal_tool_error_fails_the_run_and_the_document_at_once(
    db_session: Session,
    make_document: MakeDocument,
    run_agent: RunAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_text(*_args: Any, **_kwargs: Any) -> Any:
        raise TextExtractionError("No readable text was found.", code="no_text_found")

    monkeypatch.setattr(tools.text_extraction_service, "extract_text", no_text)
    document_id = make_document()
    fake = FakeLLM([tool_turn("extract_text"), tool_turn("extract_text")])

    run_agent(document_id, fake)

    assert len(fake.calls) == 1  # aborted: no second turn
    document = _document(db_session, document_id)
    assert document.status == DocumentStatus.FAILED
    assert document.error == "no_text_found: No readable text was found."
    (run,) = _runs(db_session, document_id)
    assert (run.status, run.error_code) == (RunStatus.FAILED, "no_text_found")
    assert run.result is None and run.finished_at is not None
    assert run.steps[0]["error"]["code"] == "no_text_found"
    assert (run.prompt_tokens, run.completion_tokens) == (10, 5)


def test_a_structured_extraction_llm_failure_is_fatal(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    fake = FakeLLM(
        [tool_turn("extract_text"), tool_turn("extract_structured_data"), LLMError("down")]
    )

    run_agent(document_id, fake)

    document = _document(db_session, document_id)
    assert document.status == DocumentStatus.FAILED
    assert document.error == "llm_error: down"
    # The text saved before the failure stays saved (partial results, PRD D8).
    assert text_extraction_service.find_text(db_session, document_id) is not None


@pytest.mark.parametrize(
    ("script", "code"),
    [
        ([text_turn("I am done.")], "agent_incomplete"),
        ([LLMError("OpenAI is down")], "llm_error"),
        ([tool_turn("extract_text"), tool_turn("extract_text")], "agent_max_steps"),
    ],
)
def test_loop_failures_fail_the_run(
    db_session: Session,
    make_document: MakeDocument,
    run_agent: RunAgent,
    monkeypatch: pytest.MonkeyPatch,
    script: list[Any],
    code: str,
) -> None:
    monkeypatch.setattr(get_settings(), "agent_max_steps", 2)
    document_id = make_document()

    run_agent(document_id, FakeLLM(script))

    document = _document(db_session, document_id)
    assert document.status == DocumentStatus.FAILED
    assert document.error.startswith(f"{code}: ")
    assert _runs(db_session, document_id)[0].error_code == code


def test_a_stale_running_run_is_closed_before_a_new_one_starts(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    crud.create_run(
        db_session,
        document_id=document_id,
        mode="single",
        trigger="upload",
        model=None,
        agent_prompt_version="v",
        summary_prompt_version="v",
    )
    db_session.commit()

    run_agent(document_id, FakeLLM(happy_script()))

    stale, fresh = _runs(db_session, document_id)
    assert (stale.status, stale.error_code) == (RunStatus.FAILED, "run_abandoned")
    assert fresh.status == RunStatus.COMPLETED


# -- Reprocess ----------------------------------------------------------------------------


def test_reprocess_forces_both_extractions_and_adds_a_run(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM(happy_script()))

    response = service.start_reprocess(db_session, document_id)
    assert (response.document_id, response.status) == (document_id, DocumentStatus.PROCESSING)
    assert _document(db_session, document_id).error is None

    fake = FakeLLM(happy_script(invoice(invoice_number="INV-2025-002")))
    run_agent(document_id, fake, trigger=RunTrigger.REPROCESS, force=True)

    assert not fake.replies  # the structured extraction really ran again (forced)
    first, second = _runs(db_session, document_id)
    assert first.trigger == "upload"
    assert second.trigger == "reprocess"
    assert second.status == RunStatus.COMPLETED
    assert service.get_result(db_session, document_id).structured_data.invoice_number == (
        "INV-2025-002"
    )


def test_reprocess_is_refused_while_processing(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document()

    with pytest.raises(ConflictError) as caught:
        service.start_reprocess(db_session, document_id)

    assert caught.value.code == "already_processing"


def test_reprocess_of_an_unknown_document_is_404(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        service.start_reprocess(db_session, uuid.uuid4())


def test_a_failed_document_can_be_reprocessed(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM([text_turn("no")]))
    assert _document(db_session, document_id).status == DocumentStatus.FAILED

    service.start_reprocess(db_session, document_id)
    run_agent(document_id, FakeLLM(happy_script()), trigger=RunTrigger.REPROCESS, force=True)

    assert _document(db_session, document_id).status == DocumentStatus.COMPLETED
    assert service.get_result(db_session, document_id).summary == SUMMARY


# -- Reads ----------------------------------------------------------------------------------


def test_get_result_while_processing_is_result_not_ready(
    db_session: Session, make_document: MakeDocument
) -> None:
    with pytest.raises(ConflictError) as caught:
        service.get_result(db_session, make_document())

    assert caught.value.code == "result_not_ready"


def test_get_result_of_a_failed_document_explains_why(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM([text_turn("no")]))

    with pytest.raises(ConflictError) as caught:
        service.get_result(db_session, document_id)

    assert caught.value.code == "result_unavailable"
    assert "agent_incomplete" in caught.value.message


def test_get_result_and_list_runs_of_an_unknown_document_are_404(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        service.get_result(db_session, uuid.uuid4())
    with pytest.raises(NotFoundError):
        service.list_runs(db_session, uuid.uuid4())


def test_list_runs_is_newest_first(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM([text_turn("no")]))
    service.start_reprocess(db_session, document_id)
    run_agent(document_id, FakeLLM(happy_script()), trigger=RunTrigger.REPROCESS, force=True)

    runs = service.list_runs(db_session, document_id)

    assert [run.trigger for run in runs] == ["reprocess", "upload"]
    assert [run.status for run in runs] == [RunStatus.COMPLETED, RunStatus.FAILED]
    assert len(runs[0].steps) == 4


# -- Layering -------------------------------------------------------------------------------


def _module_imports(package: Any) -> list[tuple[str, str]]:
    found = []
    for path in Path(package.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found += [(path.name, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((path.name, node.module))
                found += [(path.name, f"{node.module}.{alias.name}") for alias in node.names]
    return found


def test_agent_imports_no_other_modules_crud_or_model() -> None:
    offenders = [
        f"{file}: {name}"
        for file, name in _module_imports(agent_module)
        if name.startswith("app.modules.")
        and not name.startswith("app.modules.agent")
        and name.rsplit(".", 1)[-1] in {"crud", "model"}
    ]
    assert offenders == []


def test_documents_does_not_import_the_agent() -> None:
    offenders = [
        f"{file}: {name}"
        for file, name in _module_imports(documents_module)
        if name.startswith("app.modules.agent")
    ]
    assert offenders == []
