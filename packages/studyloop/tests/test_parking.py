"""Tests for parking.py — parking lot CRUD operations."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def parking_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp DB with the parked_topics table (post-v26 schema)."""
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
    # Create the parked_topics table (v14 + v15 + v16 + v17 + v26 schema)
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
            created_by TEXT DEFAULT 'agent',
            source TEXT NOT NULL DEFAULT 'parked'
                CHECK(source IN ('parked', 'struggled', 'manual')),
            tech_area TEXT,
            priority INTEGER,
            park_count INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uix_parked_topics_question_source_pending
        ON parked_topics (question, source) WHERE status = 'pending'
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr("studyloop.parking.get_db_path", lambda: db_path)
    return db_path


def test_park_topic(parking_db: Path) -> None:
    """park_topic inserts a row and returns the ID."""
    from studyloop.parking import park_topic

    row_id = park_topic("How does the GIL work?", topic_tag="python")
    assert row_id is not None
    assert row_id > 0


def test_park_topic_with_context(parking_db: Path) -> None:
    """park_topic stores context and study_session_id."""
    from studyloop.parking import get_parked_topics, park_topic

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
    from studyloop.parking import get_parked_topics, park_topic, resolve_parked_topic

    id1 = park_topic("Topic A")
    park_topic("Topic B")
    assert id1 is not None
    resolve_parked_topic(id1)

    pending = get_parked_topics(status="pending")
    assert len(pending) == 1
    assert pending[0]["question"] == "Topic B"

    resolved = get_parked_topics(status="resolved")
    assert len(resolved) == 1
    assert resolved[0]["question"] == "Topic A"


def test_get_unscheduled_parked_topics(parking_db: Path) -> None:
    """get_unscheduled returns only pending topics."""
    from studyloop.parking import (
        get_unscheduled_parked_topics,
        park_topic,
        schedule_parked_topic,
    )

    park_topic("Topic A", topic_tag="python")
    id2 = park_topic("Topic B", topic_tag="python")
    park_topic("Topic C", topic_tag="sql")
    assert id2 is not None
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
    from studyloop.parking import get_parked_topics, park_topic, schedule_parked_topic

    row_id = park_topic("Learn asyncio")
    assert row_id is not None
    result = schedule_parked_topic(row_id, "2026-04-01")
    assert result is True

    scheduled = get_parked_topics(status="scheduled")
    assert len(scheduled) == 1
    assert scheduled[0]["scheduled_for"] == "2026-04-01"


def test_schedule_nonexistent_topic(parking_db: Path) -> None:
    """schedule_parked_topic returns False for missing ID."""
    from studyloop.parking import schedule_parked_topic

    assert schedule_parked_topic(9999, "2026-04-01") is False


def test_resolve_parked_topic(parking_db: Path) -> None:
    """resolve_parked_topic sets status and resolved_at."""
    from studyloop.parking import get_parked_topics, park_topic, resolve_parked_topic

    row_id = park_topic("GIL question")
    assert row_id is not None
    result = resolve_parked_topic(row_id)
    assert result is True

    resolved = get_parked_topics(status="resolved")
    assert len(resolved) == 1
    assert resolved[0]["resolved_at"] is not None


def test_dismiss_parked_topic(parking_db: Path) -> None:
    """dismiss_parked_topic sets status to dismissed."""
    from studyloop.parking import dismiss_parked_topic, get_parked_topics, park_topic

    row_id = park_topic("Not worth pursuing")
    assert row_id is not None
    result = dismiss_parked_topic(row_id)
    assert result is True

    dismissed = get_parked_topics(status="dismissed")
    assert len(dismissed) == 1

    # Can't dismiss again (already dismissed, not pending)
    assert dismiss_parked_topic(row_id) is False


def test_dismiss_only_pending(parking_db: Path) -> None:
    """dismiss_parked_topic only works on pending topics."""
    from studyloop.parking import (
        dismiss_parked_topic,
        park_topic,
        schedule_parked_topic,
    )

    row_id = park_topic("Scheduled topic")
    assert row_id is not None
    schedule_parked_topic(row_id, "2026-04-01")
    # Can't dismiss a scheduled topic
    assert dismiss_parked_topic(row_id) is False


def test_demote_parked_topic_moves_to_back(parking_db: Path) -> None:
    """Demote makes the row the OLDEST pending entry (frees an active slot)."""

    from studyloop.parking import demote_parked_topic, get_parked_topics, park_topic

    ids = []
    for i, q in enumerate(["first", "second", "third", "fourth"]):
        row_id = park_topic(q)
        assert row_id is not None
        # parked_at has 1s resolution — force distinct timestamps
        import sqlite3

        conn = sqlite3.connect(str(parking_db))
        conn.execute(
            "UPDATE parked_topics SET parked_at = datetime('now', ?) WHERE id = ?",
            (f"-{40 - i * 10} seconds", row_id),
        )
        conn.commit()
        conn.close()
        ids.append(row_id)

    # Most-recent-first: 'fourth' leads
    before = [t["question"] for t in get_parked_topics(status="pending")]
    assert before[0] == "fourth"

    # Demote 'fourth' → it must drop to the very back
    assert demote_parked_topic(ids[3]) is True
    after = [t["question"] for t in get_parked_topics(status="pending")]
    assert after[-1] == "fourth"
    assert after[0] == "third"


