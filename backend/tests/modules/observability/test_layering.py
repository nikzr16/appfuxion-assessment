"""observability reads other modules only through their service / schema, and app.core
never imports a feature module (the recorder is a hook registered by app.main)."""

import ast
from pathlib import Path

import app.core as core
import app.modules.observability as observability


def _imports(package_dir: Path) -> list[tuple[str, str]]:
    """``(file, imported name)``; ``from a.b import c`` yields both ``a.b`` and ``a.b.c``."""
    found = []
    for path in package_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found += [(path.name, alias.name) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((path.name, node.module))
                found += [(path.name, f"{node.module}.{alias.name}") for alias in node.names]
    return found


def test_observability_uses_only_other_modules_service_and_schema() -> None:
    offenders = [
        f"{file}: {name}"
        for file, name in _imports(Path(observability.__file__).parent)
        if name.startswith("app.modules.")
        and not name.startswith("app.modules.observability")
        and name.split(".")[3:4] in (["crud"], ["model"])
    ]
    assert offenders == []


def test_core_imports_no_feature_module() -> None:
    offenders = [
        f"{file}: {name}"
        for file, name in _imports(Path(core.__file__).parent)
        if name.startswith("app.modules")
    ]
    assert offenders == []


def test_service_never_imports_fastapi() -> None:
    offenders = [
        name
        for file, name in _imports(Path(observability.__file__).parent)
        if file == "service.py" and name.startswith(("fastapi", "starlette"))
    ]
    assert offenders == []
