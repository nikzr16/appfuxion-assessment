"""validation is a pure module: only structured_extraction.schema from other modules, and no
database, LLM, storage or web framework."""

import ast
from pathlib import Path

import app.modules.validation as validation

ALLOWED_MODULE_IMPORTS = ("app.modules.validation", "app.modules.structured_extraction.schema")
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
    for path in Path(validation.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found += [(path.name, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((path.name, node.module))
    return found


def test_only_structured_extraction_schema_from_other_modules() -> None:
    offenders = [
        f"{file}: {name}"
        for file, name in _imports()
        if name.startswith("app.modules.") and not name.startswith(ALLOWED_MODULE_IMPORTS)
    ]
    assert offenders == []


def test_no_db_llm_storage_or_web_imports() -> None:
    offenders = [
        f"{file}: {name}" for file, name in _imports() if name.startswith(FORBIDDEN_PREFIXES)
    ]
    assert offenders == []
