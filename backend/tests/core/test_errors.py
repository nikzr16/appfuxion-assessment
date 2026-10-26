import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import (
    AppError,
    ConflictError,
    LLMError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaError,
    ValidationFailedError,
    register_error_handlers,
)


def build_client(error: AppError) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise error

    return TestClient(app)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (NotFoundError("no such document"), 404, "not_found"),
        (ConflictError("not ready"), 409, "conflict"),
        (ValidationFailedError("bad value"), 422, "validation_failed"),
        (UnsupportedMediaError("only pdf/jpg/png"), 415, "unsupported_media_type"),
        (PayloadTooLargeError("too big"), 413, "payload_too_large"),
        (LLMError("upstream down"), 502, "llm_error"),
        (AppError("generic"), 500, "internal_error"),
    ],
)
def test_app_errors_map_to_json_error_shape(error: AppError, status: int, code: str) -> None:
    response = build_client(error).get("/boom")

    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": error.message}}


def test_error_code_can_be_overridden_per_instance() -> None:
    response = build_client(NotFoundError("gone", code="document_not_found")).get("/boom")
    assert response.json()["error"]["code"] == "document_not_found"


def test_conflict_error_code_can_be_specific() -> None:
    response = build_client(ConflictError("still running", code="text_not_ready")).get("/boom")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "text_not_ready"


def test_framework_errors_use_the_same_shape() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/items/{item_id}")
    def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    client = TestClient(app)

    missing = client.get("/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    invalid = client.get("/items/not-a-number")
    assert invalid.status_code == 422
    body = invalid.json()["error"]
    assert body["code"] == "request_validation_failed"
    assert body["details"][0]["loc"] == ["path", "item_id"]
