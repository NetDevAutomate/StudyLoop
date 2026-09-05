"""The openspec early-warning hook: block release actions, warn on commits.

Drives ``scripts/openspec-gate.py`` in a subprocess with the same stdin JSON
shape every harness sends (``tool_input.command``), against fixture git repos
where the release guard genuinely fails and genuinely passes — so both the
exit-2 branch and the fail-open contract are proven, not assumed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[3] / "scripts" / "openspec-gate.py"
CONSISTENCY = GATE.parent / "check-release-consistency.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(cwd),
        },
        timeout=60,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repo with an UNARCHIVED, UNDEFERRED change committed after the tag —
    the exact state the 0.2.0 cut shipped in."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    # The gate imports the guard from the repo under test, so the fixture
    # carries the REAL script — a stub here would test the stub.
    (root / "scripts" / "check-release-consistency.py").write_text(
        CONSISTENCY.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "seed.txt").write_text("seed")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "seed")
    _git(root, "tag", "v0.0.1")
    change = root / "openspec" / "changes" / "unshipped-thing"
    change.mkdir(parents=True)
    (change / "proposal.md").write_text("## Why\n")
    _git(root, "add", "openspec")
    _git(root, "commit", "-qm", "work on unshipped-thing")
    return root


def _run_gate(repo_root: Path, command: str, mode: str = "pre-tool-use"):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(GATE), mode, "--repo-root", str(repo_root)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_release_actions_are_blocked_when_the_guard_fails(repo: Path) -> None:
    for command in ("git tag v0.0.2", "uv run python scripts/prepare-release.py 0.0.2"):
        result = _run_gate(repo, command)
        assert result.returncode == 2, f"{command!r} was not blocked: {result.stdout}"
        assert "unshipped-thing" in result.stderr
        assert "release-check" in result.stderr, "the block must name the hard gate"


def test_commits_are_warned_never_blocked(repo: Path) -> None:
    result = _run_gate(repo, "git commit -m 'normal cycle work'")
    assert result.returncode == 0, "a commit was blocked — open changes are legal in a cycle"
    assert "unshipped-thing" in result.stdout


def test_unrelated_commands_pass_silently(repo: Path) -> None:
    result = _run_gate(repo, "ls -la && pytest -q")
    assert result.returncode == 0
    assert result.stdout == ""


def test_deferred_change_unblocks_the_release_action(repo: Path) -> None:
    meta = repo / "openspec" / "changes" / "unshipped-thing" / ".openspec.yaml"
    meta.write_text("deferred: waiting on the transport decision\n")
    _git(repo, "add", str(meta.relative_to(repo)))
    _git(repo, "commit", "-qm", "defer it")

    result = _run_gate(repo, "git tag v0.0.2")
    assert result.returncode == 0, result.stderr


def test_remind_mode_is_terse_and_never_blocks(repo: Path) -> None:
    result = _run_gate(repo, "", mode="remind")
    assert result.returncode == 0
    assert "unshipped-thing" in result.stdout
    assert len(result.stdout.splitlines()) == 1


def test_garbage_stdin_fails_open(repo: Path) -> None:
    """A broken early warning must never block work the hard gate allows."""
    result = subprocess.run(
        [sys.executable, str(GATE), "pre-tool-use", "--repo-root", str(repo)],
        input="not json at all {",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0


def test_the_wrappers_call_the_same_one_body() -> None:
    """Three harness wrappers, one script — the xTiles skill's hub pattern.
    A wrapper drifting to its own logic is exactly what this pins against."""
    repo_root = GATE.parents[1]
    wrappers = [
        repo_root / ".kiro" / "hooks" / "openspec-gate.json",
        repo_root / ".claude" / "settings.json",
        repo_root / ".codex" / "hooks.json",
    ]
    for wrapper in wrappers:
        assert wrapper.is_file(), f"missing hook wrapper: {wrapper}"
        text = wrapper.read_text(encoding="utf-8")
        assert "scripts/openspec-gate.py" in text, f"{wrapper} does not call the one body"
    # And the one body says what it is: early warning, with per-harness
    # verification state — never "enforcement".
    body = GATE.read_text(encoding="utf-8")
    assert "NOT ENFORCEMENT" in body
    assert "release-check" in body
