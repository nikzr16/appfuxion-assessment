from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import BACKEND_DIR, Settings, build_database_url


def make_settings(**overrides: object) -> Settings:
    # _env_file=None: ignore the developer's real .env so the test is hermetic.
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "DB_PORT",
        "STORAGE_DIR",
        "VISION_MAX_PAGES",
        "OPENAI_API_KEY",
        "AGENT_MODE",
        "BASE_CURRENCY",
        "AGENT_MAX_STEPS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_database_url_is_derived_from_postgres_parts() -> None:
    settings = make_settings(
        postgres_user="alice",
        postgres_password="secret",
        postgres_host="db",
        db_port=5433,
        postgres_db="docs",
    )
    assert settings.database_url == "postgresql+psycopg://alice:secret@db:5433/docs"


def test_database_url_escapes_special_characters_in_password() -> None:
    url = make_url(
        build_database_url(user="u", password="p@ss/w:rd", host="h", port=1, database="d")
    )
    assert url.password == "p@ss/w:rd"
    assert url.host == "h"


def test_explicit_database_url_wins() -> None:
    settings = make_settings(database_url="postgresql+psycopg://x:y@elsewhere:1/other")
    assert settings.database_url == "postgresql+psycopg://x:y@elsewhere:1/other"


def test_blank_database_url_falls_back_to_derived() -> None:
    settings = make_settings(database_url="", postgres_host="db")
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert "@db:5432/" in settings.database_url


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PORT", "5999")
    monkeypatch.setenv("MAX_UPLOAD_MB", "3")
    settings = make_settings()
    assert settings.db_port == 5999
    assert settings.max_upload_bytes == 3 * 1024 * 1024


def test_openai_key_is_optional() -> None:
    settings = make_settings()
    assert settings.openai_configured is False
    assert make_settings(openai_api_key="sk-test").openai_configured is True


def test_relative_storage_dir_resolves_against_backend_dir() -> None:
    assert make_settings(storage_dir="./storage").storage_path == BACKEND_DIR / "storage"
    absolute = Path(BACKEND_DIR.anchor) / "data" / "uploads"
    assert make_settings(storage_dir=str(absolute)).storage_path == absolute


def test_vision_max_pages_defaults_to_five_and_reads_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert make_settings().vision_max_pages == 5
    monkeypatch.setenv("VISION_MAX_PAGES", "3")
    assert make_settings().vision_max_pages == 3


@pytest.mark.parametrize("value", [0, -1])
def test_vision_max_pages_must_be_at_least_one(value: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(vision_max_pages=value)


def test_agent_settings_defaults() -> None:
    settings = make_settings()
    assert settings.agent_mode == "multi"  # runs the single agent until B4 (PRD 0005 D13)
    assert settings.base_currency == "MYR"
    assert settings.agent_max_steps == 10


def test_base_currency_is_normalised_and_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BASE_CURRENCY", " sgd ")
    assert make_settings().base_currency == "SGD"


@pytest.mark.parametrize("value", ["RM", "MYRR", "", "12A"])
def test_base_currency_must_be_a_three_letter_code(value: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(base_currency=value)


@pytest.mark.parametrize("value", [0, 31])
def test_agent_max_steps_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(agent_max_steps=value)
