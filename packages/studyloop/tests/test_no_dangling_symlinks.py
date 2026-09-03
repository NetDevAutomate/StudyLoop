"""R-66 guard: no tracked symlink may point at a target that does not exist.

`GEMINI.md` -> `agents/gemini/GEMINI.md` was exactly this defect: `git
ls-files -s` shows mode `120000` (a symlink) but `agents/gemini/` was deleted
when Gemini CLI was retired as a mentor harness, leaving a broken link that
`ls -la` (and anything that follows it, like a docs build or an editor)
reports as dangling on every checkout.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _tracked_symlink_paths() -> list[str]:
    """Every path `git ls-files -s` reports with mode 120000 (a symlink)."""
    paths = []
    for line in _git("ls-files", "-s").splitlines():
        mode, rest = line.split(" ", 1)
        if mode != "120000":
            continue
        # "<sha> <stage>\t<path>"
        paths.append(rest.split("\t", 1)[1])
    return paths


def test_at_least_one_tracked_symlink_exists() -> None:
    """Sanity check that this test would actually catch a regression --

    without this, a change that untracked every symlink would make the real
    assertion below vacuously pass.
    """
    assert _tracked_symlink_paths(), "no tracked symlinks found; is git ls-files -s broken here?"


def test_no_tracked_symlink_is_dangling() -> None:
    dangling = [path for path in _tracked_symlink_paths() if not (REPO_ROOT / path).exists()]
    assert not dangling, f"dangling tracked symlink(s): {dangling}"
