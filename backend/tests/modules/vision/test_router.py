import io
import uuid

import httpx
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.core.storage import LocalStorage
from app.modules.documents import service as documents_service
from app.modules.text_extraction.schema import ExtractionMethod
from app.modules.vision import service
from tests.modules.vision import samples
from tests.modules.vision.conftest import MakeDocument

PDF = "application/pdf"
PNG = "image/png"


def _assert_error(response: httpx.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]


def test_get_layout_returns_the_newest_analysis_and_its_history(
    client: TestClient, db_session: Session, storage: LocalStorage, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.invoice_pdf())
    method = ExtractionMethod.PDF_PARSER
    service.extract_tables(db_session, storage, document_id, method=method)
    service.extract_tables(db_session, storage, document_id, method=method, force=True)

    response = client.get(f"/api/documents/{document_id}/layout")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "document_id",
        "layout_id",
        "source",
        "layout_version",
        "run_id",
        "created_at",
        "page_count",
        "pages",
        "tables",
        "blocks",
        "history",
    }
    assert body["source"] == "pdf_parser"
    assert body["layout_version"] == "layout.v1"
    assert body["tables"][0]["kind"] == "line_items"
    assert body["tables"][0]["header"] == list(samples.HEADER)
    assert len(body["tables"][0]["rows"][0]["box"]) == 4
    assert [b["type"] for b in body["blocks"]][-1] == "payment"
    assert len(body["history"]) == 1
    assert set(body["history"][0]) == {
        "layout_id",
        "created_at",
        "source",
        "layout_version",
        "run_id",
    }


def test_get_layout_is_409_until_analysed_and_404_for_unknown(
    client: TestClient, db_session: Session, make_document: MakeDocument
) -> None:
    document_id = make_document(PDF, samples.invoice_pdf())

    _assert_error(client.get(f"/api/documents/{document_id}/layout"), 409, "layout_not_ready")
    documents_service.mark_failed(db_session, document_id, "boom")
    db_session.commit()
    _assert_error(client.get(f"/api/documents/{document_id}/layout"), 409, "layout_unavailable")
    _assert_error(client.get(f"/api/documents/{uuid.uuid4()}/layout"), 404, "not_found")


def test_page_image_is_a_cacheable_jpeg(client: TestClient, make_document: MakeDocument) -> None:
    document_id = make_document(PDF, samples.invoice_pdf())

    response = client.get(f"/api/documents/{document_id}/pages/1/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert Image.open(io.BytesIO(response.content)).format == "JPEG"


def test_page_image_errors(client: TestClient, make_document: MakeDocument) -> None:
    document_id = make_document(PNG, samples.scanned_png())

    assert client.get(f"/api/documents/{document_id}/pages/1/image").status_code == 200
    _assert_error(client.get(f"/api/documents/{document_id}/pages/2/image"), 404, "page_not_found")
    assert client.get(f"/api/documents/{document_id}/pages/0/image").status_code == 422
    _assert_error(client.get(f"/api/documents/{uuid.uuid4()}/pages/1/image"), 404, "not_found")
