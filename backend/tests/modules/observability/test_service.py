"""Token ledger, trace and metrics on real Postgres with a scripted FakeLLM."""

import io
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import LLMError, NotFoundError
from app.core.llm import FakeLLM, LLMCallRecord, TokenUsage
from app.core.logging import JsonFormatter, TraceLabels, bind_trace
from app.modules.agent import prompts as agent_prompts
from app.modules.agent.model import AgentRun
from app.modules.agent.schema import RunTrigger
from app.modules.documents import service as documents_service
from app.modules.observability import crud, service
from app.modules.observability.model import LlmCall
from app.modules.observability.schema import LLMSpan, ToolSpan
from app.modules.structured_extraction import prompts as extraction_prompts
from app.modules.vision import prompts as vision_prompts
from app.modules.vision.schema import PageAnalysis
from tests.modules.agent.conftest import (
    MakeDocument,
    happy_script,
    tool_turn,
)
from tests.modules.text_extraction import samples

RunAgent = Callable[..., None]

PAGE_TEXT = "\n".join(
    [
        "ACME Supplies Sdn Bhd",
        "Invoice INV-2025-001",
        "Date: 2025-03-04",
        "Widget 2 x 10.00 = 20.00",
        "Gadget 1 x 103.45 = 103.45",
        "Total: MYR 123.45",
    ]
)


def _calls(db_session: Session, document_id: uuid.UUID) -> list[LlmCall]:
    db_session.expire_all()
    return list(
        db_session.execute(
            select(LlmCall)
            .where(LlmCall.document_id == document_id)
            .order_by(LlmCall.started_at, LlmCall.id)
        ).scalars()
    )


def _run_id(db_session: Session, document_id: uuid.UUID) -> uuid.UUID:
    db_session.expire_all()
    return db_session.execute(
        select(AgentRun.id)
        .where(AgentRun.document_id == document_id)
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    ).scalar_one()


# -- Recording through a real run (PRD D1-D3, D5) ---------------------------------------


