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

from app.core import llm as llm_module  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.llm import FakeLLM, get_llm_client, register_llm_recorder  # noqa: E402
from app.core.storage import LocalStorage, get_storage  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.documents.pipeline import register_pipeline_runner  # noqa: E402
from app.modules.observability.service import record_llm_call  # noqa: E402


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


@pytest.fixture(autouse=True)
def no_pipeline() -> Iterator[None]:
    """Uploads in tests do not run the agent unless a test opts in (``agent_pipeline``).

    ``app.main`` registers the Document Agent at import; earlier modules' upload tests
    expect a document to stay ``processing``, so the hook is a no-op by default.
    """
    register_pipeline_runner(None)
    yield
    register_pipeline_runner(None)


@pytest.fixture(autouse=True)
def no_llm_recorder() -> Iterator[None]:
    """LLM calls in tests are not written to the ledger unless a test opts in.

    ``app.main`` registers the ledger recorder at import; most tests make LLM calls with no
    real document or run behind their labels, so recording is off by default.
    """
    register_llm_recorder(None)
    yield
    register_llm_recorder(None)


@pytest.fixture(autouse=True)
def retry_waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Transient-error backoff never sleeps in tests; the waits are collected instead."""
    waits: list[float] = []
    monkeypatch.setattr(llm_module, "_sleep", waits.append)
    return waits


@pytest.fixture
def llm_recorder() -> None:
    """Opt in: every LLM call in this test writes a real ``llm_calls`` row (feature 0007)."""
    register_llm_recorder(record_llm_call)


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
