from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.main import app


def test_health_returns_200_with_app_and_database_status(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_is_not_served_outside_the_api_prefix(client: TestClient) -> None:
    assert client.get("/health").status_code == 404


@pytest.fixture
def broken_db() -> Iterator[None]:
    session = MagicMock(spec=Session)
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("down"))
    app.dependency_overrides[get_db] = lambda: session
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.usefixtures("broken_db")
def test_health_returns_503_when_database_is_down(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "error"}
