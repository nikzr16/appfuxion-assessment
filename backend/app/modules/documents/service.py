import logging
import os
import re
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.errors import (
    AppError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaError,
    ValidationFailedError,
)
from app.core.logging import bind_document_id
from app.core.storage import Storage
from app.modules.documents import crud
from app.modules.documents.model import Document
from app.modules.documents.pipeline import DocumentPipeline
from app.modules.documents.schema import (
    DocumentList,
    DocumentRead,
    DocumentStatus,
    UploadedFile,
)

logger = logging.getLogger(__name__)

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
ALLOWED_CONTENT_TYPES = frozenset({PDF, PNG, JPEG})

# (magic bytes, content type)
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", PDF),
    (b"\x89PNG\r\n\x1a\n", PNG),
    (b"\xff\xd8\xff", JPEG),
)

_DEFAULT_NAME = "upload"
# Leaves room for a "(N)" suffix under the 255-byte filesystem limit.
_MAX_NAME_BYTES = 200
_MAX_ATTEMPTS = 20
_MAX_ERROR_CHARS = 1000
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
_PATH_SEPARATORS = re.compile(r"[/\\]")


# -- Pure helpers ---------------------------------------------------------------------


def _truncate_bytes(text: str, max_bytes: int) -> str:
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _clean_filename(raw: str | None) -> str:
    """Turn a client-supplied name into a safe, single path component (see the plan)."""
    if not raw:
        return _DEFAULT_NAME
    name = _PATH_SEPARATORS.split(raw)[-1]
    name = "".join(c if c.isalnum() or c in ".-_() " else "_" for c in name)
    name = name.strip(" .")
    if name.split(".")[0].strip().upper() in _WINDOWS_RESERVED:
        name = f"_{name}"
    stem, dot, ext = name.rpartition(".")
    if dot:
        ext = f".{ext}"
    else:
        stem, ext = name, ""
    if len(ext.encode("utf-8")) > _MAX_NAME_BYTES // 2:
        stem, ext = name, ""  # absurdly long "extension": just truncate the whole name
    stem = _truncate_bytes(stem, _MAX_NAME_BYTES - len(ext.encode("utf-8"))).rstrip(" .")
    return f"{stem}{ext}" or _DEFAULT_NAME


def _disk_name(filename: str, version: int) -> str:
    """Version 1 keeps the name; version N puts ``(N)`` before the last extension."""
    if version <= 1:
        return filename
    stem, ext = os.path.splitext(filename)
    return f"{stem}({version}){ext}"


def _sniff_content_type(data: bytes) -> str | None:
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    return None


def _normalise_content_type(header: str | None) -> str | None:
    if not header:
        return None
    value = header.split(";", 1)[0].strip().lower()
    if value == "image/jpg":
        return JPEG
    return value or None


def _to_read(document: Document) -> DocumentRead:
    return DocumentRead.model_validate(document)


def _get_or_raise(db: Session, document_id: uuid.UUID) -> Document:
    document = crud.get(db, document_id)
    if document is None:
        raise NotFoundError(f"Document not found: {document_id}")
    return document


# -- Use cases ------------------------------------------------------------------------


def create_document(db: Session, storage: Storage, upload: UploadedFile) -> DocumentRead:
    """Validate, store the file under its versioned real name and insert a ``processing`` row.

    Nothing is stored when the upload is rejected, and the file is removed again if the
    row cannot be inserted.
    """
    data = upload.data
    if not data:
        raise ValidationFailedError("The uploaded file is empty.")
    max_bytes = get_settings().max_upload_bytes
    if len(data) > max_bytes:
        raise PayloadTooLargeError(
            f"The file is larger than the {max_bytes / (1024 * 1024):g} MB limit."
        )
    sniffed = _sniff_content_type(data)
    header = _normalise_content_type(upload.content_type)
    if sniffed is None or header not in ALLOWED_CONTENT_TYPES or header != sniffed:
        raise UnsupportedMediaError("Only PDF, JPEG and PNG files are supported.")

    filename = _clean_filename(upload.filename)
    document_id = uuid.uuid4()
    version = crud.max_version(db, filename) + 1

    for _ in range(_MAX_ATTEMPTS):
        disk_name = _disk_name(filename, version)
        try:
            storage.save_as(disk_name, data)
        except FileExistsError:
            # Taken on disk: a case-insensitive clash, or a file literally named "x(2).pdf".
            version += 1
            continue
        try:
            document = crud.create(
                db,
                document_id=document_id,
                filename=filename,
                version=version,
                storage_path=disk_name,
                content_type=sniffed,
                size_bytes=len(data),
            )
            db.commit()
        except IntegrityError:
            # A concurrent upload took this version.
            db.rollback()
            storage.delete(disk_name)
            version = crud.max_version(db, filename) + 1
            continue
        except Exception:
            db.rollback()
            storage.delete(disk_name)
            raise
        with bind_document_id(str(document_id)):
            logger.info(
                "document stored",
                extra={"stored_filename": filename, "version": version, "size_bytes": len(data)},
            )
        return _to_read(document)

    raise AppError("Could not allocate a file name")


def get_document(db: Session, document_id: uuid.UUID) -> DocumentRead:
    return _to_read(_get_or_raise(db, document_id))


def list_documents(
    db: Session, *, limit: int, offset: int, status: DocumentStatus | None = None
) -> DocumentList:
    rows, total = crud.list_(db, limit=limit, offset=offset, status=status)
    return DocumentList(
        items=[_to_read(row) for row in rows], total=total, limit=limit, offset=offset
    )


# -- Status lifecycle (used by the pipeline, 0002-0005) --------------------------------


# Both helpers flush but do not commit: the caller commits, so a pipeline can save its
# results and the status change in one transaction.


def mark_completed(db: Session, document_id: uuid.UUID) -> DocumentRead:
    document = crud.update_status(db, document_id, DocumentStatus.COMPLETED)
    if document is None:
        raise NotFoundError(f"Document not found: {document_id}")
    return _to_read(document)


def mark_failed(db: Session, document_id: uuid.UUID, error: str) -> DocumentRead:
    document = crud.update_status(db, document_id, DocumentStatus.FAILED, error[:_MAX_ERROR_CHARS])
    if document is None:
        raise NotFoundError(f"Document not found: {document_id}")
    return _to_read(document)


def run_pipeline(document_id: uuid.UUID, pipeline: DocumentPipeline) -> None:
    """Background task: run the pipeline hook; on failure mark the document ``failed``.

    Never raises. The request's session is closed by now, so this opens its own.
    """
    with bind_document_id(str(document_id)):
        try:
            pipeline(document_id)
        except Exception as exc:
            logger.exception("pipeline failed")
            _record_failure(document_id, f"{type(exc).__name__}: {exc}")


def _record_failure(document_id: uuid.UUID, error: str) -> None:
    db = SessionLocal()
    try:
        mark_failed(db, document_id, error)
        db.commit()
    except Exception:
        logger.exception("could not mark document as failed")
    finally:
        db.close()
