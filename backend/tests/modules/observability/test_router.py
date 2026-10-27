"""HTTP: GET /documents/{id}/trace and GET /metrics/summary."""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.llm import FakeLLM
from tests.modules.agent.conftest import happy_script, invoice_pdf


def _assert_error(response: httpx.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


@pytest.fixture
def processed(
    client: TestClient, fake_llm: FakeLLM, agent_pipeline: None, llm_recorder: None
) -> str:
    """A document uploaded through the real route and processed with the ledger on."""
    fake_llm.queue(*happy_script())
    response = client.post(
        "/api/documents", files={"file": ("invoice.pdf", invoice_pdf(), "application/pdf")}
    )
    assert response.status_code == 202
    return response.json()["document_id"]


def test_trace_of_an_uploaded_document(client: TestClient, processed: str) -> None:
    response = client.get(f"/api/documents/{processed}/trace")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == processed
    assert body["llm_calls_recorded"] is True
    assert body["run"]["status"] == "completed"
    assert body["run"]["queue_ms"] >= 0
    assert body["totals"]["llm_calls"] == 11
    assert body["totals"]["cost_complete"] is False  # fake-model is unpriced
    assert body["prices_as_of"] == "2026-10-27"
    kinds = [span["kind"] for span in body["spans"]]
    assert kinds.count("tool") == 8 and kinds.count("llm") == 11
    assert all(span["attempt"] == 1 for span in body["spans"] if span["kind"] == "llm")
    llm = next(span for span in body["spans"] if span["kind"] == "llm")
    assert set(llm) >= {"purpose", "model", "prompt_tokens", "offset_ms", "duration_ms"}

    run_id = body["run"]["run_id"]
    again = client.get(f"/api/documents/{processed}/trace", params={"run_id": run_id})
    assert again.status_code == 200 and again.json()["run"]["run_id"] == run_id


def test_trace_errors(client: TestClient, processed: str) -> None:
    _assert_error(client.get(f"/api/documents/{uuid.uuid4()}/trace"), 404, "not_found")
    _assert_error(
        client.get(f"/api/documents/{processed}/trace", params={"run_id": str(uuid.uuid4())}),
        404,
        "run_not_found",
    )
    assert client.get("/api/documents/not-a-uuid/trace").status_code == 422
    assert client.get(f"/api/documents/{processed}/trace?run_id=x").status_code == 422


def test_metrics_summary(client: TestClient, processed: str) -> None:
    response = client.get("/api/metrics/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["window_days"] is None
    assert body["documents"]["completed"] == 1
    assert body["documents"]["success_rate"] == 1.0
    assert body["runs"]["completed"] == 1
    assert body["llm"]["llm_calls"] == 11
    assert body["llm"]["avg_tokens_per_document"] == 170
    assert body["vision"]["layouts_analysed"] == 1
    assert body["retrieval"]["documents_indexed"] == 1
    assert body["retrieval"]["new_vendor_flags"] == 1
    assert {g["key"] for g in body["by_purpose"]} == {
        "agent_loop",
        "structured_extraction",
        "embedding",
        "summary",
    }
    assert [g["key"] for g in body["by_agent"]] == ["document"]

    week = client.get("/api/metrics/summary", params={"days": 7})
    assert week.status_code == 200 and week.json()["window_days"] == 7


@pytest.mark.parametrize("days", ["0", "366", "x"])
def test_metrics_window_must_be_1_to_365_days(client: TestClient, days: str) -> None:
    assert client.get("/api/metrics/summary", params={"days": days}).status_code == 422
