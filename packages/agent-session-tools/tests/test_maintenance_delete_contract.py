"""`session-maint delete` says what it keeps, and destroys learner records only on request (D5).

An age-based delete keeps every session that owns learner records (study
sessions, teach-backs, parked topics, notes): a permanent delete tombstones the
session and forgets those records. The keep was printed but the help text and
the final summary did not say so, and a run where every old session was kept
reported "No sessions older than N days found". Pass 3 ruled: name the keep in
`--days` help and in the summary, and add `--forget-learner-records`, which
destroys the anchored sessions and their learner records through
`context.lifecycle.purge_session` (tombstone path, foreign keys on, never a
bare cascade), prints what it destroyed, and still needs `--confirm`.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_session_tools.maintenance import _delete_old, app

runner = CliRunner()


def _old_iso(days_ago: int = 100) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def _current_db(tmp_path: Path) -> Path:
    from agent_session_tools.export_sessions import init_db

    db_path = tmp_path / "sessions.db"
    init_db(str(db_path)).close()
    return db_path


def _export(db_path: Path, session_id: str, when: str) -> None:
    from agent_session_tools.exporters.base import ExportStats, commit_batch

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        commit_batch(
            conn,
            [
                {
                    "id": session_id,
                    "source": "claude_code",
                    "project_path": "/p",
                    "created_at": when,
                    "updated_at": when,
                }
            ],
            [
                {
                    "id": f"{session_id}-m1",
                    "session_id": session_id,
                    "role": "user",
                    "content": "hello",
                    "timestamp": when,
                }
            ],
            ExportStats(),
        )
    finally:
        conn.close()


def _plant_learner_records(db_path: Path, session_id: str) -> None:
    """One study session, one teach-back and one parked topic owned by session_id."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO study_sessions (id, session_id, topic, started_at)"
            " VALUES (?, ?, ?, ?)",
            (f"study-{session_id}", session_id, "sql", _old_iso()),
        )
        conn.execute(
            "INSERT INTO teach_back_scores (concept, topic, session_id, review_type)"
            " VALUES (?, ?, ?, ?)",
            ("joins", "sql", session_id, "micro"),
        )
        conn.execute(
            "INSERT INTO parked_topics (session_id, question) VALUES (?, ?)",
            (session_id, f"what is a window frame? ({session_id})"),
        )
        conn.commit()
    finally:
        conn.close()


