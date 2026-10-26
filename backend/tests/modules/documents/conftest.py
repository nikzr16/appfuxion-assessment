"""Fixtures shared by the documents service and router tests.

Byte samples are built in code (only the leading magic bytes matter to the module), so no
binary files live in the repo.
"""

import uuid
from collections.abc import Iterator

import pytest

from app.core.config import Settings
from app.main import app
from app.modules.documents.pipeline import get_document_pipeline

SMALL_LIMIT_BYTES = 1024


@pytest.fixture
def pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


@pytest.fixture
def png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 16


@pytest.fixture
def jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 16


@pytest.fixture
def small_upload_limit(monkeypatch: pytest.MonkeyPatch) -> int:
    """Lower the upload limit to 1 KB so tests never need 10 MB payloads."""
    monkeypatch.setattr(Settings, "max_upload_bytes", property(lambda _self: SMALL_LIMIT_BYTES))
    return SMALL_LIMIT_BYTES


class PipelineSpy:
    """Records the document ids the pipeline hook was called with."""

    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    def __call__(self, document_id: uuid.UUID) -> None:
        self.calls.append(document_id)


@pytest.fixture
def pipeline_spy() -> Iterator[PipelineSpy]:
    spy = PipelineSpy()
    app.dependency_overrides[get_document_pipeline] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_document_pipeline, None)
