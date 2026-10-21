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
