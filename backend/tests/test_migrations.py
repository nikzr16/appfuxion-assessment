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
    assert version == "0007"


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


# -- extractions (0003 structured extraction) ------------------------------------------


def test_extractions_table_has_native_uuid_keys_and_jsonb_data(db_session: Session) -> None:
    columns = dict(
        db_session.execute(
            text(
                "SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_name = 'extractions'"
            )
        ).all()
    )
    assert columns["id"] == "uuid"
    assert columns["document_id"] == "uuid"
    assert columns["data"] == "jsonb"
    assert set(columns) == {
        "id",
        "document_id",
        "data",
        "model",
        "prompt_version",
        "attempts",
        "prompt_tokens",
        "completion_tokens",
        "grounding",
        "created_at",
        "updated_at",
    }


def test_extractions_table_has_its_constraints(db_session: Session) -> None:
    constraints = dict(
        db_session.execute(
            text(
                "SELECT conname, contype FROM pg_constraint "
                "WHERE conrelid = 'extractions'::regclass AND contype <> 'n'"
            )
        ).all()
    )
    assert constraints == {
        "pk_extractions": "p",
        "uq_extractions_document_id": "u",
        "fk_extractions_document_id_documents": "f",
        "ck_extractions_attempts_positive": "c",
        "ck_extractions_prompt_tokens_non_negative": "c",
        "ck_extractions_completion_tokens_non_negative": "c",
    }


def _insert_extraction(
    db_session: Session, document_id: str, *, attempts: int = 1, prompt_tokens: int = 0
) -> None:
    db_session.execute(
        text(
            "INSERT INTO extractions (id, document_id, data, model, prompt_version, attempts, "
            "prompt_tokens, completion_tokens) VALUES (gen_random_uuid(), :document_id, "
            "'{}'::jsonb, 'm', 'v1', :attempts, :prompt_tokens, 0)"
        ),
        {"document_id": document_id, "attempts": attempts, "prompt_tokens": prompt_tokens},
    )


@pytest.mark.parametrize(("attempts", "prompt_tokens"), [(0, 0), (1, -1)])
def test_extractions_check_constraints_reject_bad_values(
    db_session: Session, attempts: int, prompt_tokens: int
) -> None:
    document_id = _insert_document(db_session)
    with pytest.raises(IntegrityError):
        _insert_extraction(db_session, document_id, attempts=attempts, prompt_tokens=prompt_tokens)
    db_session.rollback()


def test_extractions_allows_one_row_per_document(db_session: Session) -> None:
    document_id = _insert_document(db_session)
    _insert_extraction(db_session, document_id)
    with pytest.raises(IntegrityError):
        _insert_extraction(db_session, document_id)
    db_session.rollback()


def test_extractions_requires_an_existing_document(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        _insert_extraction(db_session, str(uuid.uuid4()))
    db_session.rollback()


def test_deleting_a_document_cascades_to_its_extraction(db_session: Session) -> None:
    document_id = _insert_document(db_session)
    _insert_extraction(db_session, document_id)
    db_session.commit()

    db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
    db_session.commit()

    assert db_session.execute(text("SELECT count(*) FROM extractions")).scalar() == 0


# -- agent_runs (0005) ----------------------------------------------------------------


def test_agent_runs_table_has_native_uuid_keys_and_jsonb_columns(db_session: Session) -> None:
    columns = dict(
        db_session.execute(
            text(
                "SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_name = 'agent_runs'"
            )
        ).all()
    )
    assert columns["id"] == "uuid"
    assert columns["document_id"] == "uuid"
    assert columns["steps"] == "jsonb"
    assert columns["result"] == "jsonb"
    assert set(columns) == {
        "id",
        "document_id",
        "mode",
        "trigger",
        "status",
        "steps",
        "result",
        "summary",
        "error_code",
        "error",
        "model",
        "agent_prompt_version",
        "summary_prompt_version",
        "prompt_tokens",
        "completion_tokens",
        "overall_confidence",
        "needs_review",
        "started_at",
        "finished_at",
    }


def test_agent_runs_table_has_its_constraints_and_indexes(db_session: Session) -> None:
    constraints = dict(
        db_session.execute(
            text(
                "SELECT conname, contype FROM pg_constraint "
                "WHERE conrelid = 'agent_runs'::regclass AND contype <> 'n'"
            )
        ).all()
    )
    assert constraints == {
        "pk_agent_runs": "p",
        "fk_agent_runs_document_id_documents": "f",
        "ck_agent_runs_mode_valid": "c",
        "ck_agent_runs_trigger_valid": "c",
        "ck_agent_runs_status_valid": "c",
        "ck_agent_runs_prompt_tokens_non_negative": "c",
        "ck_agent_runs_completion_tokens_non_negative": "c",
        "ck_agent_runs_overall_confidence_range": "c",
    }
    indexes = dict(
        db_session.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'agent_runs'")
        ).all()
    )
    assert "ix_agent_runs_document_id_started_at" in indexes
    running = indexes["uq_agent_runs_document_running"]
    assert "UNIQUE" in running
    assert "WHERE" in running and "running" in running


