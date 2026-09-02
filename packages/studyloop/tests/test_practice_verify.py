"""Tests for practice task verification."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from studyloop.cli._practice import practice_group
from studyloop.learning import practice

if TYPE_CHECKING:
    from pathlib import Path


def _practice_file(tmp_path: Path, verification: dict) -> Path:
    path = tmp_path / "deck-practice.json"
    path.write_text(
        json.dumps(
            {
                "title": "Python Practice",
                "tasks": [
                    {
                        "taskType": "build",
                        "prompt": "Build a tiny decorator.",
                        "setup": "",
                        "successCriteria": ["It wraps a function."],
                        "hint": "",
                        "expectedLearningOutcome": "decorator wrapper",
                        "verification": verification,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _attempt_db(tmp_path: Path) -> Path:
    db = tmp_path / "sessions.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE practice_attempts (
            id TEXT PRIMARY KEY,
            practice_path TEXT NOT NULL,
            task_index INTEGER NOT NULL,
            task_prompt TEXT NOT NULL,
            verification_kind TEXT NOT NULL,
            passed INTEGER NOT NULL,
            notes TEXT,
            command TEXT,
            exit_code INTEGER,
            stdout TEXT,
            stderr TEXT,
            duration_seconds REAL,
            expected_artifacts TEXT,
            missing_artifacts TEXT,
            workdir TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def _patch_db(monkeypatch, db: Path) -> None:
    def connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(practice._connection, "_connect", connect)


def test_checklist_verification_records_attempt(monkeypatch, tmp_path: Path) -> None:
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    monkeypatch.setattr(practice, "record_progress", lambda **kwargs: True)
    deck = _practice_file(
        tmp_path,
        {"kind": "checklist", "successCriteria": ["The wrapper runs."]},
    )

    result = practice.verify_practice_task(deck, task_index=1, notes="I ran it manually.")

    assert result.passed is True
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM practice_attempts").fetchone()[0]
    conn.close()
    assert count == 1


def test_verification_metadata_surfaces_in_result(monkeypatch, tmp_path: Path) -> None:
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    monkeypatch.setattr(practice, "record_progress", lambda **kwargs: True)
    deck = _practice_file(
        tmp_path,
        {
            "kind": "rubric",
            "successCriteria": ["The wrapper runs."],
            "rubric": ["Names the trade-off"],
            "evidencePrompts": ["What proved it worked?"],
            "setupCommand": "python -m pytest",
            "timeoutSeconds": 45,
        },
    )

    result = practice.verify_practice_task(deck, task_index=1, notes="I ran it manually.")

    assert result.rubric == ["Names the trade-off"]
    assert result.evidence_prompts == ["What proved it worked?"]
    assert result.setup_command == "python -m pytest"
    assert result.timeout_seconds == 45


def test_command_verification_requires_explicit_run_command(monkeypatch, tmp_path: Path) -> None:
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    deck = _practice_file(
        tmp_path,
        {
            "kind": "command",
            "successCriteria": ["Command passes."],
            "command": "python -c 'print(1)'",
        },
    )

    with pytest.raises(PermissionError, match="--run-command"):
        practice.verify_practice_task(deck, task_index=1)


def test_command_verification_requires_confirmation_even_with_run_command(
    monkeypatch, tmp_path: Path
) -> None:
    """R-15: --run-command alone is not enough. A resolved command from a
    (possibly LLM-authored) practice deck must also be explicitly confirmed
    before it runs -- this is the gate the CLI's --yes/interactive-y dance
    exists to satisfy, enforced here independent of any CLI."""
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    deck = _practice_file(
        tmp_path,
        {
            "kind": "command",
            "successCriteria": ["Command passes."],
            "command": "python -c 'print(1)'",
        },
    )

    with pytest.raises(PermissionError, match="confirmation"):
        practice.verify_practice_task(deck, task_index=1, run_command=True)


def test_peek_verification_command_does_not_run_or_record_anything(
    monkeypatch, tmp_path: Path
) -> None:
    """The CLI peeks at the resolved command to print+confirm it BEFORE
    verify_practice_task (which actually runs it) is ever called."""
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    marker = tmp_path / "marker.txt"
    deck = _practice_file(
        tmp_path,
        {
            "kind": "command",
            "successCriteria": ["Command passes."],
            "command": f"touch {marker}",
        },
    )

    kind, command = practice.peek_verification_command(deck, task_index=1)

    assert kind == "command"
    assert command == f"touch {marker}"
    assert not marker.exists()
    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM practice_attempts").fetchone()[0]
    conn.close()
    assert count == 0


def test_failing_command_records_failure_without_crashing(monkeypatch, tmp_path: Path) -> None:
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    monkeypatch.setattr(practice, "record_progress", lambda **kwargs: True)
    deck = _practice_file(
        tmp_path,
        {
            "kind": "command",
            "successCriteria": ["Command passes."],
            "command": "python -c 'import sys; sys.exit(7)'",
        },
    )

    result = practice.verify_practice_task(deck, task_index=1, run_command=True, confirmed=True)

    assert result.passed is False
    assert result.exit_code == 7


def test_timing_out_command_records_failure_without_crashing(monkeypatch, tmp_path: Path) -> None:
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    monkeypatch.setattr(practice, "record_progress", lambda **kwargs: True)
    deck = _practice_file(
        tmp_path,
        {
            "kind": "command",
            "successCriteria": ["Command finishes."],
            "command": "python -c 'import time; time.sleep(1)'",
        },
    )

    result = practice.verify_practice_task(
        deck,
        task_index=1,
        run_command=True,
        confirmed=True,
        timeout_seconds=0,
    )

    assert result.passed is False
    assert result.exit_code == -1


def test_passing_verification_updates_study_progress(monkeypatch, tmp_path: Path) -> None:
    db = _attempt_db(tmp_path)
    _patch_db(monkeypatch, db)
    calls: list[dict] = []
    monkeypatch.setattr(practice, "record_progress", lambda **kwargs: calls.append(kwargs) or True)
    deck = _practice_file(
        tmp_path,
        {"kind": "checklist", "successCriteria": ["It works."]},
    )

    result = practice.verify_practice_task(deck, task_index=1, notes="done")

    assert result.progress_recorded is True
    assert calls[0]["confidence"] == "confident"
    assert calls[0]["created_by"] == "practice-verify"


class TestPracticeVerifyCli:
    """R-15: `practice verify --run-command` must not run a resolved shell
    command until a human has seen it and said yes -- exercised through the
    real CLI (Click's exit codes and stdout ARE the contract here)."""

    def test_run_command_without_yes_shows_the_command_and_does_not_run_it(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        db = _attempt_db(tmp_path)
        _patch_db(monkeypatch, db)
        marker = tmp_path / "marker.txt"
        deck = _practice_file(
            tmp_path,
            {
                "kind": "command",
                "successCriteria": ["Command passes."],
                "command": f"touch {marker}",
            },
        )

        result = CliRunner().invoke(
            practice_group, ["verify", str(deck), "--task", "1", "--run-command"]
        )

        assert result.exit_code == 2
        assert not marker.exists()
        # Rich word-wraps long output; a long path can be hard-broken across
        # lines with no inserted characters, so compare with newlines removed.
        assert str(marker) in result.output.replace("\n", "")

    def test_run_command_with_yes_runs_it(self, monkeypatch, tmp_path: Path) -> None:
        db = _attempt_db(tmp_path)
        _patch_db(monkeypatch, db)
        monkeypatch.setattr(practice, "record_progress", lambda **kwargs: True)
        marker = tmp_path / "marker.txt"
        deck = _practice_file(
            tmp_path,
            {
                "kind": "command",
                "successCriteria": ["Command passes."],
                "command": f"touch {marker}",
            },
        )

        result = CliRunner().invoke(
            practice_group,
            ["verify", str(deck), "--task", "1", "--run-command", "--yes"],
        )

        assert result.exit_code == 0, result.output
        assert marker.exists()
        assert str(marker) in result.output.replace("\n", "")

    def test_run_command_without_run_command_flag_is_unaffected(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """--yes with no --run-command is inert -- the original gate stands."""
        db = _attempt_db(tmp_path)
        _patch_db(monkeypatch, db)
        deck = _practice_file(
            tmp_path,
            {
                "kind": "command",
                "successCriteria": ["Command passes."],
                "command": "python -c 'print(1)'",
            },
        )

        result = CliRunner().invoke(practice_group, ["verify", str(deck), "--task", "1", "--yes"])

        assert result.exit_code != 0
        assert "--run-command" in result.output

    def test_checklist_task_is_unaffected_by_run_command(self, monkeypatch, tmp_path: Path) -> None:
        """--run-command on a non-command task is a no-op, not a crash."""
        db = _attempt_db(tmp_path)
        _patch_db(monkeypatch, db)
        monkeypatch.setattr(practice, "record_progress", lambda **kwargs: True)
        deck = _practice_file(
            tmp_path,
            {"kind": "checklist", "successCriteria": ["The wrapper runs."]},
        )

        result = CliRunner().invoke(
            practice_group,
            ["verify", str(deck), "--task", "1", "--run-command", "--notes", "done"],
        )

        assert result.exit_code == 0, result.output
