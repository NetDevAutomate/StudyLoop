"""Git operations for the evaluation harness."""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[4]  # up to repo root


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_DIR,
        check=False,
    )


def is_clean() -> bool:
    """True if working tree has no uncommitted changes."""
    r = _git("status", "--porcelain")
    return r.returncode == 0 and r.stdout.strip() == ""


def short_hash() -> str:
    """Current HEAD short hash (7 chars)."""
    r = _git("rev-parse", "--short=7", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def abort_if_dirty(*, allow_override: bool = False) -> None:
    """Raise click.ClickException if working tree is dirty."""
    if allow_override:
        return
    if not is_clean():
        import click

        raise click.ClickException(
            "Working tree is not clean. Commit or stash changes first.\n"
            "Use --no-git-check to skip this check."
        )
