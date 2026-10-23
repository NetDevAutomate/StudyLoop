"""`purge_session` refuses only the orphans it would create, and names them.

Plan 5, lane Q, larger #2 item 7 (lane 4's found-not-fixed #7). After its
deletes, ``purge_session`` ran a whole-database ``PRAGMA foreign_key_check``
and refused on ANY violation, so one pre-existing orphan anywhere -- a
``session_notes`` row left by an archive/delete run before c0ff6e3f, a
``context_relations`` edge whose assertion is gone -- made every
``session-maint delete``, ``session-context forget --apply`` and modern
``prune`` refuse with "Purge violated a database dependency", stranding the
learner. The purge itself cannot create an orphan: it requires
``PRAGMA foreign_keys = 1`` and no constraint is deferred, so SQLite refuses
any delete that would leave a dependent row. The check is now scoped to what
this purge changed: violations present before it ran are reported (table and
count) and left exactly as found -- never repaired -- while a dependent the
schema does not cascade is still a refusal, with its table named.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_session_tools.context.lifecycle import forget_session, purge_session
from agent_session_tools.export_sessions import init_db

runner = CliRunner()


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "sessions.db"
    init_db(str(path)).close()
    return path


def _plant(path: Path, statements: list[str]) -> None:
    """Write rows with foreign keys OFF: the way old tools left orphans behind."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=OFF")
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


def _session(sid: str, when: str = "2026-01-01") -> list[str]:
    return [
        f"INSERT INTO sessions(id,source,created_at,updated_at,content_hash) "
        f"VALUES('{sid}','claude_code','{when}','{when}','h-{sid}')",
        f"INSERT INTO messages(id,session_id,role,content,timestamp) "
        f"VALUES('{sid}-m0','{sid}','user','body of {sid}','{when}')",
    ]


UNRELATED_ORPHAN = [
    "INSERT INTO context_assertions VALUES('a1','st','planned',NULL,'g','2026-01-01')",
    "INSERT INTO context_relations VALUES('r1','a1','a-missing','supports','p','2026-01-01')",
]
# The F-AST-02 shape: a note for a session an old archive/delete removed.
TOUCHED_TABLE_ORPHAN = [
    "INSERT INTO session_notes(session_id, notes) VALUES('gone-long-ago','n')",
]


