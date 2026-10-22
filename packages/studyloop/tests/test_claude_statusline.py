"""The Claude Code status line treats every value it shows as data.

``agents/claude/study-statusline.sh`` is copied to ``~/.claude/`` by
``installers._configure_claude`` and Claude Code runs it on every render,
outside any tool-approval gate. Its inputs are the JSON Claude Code pipes on
stdin and ``~/.config/studyloop/session-state.json``, whose ``topic`` is free
text from ``studyloop session start --topic`` or ``POST /api/session/start``.
None of it may reach the shell as code (review finding F-OPS-01).

The injected payload spells its marker with shell arithmetic: executed, it
prints ``MARKER7731RAN``; shown verbatim as a topic, the status line carries
``MARKER$((7700+31))RAN``. That keeps "the topic is displayed" and "the topic
ran" distinguishable in one stdout.

Each test runs under every distinct bash on the machine: ``#!/usr/bin/env
bash`` resolves to macOS's bash 3.2 for anyone without a newer one on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

EXECUTED_MARKER = "MARKER7731RAN"
INJECTION = "x;echo MARKER$((7700+31))RAN"
SEPARATOR = " │ "


def _repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents/manifest.json").exists():
        root = root.parent
    return root


SCRIPT = _repo_root() / "agents/claude/study-statusline.sh"


def _bash_binaries() -> list[str]:
    found: list[str] = []
    seen: set[Path] = set()
    for candidate in (shutil.which("bash"), "/bin/bash"):
        if candidate is None or not Path(candidate).is_file():
            continue
        real = Path(candidate).resolve()
        if real not in seen:
            seen.add(real)
            found.append(candidate)
    return found


@pytest.fixture(params=_bash_binaries())
def bash(request: pytest.FixtureRequest) -> str:
    return request.param


def _render(
    bash: str,
    tmp_path: Path,
    *,
    state: dict[str, Any] | None = None,
    stdin: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the status line against a temporary HOME, never the real one."""
    home = tmp_path / "home"
    (home / ".config/studyloop").mkdir(parents=True)
    if state is not None:
        (home / ".config/studyloop/session-state.json").write_text(json.dumps(state))
    payload = {"model": {"display_name": "test"}} if stdin is None else stdin
    return subprocess.run(
        [bash, str(SCRIPT)],
        input=json.dumps(payload) + "\n",
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        cwd=tmp_path,
        timeout=10,
        check=False,
    )


def test_topic_with_shell_metacharacters_is_not_executed(bash: str, tmp_path: Path) -> None:
    result = _render(bash, tmp_path, state={"energy_label": "medium", "topic": INJECTION})

    assert result.returncode == 0, result.stderr
    assert EXECUTED_MARKER not in result.stdout + result.stderr
    assert INJECTION in result.stdout, f"topic not shown verbatim: {result.stdout!r}"


def test_multi_word_topic_renders(bash: str, tmp_path: Path) -> None:
    result = _render(bash, tmp_path, state={"energy_label": "medium", "topic": "SQL joins"})

    assert result.returncode == 0, result.stderr
    assert "SQL joins" in result.stdout


def test_model_field_from_stdin_is_not_executed(bash: str, tmp_path: Path) -> None:
    result = _render(bash, tmp_path, stdin={"model": {"display_name": INJECTION}})

    assert result.returncode == 0, result.stderr
    assert EXECUTED_MARKER not in result.stdout + result.stderr


def test_numeric_fields_from_stdin_are_not_evaluated(bash: str, tmp_path: Path) -> None:
    """A string where a number belongs must not reach shell arithmetic.

    Bash evaluates an array subscript inside ``$((...))``, so a value such as
    ``a[$(cmd)]`` used in arithmetic runs ``cmd`` even without ``eval``.
    """
    subscript = "a[$(echo MARKER$((7700+31))RAN >&2)]"
    result = _render(
        bash,
        tmp_path,
        stdin={
            "context_window": {"used_percentage": subscript},
            "cost": {"total_cost_usd": subscript, "total_duration_ms": subscript},
        },
    )

    assert result.returncode == 0, result.stderr
    assert EXECUTED_MARKER not in result.stdout + result.stderr


def test_control_characters_in_topic_cannot_shift_fields_or_reach_the_terminal(
    bash: str, tmp_path: Path
) -> None:
    """A NUL would split the topic into extra fields; an ESC would drive the terminal."""
    result = _render(
        bash,
        tmp_path,
        state={"energy_label": "medium", "topic": "a\u0000b\u001b[2Jc\nd"},
    )

    assert result.returncode == 0, result.stderr
    assert "\u001b[2J" not in result.stdout
    assert "Med" in result.stdout, f"energy lost to a shifted field: {result.stdout!r}"
    assert "ab[2Jcd" in result.stdout
    assert result.stdout.count("\n") == 1, f"status line is not one line: {result.stdout!r}"


def test_topic_backslashes_are_printed_literally(bash: str, tmp_path: Path) -> None:
    result = _render(bash, tmp_path, state={"energy_label": "medium", "topic": r"notes\new\c"})

    assert result.returncode == 0, result.stderr
    assert r"notes\new\c" in result.stdout
    assert result.stdout.count("\n") == 1, f"status line is not one line: {result.stdout!r}"


def test_segments_are_joined_with_box_drawing_separator(bash: str, tmp_path: Path) -> None:
    """Topic, energy, timer, context and cost: five segments, four separators."""
    result = _render(bash, tmp_path, state={"energy_label": "medium", "topic": "SQL"})

    assert result.returncode == 0, result.stderr
    assert result.stdout.count(SEPARATOR) == 4, f"segments not joined by │: {result.stdout!r}"


def test_script_reads_no_pomodoro_state() -> None:
    """The ``pomodoro`` segment had no writer, so it could never render.

    Nothing puts a ``pomodoro`` object in ``session-state.json``: the web
    timer is a browser-local Alpine store, and the only persisted
    pomodoro-related key is ``timer_mode``. A segment reading a key no writer
    produces is dead code that implies a feature the line does not have.
    """
    source = SCRIPT.read_text(encoding="utf-8").lower()

    assert "pomodoro" not in source
    assert "pomo_" not in source


def test_ended_session_shows_no_topic_or_energy(bash: str, tmp_path: Path) -> None:
    """An ended session's state file keeps its last topic and energy.

    ``session_state.write_session_state`` merges ``{"mode": "ended"}`` into
    the existing file, so the old ``topic`` and ``energy_label`` stay on disk
    until the next start. The line must not present them as current.
    """
    result = _render(
        bash,
        tmp_path,
        state={"mode": "ended", "energy_label": "high", "topic": "Stale topic"},
    )

    assert result.returncode == 0, result.stderr
    assert "Stale topic" not in result.stdout
    assert "🔋" not in result.stdout, f"energy shown for an ended session: {result.stdout!r}"
    assert result.stdout.count(SEPARATOR) == 2, f"expected timer, context, cost: {result.stdout!r}"


def test_live_session_still_shows_topic_and_energy(bash: str, tmp_path: Path) -> None:
    result = _render(
        bash, tmp_path, state={"mode": "focus", "energy_label": "high", "topic": "Live topic"}
    )

    assert result.returncode == 0, result.stderr
    assert "Live topic" in result.stdout
    assert "High" in result.stdout