def test_demote_nonexistent_returns_false(parking_db: Path) -> None:
    from studyloop.parking import demote_parked_topic

    assert demote_parked_topic(99999) is False


# ============================================================================
# Deduplication tests (issue 0004) — partial unique index on (question, source)
# ============================================================================


class TestParkingDeduplication:
    """Verify the partial unique index prevents concurrent pending duplicates."""

    def test_same_question_different_sessions_yields_one_pending_row(
        self, parking_db: Path
    ) -> None:
        """Park the same question under two distinct study_session_ids.

        The partial index on (question, source) WHERE status='pending' means
        the second INSERT OR IGNORE hits the constraint. Only one pending row
        should exist, and park_count must be 2.
        """
        from studyloop.parking import park_topic

        id1 = park_topic(
            "How do generators relate to closures?",
            study_session_id="sess-aaa",
            source="parked",
        )
        id2 = park_topic(
            "How do generators relate to closures?",
            study_session_id="sess-bbb",
            source="parked",
        )
        assert id1 is not None
        assert id2 is not None
        # Both calls return the same row ID
        assert id1 == id2

        # Verify exactly one pending row
        conn = sqlite3.connect(str(parking_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM parked_topics WHERE question = ? AND status = 'pending'",
            ("How do generators relate to closures?",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["park_count"] == 2
        conn.close()

    def test_same_question_null_session_ids_yields_one_pending_row(self, parking_db: Path) -> None:
        """Park the same question twice with study_session_id=None.

        The old index couldn't dedupe NULLs. The new partial index on
        (question, source) doesn't include study_session_id, so NULLs
        are irrelevant — deduplication works correctly.
        """
        from studyloop.parking import park_topic

        id1 = park_topic(
            "Does the wrapper actually work?",
            study_session_id=None,
            source="parked",
        )
        id2 = park_topic(
            "Does the wrapper actually work?",
            study_session_id=None,
            source="parked",
        )
        assert id1 is not None
        assert id2 is not None
        assert id1 == id2

        conn = sqlite3.connect(str(parking_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM parked_topics WHERE question = ? AND status = 'pending'",
            ("Does the wrapper actually work?",),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["park_count"] == 2
        conn.close()

    def test_park_dismiss_repark_creates_new_pending_row(self, parking_db: Path) -> None:
        """Park -> dismiss -> park the same question: a NEW pending row is allowed.

        The partial index only constrains rows WHERE status='pending'. Once
        dismissed, the constraint no longer covers that row, so a fresh
        pending row can be created.
        """
        from studyloop.parking import dismiss_parked_topic, park_topic

        id1 = park_topic("Revisit closures", source="parked")
        assert id1 is not None

        # Dismiss it
        assert dismiss_parked_topic(id1) is True

        # Re-park the same question — should create a NEW row
        id2 = park_topic("Revisit closures", source="parked")
        assert id2 is not None
        assert id2 != id1  # Different row

        # Both rows exist: one dismissed, one pending
        conn = sqlite3.connect(str(parking_db))
        conn.row_factory = sqlite3.Row
        all_rows = conn.execute(
            "SELECT * FROM parked_topics WHERE question = ?",
            ("Revisit closures",),
        ).fetchall()
        assert len(all_rows) == 2

        pending = [r for r in all_rows if r["status"] == "pending"]
        dismissed = [r for r in all_rows if r["status"] == "dismissed"]
        assert len(pending) == 1
        assert len(dismissed) == 1
        assert pending[0]["id"] == id2
        assert pending[0]["park_count"] == 1  # Fresh row, count starts at 1
        conn.close()

    def test_get_topic_frequencies_uses_park_count(self, parking_db: Path) -> None:
        """get_topic_frequencies returns park_count, not COUNT(*) of rows."""
        from studyloop.parking import get_topic_frequencies, park_topic

        # Park same question 3 times (from different sessions)
        park_topic("Closures deep dive", study_session_id="s1", source="parked")
        park_topic("Closures deep dive", study_session_id="s2", source="parked")
        park_topic("Closures deep dive", study_session_id="s3", source="parked")

        # Park a different question once
        park_topic("Async generators", study_session_id="s1", source="parked")

        freqs = get_topic_frequencies()
        assert freqs["Closures deep dive"] == 3
        assert freqs["Async generators"] == 1

    def test_get_topic_frequencies_sums_across_sources(self, parking_db: Path) -> None:
        """A question parked under two sources sums both park_counts.

        The partial unique index is scoped to ``(question, source)``, so one
        question can legitimately hold two pending rows — e.g. the learner
        parked it as a tangent ('parked') and the extractor also flagged it as
        a struggle ('struggled'). Reporting only one of the two rows would
        under-count the signal, which is what a bare per-row SELECT does.
        """
        from studyloop.parking import get_topic_frequencies, park_topic

        park_topic("Generators vs closures", study_session_id="s1", source="parked")
        park_topic("Generators vs closures", study_session_id="s2", source="parked")
        park_topic("Generators vs closures", study_session_id="s1", source="struggled")

        freqs = get_topic_frequencies()
        assert freqs["Generators vs closures"] == 3, "2 parked + 1 struggled"
