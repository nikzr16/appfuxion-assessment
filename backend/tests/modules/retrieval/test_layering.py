"""retrieval reads other modules only through their service / schema and never imports the
agent (one-way dependency, PRD 0010 D1)."""

import ast
from pathlib import Path

import app.modules.retrieval as retrieval

# The back-fill command is an entry point (like ``app.main``): it wires the ledger recorder.
LAYERS = {"router.py", "service.py", "schema.py", "crud.py", "model.py", "rules.py"}


def _imports() -> list[tuple[str, str]]:
    found = []
    for path in Path(retrieval.__file__).parent.glob("*.py"):
        if path.name not in LAYERS:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found += [(path.name, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((path.name, node.module))
                found += [(path.name, f"{node.module}.{alias.name}") for alias in node.names]
    return found


def test_retrieval_uses_only_other_modules_service_and_schema() -> None:
    offenders = [
        f"{file}: {name}"
        for file, name in _imports()
        if name.startswith("app.modules.")
        and not name.startswith("app.modules.retrieval")
        and len(name.split(".")) > 3
        and name.split(".")[3] not in ("service", "schema")
    ]
    assert offenders == []


def test_retrieval_never_imports_the_agent_or_observability() -> None:
    offenders = [
        f"{file}: {name}"
        for file, name in _imports()
        if name.startswith(("app.modules.agent", "app.modules.observability"))
    ]
    assert offenders == []


def test_service_and_rules_never_import_fastapi() -> None:
    offenders = [
        name
        for file, name in _imports()
        if file in ("service.py", "rules.py") and name.startswith(("fastapi", "starlette"))
    ]
    assert offenders == []


def test_other_modules_use_only_retrieval_service_and_schema() -> None:
    root = Path(retrieval.__file__).parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if path.is_relative_to(root / "retrieval"):
            continue
        text = path.read_text(encoding="utf-8")
        for name in ("rules", "crud", "model"):
            if f"app.modules.retrieval.{name}" in text or f"retrieval import {name}" in text:
                offenders.append(f"{path.name}: {name}")
    assert offenders == []
