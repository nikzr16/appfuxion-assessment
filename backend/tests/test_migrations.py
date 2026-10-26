from sqlalchemy import text
from sqlalchemy.orm import Session


def test_pgvector_extension_is_enabled_by_migration(db_session: Session) -> None:
    extensions = db_session.execute(text("SELECT extname FROM pg_extension")).scalars().all()
    assert "vector" in extensions


def test_pgvector_type_is_usable(db_session: Session) -> None:
    distance = db_session.execute(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")).scalar()
    assert distance == 1.0


def test_alembic_version_is_at_head(db_session: Session) -> None:
    version = db_session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0001"
