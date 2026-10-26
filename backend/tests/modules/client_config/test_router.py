from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app


def test_config_returns_public_settings(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"max_upload_mb", "accepted_content_types", "base_currency"}
    assert body["accepted_content_types"] == ["application/pdf", "image/jpeg", "image/png"]


@pytest.fixture
def custom_settings() -> Iterator[None]:
    app.dependency_overrides[get_settings] = lambda: Settings(max_upload_mb=3, base_currency="SGD")
    yield
    app.dependency_overrides.pop(get_settings, None)


@pytest.mark.usefixtures("custom_settings")
def test_config_follows_settings(client: TestClient) -> None:
    body = client.get("/api/config").json()

    assert body["max_upload_mb"] == 3
    assert body["base_currency"] == "SGD"