def _rows(db_path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _session_ids(db_path: Path) -> set[str]:
    return {r[0] for r in _rows(db_path, "SELECT id FROM sessions")}


def _tombstoned(db_path: Path) -> set[str]:
    return {r[0] for r in _rows(db_path, "SELECT session_id FROM context_tombstones")}


def _learner_counts(db_path: Path) -> dict[str, int]:
    return {
        table: _rows(db_path, f"SELECT COUNT(*) FROM {table}")[0][0]
        for table in ("study_sessions", "teach_back_scores", "parked_topics")
    }


def _fk_violations(db_path: Path) -> list[tuple]:
    return _rows(db_path, "PRAGMA foreign_key_check")


def _summary(out: str) -> str:
    return [line for line in out.splitlines() if line.strip()][-1]


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """old-learner owns learner records; old-plain does not; new-1 is recent."""
    db_path = _current_db(tmp_path)
    _export(db_path, "old-learner", _old_iso())
    _export(db_path, "old-plain", _old_iso())
    _export(db_path, "new-1", _old_iso(1))
    _plant_learner_records(db_path, "old-learner")
    return db_path


class TestDefaultKeepsLearnerSessions:
    def test_default_run_keeps_them_and_the_summary_says_so(self, db, capsys):
        assert _delete_old(db, days=30, confirm=True, backup=False) == 0

        assert _session_ids(db) == {"old-learner", "new-1"}
        assert _tombstoned(db) == {"old-plain"}
        assert _learner_counts(db) == {
            "study_sessions": 1,
            "teach_back_scores": 1,
            "parked_topics": 1,
        }
        summary = _summary(capsys.readouterr().out)
        assert "Deleted 1 session(s)" in summary
        assert "kept 1 that own learner records" in summary
        assert "--forget-learner-records" in summary
        assert _fk_violations(db) == []

    def test_a_run_that_keeps_every_old_session_does_not_say_none_were_found(
        self, tmp_path, capsys
    ):
        db_path = _current_db(tmp_path)
        _export(db_path, "old-learner", _old_iso())
        _plant_learner_records(db_path, "old-learner")

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 0

        out = capsys.readouterr().out
        assert "No sessions older than" not in out
        summary = _summary(out)
        assert "Deleted 0 session(s)" in summary
        assert "kept 1 that own learner records" in summary
        assert _session_ids(db_path) == {"old-learner"}
        assert _fk_violations(db_path) == []

    def test_without_confirm_nothing_happens(self, db, capsys):
        assert _delete_old(db, days=30, confirm=False, backup=False) == 1

        assert _session_ids(db) == {"old-learner", "old-plain", "new-1"}
        assert _tombstoned(db) == set()
        assert "Use --confirm to proceed" in capsys.readouterr().out


class TestForgetLearnerRecords:
    def test_destroys_them_through_the_tombstone_path(self, db, capsys):
        assert (
            _delete_old(
                db, days=30, confirm=True, backup=False, forget_learner_records=True
            )
            == 0
        )

        assert _session_ids(db) == {"new-1"}
        assert _tombstoned(db) == {"old-learner", "old-plain"}
        assert _learner_counts(db) == {
            "study_sessions": 0,
            "teach_back_scores": 0,
            "parked_topics": 0,
        }
        assert _fk_violations(db) == []
        out = capsys.readouterr().out
        assert "Destroyed 3 learner record(s)" in out
        for line in ("study_sessions: 1", "teach_back_scores: 1", "parked_topics: 1"):
            assert line in out
        summary = _summary(out)
        assert "Deleted 2 session(s)" in summary
        assert "1 that owned learner records" in summary

        # The tombstone holds: re-exporting the native transcript re-imports nothing.
        _export(db, "old-learner", _old_iso())
        assert _session_ids(db) == {"new-1"}

    def test_routes_every_session_through_purge_session(self, db, monkeypatch):
        from agent_session_tools.context import lifecycle

        real = lifecycle.purge_session
        calls: list[tuple[str, bool, int]] = []

        def spy(conn, session_id, *, permanent=True):
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            calls.append((session_id, permanent, fk))
            return real(conn, session_id, permanent=permanent)

        monkeypatch.setattr(lifecycle, "purge_session", spy)

        assert (
            _delete_old(
                db, days=30, confirm=True, backup=False, forget_learner_records=True
            )
            == 0
        )

        assert sorted(calls) == [("old-learner", True, 1), ("old-plain", True, 1)]

    def test_learner_records_of_a_kept_session_survive(self, db):
        _plant_learner_records(db, "new-1")

        assert (
            _delete_old(
                db, days=30, confirm=True, backup=False, forget_learner_records=True
            )
            == 0
        )

        assert _learner_counts(db) == {
            "study_sessions": 1,
            "teach_back_scores": 1,
            "parked_topics": 1,
        }
        assert _rows(db, "SELECT session_id FROM teach_back_scores") == [("new-1",)]
        assert _fk_violations(db) == []

    def test_without_confirm_nothing_happens_and_it_says_what_it_would_destroy(
        self, db, capsys
    ):
        before = _learner_counts(db)

        assert (
            _delete_old(
                db, days=30, confirm=False, backup=False, forget_learner_records=True
            )
            == 1
        )

        assert _session_ids(db) == {"old-learner", "old-plain", "new-1"}
        assert _tombstoned(db) == set()
        assert _learner_counts(db) == before
        out = capsys.readouterr().out
        assert "Would destroy 3 learner record(s)" in out
        assert "Use --confirm to proceed" in out
        assert _fk_violations(db) == []

    def test_refused_on_a_pre_lifecycle_database(self, tmp_path, capsys):
        """purge_session needs schema 41+; the flag never falls back to a bare delete."""
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL,"
            " project_path TEXT, created_at TEXT, updated_at TEXT);"
            "CREATE TABLE messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,"
            " role TEXT NOT NULL, content TEXT, timestamp TEXT);"
        )
        conn.execute(
            "INSERT INTO sessions VALUES ('old-1', 'claude_code', '/p', ?, ?)",
            (_old_iso(), _old_iso()),
        )
        conn.commit()
        conn.close()

        assert (
            _delete_old(
                db_path,
                days=30,
                confirm=True,
                backup=False,
                forget_learner_records=True,
            )
            == 1
        )

        assert _session_ids(db_path) == {"old-1"}
        assert "--forget-learner-records needs the current schema" in (
            capsys.readouterr().out
        )


class TestCli:
    def test_days_help_names_the_keep_and_the_flag_exists(self):
        result = runner.invoke(app, ["delete", "--help"], terminal_width=200)

        assert result.exit_code == 0
        text = " ".join(result.output.split())
        assert "learner records" in text
        assert "--forget-learner-records" in text

    def test_flag_reaches_the_purge(self, db):
        result = runner.invoke(
            app,
            [
                "delete",
                "--days",
                "30",
                "--db",
                str(db),
                "--confirm",
                "--no-backup",
                "--forget-learner-records",
            ],
        )

        assert result.exit_code == 0, result.output
        assert _session_ids(db) == {"new-1"}
        assert _fk_violations(db) == []

    def test_flag_without_confirm_changes_nothing(self, db):
        result = runner.invoke(
            app,
            [
                "delete",
                "--days",
                "30",
                "--db",
                str(db),
                "--no-backup",
                "--forget-learner-records",
            ],
        )

        assert result.exit_code == 1
        assert _session_ids(db) == {"old-learner", "old-plain", "new-1"}
        assert _tombstoned(db) == set()
