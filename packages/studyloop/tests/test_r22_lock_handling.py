"""R-22: `except sqlite3.OperationalError: return <fallback>` must not swallow
a real lock error the same way it swallows a genuinely missing table.

Pattern: narrow to "no such table" (matched via
`history._connection.is_missing_table_error`); log a warning and re-raise for
anything else. Modeled on the explorer FTS fix (`e692510`) -- a lock
collision must not read back indistinguishably from "no struggling topics" /
"no wins" / "no progress".

One representative read (and one write) function per file in scope
(`history/{sessions,progress,bridges,streaks,teachback}.py`,
`learning/mastery.py`) is exercised here with both failure modes:
- a DB that genuinely lacks the table -> fallback, no exception, no warning.
- a DB whose connection's `execute` is monkeypatched to raise
  `sqlite3.OperationalError("database is locked")` -> the exception
  propagates (not a silent empty list/None/dict) and a warning is logged.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

import pytest

from studyloop.history import _connection

if TYPE_CHECKING:
    from pathlib import Path


class _RaisingConn:
    """Stands in for `_connection._connect()`'s return value.

    Every `execute()` call raises the given OperationalError, regardless of
    the SQL -- simulating a genuine lock/timeout fault rather than a missing
    table, so the fix under test can't just get lucky on the message.
    """

    def __init__(self, real_conn: sqlite3.Connection, message: str = "database is locked"):
        self._real = real_conn
        self._message = message

    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError(self._message)

    def close(self) -> None:
        self._real.close()

    def commit(self) -> None:
        self._real.commit()

    def rollback(self) -> None:
        self._real.rollback()


class TestIsMissingTableError:
    def test_matches_missing_table_message(self):
        exc = sqlite3.OperationalError("no such table: study_progress")
        assert _connection.is_missing_table_error(exc)

    def test_does_not_match_lock_message(self):
        exc = sqlite3.OperationalError("database is locked")
        assert not _connection.is_missing_table_error(exc)

    def test_does_not_match_unrelated_message(self):
        exc = sqlite3.OperationalError("disk I/O error")
        assert not _connection.is_missing_table_error(exc)


def _real_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


class TestSessionsNoSuchTableVsLocked:
    def test_no_such_table_returns_fallback(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).close()  # no tables at all

        import studyloop.history.sessions as sessions_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _real_conn(db_path))

        assert sessions_mod.get_last_study_session() is None

    def test_locked_db_raises_and_logs_not_silent_fallback(self, tmp_path, monkeypatch, caplog):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).execute(
            "CREATE TABLE study_sessions (id TEXT PRIMARY KEY, topic TEXT, "
            "topic_slug TEXT, energy_level TEXT, started_at TEXT, ended_at TEXT)"
        )

        import studyloop.history.sessions as sessions_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _RaisingConn(_real_conn(db_path)))

        with (
            caplog.at_level(logging.WARNING, logger="studyloop.history.sessions"),
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            sessions_mod.get_last_study_session()

        assert any("get_last_study_session" in r.message for r in caplog.records)


class TestProgressNoSuchTableVsLocked:
    def test_no_such_table_returns_fallback(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).close()

        import studyloop.history.progress as progress_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _real_conn(db_path))

        assert progress_mod.get_wins() == []

    def test_locked_db_raises_and_logs_not_silent_fallback(self, tmp_path, monkeypatch, caplog):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).execute(
            "CREATE TABLE study_progress (id TEXT PRIMARY KEY, topic TEXT, "
            "concept TEXT, confidence TEXT, first_seen TEXT, last_seen TEXT, "
            "session_count INTEGER)"
        )

        import studyloop.history.progress as progress_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _RaisingConn(_real_conn(db_path)))

        with (
            caplog.at_level(logging.WARNING, logger="studyloop.history.progress"),
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            progress_mod.get_wins()

        assert any("get_wins" in r.message for r in caplog.records)


class TestBridgesNoSuchTableVsLocked:
    def test_no_such_table_returns_fallback(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).close()

        import studyloop.history.bridges as bridges_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _real_conn(db_path))

        assert bridges_mod.get_bridges() == []

    def test_locked_db_raises_and_logs_not_silent_fallback(self, tmp_path, monkeypatch, caplog):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).execute(
            "CREATE TABLE knowledge_bridges (id INTEGER PRIMARY KEY, "
            "source_concept TEXT, source_domain TEXT, target_concept TEXT, "
            "target_domain TEXT, structural_mapping TEXT, quality TEXT, "
            "times_used INTEGER, times_helpful INTEGER, created_by TEXT, "
            "created_at TEXT)"
        )

        import studyloop.history.bridges as bridges_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _RaisingConn(_real_conn(db_path)))

        with (
            caplog.at_level(logging.WARNING, logger="studyloop.history.bridges"),
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            bridges_mod.get_bridges()

        assert any("get_bridges" in r.message for r in caplog.records)


class TestStreaksNoSuchTableVsLocked:
    def test_no_such_table_returns_fallback(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).close()

        import studyloop.history.streaks as streaks_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _real_conn(db_path))

        result = streaks_mod.get_study_streaks()
        assert result["current_streak"] == 0
        assert result["last_session_date"] is None

    def test_locked_db_raises_and_logs_not_silent_fallback(self, tmp_path, monkeypatch, caplog):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT)"
        )

        import studyloop.history.streaks as streaks_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _RaisingConn(_real_conn(db_path)))

        with (
            caplog.at_level(logging.WARNING, logger="studyloop.history.streaks"),
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            streaks_mod.get_study_streaks()

        assert any("get_study_streaks" in r.message for r in caplog.records)


class TestTeachbackNoSuchTableVsLocked:
    def test_no_such_table_returns_fallback(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).close()

        import studyloop.history.teachback as teachback_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _real_conn(db_path))

        assert teachback_mod.get_teachback_history("decorators") == []

    def test_locked_db_raises_and_logs_not_silent_fallback(self, tmp_path, monkeypatch, caplog):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).execute(
            "CREATE TABLE teach_back_scores (id INTEGER PRIMARY KEY, concept TEXT, "
            "topic TEXT, score_accuracy INTEGER, score_own_words INTEGER, "
            "score_structure INTEGER, score_depth INTEGER, score_transfer INTEGER, "
            "total_score INTEGER, review_type TEXT, question_angle TEXT, "
            "notes TEXT, created_at TEXT)"
        )

        import studyloop.history.teachback as teachback_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _RaisingConn(_real_conn(db_path)))

        with (
            caplog.at_level(logging.WARNING, logger="studyloop.history.teachback"),
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            teachback_mod.get_teachback_history("decorators")

        assert any("get_teachback_history" in r.message for r in caplog.records)


class TestMasteryNoSuchTableVsLocked:
    """`upsert_dependency` -- the one write path in mastery.py's ~six sites."""

    def _edge(self):
        from studyloop.learning.mastery import ConceptDependency

        return ConceptDependency(
            topic="python",
            source_concept="closures",
            target_concept="decorators",
            relation_type="prerequisite",
            evidence="test",
            source_type="explicit",
            confidence=0.9,
        )

    def test_no_such_table_returns_fallback(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).close()

        import studyloop.learning.mastery as mastery_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _real_conn(db_path))

        assert mastery_mod.upsert_dependency(self._edge()) is False

    def test_locked_db_raises_and_logs_not_silent_fallback(self, tmp_path, monkeypatch, caplog):
        db_path = tmp_path / "sessions.db"
        sqlite3.connect(db_path).execute(
            "CREATE TABLE concept_dependencies (id TEXT PRIMARY KEY, topic TEXT, "
            "source_concept TEXT, target_concept TEXT, relation_type TEXT, "
            "evidence TEXT, source_type TEXT, confidence REAL, "
            "created_at TEXT, updated_at TEXT)"
        )

        import studyloop.learning.mastery as mastery_mod

        monkeypatch.setattr(_connection, "_connect", lambda: _RaisingConn(_real_conn(db_path)))

        with (
            caplog.at_level(logging.WARNING, logger="studyloop.learning.mastery"),
            pytest.raises(sqlite3.OperationalError, match="locked"),
        ):
            mastery_mod.upsert_dependency(self._edge())

        assert any("upsert_dependency" in r.message for r in caplog.records)
