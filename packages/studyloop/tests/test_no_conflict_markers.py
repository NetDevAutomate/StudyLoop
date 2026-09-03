"""Guard: no merge-conflict markers survive in tracked text files (R-82).

Why this exists
---------------
A merge resolution during the 2026-09 remediation removed the ``<<<<<<<``,
``=======`` and ``>>>>>>>`` lines from ``CHANGELOG.md`` but left the diff3
*base* marker (``||||||| <sha>``) and the base block behind. Nothing caught it:
pre-commit's ``check-merge-conflict`` hook only knows the three two-way
markers, and it only runs while a merge is in progress. This test scans every
tracked text file on every run, so a marker cannot travel further than the
commit that introduced it.

The bare ``=======`` line is deliberately NOT a marker here: it is a legal
setext heading underline in Markdown and a section adornment in
reStructuredText, and the other three markers always accompany it in a real
conflict. Eight-or-more repeated characters (``<<<<<<<<``) are not markers
either; git writes exactly seven.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Exactly seven of `<`, `>` or `|`, then a space (git appends a label) or end
# of line. Written with quantifiers so this file never matches itself.
CONFLICT_MARKER = re.compile(r"^(?:<{7}|>{7}|\|{7})(?: |$)")

# Files whose whole point is to hold diffs or binaries.
_SKIP_SUFFIXES = frozenset(
    {".diff", ".patch", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp"}
    | {".woff", ".woff2", ".pdf", ".db"}
)


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:  # not a checkout, or no git
        pytest.skip(f"git ls-files unavailable: {exc}")
    return [REPO_ROOT / p.decode() for p in out.split(b"\0") if p]


def _marker_hits(path: Path, *, root: Path = REPO_ROOT) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError:  # deleted-but-tracked, dangling symlink
        return []
    if b"\0" in raw[:8192]:  # binary
        return []
    text = raw.decode("utf-8", errors="replace")
    return [
        f"{path.relative_to(root)}:{n}: {line[:60]}"
        for n, line in enumerate(text.splitlines(), start=1)
        if CONFLICT_MARKER.match(line)
    ]


def test_tracked_text_files_contain_no_conflict_markers() -> None:
    hits: list[str] = []
    for path in _tracked_files():
        if path.suffix.lower() in _SKIP_SUFFIXES or not path.is_file():
            continue
        hits.extend(_marker_hits(path))
    assert not hits, "merge-conflict markers in tracked files:\n" + "\n".join(hits)


@pytest.mark.parametrize(
    "line",
    ["<<<<<<< HEAD", ">>>>>>> lane/m2-session-authority", "||||||| 22a91e6", "<<<<<<<", "|||||||"],
)
def test_marker_regex_matches_all_three_git_markers(line: str) -> None:
    assert CONFLICT_MARKER.match(line)


@pytest.mark.parametrize(
    "line",
    ["=======", "<<<<<<<< eight", "<<<<<<", " <<<<<<< indented", "||| short", "text <<<<<<< HEAD"],
)
def test_marker_regex_ignores_non_markers(line: str) -> None:
    assert not CONFLICT_MARKER.match(line)


def test_marker_scan_reports_file_and_line(tmp_path: Path) -> None:
    """The failure message must point at the offending line, not just the file."""
    bad = tmp_path / "CHANGELOG.md"
    bad.write_text(
        "# Changelog\n\n||||||| 22a91e6\nold base text\n>>>>>>> theirs\n",
        encoding="utf-8",
    )
    assert _marker_hits(bad, root=tmp_path) == [
        "CHANGELOG.md:3: ||||||| 22a91e6",
        "CHANGELOG.md:5: >>>>>>> theirs",
    ]


def test_binary_files_are_skipped(tmp_path: Path) -> None:
    blob = tmp_path / "image.bin"
    blob.write_bytes(b"\x00\x01<<<<<<< HEAD\n")
    assert _marker_hits(blob, root=tmp_path) == []
