import uuid

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.llm import FakeLLM
from app.core.storage import LocalStorage
from app.modules.documents import service as documents_service
from app.modules.text_extraction import service
from tests.modules.text_extraction import samples
from tests.modules.text_extraction.conftest import MakeDocument

PDF = "application/pdf"


def _assert_error(response: httpx.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]


def test_get_text_returns_the_extracted_text(
    client: TestClient,
    db_session: Session,
    storage: LocalStorage,
    fake_llm: FakeLLM,
    make_document: MakeDocument,
) -> None:
    document_id = make_document(PDF, samples.text_pdf())
    extracted = service.extract_text(db_session, storage, fake_llm, document_id)

    response = client.get(f"/api/documents/{document_id}/text")

    assert response.status_code == 200
    assert response.json() == {
        "document_id": str(document_id),
        "raw_text": extracted.raw_text,
        "method": "pdf_parser",
        "page_count": 1,
    }
    assert "INVOICE INV-001" in response.json()["raw_text"]


def test_get_text_works_whatever_the_document_status(
    client: TestClient,
    db_session: Session,
    storage: LocalStorage,
    fake_llm: FakeLLM,
    make_document: MakeDocument,
) -> None:
    document_id = make_document(PDF, samples.text_pdf())
    service.extract_text(db_session, storage, fake_llm, document_id)
    documents_service.mark_failed(db_session, document_id, "a later step failed")
    db_session.commit()

    response = client.get(f"/api/documents/{document_id}/text")

    assert response.status_code == 200
    assert response.json()["method"] == "pdf_parser"


def test_get_text_for_an_unknown_document_is_404(client: TestClient) -> None:
    response = client.get(f"/api/documents/{uuid.uuid4()}/text")

    _assert_error(response, 404, "not_found")


def test_get_text_rejects_a_malformed_id(client: TestClient) -> None:
    response = client.get("/api/documents/not-a-uuid/text")

    _assert_error(response, 422, "request_validation_failed")


def test_get_text_for_a_fresh_upload_is_409_text_not_ready(
    client: TestClient, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())

    response = client.get(f"/api/documents/{document_id}/text")

    _assert_error(response, 409, "text_not_ready")


def test_get_text_for_a_failed_document_is_409_text_unavailable(
    client: TestClient, db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.text_pdf())
    documents_service.mark_failed(db_session, document_id, "TextExtractionError: no_text_found")
    db_session.commit()

    response = client.get(f"/api/documents/{document_id}/text")

    _assert_error(response, 409, "text_unavailable")
    assert "no_text_found" in response.json()["error"]["message"]


def test_get_text_never_calls_the_llm_or_starts_an_extraction(
    client: TestClient, db_session: Session, fake_llm: FakeLLM, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.scanned_pdf())

    response = client.get(f"/api/documents/{document_id}/text")

    _assert_error(response, 409, "text_not_ready")
    assert fake_llm.calls == []
    # Still no text afterwards: GET is read-only.
    assert client.get(f"/api/documents/{document_id}/text").status_code == 409
