#!/usr/bin/env python3
"""SessionStart hook: auto-pull the shared harness core, then inject the
project-aware onboarding brief.

Claude Code runs this on a fresh session start (before any orchestration),
pipes session JSON (including `cwd`) on stdin, and injects the returned
`additionalContext` as a system-reminder. The text instructs the agent to lead
its first response with a short onboarding brief.

Core auto-pull (opt-in, safe):
  Before onboarding, this hook can refresh the reusable harness **core** (the
  files listed in `.claude/CORE.manifest`) from the GitHub template, so every
  project stays current without a manual merge. It is intentionally conservative:

  - It runs ONLY when a core source is configured — an `upstream` remote (name
    overridable via HARNESS_CORE_REMOTE) or a HARNESS_CORE_URL. The template repo
    itself has no `upstream`, so it safely no-ops there (never clobbers the
    maintainer's in-progress core work).
  - It updates ONLY core paths (from CORE.manifest) via `git checkout <src> --`,
    never project (`proj.*`) files, so there are no merge conflicts.
  - It regenerates CORE.manifest so the freshly pulled core passes the core-lock.
  - It fails safe and silent (no git / offline / no source / timeout → skip) and
    is fully disableable with HARNESS_NO_CORE_SYNC=1.

  Manual run / test:  python .claude/hooks/session_start.py --sync-core

Project-name agnostic by design: this repo is meant to be used as a GitHub
template, so the project name is derived at runtime from the working directory.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REMOTE = "upstream"
DEFAULT_BRANCH = "main"
FETCH_TIMEOUT = 25   # seconds
GIT_TIMEOUT = 15     # seconds per non-fetch git call


def read_payload() -> dict:
    """Best-effort parse of the hook JSON Claude Code pipes on stdin."""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def project_name(payload: dict) -> str:
    cwd = payload.get("cwd") or os.getcwd()
    name = os.path.basename(os.path.normpath(str(cwd)))
    return name or "this project"


def _git(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    """Run a git command best-effort; return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, "", "git unavailable or failed"


def _repo_root(start: Path) -> Path | None:
    rc, out, _ = _git(["rev-parse", "--show-toplevel"], start, GIT_TIMEOUT)
    if rc != 0 or not out:
        return None
    return Path(out)


def _core_paths(root: Path) -> list[str]:
    """Repo-relative core paths from .claude/CORE.manifest (skips comments)."""
    manifest = root / ".claude" / "CORE.manifest"
    if not manifest.is_file():
        return []
    paths: list[str] = []
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            rel = parts[1].replace("\\", "/")
            paths.append(f".claude/{rel}")
    return paths


def _resolve_source(root: Path) -> tuple[str, str] | None:
    """Return (fetch_target, ref) for the core source, or None if unconfigured.

    Prefers the configured remote (default `upstream`); falls back to
    HARNESS_CORE_URL. Never uses `origin` implicitly — that would let a project
    pull core from itself, or the template clobber its own work.
    """
    branch = os.environ.get("HARNESS_CORE_BRANCH", DEFAULT_BRANCH)
    remote = os.environ.get("HARNESS_CORE_REMOTE", DEFAULT_REMOTE)
    url = os.environ.get("HARNESS_CORE_URL", "").strip()

    rc, out, _ = _git(["remote"], root, GIT_TIMEOUT)
    remotes = set(out.split()) if rc == 0 else set()
    if remote in remotes:
        return remote, f"{remote}/{branch}"
    if url:
        return url, "FETCH_HEAD"
    return None


def sync_core(root: Path) -> str | None:
    """Refresh core from the configured source. Returns a short status note."""
    if os.environ.get("HARNESS_NO_CORE_SYNC", "").strip() in ("1", "true", "yes"):
        return None

    source = _resolve_source(root)
    if source is None:
        return None  # no core source configured → nothing to do (e.g. the template repo)

    core = _core_paths(root)
    if not core:
        return None

    fetch_target, ref = source
    branch = os.environ.get("HARNESS_CORE_BRANCH", DEFAULT_BRANCH)
    rc, _, err = _git(["fetch", "--quiet", fetch_target, branch], root, FETCH_TIMEOUT)
    if rc != 0:
        return f"[core-sync] skipped: could not fetch core ({err.splitlines()[0] if err else 'fetch failed'})."

    updated = 0
    failed = 0
    for path in core:
        rc, _, _ = _git(["checkout", ref, "--", path], root, GIT_TIMEOUT)
        if rc != 0:
            failed += 1
    # `git checkout <ref> -- <path>` stages the update, so compare against HEAD
    # (not the index) to detect which core files actually changed.
    rc, out, _ = _git(["diff", "--name-only", "HEAD", "--", *core], root, GIT_TIMEOUT)
    if rc == 0 and out:
        updated = len([ln for ln in out.splitlines() if ln.strip()])

    if updated:
        # Re-lock: regenerate CORE.manifest so the freshly pulled core validates.
        _regenerate_manifest(root)
        note = f"[core-sync] Updated {updated} core file(s) from {ref}; CORE.manifest re-locked. Review & commit the core update."
    else:
        note = f"[core-sync] Core already up to date with {ref}."
    if failed:
        note += f" ({failed} core path(s) not present upstream — skipped.)"
    return note


def _regenerate_manifest(root: Path) -> None:
    script = root / ".claude" / "skills" / "validate-config" / "scripts" / "validate_config.py"
    if not script.is_file():
        return
    try:
        subprocess.run(
            [sys.executable, str(script), "--update-core-manifest"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def build_context(name: str, sync_note: str | None) -> str:
    base = (
        "[HARNESS ONBOARDING - first response only]\n"
        f"You are working in the project '{name}', which is scaffolded on the "
        "Orchestral Harness: a hands-off agent-orchestration template (the harness "
        "is the framework, not the project's name). UNLESS the user's first message "
        "is already a concrete task, begin your first response with a brief "
        "(<=5 lines) orientation, then offer to help:\n"
        "- What this is: a hands-off agent-orchestration harness that routes your "
        "requests to the right agents and workflows — just describe work in plain "
        "language; no @agent or skill tagging.\n"
        "- Routing: trivial edits run directly; features/changes/bugs route through the "
        "orchestrator, which runs the matching workflow from .claude/workflows/registry.yml "
        "(or the built-in ad-hoc route, since the registry ships routeless).\n"
        "- Author a workflow: mention a 'workflow' (aka cycle/pipeline) and the "
        "workflow-author agent scaffolds, validates, and registers it.\n"
        "- Point to README.md and CLAUDE.md for more.\n"
        "Show this only once per session; if the user opens with a concrete task, skip "
        "the greeting and just do the work."
    )
    if sync_note:
        base += (
            "\n\n[HARNESS CORE-SYNC - mention only if core changed]\n" + sync_note +
            "\nIf core files were updated, briefly tell the user so they can review/commit; "
            "otherwise stay silent about core-sync."
        )
    return base


def main() -> int:
    if "--sync-core" in sys.argv[1:]:
        root = _repo_root(Path.cwd()) or Path.cwd()
        note = sync_core(root)
        print(note or "[core-sync] No core source configured (set an 'upstream' remote "
              "or HARNESS_CORE_URL). Nothing to do.")
        return 0

    payload = read_payload()
    name = project_name(payload)
    root = _repo_root(Path(str(payload.get("cwd") or os.getcwd())))
    sync_note = None
    if root is not None:
        try:
            sync_note = sync_core(root)
        except Exception:  # never let core-sync break session start
            sync_note = None
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": build_context(name, sync_note),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
