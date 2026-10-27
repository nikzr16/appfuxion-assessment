"""guardrails is a pure module: other modules' schemas plus validation's service only, and no
database, LLM, storage or web framework (PRD 0008 constraints)."""

import ast
from pathlib import Path

import app.modules.guardrails as guardrails

ALLOWED_MODULE_IMPORTS = (
    "app.modules.guardrails",
    "app.modules.structured_extraction.schema",
    "app.modules.text_extraction.schema",
    "app.modules.validation.schema",
    "app.modules.validation.service",
    "app.modules.validation",  # ``from app.modules.validation import service``
)
FORBIDDEN_PREFIXES = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "openai",
    "app.core.db",
    "app.core.llm",
    "app.core.storage",
)


def _imports() -> list[tuple[str, str]]:
    found = []
    for path in Path(guardrails.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found += [(path.name, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [f"{node.module}.{alias.name}" for alias in node.names]
                found += [(path.name, name) for name in names]
    return found


def test_only_schemas_and_validation_service_from_other_modules() -> None:
    offenders = [
        f"{file}: {name}"
        for file, name in _imports()
        if (name.startswith("app.modules.") and not name.startswith(ALLOWED_MODULE_IMPORTS))
        or any(part in name for part in (".crud", ".model", ".router"))
    ]
    assert offenders == []


def test_no_db_llm_storage_or_web_imports() -> None:
    offenders = [
        f"{file}: {name}" for file, name in _imports() if name.startswith(FORBIDDEN_PREFIXES)
    ]
    assert offenders == []
