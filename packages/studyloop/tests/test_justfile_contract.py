"""Contract tests for the Justfile's workspace-sync recipes."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
JUSTFILE = REPO_ROOT / "Justfile"
SYNC_RECIPES = ("sync-dev", "sync-full", "sync-web", "sync-content", "sync-semantic")
ASSIGNMENT = re.compile(r"^(?:export\s+|set\s+|alias\s+)?[A-Za-z0-9_-]+\s*:=")
RECIPE_HEADER = re.compile(r"^@?(?P<name>[A-Za-z0-9_-]+)[^:]*:")


def _recipe_bodies() -> dict[str, list[str]]:
    """Map each recipe name to the command lines of its indented body."""
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in JUSTFILE.read_text(encoding="utf-8").splitlines():
        if line[:1] in (" ", "\t"):
            if current is not None and line.strip() and not line.lstrip().startswith("#"):
                bodies[current].append(line.strip())
            continue
        match = None if ASSIGNMENT.match(line) else RECIPE_HEADER.match(line)
        current = match.group("name") if match else None
        if current is not None:
            bodies[current] = []
    return bodies


def test_sync_recipes_preserve_existing_extras() -> None:
    """A plain ``uv sync`` removes every package the requested extras do not
    need, so ``just sync-full`` followed by ``just sync-semantic`` silently
    strips the web and content extras from the same ``.venv``. ``install.sh``
    and ``install_workspace_tools`` already pass ``--inexact`` for this
    reason; the developer-facing recipes must too."""
    bodies = _recipe_bodies()
    missing = [name for name in SYNC_RECIPES if name not in bodies]
    assert missing == [], f"sync recipes not found in the Justfile: {missing}"

    for name in SYNC_RECIPES:
        syncs = [line for line in bodies[name] if line.startswith("uv sync")]
        assert syncs, f"{name} no longer runs uv sync?"
        exact = [line for line in syncs if "--inexact" not in line.split()]
        assert exact == [], f"{name} would remove extras the developer synced: {exact}"


AUDIT_RECIPES = ("audit", "audit-full")
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _ci_pip_audit_pin() -> str:
    """The ``pip-audit@<version>`` CI runs; the recipes must run the same release."""
    pins = set(re.findall(r"pip-audit@(\d+\.\d+\.\d+)", CI_WORKFLOW.read_text(encoding="utf-8")))
    assert len(pins) == 1, f"ci.yml must pin pip-audit once, found {sorted(pins)}"
    return pins.pop()


def test_audit_recipes_match_the_ci_audit_jobs() -> None:
    """``just audit`` / ``just audit-full`` are the local mirror of CI's ``audit`` and
    ``audit-full`` jobs. Three ways they used to disagree, each of which makes a
    local pass worthless as evidence that CI would pass: an unpinned
    ``uv tool run pip-audit`` (CI pins the release), a fixed ``/tmp`` path shared
    by every concurrent run on the machine (CI uses the per-job ``runner.temp``),
    and an ``--ignore-vuln`` that CI does not pass (the recipe was green on an
    advisory CI was red on)."""
    bodies = _recipe_bodies()
    missing = [name for name in AUDIT_RECIPES if name not in bodies]
    assert missing == [], f"audit recipes not found in the Justfile: {missing}"
    pin = _ci_pip_audit_pin()

    for name in AUDIT_RECIPES:
        body = " ".join(bodies[name])
        assert f"pip-audit@{pin}" in body, f"{name} must run pip-audit@{pin}, CI's release: {body}"
        assert "/tmp/" not in body, f"{name} still writes a fixed /tmp path: {body}"
        assert "--ignore-vuln" not in body, (
            f"{name} ignores an advisory CI does not; add it to CI with a reason or drop it: {body}"
        )
