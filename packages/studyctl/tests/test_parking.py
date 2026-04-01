"""Tests for parking.py — parking lot CRUD operations."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def parking_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp DB with the parked_topics table."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    # Create the study_sessions table (FK target)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            topic TEXT,
            energy_level TEXT,
            started_at TEXT,
            ended_at TEXT,
            duration_minutes INTEGER,
            pomodoro_cycles INTEGER DEFAULT 0,
            notes TEXT
        )
    """)
    # Create the sessions table (FK target)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    # Create the parked_topics table (migration v14)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parked_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_session_id TEXT REFERENCES study_sessions(id) ON DELETE SET NULL,
            session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
            topic_tag TEXT,
            question TEXT NOT NULL,
            context TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'scheduled', 'resolved', 'dismissed')),
            scheduled_for TEXT,
            resolved_at TEXT,
            parked_at TEXT NOT NULL DEFAULT (datetime('now')),
            created_by TEXT DEFAULT 'agent'
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr("studyctl.parking.get_db_path", lambda: db_path)
    return db_path


def test_park_topic(parking_db: Path) -> None:
    """park_topic inserts a row and returns the ID."""
    from studyctl.parking import park_topic

    row_id = park_topic("How does the GIL work?", topic_tag="python")
    assert row_id is not None
    assert row_id > 0


def test_park_topic_with_context(parking_db: Path) -> None:
    """park_topic stores context and study_session_id."""
    from studyctl.parking import get_parked_topics, park_topic

    park_topic(
        "VPC peering vs TGW",
        topic_tag="networking",
        context="Discussing Spark shuffle",
        study_session_id="sess-001",
        created_by="cli",
    )
    topics = get_parked_topics(study_session_id="sess-001")
    assert len(topics) == 1
    assert topics[0]["question"] == "VPC peering vs TGW"
    assert topics[0]["context"] == "Discussing Spark shuffle"
    assert topics[0]["created_by"] == "cli"


def test_get_parked_topics_filters_by_status(parking_db: Path) -> None:
    """get_parked_topics filters by status."""
    from studyctl.parking import get_parked_topics, park_topic, resolve_parked_topic

    id1 = park_topic("Topic A")
    park_topic("Topic B")
    resolve_parked_topic(id1)

    pending = get_parked_topics(status="pending")
    assert len(pending) == 1
    assert pending[0]["question"] == "Topic B"

    resolved = get_parked_topics(status="resolved")
    assert len(resolved) == 1
    assert resolved[0]["question"] == "Topic A"


def test_get_unscheduled_parked_topics(parking_db: Path) -> None:
    """get_unscheduled returns only pending topics."""
    from studyctl.parking import (
        get_unscheduled_parked_topics,
        park_topic,
        schedule_parked_topic,
    )

    park_topic("Topic A", topic_tag="python")
    id2 = park_topic("Topic B", topic_tag="python")
    park_topic("Topic C", topic_tag="sql")

    schedule_parked_topic(id2, "2026-04-01")

    # All pending
    all_pending = get_unscheduled_parked_topics()
    assert len(all_pending) == 2

    # Filtered by tag
    python_pending = get_unscheduled_parked_topics(topic_tag="python")
    assert len(python_pending) == 1
    assert python_pending[0]["question"] == "Topic A"

    # With limit
    limited = get_unscheduled_parked_topics(limit=1)
    assert len(limited) == 1


def test_schedule_parked_topic(parking_db: Path) -> None:
    """schedule_parked_topic sets status and date."""
    from studyctl.parking import get_parked_topics, park_topic, schedule_parked_topic

    row_id = park_topic("Learn asyncio")
    result = schedule_parked_topic(row_id, "2026-04-01")
    assert result is True

    scheduled = get_parked_topics(status="scheduled")
    assert len(scheduled) == 1
    assert scheduled[0]["scheduled_for"] == "2026-04-01"


def test_schedule_nonexistent_topic(parking_db: Path) -> None:
    """schedule_parked_topic returns False for missing ID."""
    from studyctl.parking import schedule_parked_topic

    assert schedule_parked_topic(9999, "2026-04-01") is False


def test_resolve_parked_topic(parking_db: Path) -> None:
    """resolve_parked_topic sets status and resolved_at."""
    from studyctl.parking import get_parked_topics, park_topic, resolve_parked_topic

    row_id = park_topic("GIL question")
    result = resolve_parked_topic(row_id)
    assert result is True

    resolved = get_parked_topics(status="resolved")
    assert len(resolved) == 1
    assert resolved[0]["resolved_at"] is not None


def test_dismiss_parked_topic(parking_db: Path) -> None:
    """dismiss_parked_topic sets status to dismissed."""
    from studyctl.parking import dismiss_parked_topic, get_parked_topics, park_topic

    row_id = park_topic("Not worth pursuing")
    result = dismiss_parked_topic(row_id)
    assert result is True

    dismissed = get_parked_topics(status="dismissed")
    assert len(dismissed) == 1

    # Can't dismiss again (already dismissed, not pending)
    assert dismiss_parked_topic(row_id) is False


def test_dismiss_only_pending(parking_db: Path) -> None:
    """dismiss_parked_topic only works on pending topics."""
    from studyctl.parking import (
        dismiss_parked_topic,
        park_topic,
        schedule_parked_topic,
    )

    row_id = park_topic("Scheduled topic")
    schedule_parked_topic(row_id, "2026-04-01")
    # Can't dismiss a scheduled topic
    assert dismiss_parked_topic(row_id) is False
