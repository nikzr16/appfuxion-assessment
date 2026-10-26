"""Application settings.

Values come from real environment variables first (Docker Compose), then the root
``.env`` file (``../.env`` when running from ``backend/``, or ``.env`` in the cwd).
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- App ------------------------------------------------------------------
    app_name: str = "Document Intelligence Agent"
    api_prefix: str = "/api"
    log_level: str = "INFO"
    agent_mode: Literal["single", "multi"] = "multi"

    # -- OpenAI ---------------------------------------------------------------
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4.1-mini"
    openai_vision_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = 2

    # -- Database -------------------------------------------------------------
    postgres_user: str = "appfuxion"
    postgres_password: str = "change_me_locally"
    postgres_db: str = "appfuxion"
    postgres_host: str = "localhost"
    # Port the database is reachable on from *this* process. Locally that is the
    # published host port; Compose pins it to 5432 for the backend container.
    db_port: int = 5432
    # Explicit SQLAlchemy URL. When blank it is derived from the POSTGRES_* values.
    database_url: str = ""

    # -- Uploads --------------------------------------------------------------
    max_upload_mb: int = 10
    storage_dir: Path = Path("storage")

    # -- Text extraction ------------------------------------------------------
    # Most pages of a scanned PDF sent to the vision model; later pages are skipped.
    vision_max_pages: int = Field(default=5, ge=1)

    # -- Agent ------------------------------------------------------------------
    # Totals in another currency are converted to this one (ISO 4217 code).
    base_currency: str = "MYR"
    # Most model turns one agent run may take before it fails with ``agent_max_steps``.
    agent_max_steps: int = Field(default=8, ge=1, le=30)

    @field_validator("base_currency")
    @classmethod
    def _normalise_base_currency(cls, value: str) -> str:
        code = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise ValueError("BASE_CURRENCY must be a 3-letter ISO 4217 code such as MYR")
        return code

    @model_validator(mode="after")
    def _derive_database_url(self) -> "Settings":
        if not self.database_url:
            self.database_url = build_database_url(
                user=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.db_port,
                database=self.postgres_db,
            )
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def storage_path(self) -> Path:
        """Absolute storage root; a relative ``STORAGE_DIR`` resolves against backend/."""
        return (
            self.storage_dir if self.storage_dir.is_absolute() else BACKEND_DIR / self.storage_dir
        )

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key.get_secret_value())


def build_database_url(*, user: str, password: str, host: str, port: int, database: str) -> str:
    """Build a psycopg 3 SQLAlchemy URL, escaping special characters in credentials."""
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port,
        database=database,
    ).render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
