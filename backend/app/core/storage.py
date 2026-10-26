"""File storage for uploaded documents.

``Storage`` is deliberately tiny so a different backend (e.g. S3) can replace
``LocalStorage`` without touching callers.
"""

import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import NotFoundError


@dataclass(frozen=True)
class StoredFile:
    key: str
    size: int


class Storage(Protocol):
    def save(self, data: bytes, *, extension: str = "") -> StoredFile: ...

    def read(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Stores files under ``root`` using generated names (never user-supplied ones)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, *, extension: str = "") -> StoredFile:
        ext = extension.lower().lstrip(".")
        if ext and not ext.isalnum():
            raise ValueError(f"Invalid file extension: {extension!r}")
        key = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
        self._path(key).write_bytes(data)
        return StoredFile(key=key, size=len(data))

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise NotFoundError(f"Stored file not found: {key}")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise ValueError(f"Invalid storage key: {key!r}")
        return path


@lru_cache
def get_storage() -> Storage:
    """FastAPI dependency / factory for the configured storage backend."""
    return LocalStorage(get_settings().storage_path)
