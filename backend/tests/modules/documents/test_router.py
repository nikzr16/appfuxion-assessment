import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.storage import LocalStorage
from app.main import app
from app.modules.documents import service
from app.modules.documents.pipeline import get_document_pipeline
from app.modules.documents.schema import DocumentStatus


def _post(
    client: TestClient,
    data: bytes,
    name: str = "invoice.pdf",
    content_type: str = "application/pdf",
) -> httpx.Response:
    return client.post("/api/documents", files={"file": (name, data, content_type)})


def _files(storage: LocalStorage) -> list[str]:
    return sorted(p.name for p in storage.root.iterdir())


def _assert_error(response: httpx.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]


# -- POST /api/documents --------------------------------------------------------------


@pytest.mark.parametrize(
    ("data_fixture", "name", "content_type"),
    [
        ("pdf_bytes", "invoice.pdf", "application/pdf"),
        ("png_bytes", "receipt.png", "image/png"),
        ("jpeg_bytes", "scan.jpg", "image/jpeg"),
    ],
)
def test_upload_returns_202_with_a_plain_uuid_and_processing_status(
    request: pytest.FixtureRequest,
    client: TestClient,
    storage: LocalStorage,
    pipeline_spy: Any,
    data_fixture: str,
    name: str,
    content_type: str,
) -> None:
    data: bytes = request.getfixturevalue(data_fixture)

    response = _post(client, data, name, content_type)

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"document_id", "status"}
    assert body["status"] == "processing"
    document_id = uuid.UUID(body["document_id"])
    assert document_id.version == 4
    assert body["document_id"] == str(document_id)  # plain dashed form, no prefix
    assert _files(storage) == [name]


def test_upload_calls_the_pipeline_hook_once_with_the_new_id(
    client: TestClient, pdf_bytes: bytes, pipeline_spy: Any
) -> None:
    response = _post(client, pdf_bytes)

    assert pipeline_spy.calls == [uuid.UUID(response.json()["document_id"])]


def test_upload_with_no_pipeline_registered_leaves_the_document_processing(
    client: TestClient, pdf_bytes: bytes
) -> None:
    document_id = _post(client, pdf_bytes).json()["document_id"]

    assert client.get(f"/api/documents/{document_id}").json()["status"] == "processing"


def test_a_raising_pipeline_marks_the_document_failed_but_the_upload_still_succeeds(
    client: TestClient, pdf_bytes: bytes
) -> None:
    def exploding(_document_id: uuid.UUID) -> None:
        raise RuntimeError("boom")

    app.dependency_overrides[get_document_pipeline] = lambda: exploding
    try:
        response = _post(client, pdf_bytes)
    finally:
        app.dependency_overrides.pop(get_document_pipeline, None)

    assert response.status_code == 202
    document = client.get(f"/api/documents/{response.json()['document_id']}").json()
    assert document["status"] == "failed"
    assert document["error"] == "RuntimeError: boom"


def test_same_name_uploads_get_versions_in_the_api_and_on_disk(
    client: TestClient, storage: LocalStorage, pdf_bytes: bytes, pipeline_spy: Any
) -> None:
    ids = [_post(client, pdf_bytes).json()["document_id"] for _ in range(2)]

    documents = [client.get(f"/api/documents/{document_id}").json() for document_id in ids]

    assert [(d["filename"], d["version"]) for d in documents] == [
        ("invoice.pdf", 1),
        ("invoice.pdf", 2),
    ]
    assert _files(storage) == ["invoice(2).pdf", "invoice.pdf"]


def test_unsupported_type_returns_415_and_stores_nothing(
    client: TestClient, storage: LocalStorage, pipeline_spy: Any
) -> None:
    response = _post(client, b"plain text", "notes.txt", "text/plain")

    _assert_error(response, 415, "unsupported_media_type")
    assert _files(storage) == []
    assert pipeline_spy.calls == []


def test_header_that_disagrees_with_the_magic_bytes_returns_415(
    client: TestClient, storage: LocalStorage, png_bytes: bytes
) -> None:
    response = _post(client, png_bytes, "invoice.pdf", "application/pdf")

    _assert_error(response, 415, "unsupported_media_type")
    assert _files(storage) == []


@pytest.mark.parametrize("extra_bytes", [1, 5000])
def test_oversized_file_returns_413_and_stores_nothing(
    client: TestClient,
    storage: LocalStorage,
    pdf_bytes: bytes,
    pipeline_spy: Any,
    small_upload_limit: int,
    extra_bytes: int,
) -> None:
    data = pdf_bytes + b"0" * (small_upload_limit - len(pdf_bytes) + extra_bytes)

    response = _post(client, data)

    _assert_error(response, 413, "payload_too_large")
    assert _files(storage) == []
    assert pipeline_spy.calls == []