def _insert_run(
    db_session: Session,
    document_id: str,
    *,
    status: str = "running",
    mode: str = "single",
    trigger: str = "upload",
    prompt_tokens: int = 0,
) -> None:
    db_session.execute(
        text(
            "INSERT INTO agent_runs (id, document_id, mode, trigger, status, "
            "agent_prompt_version, summary_prompt_version, prompt_tokens) VALUES "
            "(gen_random_uuid(), :document_id, :mode, :trigger, :status, 'a1', 's1', "
            ":prompt_tokens)"
        ),
        {
            "document_id": document_id,
            "status": status,
            "mode": mode,
            "trigger": trigger,
            "prompt_tokens": prompt_tokens,
        },
    )


@pytest.mark.parametrize(
    "overrides",
    [{"status": "done"}, {"mode": "solo"}, {"trigger": "cron"}, {"prompt_tokens": -1}],
)
def test_agent_runs_check_constraints_reject_bad_values(
    db_session: Session, overrides: dict[str, object]
) -> None:
    document_id = _insert_document(db_session)
    with pytest.raises(IntegrityError):
        _insert_run(db_session, document_id, **overrides)  # type: ignore[arg-type]
    db_session.rollback()


def test_agent_runs_defaults_steps_to_an_empty_list(db_session: Session) -> None:
    document_id = _insert_document(db_session)
    _insert_run(db_session, document_id)
    steps = db_session.execute(
        text("SELECT steps FROM agent_runs WHERE document_id = :id"), {"id": document_id}
    ).scalar()
    assert steps == []
    db_session.rollback()


def test_agent_runs_allow_one_running_run_but_many_finished_runs(db_session: Session) -> None:
    document_id = _insert_document(db_session)
    _insert_run(db_session, document_id, status="completed")
    _insert_run(db_session, document_id, status="failed")
    _insert_run(db_session, document_id, status="running")
    with pytest.raises(IntegrityError):
        _insert_run(db_session, document_id, status="running")
    db_session.rollback()


def test_deleting_a_document_cascades_to_its_agent_runs(db_session: Session) -> None:
    document_id = _insert_document(db_session)
    _insert_run(db_session, document_id, status="completed")
    db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
    remaining = db_session.execute(
        text("SELECT count(*) FROM agent_runs WHERE document_id = :id"), {"id": document_id}
    ).scalar()
    assert remaining == 0
    db_session.rollback()


# -- llm_calls (0006) -----------------------------------------------------------------


def test_llm_calls_table_has_native_uuid_keys_and_its_columns(db_session: Session) -> None:
    columns = dict(
        db_session.execute(
            text(
                "SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_name = 'llm_calls'"
            )
        ).all()
    )
    assert columns["id"] == columns["document_id"] == columns["run_id"] == "uuid"
    assert columns["cost_usd"] == "numeric"
    assert columns["started_at"] == "timestamptz"
    assert set(columns) == {
        "id",
        "document_id",
        "run_id",
        "step_index",
        "agent",
        "purpose",
        "kind",
        "model",
        "prompt_version",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
        "latency_ms",
        "status",
        "error_code",
        "started_at",
        "attempt",
    }


