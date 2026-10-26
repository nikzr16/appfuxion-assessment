from pathlib import Path

import pytest

from app.core.errors import NotFoundError
from app.core.storage import LocalStorage


def test_save_then_read_round_trips_bytes(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "uploads")

    stored = storage.save(b"%PDF-1.7 content", extension=".PDF")

    assert stored.key.endswith(".pdf")
    assert stored.size == len(b"%PDF-1.7 content")
    assert storage.exists(stored.key)
    assert storage.read(stored.key) == b"%PDF-1.7 content"
    assert (tmp_path / "uploads" / stored.key).is_file()


def test_generated_keys_are_unique(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    assert storage.save(b"a").key != storage.save(b"a").key


def test_read_missing_file_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        LocalStorage(tmp_path).read("missing.pdf")


def test_delete_removes_file_and_is_idempotent(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    key = storage.save(b"x", extension="png").key
    storage.delete(key)
    storage.delete(key)
    assert not storage.exists(key)


@pytest.mark.parametrize("key", ["../escape.txt", "sub/dir.txt", "/etc/passwd"])
def test_path_traversal_keys_are_rejected(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        LocalStorage(tmp_path / "root").read(key)


def test_invalid_extension_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).save(b"x", extension="../x")
