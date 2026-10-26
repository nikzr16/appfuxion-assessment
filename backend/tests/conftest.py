"""Shared test fixtures.

Tests run against a real Postgres database named ``appfuxion_test`` on the same server
the app is configured for. It is created on demand and migrated once per session. The
real OpenAI API is never used: API tests get a ``FakeLLM`` through dependency overrides.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.core.config import Settings

TEST_DB_NAME = "appfuxion_test"
BACKEND_DIR = Path(__file__).resolve().parents[1]

# Point the application at the test database *before* app.core.db builds its engine.
_configured = make_url(Settings().database_url)
ADMIN_URL = _configured.set(database="postgres")
TEST_URL = _configured.set(database=TEST_DB_NAME)
os.environ["DATABASE_URL"] = TEST_URL.render_as_string(hide_password=False)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.llm import FakeLLM, get_llm_client  # noqa: E402
from app.core.storage import LocalStorage, get_storage  # noqa: E402
from app.main import app  # noqa: E402


def _ensure_test_database() -> None:
    admin = create_engine(
        ADMIN_URL, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5}
    )
    try:
        try:
            conn_ctx = admin.connect()
        except OperationalError as exc:
            pytest.exit(
                f"Cannot reach Postgres at {ADMIN_URL.render_as_string()}. Start it with: "
                "docker compose --env-file .env -f db/docker-compose.yml up -d\n"
                f"({exc.orig})",
                returncode=2,
            )
        with conn_ctx as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Create the test database if missing and run ``alembic upgrade head`` once."""
    _ensure_test_database()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(config, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(migrated_database: None) -> Iterator[None]:
    """Empty every feature table after each test (the schema stays)."""
    yield
    tables = [t.name for t in Base.metadata.sorted_tables]
    if tables:
        names = ", ".join(f'"{name}"' for name in tables)
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def fake_llm() -> Iterator[FakeLLM]:
    """A scripted ``FakeLLM`` wired into the app's ``get_llm_client`` dependency."""
    fake = FakeLLM()
    app.dependency_overrides[get_llm_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_llm_client, None)


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[LocalStorage]:
    """A ``LocalStorage`` in a temp dir, wired into the app's ``get_storage`` dependency."""
    local = LocalStorage(tmp_path / "uploads")
    app.dependency_overrides[get_storage] = lambda: local
    yield local
    app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def client(fake_llm: FakeLLM, storage: LocalStorage) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
