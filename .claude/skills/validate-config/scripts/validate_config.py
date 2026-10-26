#!/usr/bin/env python3
"""Validate the .claude harness configuration.

Checks agents, skills, workflows, and registry.yml for internal consistency so a
broken workflow can never be registered. This is the ONE deterministic guarantee
in the harness (everything else is orchestrator prompt-adherence).

Exit policy (G-F): exit non-zero on ERRORS only. Warnings are informational and
never block registration.

Core-lock (reuse across projects): the reusable harness "core" (its stock
agents, skills, workflow template, glossary, hook, and this validator) is
checksum-locked via `.claude/CORE.manifest`. A full scan ERRORS if any core file
drifts, so project work can never silently mutate the shared harness. Project
capabilities live in the same flat folders but MUST be namespaced (`proj.*`
agents, `proj-*` skills/workflows) so they never collide with core.

Usage:
    python validate_config.py                        # full-config scan (verification / CI)
    python validate_config.py <path>                 # incremental: validate one workflow file
    python validate_config.py --update-core-manifest # (harness maintainers) rewrite CORE.manifest
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML is required (pip install pyyaml).\n")
    raise SystemExit(2)

# Emit UTF-8 regardless of the host console code page (Windows-safe).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

CLAUDE_DIR = Path(__file__).resolve().parents[3]
AGENTS_DIR = CLAUDE_DIR / "agents"
SKILLS_DIR = CLAUDE_DIR / "skills"
WORKFLOWS_DIR = CLAUDE_DIR / "workflows"
REGISTRY = WORKFLOWS_DIR / "registry.yml"
CORE_MANIFEST = CLAUDE_DIR / "CORE.manifest"

RESERVED_AGENTS = {"orchestrator", "workflow-author"}
VALID_FALLBACKS = {"adhoc"}
VALID_STEP_TYPES = {"agent", "manual"}
KNOWN_AGENT_FIELDS = {
    "name", "description", "model", "tools", "disallowedTools", "skills",
}

# Namespacing convention that separates project capabilities from the shared
# core (see the core-lock docstring). Project files must use these prefixes.
PROJECT_AGENT_PREFIX = "proj."      # e.g. agents/proj.deploy.md
PROJECT_SKILL_PREFIX = "proj-"      # e.g. skills/proj-deploy/SKILL.md
PROJECT_WORKFLOW_PREFIX = "proj-"   # e.g. workflows/proj-release.yml

# The canonical list of reusable-core files, relative to .claude/. This is the
# source of truth for "what is core"; CORE.manifest stores their checksums.
# registry.yml is intentionally NOT core: projects edit it to register routes.
CORE_FILES = [
    "agents/orchestrator.md",
    "agents/executor.md",
    "agents/workflow-author.md",
    "agents/mcp-connector.md",
    "skills/analyze-requirements/SKILL.md",
    "skills/author-workflow/SKILL.md",
    "skills/execute-plan/SKILL.md",
    "skills/generate-workflow/SKILL.md",
    "skills/mcp-connector/SKILL.md",
    "skills/validate-config/SKILL.md",
    "skills/validate-config/scripts/validate_config.py",
    "workflows/_template.yml",
    "workflows/README.md",
    "GLOSSARY.md",
    "hooks/session_start.py",
]

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def parse_frontmatter(path: Path) -> dict | None:
    """Return the YAML frontmatter of a markdown file, or None if absent/invalid."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        err(f"{path.name}: missing YAML frontmatter (--- fence)")
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        err(f"{path.name}: malformed frontmatter (no closing ---)")
        return None
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        err(f"{path.name}: unparseable frontmatter: {exc}")
        return None
    if not isinstance(data, dict):
        err(f"{path.name}: frontmatter is not a mapping")
        return None
    return data


def load_agents() -> dict[str, dict]:
    agents: dict[str, dict] = {}
    if not AGENTS_DIR.is_dir():
        return agents
    for path in sorted(AGENTS_DIR.glob("*.md")):
        data = parse_frontmatter(path)
        if data is None:
            continue
        name = data.get("name")
        if not name:
            err(f"{path.name}: agent missing required 'name'")
            continue
        if not data.get("description"):
            err(f"{path.name}: agent '{name}' missing required 'description'")
        for field in data:
            if field not in KNOWN_AGENT_FIELDS:
                warn(f"{path.name}: unknown agent field '{field}'")
        agents[name] = data
    return agents


