"""Tests for CLI session commands — session start/end/status/park."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from click.testing import CliRunner


@pytest.fixture()
def session_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up temp DB + temp session dir for CLI tests."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    # Minimal schema for study_sessions + parked_topics
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, source TEXT, created_at TEXT, updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id TEXT PRIMARY KEY, session_id TEXT, topic TEXT,
            energy_level TEXT, started_at TEXT, ended_at TEXT,
            duration_minutes INTEGER, pomodoro_cycles INTEGER DEFAULT 0, notes TEXT,
            persona_hash TEXT, win_count INTEGER, struggle_count INTEGER,
            topic_slug TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parked_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_session_id TEXT, session_id TEXT, topic_tag TEXT,
            question TEXT NOT NULL, context TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            scheduled_for TEXT, resolved_at TEXT,
            parked_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT DEFAULT 'agent',
            source TEXT NOT NULL DEFAULT 'parked',
            tech_area TEXT,
            priority INTEGER
        )
    """)
    # Mark schema as fully migrated so _connect() doesn't try to run
    # agent-session-tools migrations against this minimal test schema.
    from agent_session_tools.migrations import CURRENT_VERSION

    conn.execute(f"PRAGMA user_version = {CURRENT_VERSION}")
    conn.commit()
    conn.close()

    # Patch DB path for history, parking, and settings modules.
    monkeypatch.setattr("studyloop.settings.get_db_path", lambda: db_path)
    monkeypatch.setattr("studyloop.parking.get_db_path", lambda: db_path)
    monkeypatch.setattr("studyloop.history._connection._get_db_path", lambda: db_path)

    # Patch session state paths to use temp dir
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    monkeypatch.setattr("studyloop.session_state.SESSION_DIR", session_dir)
    monkeypatch.setattr("studyloop.session_state.STATE_FILE", session_dir / "session-state.json")
    monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", session_dir / "session-topics.md")
    monkeypatch.setattr("studyloop.session_state.PARKING_FILE", session_dir / "session-parking.md")

    return tmp_path


def test_session_start(session_env: Path) -> None:
    """session start creates DB record and state file."""
    from studyloop.cli._session import session_group

    runner = CliRunner()
    result = runner.invoke(session_group, ["start", "--topic", "Spark", "--energy", "7"])
    assert result.exit_code == 0
    assert "Session started" in result.output
    assert "Spark" in result.output


def test_session_status_no_session(session_env: Path) -> None:
    """session status reports no active session."""
    from studyloop.cli._session import session_group

    runner = CliRunner()
    result = runner.invoke(session_group, ["status"])
    assert result.exit_code == 0
    assert "No active session" in result.output


def test_session_start_then_status(session_env: Path) -> None:
    """session status shows active session after start."""
    from studyloop.cli._session import session_group

    runner = CliRunner()
    runner.invoke(session_group, ["start", "--topic", "Python", "--energy", "5"])
    result = runner.invoke(session_group, ["status"])
    assert result.exit_code == 0
    assert "Python" in result.output


def test_session_start_rejects_when_already_active(session_env: Path) -> None:
    """session start should fail closed when another session is active."""
    from studyloop.cli._session import session_group

    runner = CliRunner()
    first = runner.invoke(session_group, ["start", "--topic", "Python", "--energy", "5"])
    assert first.exit_code == 0

    second = runner.invoke(session_group, ["start", "--topic", "Rust", "--energy", "6"])
    assert second.exit_code != 0
    assert "already active" in second.output


def test_park_command(session_env: Path) -> None:
    """park command writes to DB and parking file."""
    from studyloop.cli._session import park, session_group

    runner = CliRunner()
    # Start a session first
    runner.invoke(session_group, ["start", "--topic", "Spark", "--energy", "5"])

    result = runner.invoke(park, ["How does the GIL work?", "--topic", "python"])
    assert result.exit_code == 0
    assert "Parked" in result.output

    # Verify it's in the DB
    from studyloop.parking import get_unscheduled_parked_topics

    parked = get_unscheduled_parked_topics()
    assert len(parked) == 1
    assert parked[0]["question"] == "How does the GIL work?"


