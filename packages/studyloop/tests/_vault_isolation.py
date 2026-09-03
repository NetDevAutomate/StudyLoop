"""Second-brain vault isolation: the real vault must be unreachable (R-84).

Kept out of ``conftest.py`` for the same reason ``_lane_ownership.py`` and
``_readiness.py`` are: the rules here are the subject of a guard test
(``test_obsidian_vault_isolation.py``), and a test cannot import symbols from a
conftest in a way a type checker can resolve — there is more than one
``conftest`` on the path.

The hazard this closes is the sharpest of the three isolation guards in this
suite. ``~/.config/studyloop`` holds caches and state; the vault holds notes the
learner wrote by hand, and the second-brain layer's whole purpose is to write
files into it. A test that falls through does not corrupt a cache.
"""

from __future__ import annotations

from pathlib import Path

#: The home directory this process really started with, captured at import time,
#: before any fixture can redirect ``HOME``.
REAL_HOME = Path.home()

#: The default vault root a learner gets when nothing in the config names one.
REAL_VAULT_ROOT = REAL_HOME / "Obsidian" / "Personal"

#: Only the StudyLoop-owned folder is watched, deliberately.
#:
#: Watching the whole vault would fail runs for reasons that have nothing to do
#: with StudyLoop: Obsidian itself rewrites ``.obsidian/workspace.json`` while
#: the suite runs, and a synced vault changes under the developer's feet. A guard
#: that cries wolf is a guard developers learn to ignore, which is worse than no
#: guard — the same reasoning the session-runtime snapshot in ``conftest.py``
#: gives for watching a named surface rather than the whole config directory.
REAL_VAULT_WATCHED_NAMES = ("Study",)

#: Test-only override of the default vault root, read at call time by
#: ``studyloop.settings._default_second_brain_vault`` and by the resolution
#: chain in ``_resolve_second_brain``.
VAULT_ENV = "STUDYLOOP_SECOND_BRAIN_VAULT"


def is_under_real_home(candidate: object) -> bool:
    """True when ``candidate`` resolves inside the process's original home.

    Shared by the guard test and the session-finish backstop so the two cannot
    disagree about what "the real home" means.
    """
    if candidate in (None, ""):
        return False
    try:
        Path(str(candidate)).expanduser().resolve().relative_to(REAL_HOME.resolve())
    except (ValueError, OSError):
        return False
    return True


def snapshot_real_vault() -> dict[str, float]:
    """List the watched surface of the real vault with mtimes.

    Names AND mtimes, so an in-place rewrite of an existing projection is caught
    as well as a new file. A missing root, or a missing entry, contributes
    nothing — there is nothing to violate yet.
    """
    snapshot: dict[str, float] = {}
    for name in REAL_VAULT_WATCHED_NAMES:
        entry = REAL_VAULT_ROOT / name
        if not entry.exists():
            continue
        paths = [entry] if entry.is_file() else [entry, *entry.rglob("*")]
        for path in paths:
            try:
                snapshot[str(path)] = path.stat().st_mtime
            except OSError:
                continue
    return snapshot


def describe_vault_drift(before: dict[str, float], after: dict[str, float]) -> str:
    """Render the difference between two snapshots for a failure message."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in (set(after) & set(before)) if after[p] != before[p])
    lines = []
    if added:
        lines.append(f"  created: {added}")
    if removed:
        lines.append(f"  removed: {removed}")
    if changed:
        lines.append(f"  modified: {changed}")
    return "\n".join(lines)
