import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_pgvector_extension_is_enabled_by_migration(db_session: Session) -> None:
    extensions = db_session.execute(text("SELECT extname FROM pg_extension")).scalars().all()
    assert "vector" in extensions


def test_pgvector_type_is_usable(db_session: Session) -> None:
    distance = db_session.execute(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")).scalar()
    assert distance == 1.0


def test_alembic_version_is_at_head(db_session: Session) -> None:
    version = db_session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0003"


def test_documents_table_has_a_native_uuid_primary_key(db_session: Session) -> None:
    columns = dict(
        db_session.execute(
            text(
                "SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_name = 'documents'"
            )
        ).all()
    )
    assert columns["id"] == "uuid"
    assert set(columns) == {
        "id",
        "filename",
        "version",
        "storage_path",
        "content_type",
        "size_bytes",
        "status",
        "error",
        "created_at",
        "updated_at",
    }


def test_documents_table_has_its_constraints_and_index(db_session: Session) -> None:
    constraints = dict(
        db_session.execute(
            text(
                "SELECT conname, contype FROM pg_constraint "
                "WHERE conrelid = 'documents'::regclass AND contype <> 'n'"
            )
        ).all()
    )
    assert constraints == {
        "pk_documents": "p",
        "ck_documents_status_valid": "c",
        "uq_documents_filename_version": "u",
        "uq_documents_storage_path": "u",
    }
    indexes = db_session.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'documents'")
    ).scalars()
    assert "ix_documents_created_at" in set(indexes)


def test_documents_status_check_constraint_rejects_unknown_values(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO documents "
                "(id, filename, version, storage_path, content_type, size_bytes, status) "
                "VALUES (gen_random_uuid(), 'a.pdf', 1, 'a.pdf', 'application/pdf', 1, 'bogus')"
            )
        )
    db_session.rollback()


def test_document_texts_table_has_a_native_uuid_primary_key(db_session: Session) -> None:
    columns = dict(
        db_session.execute(
            text(
                "SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_name = 'document_texts'"
            )
        ).all()
    )
    assert columns["id"] == "uuid"
    assert columns["document_id"] == "uuid"
    assert set(columns) == {
        "id",
        "document_id",
        "raw_text",
        "method",
        "page_count",
        "model",
        "prompt_version",
        "created_at",
        "updated_at",
    }


def test_document_texts_table_has_its_constraints(db_session: Session) -> None:
    constraints = dict(
        db_session.execute(
            text(
                "SELECT conname, contype FROM pg_constraint "
                "WHERE conrelid = 'document_texts'::regclass AND contype <> 'n'"
            )
        ).all()
    )
    assert constraints == {
        "pk_document_texts": "p",
        "uq_document_texts_document_id": "u",
        "fk_document_texts_document_id_documents": "f",
        "ck_document_texts_method_valid": "c",
        "ck_document_texts_page_count_positive": "c",
    }


def _insert_document(db_session: Session) -> str:
    document_id = str(uuid.uuid4())
    db_session.execute(
        text(
            "INSERT INTO documents "
            "(id, filename, version, storage_path, content_type, size_bytes, status) "
            "VALUES (:id, 'a.pdf', 1, 'a.pdf', 'application/pdf', 1, 'processing')"
        ),
        {"id": document_id},
    )
    return document_id


def _insert_text(db_session: Session, document_id: str, method: str, page_count: int) -> None:
    db_session.execute(
        text(
            "INSERT INTO document_texts (id, document_id, raw_text, method, page_count) "
            "VALUES (gen_random_uuid(), :document_id, 'x', :method, :page_count)"
        ),
        {"document_id": document_id, "method": method, "page_count": page_count},
    )


@pytest.mark.parametrize(("method", "page_count"), [("ocr", 1), ("vision", 0)])
def test_document_texts_check_constraints_reject_bad_values(
    db_session: Session, method: str, page_count: int
) -> None:
    document_id = _insert_document(db_session)
    with pytest.raises(IntegrityError):
        _insert_text(db_session, document_id, method, page_count)
    db_session.rollback()


def test_document_texts_allows_one_row_per_document(db_session: Session) -> None:
    document_id = _insert_document(db_session)
    _insert_text(db_session, document_id, "vision", 1)
    with pytest.raises(IntegrityError):
        _insert_text(db_session, document_id, "pdf_parser", 2)
    db_session.rollback()


def test_document_texts_requires_an_existing_document(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        _insert_text(db_session, str(uuid.uuid4()), "vision", 1)
    db_session.rollback()


def test_deleting_a_document_cascades_to_its_text(db_session: Session) -> None:
    document_id = _insert_document(db_session)
    _insert_text(db_session, document_id, "vision", 1)
    db_session.commit()

    db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
    db_session.commit()

    assert db_session.execute(text("SELECT count(*) FROM document_texts")).scalar() == 0