def load_skills() -> tuple[set[str], int]:
    """Return (resolvable skill identifiers, distinct skill count)."""
    skills: set[str] = set()
    slugs: set[str] = set()
    if not SKILLS_DIR.is_dir():
        return skills, 0
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        data = parse_frontmatter(skill_md)
        slug = skill_md.parent.name
        slugs.add(slug)
        if data is None:
            continue
        name = data.get("name", slug)
        if not data.get("description"):
            warn(f"{slug}/SKILL.md: skill missing 'description'")
        skills.add(name)
        skills.add(slug)
    return skills, len(slugs)


def check_agent_skill_refs(agents: dict[str, dict], skills: set[str]) -> None:
    for name, data in agents.items():
        for ref in data.get("skills", []) or []:
            if ref not in skills:
                err(f"agent '{name}': references unknown skill '{ref}'")


def is_gated(step: dict) -> bool:
    return "on_complete" in step and isinstance(step["on_complete"], dict)


def validate_workflow(path: Path, agents: dict[str, dict], skills: set[str]) -> None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        err(f"{path.name}: unparseable YAML: {exc}")
        return
    if not isinstance(data, dict):
        err(f"{path.name}: top-level YAML is not a mapping")
        return
    if not data.get("name"):
        warn(f"{path.name}: workflow missing 'name'")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        err(f"{path.name}: workflow has no 'steps' list")
        return

    step_ids = {s.get("id") for s in steps if isinstance(s, dict)}
    for step in steps:
        if not isinstance(step, dict):
            err(f"{path.name}: a step is not a mapping")
            continue
        sid = step.get("id", "<no-id>")

        step_type = step.get("type", "agent")
        if step_type not in VALID_STEP_TYPES:
            err(f"{path.name}:{sid}: unknown step type '{step_type}' (expected {sorted(VALID_STEP_TYPES)})")

        agent = step.get("agent")
        if step_type == "manual":
            if agent is not None:
                warn(f"{path.name}:{sid}: manual step ignores 'agent' (it escalates to the user)")
        elif agent is None:
            err(f"{path.name}:{sid}: agent step (type 'agent') missing required 'agent'")
        elif agent in RESERVED_AGENTS:
            err(f"{path.name}:{sid}: recursion guard - step may not spawn '{agent}'")
        elif agent not in agents:
            err(f"{path.name}:{sid}: references unknown agent '{agent}'")

        skill = step.get("skill")
        if skill is not None and skill not in skills:
            err(f"{path.name}:{sid}: references unknown skill '{skill}'")

        for dep in step.get("requires", []) or []:
            if dep not in step_ids:
                err(f"{path.name}:{sid}: requires unknown step '{dep}'")
        for par in step.get("parallel_with", []) or []:
            if par not in step_ids:
                err(f"{path.name}:{sid}: parallel_with unknown step '{par}'")

        if is_gated(step):
            contract = step.get("verdict_contract")
            if not contract or not isinstance(contract, list):
                err(f"{path.name}:{sid}: gated step (on_complete) missing 'verdict_contract' token list")
            else:
                for key in step["on_complete"]:
                    if key not in contract and key not in {"pass", "fail", "done"}:
                        warn(f"{path.name}:{sid}: on_complete key '{key}' not in verdict_contract")


def validate_registry(agents: dict[str, dict], skills: set[str]) -> None:
    if not REGISTRY.is_file():
        err("registry.yml: missing (routing source of truth)")
        return
    try:
        data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        err(f"registry.yml: unparseable YAML: {exc}")
        return

    fallback = data.get("fallback")
    if fallback not in VALID_FALLBACKS:
        err(f"registry.yml: fallback '{fallback}' not in {sorted(VALID_FALLBACKS)}")

    routes = data.get("routes") or []
    if not isinstance(routes, list):
        err("registry.yml: 'routes' must be a list")
        return
    if not routes:
        warn("registry.yml: no routes defined (all requests use the ad-hoc fallback)")
        return

    seen: set[str] = set()
    for route in routes:
        if not isinstance(route, dict):
            err("registry.yml: a route is not a mapping")
            continue
        rid = route.get("id", "<no-id>")
        if rid in seen:
            err(f"registry.yml: duplicate route id '{rid}'")
        seen.add(rid)

        wf = route.get("workflow")
        if not wf:
            err(f"registry.yml:{rid}: route missing 'workflow'")
            continue
        if wf.startswith("_"):
            err(f"registry.yml:{rid}: route points at non-routable '_'-prefixed '{wf}'")
        wf_path = WORKFLOWS_DIR / wf
        if not wf_path.is_file():
            err(f"registry.yml:{rid}: workflow file '{wf}' not found")
        else:
            validate_workflow(wf_path, agents, skills)


def routable_workflows() -> list[Path]:
    return [
        p for p in sorted(WORKFLOWS_DIR.glob("*.yml"))
        if not p.name.startswith("_") and p.name != "registry.yml"
    ]


