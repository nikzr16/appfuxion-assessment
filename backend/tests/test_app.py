from fastapi.testclient import TestClient

from app.core.llm import FakeLLM, get_llm_client
from app.main import app


def test_app_starts_without_openai_key_and_exposes_openapi(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    assert "/api/health" in schema["paths"]


def test_fake_llm_fixture_is_injected_through_the_dependency(
    client: TestClient, fake_llm: FakeLLM
) -> None:
    assert app.dependency_overrides[get_llm_client]() is fake_llm
