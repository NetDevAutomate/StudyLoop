"""Integration tests for session-db — full pipeline with real SQLite DB.

Tests migration v17, parking with source/priority, scoring pipeline,
and study session lifecycle for all session types.

Marked @pytest.mark.integration — excluded from CI (needs full DB).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def session_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a fully-migrated temp DB for integration tests."""
    db_path = tmp_path / "sessions.db"

    # Load base schema first (creates sessions, messages, etc.)
    from pathlib import Path as _Path

    from agent_session_tools.migrations import migrate

    schema_file = _Path(__file__).resolve().parents[2] / (
        "agent-session-tools/src/agent_session_tools/schema.sql"
    )

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    with open(schema_file) as f:
        conn.executescript(f.read())
    migrate(conn)
    conn.close()

    monkeypatch.setattr("studyctl.parking.get_db_path", lambda: db_path)
    monkeypatch.setattr("studyctl.settings.get_db_path", lambda: db_path)
    return db_path


def _query(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    """Helper to query the DB directly."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Migration Tests ────────────────────────────────────────────


@pytest.mark.integration
class TestMigrationV17:
    def test_migration_creates_priority_column(self, session_db: Path):
        """v17 adds priority INTEGER column to parked_topics."""
        cols = _query(session_db, "PRAGMA table_info(parked_topics)")
        col_names = {c["name"] for c in cols}
        assert "priority" in col_names
        assert "source" in col_names  # v16
        assert "tech_area" in col_names  # v16

    def test_schema_version_is_17(self, session_db: Path):
        conn = sqlite3.connect(str(session_db))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == 17


# ─── Parking with Source/Priority Tests ─────────────────────────


@pytest.mark.integration
class TestParkingIntegration:
    def test_park_topic_with_source_manual(self, session_db: Path):
        from studyctl.parking import park_topic

        row_id = park_topic(
            question="Decorators deep dive",
            topic_tag="Python",
            source="manual",
            tech_area="Python",
        )
        assert row_id is not None
        rows = _query(session_db, "SELECT * FROM parked_topics WHERE id = ?", (row_id,))
        assert rows[0]["source"] == "manual"
        assert rows[0]["tech_area"] == "Python"
        assert rows[0]["study_session_id"] is None  # manual = no session

    def test_park_topic_with_source_struggled(self, session_db: Path):
        from studyctl.parking import park_topic

        row_id = park_topic(
            question="Metaclasses",
            source="struggled",
            study_session_id="test-session-1",
        )
        assert row_id is not None
        rows = _query(session_db, "SELECT * FROM parked_topics WHERE id = ?", (row_id,))
        assert rows[0]["source"] == "struggled"

    def test_update_topic_priority(self, session_db: Path):
        from studyctl.parking import park_topic, update_topic_priority

        row_id = park_topic(question="OOP basics", source="manual")
        assert row_id is not None
        success = update_topic_priority(row_id, priority=5)
        assert success
        rows = _query(session_db, "SELECT priority FROM parked_topics WHERE id = ?", (row_id,))
        assert rows[0]["priority"] == 5

    def test_same_question_different_sources_allowed(self, session_db: Path):
        from studyctl.parking import park_topic

        id1 = park_topic(question="Closures", source="parked", study_session_id="s1")
        id2 = park_topic(question="Closures", source="struggled", study_session_id="s1")
        assert id1 is not None
        assert id2 is not None
        assert id1 != id2  # unique index includes source

    def test_get_topic_frequencies(self, session_db: Path):
        from studyctl.parking import get_topic_frequencies, park_topic

        park_topic(question="Decorators", source="parked", study_session_id="s1")
        park_topic(question="Decorators", source="struggled", study_session_id="s1")
        park_topic(question="Generators", source="parked", study_session_id="s1")

        freqs = get_topic_frequencies()
        assert freqs["Decorators"] == 2
        assert freqs["Generators"] == 1

    def test_filter_by_tech_area(self, session_db: Path):
        from studyctl.parking import get_parked_topics, park_topic

        park_topic(question="Decorators", tech_area="Python", source="manual")
        park_topic(question="Window funcs", tech_area="SQL", source="manual")

        python_topics = get_parked_topics(tech_area="Python")
        assert len(python_topics) == 1
        assert python_topics[0]["question"] == "Decorators"


# ─── Scoring Pipeline Tests ─────────────────────────────────────


@pytest.mark.integration
class TestScoringPipeline:
    def test_end_to_end_scoring(self, session_db: Path):
        """Park topics → gather frequencies → score → verify ranking."""
        from studyctl.backlog_logic import BacklogItem, ScoringInput, score_backlog_items
        from studyctl.parking import (
            get_parked_topics,
            get_topic_frequencies,
            park_topic,
            update_topic_priority,
        )

        # Create topics with different characteristics
        id1 = park_topic(question="OOP fundamentals", source="manual", tech_area="Python")
        id2 = park_topic(question="Niche syntax trick", source="manual", tech_area="Python")
        # Park OOP again from a session to boost frequency
        park_topic(question="OOP fundamentals", source="struggled", study_session_id="s1")

        # Set priorities
        assert id1 is not None and id2 is not None
        update_topic_priority(id1, 5)  # foundational
        update_topic_priority(id2, 1)  # niche

        # Gather data (same pattern as CLI/MCP)
        raw = get_parked_topics(status="pending")
        freqs = get_topic_frequencies()

        inputs = [
            ScoringInput(
                item=BacklogItem(
                    id=t["id"],
                    question=t["question"],
                    topic_tag=t.get("topic_tag"),
                    tech_area=t.get("tech_area"),
                    source=t.get("source", "parked"),
                    context=t.get("context"),
                    parked_at=t["parked_at"],
                    session_topic=None,
                ),
                frequency=freqs.get(t["question"], 1),
                priority=t.get("priority"),
            )
            for t in raw
        ]

        suggestions = score_backlog_items(inputs)

        # OOP fundamentals should rank first (high priority + higher frequency)
        assert suggestions[0].item.question == "OOP fundamentals"
        assert suggestions[0].priority == 5
        assert suggestions[0].frequency == 2


# ─── Study Session Lifecycle Tests ──────────────────────────────


@pytest.mark.integration
class TestStudySessionLifecycle:
    def _create_study_session(self, db_path: Path, topic: str, mode: str = "study") -> str:
        """Helper to insert a study session directly."""
        import uuid

        session_id = str(uuid.uuid4())[:8]
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """INSERT INTO study_sessions (id, topic, energy_level, started_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (session_id, topic, "high"),
        )
        conn.commit()
        conn.close()
        return session_id

    def test_study_session_with_parked_topics(self, session_db: Path):
        """Full lifecycle: create session → park topics → verify persistence."""
        from studyctl.parking import get_parked_topics, park_topic

        session_id = self._create_study_session(session_db, "Python Decorators")

        park_topic(
            question="How do closures work?",
            topic_tag="Python",
            study_session_id=session_id,
            source="parked",
            tech_area="Python",
        )
        park_topic(
            question="Metaclass use cases",
            topic_tag="Python",
            study_session_id=session_id,
            source="struggled",
            tech_area="Python",
        )

        # Verify both persisted with correct session ref
        topics = get_parked_topics(study_session_id=session_id)
        assert len(topics) == 2
        sources = {t["source"] for t in topics}
        assert sources == {"parked", "struggled"}

    def test_co_study_session_with_parked_topics(self, session_db: Path):
        """Co-study sessions use the same data pipeline."""
        from studyctl.parking import get_parked_topics, park_topic

        session_id = self._create_study_session(session_db, "SQL Window Functions", mode="co-study")

        park_topic(
            question="PARTITION BY vs GROUP BY",
            study_session_id=session_id,
            source="parked",
            tech_area="SQL",
        )

        topics = get_parked_topics(study_session_id=session_id)
        assert len(topics) == 1
        assert topics[0]["tech_area"] == "SQL"

    def test_auto_persist_struggled_flow(self, session_db: Path):
        """Simulate session end: struggled topics → plan → persist."""
        from studyctl.backlog_logic import plan_auto_persist
        from studyctl.parking import get_parked_topics, park_topic
        from studyctl.session_state import TopicEntry

        session_id = self._create_study_session(session_db, "Python OOP")

        # Simulate session-topics.md entries
        topic_entries = [
            TopicEntry(time="10:00", topic="Decorators", status="struggling", note="Hard"),
            TopicEntry(time="10:30", topic="Generators", status="learning", note="OK"),
            TopicEntry(time="11:00", topic="Metaclasses", status="struggling", note="Very hard"),
        ]

        # Gather existing (empty for new session)
        existing = get_parked_topics(study_session_id=session_id)
        existing_questions = {t["question"] for t in existing}

        # Plan (FCIS core)
        actions = plan_auto_persist(topic_entries, existing_questions, session_id)
        assert len(actions) == 2  # only struggling entries

        # Execute
        for action in actions:
            park_topic(
                question=action.question,
                topic_tag=action.topic_tag,
                context=action.context,
                study_session_id=action.study_session_id,
                source=action.source,
            )

        # Verify
        persisted = get_parked_topics(study_session_id=session_id)
        assert len(persisted) == 2
        questions = {t["question"] for t in persisted}
        assert questions == {"Decorators", "Metaclasses"}
        assert all(t["source"] == "struggled" for t in persisted)

    def test_resolve_across_sessions(self, session_db: Path):
        """Topics parked in one session can be resolved later."""
        from studyctl.parking import get_parked_topics, park_topic, resolve_parked_topic

        s1 = self._create_study_session(session_db, "Python Basics")
        row_id = park_topic(question="Closures", study_session_id=s1, source="parked")
        assert row_id is not None

        # Later, resolve it (no session context needed)
        success = resolve_parked_topic(row_id)
        assert success

        # Should no longer appear in pending
        pending = get_parked_topics(status="pending")
        assert not any(t["question"] == "Closures" for t in pending)

        # But should exist as resolved
        resolved = get_parked_topics(status="resolved")
        assert any(t["question"] == "Closures" for t in resolved)
