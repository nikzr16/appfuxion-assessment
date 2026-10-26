---
name: proj-fastapi-module
description: Creates or extends a backend feature module in backend/app/modules/<module>/ using this project's DTO-style anatomy (router, service, schema, crud, model — only the layers needed), layering rules, migration, wiring, and test pattern. Use whenever adding a new backend module or a new layer to an existing one.
---
# FastAPI Module (project skill)

Build backend modules the same way every time. Project rules live in
`CLAUDE.project.md` (Module anatomy, Layering, LLM access); this skill is the
step-by-step checklist.

## 1. Decide which layers the module needs

| Needs… | Add |
|---|---|
| HTTP endpoints | `router.py` |
| Business logic (always) | `service.py` |
| Data shapes in/out, LLM output schema (always) | `schema.py` |
| Its own table(s) | `model.py` + `crud.py` |
| LLM prompts | `prompts.py` (constants + `PROMPT_VERSION`) |
| Agent tools / loop / coordination | `tools.py`, `runner.py`, `coordinator.py` |

Skip any layer the module does not need (e.g. `validation` = `service.py` + `schema.py`).
State the chosen layers in the module's plan.

## 2. Write the layers (bottom-up)

1. **`model.py`** — SQLAlchemy 2.0 typed ORM (`Mapped[...]`, `mapped_column`), inherit
   the shared `Base` from `app.core.db`. Table names plural snake_case. Money
   `Numeric(14, 2)`, JSON `JSONB`, timestamps timezone-aware.
2. **`crud.py`** — plain functions taking `db: Session` first; queries only, no business
   rules, no commits hidden in loops; return ORM objects or `None`.
3. **`schema.py`** — Pydantic v2 DTOs: `<X>Create` (input), `<X>Read` (output,
   `model_config = ConfigDict(from_attributes=True)`), internal DTOs. No ORM imports.
4. **`service.py`** — business logic; takes DTOs/primitives + `Session`; returns DTOs
   (convert ORM → `<X>Read` here); raises domain errors from `app.core.errors`. Never
   import FastAPI. LLM calls only via `app.core.llm`.
5. **`router.py`** — `APIRouter(prefix=..., tags=[...])`; dependency-inject `Session`;
   call the service; declare `response_model`; map domain errors via the shared
   handlers (no try/except boilerplate per route).

Cross-module: import another module's `service` / `schema` only — never its `crud` /
`model`.

## 3. Wire it up

- Router → include it in `app/main.py` (or the router registry there).
- Model → import it in the Alembic model registry so autogenerate sees it, then
  `uv run alembic revision --autogenerate -m "<module>: <change>"`; review the file.
- New config → `app/core/config.py` + `.env.example` + `CLAUDE.project.md` env list.

## 4. Test it

- `backend/tests/modules/<module>/`: `test_service.py` (logic, FakeLLM for any LLM
  call) and `test_router.py` (FastAPI `TestClient`, real Postgres test DB).
- Never call the real OpenAI API in tests.
- Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`.

## 5. Close out

- Update `docs/reference/folder-structure.md` (files, routes, tables).
- Append the module's section to `ENGINEERING_NOTES.md`.
- Divergence from the plan → `docs/decisions/NNNN-*.md`.