def core_digest(path: Path) -> str:
    """Newline-normalized sha256 so checksums are stable across OS/git autocrlf."""
    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_core_manifest() -> dict[str, str]:
    """Return {relpath: sha256} from CORE.manifest ('<sha256>  <relpath>' lines)."""
    entries: dict[str, str] = {}
    if not CORE_MANIFEST.is_file():
        return entries
    for raw in CORE_MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            err(f"CORE.manifest: malformed line: {raw!r}")
            continue
        digest, rel = parts
        entries[rel.replace("\\", "/")] = digest
    return entries


def write_core_manifest() -> int:
    """(Re)generate CORE.manifest from CORE_FILES. For harness maintainers only."""
    lines = [
        "# CORE.manifest - checksums of the reusable harness core. DO NOT edit by hand.",
        "# Regenerate (harness maintainers only) with:",
        "#   python .claude/skills/validate-config/scripts/validate_config.py --update-core-manifest",
        "# Format: <sha256>  <relpath-from-.claude>",
        "",
    ]
    missing = 0
    for rel in CORE_FILES:
        path = CLAUDE_DIR / rel
        if not path.is_file():
            sys.stderr.write(f"WARNING: core file listed but missing: {rel}\n")
            missing += 1
            continue
        lines.append(f"{core_digest(path)}  {rel}")
    CORE_MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {CORE_MANIFEST} ({len(CORE_FILES) - missing} core files, {missing} missing).")
    return 1 if missing else 0


def check_core_integrity() -> None:
    """HARD lock: error if any manifest-listed core file is missing or modified."""
    manifest = load_core_manifest()
    if not manifest:
        warn("CORE.manifest: missing - core-lock disabled "
             "(create it with --update-core-manifest)")
        return
    for rel, expected in sorted(manifest.items()):
        path = CLAUDE_DIR / rel
        if not path.is_file():
            err(f"core file missing: {rel} (locked by CORE.manifest)")
            continue
        if core_digest(path) != expected:
            err(f"core file modified: {rel} - the shared harness core is locked. "
                f"Put changes in a namespaced project capability ({PROJECT_AGENT_PREFIX}* "
                f"agent / {PROJECT_SKILL_PREFIX}* skill), or, if you maintain the harness, "
                f"run --update-core-manifest.")


def check_namespacing(manifest: dict[str, str]) -> None:
    """Warn if a non-core capability is not namespaced as a project capability."""
    core_rel = set(manifest) or set(CORE_FILES)
    for path in sorted(AGENTS_DIR.glob("*.md")):
        rel = f"agents/{path.name}"
        if rel in core_rel:
            continue
        if not path.name.startswith(PROJECT_AGENT_PREFIX):
            warn(f"agents/{path.name}: non-core agent should be namespaced "
                 f"'{PROJECT_AGENT_PREFIX}{path.name}' to stay separate from core")
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        rel = f"skills/{skill_md.parent.name}/SKILL.md"
        if rel in core_rel:
            continue
        if not skill_md.parent.name.startswith(PROJECT_SKILL_PREFIX):
            warn(f"skills/{skill_md.parent.name}: non-core skill should be namespaced "
                 f"'{PROJECT_SKILL_PREFIX}{skill_md.parent.name}' to stay separate from core")
    for wf in routable_workflows():
        rel = f"workflows/{wf.name}"
        if rel in core_rel:
            continue
        if not wf.name.startswith(PROJECT_WORKFLOW_PREFIX):
            warn(f"workflows/{wf.name}: non-core workflow should be namespaced "
                 f"'{PROJECT_WORKFLOW_PREFIX}{wf.name}' to stay separate from core")


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "--update-core-manifest":
        return write_core_manifest()

    agents = load_agents()
    skills, skill_count = load_skills()
    check_agent_skill_refs(agents, skills)

    if len(argv) > 1:
        target = Path(argv[1]).resolve()
        if not target.is_file():
            err(f"target '{target}' not found")
        elif target.name.startswith("_"):
            print(f"Skipped '_'-prefixed (non-routable) file: {target.name}")
        else:
            validate_workflow(target, agents, skills)
    else:
        check_core_integrity()
        check_namespacing(load_core_manifest())
        validate_registry(agents, skills)
        for wf in routable_workflows():
            validate_workflow(wf, agents, skills)

    print("=" * 60)
    print(f"agents: {len(agents)}  skills: {skill_count}")
    for w in warnings:
        print(f"  WARNING  {w}")
    for e in errors:
        print(f"  ERROR    {e}")
    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"OK: 0 errors, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
