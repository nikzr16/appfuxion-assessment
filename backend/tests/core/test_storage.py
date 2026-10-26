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


def test_save_as_writes_under_the_given_name(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "uploads")

    stored = storage.save_as("invoice.pdf", b"%PDF-1.7 content")

    assert stored.key == "invoice.pdf"
    assert stored.size == len(b"%PDF-1.7 content")
    assert storage.read("invoice.pdf") == b"%PDF-1.7 content"
    assert (tmp_path / "uploads" / "invoice.pdf").is_file()


def test_save_as_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    storage.save_as("invoice.pdf", b"original")

    with pytest.raises(FileExistsError):
        storage.save_as("invoice.pdf", b"replacement")

    assert storage.read("invoice.pdf") == b"original"


@pytest.mark.parametrize("name", ["../escape.pdf", "sub/dir.pdf", "/etc/passwd", "a/../../x.pdf"])
def test_save_as_rejects_names_that_leave_the_root(tmp_path: Path, name: str) -> None:
    root = tmp_path / "root"
    with pytest.raises(ValueError):
        LocalStorage(root).save_as(name, b"x")

    assert not (tmp_path / "escape.pdf").exists()
    assert list(root.iterdir()) == []


def test_save_as_removes_a_partial_file_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalStorage(tmp_path)

    class BrokenWriter:
        def __enter__(self) -> "BrokenWriter":
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def write(self, _data: bytes) -> int:
            raise OSError("disk full")

    real_open = Path.open

    def fake_open(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        if mode == "xb":
            real_open(self, mode).close()  # the file now exists, empty
            return BrokenWriter()
        return real_open(self, mode, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", fake_open)

    with pytest.raises(OSError, match="disk full"):
        storage.save_as("invoice.pdf", b"data")

    assert not storage.exists("invoice.pdf")
