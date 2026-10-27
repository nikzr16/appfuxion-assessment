"""HTTP: the end-to-end upload, /result, /reprocess and /runs."""

import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import LLMError
from app.core.llm import FakeLLM, get_llm_client
from app.core.storage import LocalStorage
from app.main import app
from app.modules.documents import service as documents_service
from tests.modules.agent.conftest import SUMMARY, happy_script, invoice_pdf, text_turn


def _upload(client: TestClient) -> httpx.Response:
    return client.post(
        "/api/documents", files={"file": ("invoice.pdf", invoice_pdf(), "application/pdf")}
    )


def _assert_error(response: httpx.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


@pytest.fixture
def processed(client: TestClient, fake_llm: FakeLLM, agent_pipeline: None) -> str:
    """A document uploaded and processed by the agent through the real upload route."""
    fake_llm.queue(*happy_script())
    response = _upload(client)
    assert response.status_code == 202
    return response.json()["document_id"]


# -- End to end -------------------------------------------------------------------------------


def test_upload_runs_the_agent_and_the_result_is_served(client: TestClient, processed: str) -> None:
    document = client.get(f"/api/documents/{processed}").json()
    assert document["status"] == "completed"
    assert document["error"] is None

    response = client.get(f"/api/documents/{processed}/result")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "document_id",
        "structured_data",
        "validation",
        "conversion",
        "summary",
        "confidence",
    }
    assert body["confidence"]["label"] == "high"
    assert body["confidence"]["needs_review"] is False
    assert body["confidence"]["fields"]["vendor"]["grounding"] == "grounded"
    assert body["document_id"] == processed
    assert body["structured_data"]["total_amount"] == "123.45"  # money as a string
    assert body["structured_data"]["line_items"][1]["amount"] == "103.45"
    assert body["validation"]["status"] == "pass"
    assert body["conversion"] is None
    assert body["summary"] == SUMMARY


def test_runs_lists_the_tool_calls(client: TestClient, processed: str) -> None:
    response = client.get(f"/api/documents/{processed}/runs")

    assert response.status_code == 200
    (run,) = response.json()
    assert run["status"] == "completed"
    assert run["trigger"] == "upload"
    assert "result" not in run
    assert [step["tool"] for step in run["steps"]] == [
        "extract_text",
        "extract_tables",
        "extract_structured_data",
        "check_grounding",
        "validate_invoice",
        "check_vendor_history",
        "search_similar_invoices",
        "generate_summary",
    ]


def test_a_failed_agent_run_fails_the_uploaded_document(
    client: TestClient, fake_llm: FakeLLM, agent_pipeline: None
) -> None:
    fake_llm.queue(text_turn("I will not use tools."))
    document_id = _upload(client).json()["document_id"]

    document = client.get(f"/api/documents/{document_id}").json()
    assert document["status"] == "failed"
    assert document["error"].startswith("agent_incomplete: ")
    _assert_error(client.get(f"/api/documents/{document_id}/result"), 409, "result_unavailable")


# -- /result ----------------------------------------------------------------------------------


def test_result_while_processing_is_409(client: TestClient) -> None:
    document_id = _upload(client).json()["document_id"]  # no pipeline: stays processing

    _assert_error(client.get(f"/api/documents/{document_id}/result"), 409, "result_not_ready")


def test_result_of_a_failed_document_is_409_with_the_error(
    client: TestClient, db_session: Session
) -> None:
    document_id = _upload(client).json()["document_id"]
    documents_service.mark_failed(db_session, uuid.UUID(document_id), "no_text_found: Nothing.")
    db_session.commit()

    response = client.get(f"/api/documents/{document_id}/result")

    _assert_error(response, 409, "result_unavailable")
    assert "no_text_found: Nothing." in response.json()["error"]["message"]


@pytest.mark.parametrize("route", ["result", "runs"])
def test_unknown_and_malformed_ids(client: TestClient, route: str) -> None:
    _assert_error(client.get(f"/api/documents/{uuid.uuid4()}/{route}"), 404, "not_found")
    assert client.get(f"/api/documents/not-a-uuid/{route}").status_code == 422


# -- /reprocess -------------------------------------------------------------------------------


def test_reprocess_runs_the_agent_again_in_the_background(
    client: TestClient, fake_llm: FakeLLM, processed: str
) -> None:
    fake_llm.queue(*happy_script(summary="Second summary."))

    response = client.post(f"/api/documents/{processed}/reprocess")

    assert response.status_code == 202
    assert response.json() == {"document_id": processed, "status": "processing"}
    assert not fake_llm.replies  # forced re-extraction consumed the structured reply too
    runs = client.get(f"/api/documents/{processed}/runs").json()
    assert [run["trigger"] for run in runs] == ["reprocess", "upload"]
    assert client.get(f"/api/documents/{processed}/result").json()["summary"] == ("Second summary.")


def test_reprocess_while_processing_is_409(client: TestClient) -> None:
    document_id = _upload(client).json()["document_id"]

    _assert_error(client.post(f"/api/documents/{document_id}/reprocess"), 409, "already_processing")


def test_reprocess_of_an_unknown_document_is_404(client: TestClient) -> None:
    _assert_error(client.post(f"/api/documents/{uuid.uuid4()}/reprocess"), 404, "not_found")


# -- No API key -------------------------------------------------------------------------------


@pytest.fixture
def unconfigured_llm() -> Iterator[None]:
    def missing_key() -> FakeLLM:
        raise LLMError("OPENAI_API_KEY is not set.", code="llm_not_configured")

    app.dependency_overrides[get_llm_client] = missing_key
    yield
    app.dependency_overrides.pop(get_llm_client, None)


def test_upload_without_an_api_key_fails_fast_and_stores_nothing(
    storage: LocalStorage, agent_pipeline: None, unconfigured_llm: None
) -> None:
    with TestClient(app) as client:
        response = _upload(client)

        _assert_error(response, 502, "llm_not_configured")
        assert client.get("/api/documents").json()["total"] == 0
    assert not storage.root.exists() or not any(storage.root.iterdir())