@pytest.mark.usefixtures("llm_recorder")
def test_a_run_writes_one_row_per_llm_call_with_labels_and_step_links(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()  # text-layer PDF: no vision call
    run_agent(document_id, FakeLLM(happy_script()))

    rows = _calls(db_session, document_id)
    run_id = _run_id(db_session, document_id)
    assert [(r.purpose, r.step_index) for r in rows] == [
        ("agent_loop", None),
        ("agent_loop", None),
        ("agent_loop", None),
        ("structured_extraction", 2),
        ("agent_loop", None),
        ("agent_loop", None),
        ("agent_loop", None),
        ("summary", 5),
    ]
    assert {r.run_id for r in rows} == {run_id}
    assert {r.agent for r in rows} == {"document"}
    assert {(r.kind, r.status, r.model) for r in rows} == {("chat", "ok", "fake-model")}
    assert all(r.prompt_tokens == 10 and r.completion_tokens == 5 for r in rows)
    assert all(r.latency_ms >= 0 and r.error_code is None for r in rows)
    assert all(r.cost_usd is None for r in rows)  # "fake-model" is not in the price table
    versions = {r.purpose: r.prompt_version for r in rows}
    assert versions == {
        "agent_loop": agent_prompts.AGENT_PROMPT_VERSION,
        "structured_extraction": extraction_prompts.PROMPT_VERSION,
        "summary": agent_prompts.SUMMARY_PROMPT_VERSION,
    }


@pytest.mark.usefixtures("llm_recorder")
def test_vision_calls_are_recorded_inside_the_extract_text_step(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document(samples.png_invoice(), "image/png")
    script = happy_script()
    script.insert(1, PageAnalysis(tables=[], blocks=[], text=PAGE_TEXT, legible=True))
    run_agent(document_id, FakeLLM(script))

    vision = [r for r in _calls(db_session, document_id) if r.purpose == "vision_transcription"]
    assert len(vision) == 1
    assert vision[0].step_index == 0
    assert vision[0].prompt_version == vision_prompts.PROMPT_VERSION


@pytest.mark.usefixtures("llm_recorder")
def test_a_failed_run_keeps_its_ledger_rows_including_the_failed_call(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM([tool_turn("extract_text"), LLMError("rate limited")]))

    rows = _calls(db_session, document_id)
    assert [(r.purpose, r.status, r.error_code) for r in rows] == [
        ("agent_loop", "ok", None),
        ("agent_loop", "error", "llm_error"),
    ]
    assert rows[1].prompt_tokens == rows[1].completion_tokens == 0
    assert documents_service.get_document(db_session, document_id).status == "failed"


def _record(
    *,
    model: str = "gpt-4.1-mini",
    usage: TokenUsage | None = None,
    document_id: uuid.UUID | str | None = None,
    run_id: uuid.UUID | str | None = None,
    purpose: str = "summary",
    status: str = "ok",
    started_at: datetime | None = None,
    latency_ms: int = 20,
) -> LLMCallRecord:
    return LLMCallRecord(
        kind="chat",
        model=model,
        usage=usage or TokenUsage(prompt_tokens=100, completion_tokens=50),
        latency_ms=latency_ms,
        status=status,  # type: ignore[arg-type]
        error_code="llm_error" if status == "error" else None,
        started_at=started_at or datetime.now(UTC),
        labels=TraceLabels(
            document_id=str(document_id) if document_id else None,
            run_id=str(run_id) if run_id else None,
            agent="document",
            purpose=purpose,
        ),
    )


def test_a_priced_model_gets_an_estimated_cost_at_write_time(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document()
    service.record_llm_call(_record(usage=TokenUsage(1_000, 500), document_id=document_id))
    service.record_llm_call(_record(model="fake-model", document_id=document_id))

    assert [r.cost_usd for r in _calls(db_session, document_id)] == [Decimal("0.001200"), None]


def test_recording_never_raises_when_the_insert_fails(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    service.record_llm_call(_record(document_id=uuid.uuid4()))  # no such document: FK fails

    assert "llm.call not recorded" in caplog.text
    assert db_session.execute(select(LlmCall)).first() is None


def test_an_invalid_id_label_is_stored_as_null(db_session: Session) -> None:
    service.record_llm_call(_record(document_id="not-a-uuid"))

    row = db_session.execute(select(LlmCall)).scalar_one()
    assert row.document_id is None and row.purpose == "summary"


def test_log_lines_during_a_run_carry_the_document_and_run_ids(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        run_agent(document_id, FakeLLM(happy_script()))
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]

    run_id = str(_run_id(db_session, document_id))
    run_lines = [line for line in lines if line.get("run_id")]
    assert {line["run_id"] for line in run_lines} == {run_id}
    assert all(line["document_id"] == str(document_id) for line in run_lines)
    calls = [line for line in lines if line["message"] == "llm.call"]
    assert len(calls) == 8
    assert all(line["run_id"] == run_id and line["agent"] == "document" for line in calls)
    assert [line["purpose"] for line in calls].count("agent_loop") == 6
    assert {line["level"] for line in calls} == {"INFO"}
    finished = next(line for line in lines if line["message"] == "agent run finished")
    assert finished["run_id"] == run_id


# -- Trace (PRD D6, D8) ----------------------------------------------------------------


@pytest.mark.usefixtures("llm_recorder")
def test_trace_of_the_latest_run_has_timing_totals_and_ordered_spans(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM(happy_script()))

    trace = service.get_trace(db_session, document_id)

    assert trace.document_id == document_id
    assert trace.llm_calls_recorded is True
    assert trace.run is not None
    assert trace.run.status == "completed"
    assert trace.run.trigger == RunTrigger.UPLOAD
    assert trace.run.queue_ms is not None and trace.run.queue_ms >= 0
    assert trace.run.processing_ms is not None and trace.run.processing_ms >= 0
    assert [(s.kind, s.tool if isinstance(s, ToolSpan) else s.purpose) for s in trace.spans] == [
        ("llm", "agent_loop"),
        ("tool", "extract_text"),
        ("llm", "agent_loop"),
        ("tool", "extract_tables"),
        ("llm", "agent_loop"),
        ("tool", "extract_structured_data"),
        ("llm", "structured_extraction"),
        ("llm", "agent_loop"),
        ("tool", "check_grounding"),
        ("llm", "agent_loop"),
        ("tool", "validate_invoice"),
        ("llm", "agent_loop"),
        ("tool", "generate_summary"),
        ("llm", "summary"),
    ]
    assert all(s.offset_ms >= 0 and s.duration_ms >= 0 for s in trace.spans)
    llm_spans = [s for s in trace.spans if isinstance(s, LLMSpan)]
    assert [s.step_index for s in llm_spans if s.purpose != "agent_loop"] == [2, 5]
    assert trace.totals.llm_calls == 8
    assert (trace.totals.prompt_tokens, trace.totals.completion_tokens) == (80, 40)
    assert trace.totals.total_tokens == 120
    assert trace.totals.cost_usd is None and trace.totals.cost_complete is False
    assert [(g.key, g.llm_calls) for g in trace.by_purpose] == [
        ("agent_loop", 6),
        ("structured_extraction", 1),
        ("summary", 1),
    ]
    assert [(g.key, g.total_tokens) for g in trace.by_agent] == [("document", 120)]


@pytest.mark.usefixtures("llm_recorder")
def test_trace_can_select_an_earlier_run_and_rejects_another_documents_run(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM([tool_turn("extract_text"), LLMError("down")]))
    first = _run_id(db_session, document_id)
    documents_service.restart_processing(db_session, document_id)
    db_session.commit()
    run_agent(document_id, FakeLLM(happy_script()), trigger=RunTrigger.REPROCESS, force=True)

    latest = service.get_trace(db_session, document_id)
    earlier = service.get_trace(db_session, document_id, first)

    assert latest.run is not None and latest.run.trigger == RunTrigger.REPROCESS
    assert latest.run.queue_ms is None  # only meaningful for uploads
    assert earlier.run is not None and earlier.run.run_id == first
    assert earlier.run.status == "failed"
    assert earlier.totals.llm_calls == 2 and earlier.totals.failed_calls == 1

    other = make_document()
    with pytest.raises(NotFoundError) as caught:
        service.get_trace(db_session, other, first)
    assert caught.value.code == "run_not_found"


def test_trace_of_a_run_without_ledger_rows_says_so(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    run_agent(document_id, FakeLLM(happy_script()))  # recorder off: like a pre-0007 run

    trace = service.get_trace(db_session, document_id)

    assert trace.llm_calls_recorded is False
    assert [s.kind for s in trace.spans] == ["tool"] * 6
    assert trace.totals.llm_calls == 0 and trace.totals.cost_usd == Decimal(0)
    assert trace.run is not None
    assert (trace.run.run_prompt_tokens, trace.run.run_completion_tokens) == (70, 35)


def test_trace_of_a_document_without_a_run_and_of_an_unknown_document(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document()

    trace = service.get_trace(db_session, document_id)
    assert trace.run is None and trace.spans == [] and trace.llm_calls_recorded is False

    with pytest.raises(NotFoundError):
        service.get_trace(db_session, uuid.uuid4())


# -- Metrics (PRD D7) ------------------------------------------------------------------

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _seed_run(
    db_session: Session,
    document_id: uuid.UUID,
    *,
    status: str,
    duration_ms: int,
    started_at: datetime,
) -> uuid.UUID:
    run = AgentRun(
        document_id=document_id,
        mode="single",
        trigger="upload",
        status=status,
        steps=[],
        agent_prompt_version="a",
        summary_prompt_version="s",
        started_at=started_at,
        finished_at=started_at + timedelta(milliseconds=duration_ms),
    )
    db_session.add(run)
    db_session.flush()
    return run.id


def _seed_call(db_session: Session, run_id: uuid.UUID, document_id: uuid.UUID, **kw: Any) -> None:
    values: dict[str, Any] = {
        "document_id": document_id,
        "run_id": run_id,
        "agent": "document",
        "purpose": "agent_loop",
        "kind": "chat",
        "model": "gpt-4.1-mini",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "cost_usd": Decimal("0.000120"),
        "latency_ms": 200,
        "status": "ok",
        "started_at": NOW - timedelta(hours=1),
    }
    crud.insert(db_session, **{**values, **kw})


def test_metrics_summary_aggregates_documents_runs_and_the_ledger(
    db_session: Session, make_document: MakeDocument
) -> None:
    started = NOW - timedelta(hours=2)
    completed = []
    for duration in (1_000, 2_000, 3_000, 4_000):
        document_id = make_document()
        documents_service.mark_completed(db_session, document_id)
        run_id = _seed_run(
            db_session, document_id, status="completed", duration_ms=duration, started_at=started
        )
        completed.append((run_id, document_id))
    failed_doc = make_document()
    documents_service.mark_failed(db_session, failed_doc, "llm_error: down")
    failed_run = _seed_run(
        db_session, failed_doc, status="failed", duration_ms=500, started_at=started
    )
    make_document()  # still processing
    run_id, document_id = completed[0]
    _seed_call(db_session, run_id, document_id)
    _seed_call(db_session, run_id, document_id, purpose="summary", latency_ms=400)
    run_id, document_id = completed[1]
    _seed_call(db_session, run_id, document_id, model="fake-model", cost_usd=None)
    _seed_call(
        db_session,
        failed_run,
        failed_doc,
        status="error",
        error_code="llm_error",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=None,
    )
    db_session.commit()

    summary = service.get_metrics(db_session, now=NOW)

    assert summary.window_days is None and summary.since is None
    docs = summary.documents
    assert (docs.total, docs.processing, docs.completed, docs.failed) == (6, 1, 4, 1)
    assert docs.success_rate == pytest.approx(0.8)
    runs = summary.runs
    assert (runs.total, runs.completed, runs.failed) == (5, 4, 1)
    assert (runs.avg_ms, runs.p50_ms, runs.p95_ms) == (2_500, 2_500, 3_850)
    llm = summary.llm
    assert (llm.llm_calls, llm.failed_calls) == (4, 1)
    assert llm.error_rate == pytest.approx(0.25)
    assert llm.total_tokens == 450
    assert llm.cost_usd == Decimal("0.000240") and llm.cost_complete is False
    assert llm.documents_with_usage == 2  # completed runs with ledger rows
    assert llm.avg_tokens_per_document == 225  # (300 + 150) / 2
    assert llm.avg_cost_per_document == Decimal("0.000120")  # (0.00024 + 0) / 2
    assert [(g.key, g.llm_calls) for g in summary.by_model] == [
        ("gpt-4.1-mini", 3),  # 300 tokens (incl. the failed call)
        ("fake-model", 1),  # 150 tokens
    ]
    by_purpose = {g.key: g for g in summary.by_purpose}
    assert by_purpose["agent_loop"].llm_calls == 3
    assert by_purpose["summary"].avg_latency_ms == 400
    assert summary.ledger_since == NOW - timedelta(hours=1)


def test_metrics_window_leaves_out_older_rows(
    db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document()
    old_run = _seed_run(
        db_session,
        document_id,
        status="completed",
        duration_ms=9_000,
        started_at=NOW - timedelta(days=10),
    )
    _seed_call(db_session, old_run, document_id, started_at=NOW - timedelta(days=10))
    db_session.commit()

    summary = service.get_metrics(db_session, days=7, now=NOW)

    assert summary.window_days == 7
    assert summary.since == NOW - timedelta(days=7)
    assert summary.runs.total == 0 and summary.runs.p95_ms is None
    assert summary.llm.llm_calls == 0 and summary.llm.cost_usd == Decimal(0)
    assert summary.llm.error_rate is None and summary.llm.avg_tokens_per_document is None
    assert summary.by_model == []


def test_metrics_with_no_data_at_all(db_session: Session) -> None:
    summary = service.get_metrics(db_session)

    assert summary.documents.total == 0 and summary.documents.success_rate is None
    assert summary.runs.avg_ms is None
    assert summary.ledger_since is None
    assert summary.guardrails.runs_scored == 0
    assert summary.guardrails.avg_confidence is None
    assert summary.guardrails.needs_review_rate is None
    assert summary.guardrails.grounding_rate is None
    assert summary.guardrails.transient_retries == 0
    assert summary.vision.layouts_analysed == 0
    assert summary.vision.line_items_table_share is None
    assert summary.vision.pages_via_vision == summary.vision.multimodal_calls == 0


# -- Vision metrics (feature 0009) --------------------------------------------------------


@pytest.mark.usefixtures("llm_recorder")
def test_metrics_vision_block_counts_tables_line_item_sources_and_vision_calls(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    from tests.modules.vision import samples as vision_samples

    # A text PDF with a line-item table (3 items copied by code) ...
    run_agent(make_document(vision_samples.invoice_pdf()), FakeLLM(happy_script()))
    # ... and one without a table (the model's 2 items).
    run_agent(make_document(), FakeLLM(happy_script()))
    # Vision ledger rows: two pages and one multimodal call.
    for purpose in ("vision_transcription", "vision_transcription", "multimodal_extraction"):
        with bind_trace(purpose=purpose):
            FakeLLM(["{}"]).complete([{"role": "user", "content": "x"}])

    vision = service.get_metrics(db_session).vision

    assert vision.layouts_analysed == 2
    assert vision.documents_with_line_item_table == 1
    assert vision.tables_found == 1
    assert (vision.line_items_from_table, vision.line_items_from_model) == (3, 2)
    assert vision.line_items_table_share == 0.6
    assert (vision.pages_via_vision, vision.multimodal_calls) == (2, 1)


# -- Guardrails metrics (feature 0008) ----------------------------------------------------


@pytest.mark.usefixtures("llm_recorder")
def test_metrics_guardrails_block_counts_confidence_grounding_and_retries(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    run_agent(make_document(), FakeLLM(happy_script()))
    flaky = happy_script()
    flaky.insert(0, LLMError("busy", code="llm_rate_limited", retryable=True))
    run_agent(make_document(), FakeLLM(flaky))

    guardrails = service.get_metrics(db_session).guardrails

    assert guardrails.runs_scored == 2
    assert guardrails.by_label == {"high": 2, "medium": 0, "low": 0}
    assert guardrails.needs_review == 0 and guardrails.needs_review_rate == 0
    assert guardrails.values_checked > 0
    assert guardrails.grounding_rate is not None and 0.8 < guardrails.grounding_rate < 1
    assert guardrails.grounding_retry_extractions == 0
    assert guardrails.transient_retries == 1
    attempts = db_session.scalars(select(LlmCall.attempt).order_by(LlmCall.started_at)).all()
    assert sorted(attempts) == [1] * (len(attempts) - 1) + [2]


@pytest.mark.usefixtures("llm_recorder")
def test_trace_spans_carry_the_attempt(
    db_session: Session, make_document: MakeDocument, run_agent: RunAgent
) -> None:
    document_id = make_document()
    script = happy_script()
    script.insert(0, LLMError("busy", code="llm_unavailable", retryable=True))
    run_agent(document_id, FakeLLM(script))

    trace = service.get_trace(db_session, document_id)
    llm_spans = [s for s in trace.spans if isinstance(s, LLMSpan)]
    assert [(s.attempt, s.status, s.error_code) for s in llm_spans[:2]] == [
        (1, "error", "llm_unavailable"),
        (2, "ok", None),
    ]
