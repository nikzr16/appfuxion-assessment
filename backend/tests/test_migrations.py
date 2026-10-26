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
    assert version == "0002"


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
