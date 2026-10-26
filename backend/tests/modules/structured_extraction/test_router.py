import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.llm import FakeLLM
from app.modules.documents import service as documents_service
from app.modules.structured_extraction import prompts, service
from tests.modules.structured_extraction.conftest import MakeDocument, invoice


def test_get_extraction_returns_the_structured_data(
    client: TestClient, db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()
    fake_llm.queue(invoice())
    service.extract_structured_data(db_session, fake_llm, document_id)

    response = client.get(f"/api/documents/{document_id}/extraction")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"document_id", "structured_data", "model", "prompt_version", "attempts"}
    assert body["document_id"] == str(document_id)
    assert body["model"] == "fake-model"
    assert body["prompt_version"] == prompts.PROMPT_VERSION
    assert body["attempts"] == 1
    data = body["structured_data"]
    assert data["total_amount"] == "123.45"  # money is an exact decimal string
    assert data["invoice_date"] == "2025-03-04"
    assert data["currency"] == "MYR"
    assert data["line_items"][1]["unit_price"] == "103.45"


def test_get_extraction_for_an_unknown_document_is_404(client: TestClient) -> None:
    response = client.get(f"/api/documents/{uuid.uuid4()}/extraction")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_extraction_rejects_a_malformed_id(client: TestClient) -> None:
    response = client.get("/api/documents/not-a-uuid/extraction")

    assert response.status_code == 422


def test_get_extraction_for_a_fresh_upload_is_409_not_ready(
    client: TestClient, make_document: MakeDocument
) -> None:
    document_id = make_document()

    response = client.get(f"/api/documents/{document_id}/extraction")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "extraction_not_ready"


def test_get_extraction_for_a_failed_document_is_409_unavailable(
    client: TestClient, db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document()
    documents_service.mark_failed(db_session, document_id, "StructuredExtractionError: boom")
    db_session.commit()

    response = client.get(f"/api/documents/{document_id}/extraction")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "extraction_unavailable"
    assert "StructuredExtractionError: boom" in error["message"]


def test_get_extraction_never_calls_the_llm(
    client: TestClient, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document()

    client.get(f"/api/documents/{document_id}/extraction")

    assert fake_llm.calls == []
