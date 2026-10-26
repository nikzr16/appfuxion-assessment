import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    AppError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaError,
    ValidationFailedError,
)
from app.core.storage import LocalStorage, StoredFile
from app.modules.documents import service
from app.modules.documents.model import Document
from app.modules.documents.schema import DocumentRead, DocumentStatus, UploadedFile

PDF = "application/pdf"


def _upload(
    db: Session,
    storage: LocalStorage,
    filename: str | None,
    data: bytes,
    content_type: str | None = PDF,
) -> DocumentRead:
    return service.create_document(
        db, storage, UploadedFile(filename=filename, content_type=content_type, data=data)
    )


def _files(storage: LocalStorage) -> list[str]:
    return sorted(p.name for p in storage.root.iterdir())


def _row_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Document)).scalar_one()


def _is_case_insensitive(directory: Path) -> bool:
    probe = directory / "CaseProbe.tmp"
    probe.write_bytes(b"")
    try:
        return (directory / "caseprobe.tmp").exists()
    finally:
        probe.unlink()


# -- Pure helpers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("invoice.pdf", "invoice.pdf"),
        ("../../secret.pdf", "secret.pdf"),
        ("C:\\x\\a.pdf", "a.pdf"),
        ("/etc/passwd.pdf", "passwd.pdf"),
        ("inv<>|?.pdf", "inv____.pdf"),
        ("my invoice (final).pdf", "my invoice (final).pdf"),
        ("résumé.pdf", "résumé.pdf"),
        (".pdf", "pdf"),
        (".hidden.pdf", "hidden.pdf"),
        ("invoice.pdf  ", "invoice.pdf"),
        ("invoice.pdf...", "invoice.pdf"),
        ("CON.pdf", "_CON.pdf"),
        ("nul", "_nul"),
        ("com1.txt", "_com1.txt"),
        ("console.pdf", "console.pdf"),
        (None, "upload"),
        ("", "upload"),
        ("   ", "upload"),
        ("...", "upload"),
        ("dir/", "upload"),
    ],
)
def test_clean_filename(raw: str | None, expected: str) -> None:
    assert service._clean_filename(raw) == expected


@pytest.mark.parametrize("stem", ["a", "é"])
def test_clean_filename_trims_long_names_but_keeps_the_extension(stem: str) -> None:
    cleaned = service._clean_filename(stem * 300 + ".pdf")

    assert cleaned.endswith(".pdf")
    assert len(cleaned.encode("utf-8")) <= 200
    cleaned.encode("utf-8").decode("utf-8")  # still valid text


def test_clean_filename_trims_an_absurdly_long_extension() -> None:
    cleaned = service._clean_filename("x." + "a" * 400)

    assert 0 < len(cleaned.encode("utf-8")) <= 200


@pytest.mark.parametrize(
    ("filename", "version", "expected"),
    [
        ("invoice.pdf", 1, "invoice.pdf"),
        ("invoice.pdf", 2, "invoice(2).pdf"),
        ("invoice.pdf", 10, "invoice(10).pdf"),
        ("invoice_v2.pdf", 2, "invoice_v2(2).pdf"),
        ("report.tar.gz", 3, "report.tar(3).gz"),
        ("notes", 2, "notes(2)"),
        ("invoice(2).pdf", 2, "invoice(2)(2).pdf"),
    ],
)
def test_disk_name(filename: str, version: int, expected: str) -> None:
    assert service._disk_name(filename, version) == expected


def test_sniff_content_type(pdf_bytes: bytes, png_bytes: bytes, jpeg_bytes: bytes) -> None:
    assert service._sniff_content_type(pdf_bytes) == "application/pdf"
    assert service._sniff_content_type(png_bytes) == "image/png"
    assert service._sniff_content_type(jpeg_bytes) == "image/jpeg"
    assert service._sniff_content_type(b"hello world") is None
    assert service._sniff_content_type(b"\x89PNG") is None  # incomplete signature


# -- create_document ------------------------------------------------------------------