def test_file_at_the_size_limit_is_accepted(
    client: TestClient, pdf_bytes: bytes, small_upload_limit: int, pipeline_spy: Any
) -> None:
    data = pdf_bytes + b"0" * (small_upload_limit - len(pdf_bytes))

    assert _post(client, data).status_code == 202


def test_empty_file_returns_422_validation_failed(
    client: TestClient, storage: LocalStorage, pipeline_spy: Any
) -> None:
    response = _post(client, b"")

    _assert_error(response, 422, "validation_failed")
    assert _files(storage) == []
    assert pipeline_spy.calls == []


def test_missing_file_field_returns_422_request_validation_failed(client: TestClient) -> None:
    response = client.post("/api/documents", data={"other": "value"})

    _assert_error(response, 422, "request_validation_failed")


# -- GET /api/documents/{document_id} -------------------------------------------------


def test_get_document_returns_metadata_without_the_storage_path(
    client: TestClient, pdf_bytes: bytes, pipeline_spy: Any
) -> None:
    document_id = _post(client, pdf_bytes, "../../invoice.pdf").json()["document_id"]

    response = client.get(f"/api/documents/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "document_id",
        "filename",
        "version",
        "content_type",
        "size_bytes",
        "status",
        "error",
        "created_at",
        "updated_at",
    }
    assert body["document_id"] == document_id
    assert body["filename"] == "invoice.pdf"
    assert body["version"] == 1
    assert body["content_type"] == "application/pdf"
    assert body["size_bytes"] == len(pdf_bytes)
    assert body["status"] == "processing"
    assert body["error"] is None


def test_get_unknown_document_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/documents/{uuid.uuid4()}")

    _assert_error(response, 404, "not_found")


def test_get_document_with_a_malformed_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/documents/doc_123")

    _assert_error(response, 422, "request_validation_failed")


# -- GET /api/documents ---------------------------------------------------------------


def _seed(client: TestClient, pdf_bytes: bytes, count: int) -> list[str]:
    return [_post(client, pdf_bytes, f"doc{n}.pdf").json()["document_id"] for n in range(count)]


def test_list_is_newest_first_with_paging_metadata(
    client: TestClient, pdf_bytes: bytes, pipeline_spy: Any
) -> None:
    ids = _seed(client, pdf_bytes, 3)

    response = client.get("/api/documents")

    assert response.status_code == 200
    body = response.json()
    assert [item["document_id"] for item in body["items"]] == list(reversed(ids))
    assert (body["total"], body["limit"], body["offset"]) == (3, 20, 0)
    assert "storage_path" not in body["items"][0]


def test_list_honours_limit_and_offset(
    client: TestClient, pdf_bytes: bytes, pipeline_spy: Any
) -> None:
    ids = _seed(client, pdf_bytes, 4)
    newest_first = list(reversed(ids))

    body = client.get("/api/documents", params={"limit": 2, "offset": 1}).json()

    assert [item["document_id"] for item in body["items"]] == newest_first[1:3]
    assert (body["total"], body["limit"], body["offset"]) == (4, 2, 1)


def test_list_filters_by_status(
    client: TestClient, db_session: Session, pdf_bytes: bytes, pipeline_spy: Any
) -> None:
    ids = _seed(client, pdf_bytes, 3)
    service.mark_failed(db_session, uuid.UUID(ids[0]), "boom")
    service.mark_completed(db_session, uuid.UUID(ids[1]))
    db_session.commit()

    def ids_for(status: DocumentStatus) -> list[str]:
        body = client.get("/api/documents", params={"status": status.value}).json()
        return [item["document_id"] for item in body["items"]]

    assert ids_for(DocumentStatus.FAILED) == [ids[0]]
    assert ids_for(DocumentStatus.COMPLETED) == [ids[1]]
    assert ids_for(DocumentStatus.PROCESSING) == [ids[2]]


@pytest.mark.parametrize(
    "params",
    [{"limit": 101}, {"limit": 0}, {"offset": -1}, {"status": "archived"}, {"limit": "many"}],
)
def test_list_rejects_invalid_query_params(client: TestClient, params: dict[str, Any]) -> None:
    response = client.get("/api/documents", params=params)

    _assert_error(response, 422, "request_validation_failed")


def test_list_accepts_the_maximum_limit(client: TestClient) -> None:
    response = client.get("/api/documents", params={"limit": 100})

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 100, "offset": 0}