def test_session_end(session_env: Path) -> None:
    """session end shows summary and cleans up."""
    from studyloop.cli._session import session_group
    from studyloop.session_state import append_topic

    runner = CliRunner()
    runner.invoke(session_group, ["start", "--topic", "Spark", "--energy", "7"])

    # Simulate agent activity
    append_topic("09:14", "Spark partitioning", "win", "Got it")
    append_topic("09:31", "SQL windows", "struggling", "Needs more practice")

    result = runner.invoke(session_group, ["end", "--notes", "Good session"])
    assert result.exit_code == 0
    assert "Session Complete" in result.output
    assert "WINS" in result.output

    conn = sqlite3.connect(str(session_env / "test.db"))
    row = conn.execute("SELECT win_count, struggle_count FROM study_sessions").fetchone()
    conn.close()
    assert row == (1, 1)


@pytest.mark.parametrize(
    ("status", "expected_confidence"),
    [
        ("struggling", "struggling"),
        ("win", "confident"),
        ("insight", "confident"),
    ],
)
def test_topic_cmd_records_outcome_progress(
    session_env: Path,
    status: str,
    expected_confidence: str,
) -> None:
    """topic command records durable progress for outcome statuses."""
    from studyloop.cli._session import session_group, topic_cmd

    runner = CliRunner()
    runner.invoke(session_group, ["start", "--topic", "Spark", "--energy", "7"])

    with patch("studyloop.history.record_progress", return_value=True) as mock_progress:
        result = runner.invoke(
            topic_cmd,
            ["Spark partitioning", "--status", status, "--note", "Got it"],
        )

    assert result.exit_code == 0
    assert "Spark partitioning" in result.output
    mock_progress.assert_called_once_with(
        topic="Spark",
        concept="Spark partitioning",
        confidence=expected_confidence,
        notes="Got it",
        source_course="Spark",
    )


def test_topic_cmd_leaves_learning_as_live_feed_only(session_env: Path) -> None:
    """learning remains a live session feed update, not durable progress."""
    from studyloop.cli._session import session_group, topic_cmd

    runner = CliRunner()
    runner.invoke(session_group, ["start", "--topic", "Spark", "--energy", "7"])

    with patch("studyloop.history.record_progress", return_value=True) as mock_progress:
        result = runner.invoke(
            topic_cmd,
            ["Spark partitioning", "--status", "learning", "--note", "Still exploring"],
        )

    assert result.exit_code == 0
    assert "Spark partitioning" in result.output
    mock_progress.assert_not_called()


def test_topic_cmd_progress_falls_back_to_concept_when_session_topic_missing(
    session_env: Path,
) -> None:
    """If state lacks a topic/course, the concept itself is the progress bucket."""
    from studyloop.cli._session import topic_cmd

    runner = CliRunner()
    with (
        patch(
            "studyloop.session_state.read_session_state",
            return_value={"study_session_id": "s1"},
        ),
        patch("studyloop.session_state.append_topic"),
        patch("studyloop.history.record_progress", return_value=True) as mock_progress,
    ):
        result = runner.invoke(topic_cmd, ["Spark partitioning", "--status", "win"])

    assert result.exit_code == 0
    mock_progress.assert_called_once_with(
        topic="Spark partitioning",
        concept="Spark partitioning",
        confidence="confident",
        notes=None,
        source_course=None,
    )


def test_topic_cmd_no_active_session_does_not_record_progress(session_env: Path) -> None:
    """The active-session guard still prevents feed and progress writes."""
    from studyloop.cli._session import topic_cmd

    runner = CliRunner()
    with (
        patch("studyloop.session_state.append_topic") as mock_append,
        patch("studyloop.history.record_progress", return_value=True) as mock_progress,
    ):
        result = runner.invoke(topic_cmd, ["Spark partitioning", "--status", "win"])

    assert result.exit_code == 0
    assert "No active session" in result.output
    mock_append.assert_not_called()
    mock_progress.assert_not_called()