def test_create_document_stores_the_file_and_row(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    result = _upload(db_session, storage, "invoice.pdf", pdf_bytes)

    assert isinstance(result.document_id, uuid.UUID)
    assert result.document_id.version == 4
    assert result.filename == "invoice.pdf"
    assert result.version == 1
    assert result.content_type == "application/pdf"
    assert result.size_bytes == len(pdf_bytes)
    assert result.status == DocumentStatus.PROCESSING
    assert result.error is None
    assert storage.read("invoice.pdf") == pdf_bytes

    row = db_session.get(Document, result.document_id)
    assert row is not None
    assert row.storage_path == "invoice.pdf"
    assert row.status == "processing"
    assert row.created_at is not None


@pytest.mark.parametrize(
    ("data_fixture", "content_type"),
    [
        ("pdf_bytes", "application/pdf"),
        ("png_bytes", "image/png"),
        ("jpeg_bytes", "image/jpeg"),
    ],
)
def test_create_document_accepts_every_supported_type(
    request: pytest.FixtureRequest,
    db_session: Session,
    storage: LocalStorage,
    data_fixture: str,
    content_type: str,
) -> None:
    data: bytes = request.getfixturevalue(data_fixture)

    result = _upload(db_session, storage, "file", data, content_type)

    assert result.content_type == content_type


def test_same_name_gets_increasing_copy_suffixes(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    results = [_upload(db_session, storage, "invoice.pdf", pdf_bytes) for _ in range(3)]
    results += [_upload(db_session, storage, "invoice_v2.pdf", pdf_bytes) for _ in range(2)]

    assert [(r.filename, r.version) for r in results] == [
        ("invoice.pdf", 1),
        ("invoice.pdf", 2),
        ("invoice.pdf", 3),
        ("invoice_v2.pdf", 1),
        ("invoice_v2.pdf", 2),
    ]
    assert _files(storage) == [
        "invoice(2).pdf",
        "invoice(3).pdf",
        "invoice.pdf",
        "invoice_v2(2).pdf",
        "invoice_v2.pdf",
    ]
    assert "invoice(1).pdf" not in _files(storage)


def test_names_are_matched_case_sensitively_in_the_database(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    original = pdf_bytes
    other = pdf_bytes + b"% different content\n"

    _upload(db_session, storage, "invoice.pdf", original)
    second = _upload(db_session, storage, "Invoice.pdf", other)

    # The API-level name is its own name starting at version 1 ...
    assert second.filename == "Invoice.pdf"
    if _is_case_insensitive(storage.root):
        # ... but on a case-insensitive disk the file must not replace invoice.pdf.
        assert second.version == 2
        assert _files(storage) == ["Invoice(2).pdf", "invoice.pdf"]
    else:
        assert second.version == 1
        assert _files(storage) == ["Invoice.pdf", "invoice.pdf"]
    assert storage.read("invoice.pdf") == original


def test_a_file_literally_named_like_a_versioned_copy_never_overwrites(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    _upload(db_session, storage, "invoice.pdf", pdf_bytes + b"%1\n")
    _upload(db_session, storage, "invoice.pdf", pdf_bytes + b"%2\n")

    literal = _upload(db_session, storage, "invoice(2).pdf", pdf_bytes + b"%3\n")

    assert literal.filename == "invoice(2).pdf"
    assert literal.version == 2
    assert _files(storage) == ["invoice(2)(2).pdf", "invoice(2).pdf", "invoice.pdf"]
    assert storage.read("invoice.pdf") == pdf_bytes + b"%1\n"
    assert storage.read("invoice(2).pdf") == pdf_bytes + b"%2\n"
    assert storage.read("invoice(2)(2).pdf") == pdf_bytes + b"%3\n"


def test_hostile_names_are_cleaned_and_stay_inside_storage(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes, tmp_path: Path
) -> None:
    result = _upload(db_session, storage, "../../secret.pdf", pdf_bytes)

    assert result.filename == "secret.pdf"
    assert _files(storage) == ["secret.pdf"]
    assert not (tmp_path / "secret.pdf").exists()
    assert not (tmp_path.parent / "secret.pdf").exists()


def test_missing_filename_becomes_upload(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    result = _upload(db_session, storage, None, pdf_bytes)

    assert result.filename == "upload"
    assert _files(storage) == ["upload"]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("image/jpg", "image/jpeg"),
        ("IMAGE/JPEG", "image/jpeg"),
        ("image/jpeg; charset=binary", "image/jpeg"),
    ],
)
def test_content_type_header_is_normalised(
    db_session: Session, storage: LocalStorage, jpeg_bytes: bytes, header: str, expected: str
) -> None:
    result = _upload(db_session, storage, "scan.jpg", jpeg_bytes, header)

    assert result.content_type == expected


def test_empty_file_is_rejected(db_session: Session, storage: LocalStorage) -> None:
    with pytest.raises(ValidationFailedError):
        _upload(db_session, storage, "invoice.pdf", b"")

    assert _files(storage) == []
    assert _row_count(db_session) == 0


def test_oversized_file_is_rejected_and_nothing_is_stored(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes, small_upload_limit: int
) -> None:
    too_big = pdf_bytes + b"0" * (small_upload_limit - len(pdf_bytes) + 1)
    assert len(too_big) == small_upload_limit + 1

    with pytest.raises(PayloadTooLargeError):
        _upload(db_session, storage, "invoice.pdf", too_big)

    assert _files(storage) == []
    assert _row_count(db_session) == 0


def test_file_exactly_at_the_limit_is_accepted(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes, small_upload_limit: int
) -> None:
    at_limit = pdf_bytes + b"0" * (small_upload_limit - len(pdf_bytes))

    result = _upload(db_session, storage, "invoice.pdf", at_limit)

    assert result.size_bytes == small_upload_limit


@pytest.mark.parametrize(
    ("data_fixture", "header"),
    [
        (None, "application/pdf"),  # plain text claiming to be a PDF
        ("pdf_bytes", "text/plain"),  # unsupported header
        ("pdf_bytes", None),  # no header at all
        ("pdf_bytes", "image/png"),  # header disagrees with the magic bytes
        ("png_bytes", "application/pdf"),
        ("jpeg_bytes", "image/png"),
    ],
)
def test_unsupported_or_mismatched_types_are_rejected(
    request: pytest.FixtureRequest,
    db_session: Session,
    storage: LocalStorage,
    data_fixture: str | None,
    header: str | None,
) -> None:
    data: bytes = request.getfixturevalue(data_fixture) if data_fixture else b"just some text"

    with pytest.raises(UnsupportedMediaError):
        _upload(db_session, storage, "file.pdf", data, header)

    assert _files(storage) == []
    assert _row_count(db_session) == 0


def test_file_is_deleted_when_the_database_insert_fails(
    db_session: Session,
    storage: LocalStorage,
    pdf_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_create(*_args: object, **_kwargs: object) -> Document:
        raise RuntimeError("database exploded")

    monkeypatch.setattr(service.crud, "create", broken_create)

    with pytest.raises(RuntimeError, match="database exploded"):
        _upload(db_session, storage, "invoice.pdf", pdf_bytes)

    assert _files(storage) == []
    assert _row_count(db_session) == 0


def test_losing_a_version_race_retries_with_the_next_version(
    db_session: Session,
    storage: LocalStorage,
    pdf_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row for version 1 exists but its file is not on disk and the version read is stale."""
    _upload(db_session, storage, "invoice.pdf", pdf_bytes)
    storage.delete("invoice.pdf")

    real_max_version = service.crud.max_version
    calls = {"n": 0}

    def stale_first_call(db: Session, filename: str) -> int:
        calls["n"] += 1
        return 0 if calls["n"] == 1 else real_max_version(db, filename)

    monkeypatch.setattr(service.crud, "max_version", stale_first_call)

    result = _upload(db_session, storage, "invoice.pdf", pdf_bytes)

    assert result.version == 2
    assert _files(storage) == ["invoice(2).pdf"]  # the file from the failed attempt was removed
    assert _row_count(db_session) == 2


def test_gives_up_after_too_many_name_clashes(db_session: Session, pdf_bytes: bytes) -> None:
    class AlwaysTaken:
        calls = 0

        def save_as(self, name: str, data: bytes) -> StoredFile:
            self.calls += 1
            raise FileExistsError(name)

        def delete(self, key: str) -> None:  # pragma: no cover - never reached
            raise AssertionError("nothing was saved")

    taken = AlwaysTaken()

    with pytest.raises(AppError, match="Could not allocate a file name"):
        service.create_document(
            db_session,
            taken,  # type: ignore[arg-type]
            UploadedFile(filename="invoice.pdf", content_type=PDF, data=pdf_bytes),
        )

    assert taken.calls == 20
    assert _row_count(db_session) == 0


# -- get / list -----------------------------------------------------------------------


def test_get_document_returns_the_read_dto(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    created = _upload(db_session, storage, "invoice.pdf", pdf_bytes)

    fetched = service.get_document(db_session, created.document_id)

    assert fetched == created
    assert "storage_path" not in fetched.model_dump()


def test_get_document_raises_not_found_for_an_unknown_id(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        service.get_document(db_session, uuid.uuid4())


def test_list_documents_is_newest_first_with_total_and_paging(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    created = [_upload(db_session, storage, f"doc{n}.pdf", pdf_bytes) for n in range(5)]
    newest_first = [d.document_id for d in reversed(created)]

    everything = service.list_documents(db_session, limit=20, offset=0)
    first_page = service.list_documents(db_session, limit=2, offset=0)
    second_page = service.list_documents(db_session, limit=2, offset=2)
    past_the_end = service.list_documents(db_session, limit=2, offset=10)

    assert [d.document_id for d in everything.items] == newest_first
    assert everything.total == 5
    assert (everything.limit, everything.offset) == (20, 0)
    assert [d.document_id for d in first_page.items] == newest_first[:2]
    assert [d.document_id for d in second_page.items] == newest_first[2:4]
    assert (second_page.total, second_page.limit, second_page.offset) == (5, 2, 2)
    assert past_the_end.items == []
    assert past_the_end.total == 5


def test_list_documents_filters_by_status(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    first = _upload(db_session, storage, "a.pdf", pdf_bytes)
    second = _upload(db_session, storage, "b.pdf", pdf_bytes)
    _upload(db_session, storage, "c.pdf", pdf_bytes)
    service.mark_failed(db_session, first.document_id, "boom")
    service.mark_completed(db_session, second.document_id)

    failed = service.list_documents(db_session, limit=20, offset=0, status=DocumentStatus.FAILED)
    completed = service.list_documents(
        db_session, limit=20, offset=0, status=DocumentStatus.COMPLETED
    )
    processing = service.list_documents(
        db_session, limit=20, offset=0, status=DocumentStatus.PROCESSING
    )

    assert [d.document_id for d in failed.items] == [first.document_id]
    assert failed.total == 1
    assert [d.document_id for d in completed.items] == [second.document_id]
    assert processing.total == 1


# -- status lifecycle and pipeline ----------------------------------------------------


def test_mark_completed_sets_status_and_bumps_updated_at(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    created = _upload(db_session, storage, "invoice.pdf", pdf_bytes)

    completed = service.mark_completed(db_session, created.document_id)

    assert completed.status == DocumentStatus.COMPLETED
    assert completed.error is None
    assert completed.updated_at > created.updated_at
    assert completed.created_at == created.created_at


def test_mark_failed_records_the_error_trimmed_to_1000_chars(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    created = _upload(db_session, storage, "invoice.pdf", pdf_bytes)

    failed = service.mark_failed(db_session, created.document_id, "x" * 5000)

    assert failed.status == DocumentStatus.FAILED
    assert failed.error == "x" * 1000


def test_mark_helpers_leave_the_commit_to_the_caller(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    created = _upload(db_session, storage, "invoice.pdf", pdf_bytes)

    service.mark_completed(db_session, created.document_id)
    db_session.rollback()

    document = service.get_document(db_session, created.document_id)
    assert document.status == DocumentStatus.PROCESSING


def test_mark_helpers_raise_not_found_for_an_unknown_id(db_session: Session) -> None:
    with pytest.raises(NotFoundError):
        service.mark_completed(db_session, uuid.uuid4())
    with pytest.raises(NotFoundError):
        service.mark_failed(db_session, uuid.uuid4(), "boom")


def test_run_pipeline_calls_the_hook_with_the_document_id(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    created = _upload(db_session, storage, "invoice.pdf", pdf_bytes)
    calls: list[uuid.UUID] = []

    service.run_pipeline(created.document_id, calls.append)

    assert calls == [created.document_id]
    db_session.expire_all()
    assert service.get_document(db_session, created.document_id).status == "processing"


def test_run_pipeline_marks_the_document_failed_when_the_hook_raises(
    db_session: Session, storage: LocalStorage, pdf_bytes: bytes
) -> None:
    created = _upload(db_session, storage, "invoice.pdf", pdf_bytes)

    def exploding(_document_id: uuid.UUID) -> None:
        raise RuntimeError("model unavailable")

    service.run_pipeline(created.document_id, exploding)  # must not raise

    db_session.expire_all()
    document = service.get_document(db_session, created.document_id)
    assert document.status == DocumentStatus.FAILED
    assert document.error == "RuntimeError: model unavailable"


def test_run_pipeline_never_raises_even_if_the_document_is_gone() -> None:
    def exploding(_document_id: uuid.UUID) -> None:
        raise RuntimeError("boom")

    service.run_pipeline(uuid.uuid4(), exploding)