def _violations(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()


def _purge(path: Path, sid: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            purge_session(conn, sid)
        except BaseException:
            conn.rollback()
            raise
        conn.commit()
    finally:
        conn.close()


def _ids(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM sessions")}
    finally:
        conn.close()


class TestPreExistingOrphansDoNotStrandTheLearner:
    @pytest.mark.parametrize(
        ("orphan", "table", "reported"),
        [
            # Its parent (context_assertions) is nothing purge deletes from: the
            # scoped check never looks at it, so it is neither refused nor named.
            pytest.param(
                UNRELATED_ORPHAN, "context_relations", False, id="unrelated-table"
            ),
            # Its parent is sessions, which purge deletes from: in scope, so it is
            # named as pre-existing -- and still left alone.
            pytest.param(
                TOUCHED_TABLE_ORPHAN, "session_notes", True, id="touched-table"
            ),
        ],
    )
    def test_purge_of_an_unrelated_session_succeeds_and_repairs_nothing(
        self, tmp_path, caplog, orphan, table, reported
    ):
        path = _db(tmp_path)
        _plant(path, _session("keep") + _session("doomed") + orphan)
        before = _violations(path)
        assert before and before[0][0] == table

        with caplog.at_level(logging.WARNING, "agent_session_tools.context.lifecycle"):
            _purge(path, "doomed")

        assert _ids(path) == {"keep"}
        # Left exactly as found: not refused, not repaired.
        assert _violations(path) == before
        named = any(
            table in record.getMessage() and "pre-existing" in record.getMessage()
            for record in caplog.records
        )
        assert named is reported, caplog.text

    def test_forget_with_a_pre_existing_orphan_applies(self, tmp_path, monkeypatch):
        path = _db(tmp_path)
        _plant(path, _session("doomed") + TOUCHED_TABLE_ORPHAN)
        config = tmp_path / "config.yaml"
        config.write_text(
            f"database:\n  path: {path}\nmemory:\n  default_scope: unclassified\n"
        )
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys=ON")

        result = forget_session(conn, "doomed", apply=True)
        conn.commit()
        conn.close()

        assert result["applied"] is True
        assert _ids(path) == set()
        assert _violations(path) == [("session_notes", 1, "sessions", 0)]

    def test_session_maint_delete_with_a_pre_existing_orphan_deletes(
        self, tmp_path, monkeypatch
    ):
        """Lane 4 verified rc 1 and nothing deleted; now rc 0 and the session goes."""
        from agent_session_tools import maintenance
        from agent_session_tools.maintenance import app

        path = _db(tmp_path)
        _plant(path, _session("old", "2024-01-01") + TOUCHED_TABLE_ORPHAN)
        monkeypatch.setattr(
            maintenance,
            "_config",
            {
                "database": {
                    "path": str(path),
                    "backup_dir": str(tmp_path / "backups"),
                },
                "logging": {
                    "path": str(tmp_path / "sessions.log"),
                    "level": "INFO",
                },
            },
        )

        result = runner.invoke(
            app, ["delete", "--days", "365", "--confirm", "--no-backup"]
        )

        assert result.exit_code == 0, result.output
        assert "Deleted 1 session(s)" in result.output
        assert _ids(path) == set()
        assert _violations(path) == [("session_notes", 1, "sessions", 0)]


class TestAnOrphanThePurgeWouldCreateIsStillRefused:
    def test_a_dependent_declared_with_the_parent_in_another_case_is_still_in_scope(
        self, tmp_path
    ):
        """SQLite identifiers are case-insensitive and ``PRAGMA foreign_key_list``
        reports the parent as written in the FK clause, so ``REFERENCES
        SESSIONS(id)`` named a parent the scoped check compared case-sensitively
        and missed (council pass 6). The dependent set must include it."""
        from agent_session_tools.context.lifecycle import _dependent_tables

        path = _db(tmp_path)
        _plant(
            path,
            _session("held")
            + [
                "CREATE TABLE shouty_ref(session_id TEXT NOT NULL REFERENCES SESSIONS(id))",
                "INSERT INTO shouty_ref VALUES('held')",
            ],
        )
        conn = sqlite3.connect(path)
        try:
            assert "shouty_ref" in _dependent_tables(conn)
        finally:
            conn.close()

    def test_a_dependent_the_schema_does_not_cascade_names_its_table(self, tmp_path):
        """SQLite's own refusal, re-raised as the same type (the replication
        withdrawal path rolls back on IntegrityError) with the table named."""
        from agent_session_tools.context.lifecycle import PurgeDependencyError

        path = _db(tmp_path)
        _plant(
            path,
            _session("held")
            + [
                "CREATE TABLE local_ref(session_id TEXT NOT NULL REFERENCES sessions(id))",
                "INSERT INTO local_ref VALUES('held')",
            ],
        )

        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY") as excinfo:
            _purge(path, "held")

        assert isinstance(excinfo.value, PurgeDependencyError)
        assert "local_ref" in str(excinfo.value)
        assert "transaction must roll back" in str(excinfo.value)
        assert _ids(path) == {"held"}
        assert _violations(path) == []

    def test_a_refusal_with_a_pre_existing_orphan_present_names_only_the_new_one(
        self, tmp_path
    ):
        path = _db(tmp_path)
        _plant(
            path,
            _session("held")
            + UNRELATED_ORPHAN
            + [
                "CREATE TABLE local_ref(session_id TEXT NOT NULL REFERENCES sessions(id))",
                "INSERT INTO local_ref VALUES('held')",
            ],
        )

        with pytest.raises(sqlite3.IntegrityError, match="local_ref") as excinfo:
            _purge(path, "held")

        assert "context_relations" not in str(excinfo.value)

    def test_another_integrity_failure_passes_through_unchanged(self, tmp_path):
        """A trigger's RAISE mid-purge is not a dependency refusal and is not
        re-labelled (test_local_lifecycle pins the fixture-interruption shape)."""
        path = _db(tmp_path)
        _plant(
            path,
            _session("held")
            + [
                "CREATE TRIGGER fixture_fail BEFORE DELETE ON messages "
                "BEGIN SELECT RAISE(ABORT,'fixture interruption'); END"
            ],
        )

        with pytest.raises(sqlite3.IntegrityError, match="fixture interruption") as e:
            _purge(path, "held")

        assert type(e.value) is sqlite3.IntegrityError


class TestTheCheckIsScopedToWhatPurgeChanges:
    def test_violations_are_compared_against_a_snapshot_taken_before_the_deletes(
        self, tmp_path, monkeypatch
    ):
        """Pin the mechanism: the same dependency check runs before and after, and
        only a violation absent from the before-set is a refusal."""
        from agent_session_tools.context import lifecycle

        path = _db(tmp_path)
        _plant(path, _session("doomed") + TOUCHED_TABLE_ORPHAN)
        calls: list[int] = []
        real = lifecycle._dependency_violations

        def counting(conn, tables):
            result = real(conn, tables)
            calls.append(len(result))
            return result

        monkeypatch.setattr(lifecycle, "_dependency_violations", counting)

        _purge(path, "doomed")

        # One in-scope orphan before, the same one after: nothing new, no refusal.
        assert calls == [1, 1]