def test_llm_calls_table_has_its_constraints_and_indexes(db_session: Session) -> None:
    constraints = dict(
        db_session.execute(
            text(
                "SELECT conname, contype FROM pg_constraint "
                "WHERE conrelid = 'llm_calls'::regclass AND contype <> 'n'"
            )
        ).all()
    )
    assert constraints == {
        "pk_llm_calls": "p",
        "fk_llm_calls_document_id_documents": "f",
        "fk_llm_calls_run_id_agent_runs": "f",
        "ck_llm_calls_kind_valid": "c",
        "ck_llm_calls_status_valid": "c",
        "ck_llm_calls_prompt_tokens_non_negative": "c",
        "ck_llm_calls_completion_tokens_non_negative": "c",
        "ck_llm_calls_cost_usd_non_negative": "c",
        "ck_llm_calls_latency_ms_non_negative": "c",
        "ck_llm_calls_attempt_positive": "c",
    }
    indexes = set(
        db_session.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'llm_calls'")
        ).scalars()
    )
    assert indexes == {
        "pk_llm_calls",
        "ix_llm_calls_document_id_started_at",
        "ix_llm_calls_run_id",
        "ix_llm_calls_started_at",
    }


def _insert_call(
    db_session: Session,
    *,
    document_id: str | None = None,
    run_id: str | None = None,
    kind: str = "chat",
    status: str = "ok",
    prompt_tokens: int = 1,
    cost_usd: str | None = "0.000001",
    latency_ms: int = 5,
) -> None:
    db_session.execute(
        text(
            "INSERT INTO llm_calls (id, document_id, run_id, purpose, kind, model, "
            "prompt_tokens, cost_usd, latency_ms, status, started_at) VALUES "
            "(gen_random_uuid(), :document_id, :run_id, 'summary', :kind, 'm', "
            ":prompt_tokens, CAST(:cost_usd AS numeric), :latency_ms, :status, now())"
        ),
        {
            "document_id": document_id,
            "run_id": run_id,
            "kind": kind,
            "status": status,
            "prompt_tokens": prompt_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
        },
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "image"},
        {"status": "done"},
        {"prompt_tokens": -1},
        {"cost_usd": "-0.1"},
        {"latency_ms": -1},
    ],
)
def test_llm_calls_check_constraints_reject_bad_values(
    db_session: Session, overrides: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError):
        _insert_call(db_session, **overrides)  # type: ignore[arg-type]
    db_session.rollback()


def test_deleting_a_document_cascades_to_its_runs_and_llm_calls(db_session: Session) -> None:
    document_id = _insert_document(db_session)
    _insert_run(db_session, document_id, status="completed")
    run_id = str(
        db_session.execute(
            text("SELECT id FROM agent_runs WHERE document_id = :id"), {"id": document_id}
        ).scalar()
    )
    _insert_call(db_session, document_id=document_id, run_id=run_id)
    _insert_call(db_session)  # a call outside any document is allowed
    db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document_id})
    remaining = db_session.execute(text("SELECT count(*) FROM llm_calls")).scalar()
    assert remaining == 1
    db_session.rollback()


# -- guardrails columns (0007) ---------------------------------------------------------


def test_guardrails_columns_have_their_types(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            "SELECT table_name, column_name, udt_name, is_nullable, column_default "
            "FROM information_schema.columns WHERE (table_name, column_name) IN "
            "(('extractions', 'grounding'), ('agent_runs', 'overall_confidence'), "
            "('agent_runs', 'needs_review'), ('llm_calls', 'attempt'))"
        )
    ).all()
    found = {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}
    assert found[("extractions", "grounding")] == ("jsonb", "YES", None)
    assert found[("agent_runs", "overall_confidence")][:2] == ("numeric", "YES")
    assert found[("agent_runs", "needs_review")][:2] == ("bool", "YES")
    assert found[("llm_calls", "attempt")] == ("int4", "NO", "1")


@pytest.mark.parametrize("value", ["1.001", "-0.001"])
def test_overall_confidence_must_be_between_0_and_1(db_session: Session, value: str) -> None:
    document_id = _insert_document(db_session)
    _insert_run(db_session, document_id, status="completed")
    with pytest.raises(IntegrityError):
        db_session.execute(text("UPDATE agent_runs SET overall_confidence = :v"), {"v": value})
    db_session.rollback()


def test_llm_call_attempt_defaults_to_1_and_rejects_0(db_session: Session) -> None:
    _insert_call(db_session)
    assert db_session.execute(text("SELECT attempt FROM llm_calls")).scalar_one() == 1
    with pytest.raises(IntegrityError):
        db_session.execute(text("UPDATE llm_calls SET attempt = 0"))
    db_session.rollback()
