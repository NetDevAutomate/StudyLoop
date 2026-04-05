"""Tests for CLI session commands — session start/end/status/park."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

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
    conn.commit()
    conn.close()

    # Patch DB path for history, parking, and settings modules.
    monkeypatch.setattr("studyctl.settings.get_db_path", lambda: db_path)
    monkeypatch.setattr("studyctl.parking.get_db_path", lambda: db_path)
    monkeypatch.setattr("studyctl.history._connection._get_db_path", lambda: db_path)

    # Patch session state paths to use temp dir
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    monkeypatch.setattr("studyctl.session_state.SESSION_DIR", session_dir)
    monkeypatch.setattr("studyctl.session_state.STATE_FILE", session_dir / "session-state.json")
    monkeypatch.setattr("studyctl.session_state.TOPICS_FILE", session_dir / "session-topics.md")
    monkeypatch.setattr("studyctl.session_state.PARKING_FILE", session_dir / "session-parking.md")

    return tmp_path


def test_session_start(session_env: Path) -> None:
    """session start creates DB record and state file."""
    from studyctl.cli._session import session_group

    runner = CliRunner()
    result = runner.invoke(session_group, ["start", "--topic", "Spark", "--energy", "7"])
    assert result.exit_code == 0
    assert "Session started" in result.output
    assert "Spark" in result.output


def test_session_status_no_session(session_env: Path) -> None:
    """session status reports no active session."""
    from studyctl.cli._session import session_group

    runner = CliRunner()
    result = runner.invoke(session_group, ["status"])
    assert result.exit_code == 0
    assert "No active session" in result.output


def test_session_start_then_status(session_env: Path) -> None:
    """session status shows active session after start."""
    from studyctl.cli._session import session_group

    runner = CliRunner()
    runner.invoke(session_group, ["start", "--topic", "Python", "--energy", "5"])
    result = runner.invoke(session_group, ["status"])
    assert result.exit_code == 0
    assert "Python" in result.output


def test_park_command(session_env: Path) -> None:
    """park command writes to DB and parking file."""
    from studyctl.cli._session import park, session_group

    runner = CliRunner()
    # Start a session first
    runner.invoke(session_group, ["start", "--topic", "Spark", "--energy", "5"])

    result = runner.invoke(park, ["How does the GIL work?", "--topic", "python"])
    assert result.exit_code == 0
    assert "Parked" in result.output

    # Verify it's in the DB
    from studyctl.parking import get_unscheduled_parked_topics

    parked = get_unscheduled_parked_topics()
    assert len(parked) == 1
    assert parked[0]["question"] == "How does the GIL work?"


def test_session_end(session_env: Path) -> None:
    """session end shows summary and cleans up."""
    from studyctl.cli._session import session_group
    from studyctl.session_state import append_topic

    runner = CliRunner()
    runner.invoke(session_group, ["start", "--topic", "Spark", "--energy", "7"])

    # Simulate agent activity
    append_topic("09:14", "Spark partitioning", "win", "Got it")
    append_topic("09:31", "SQL windows", "struggling", "Needs more practice")

    result = runner.invoke(session_group, ["end", "--notes", "Good session"])
    assert result.exit_code == 0
    assert "Session Complete" in result.output
    assert "WINS" in result.output
