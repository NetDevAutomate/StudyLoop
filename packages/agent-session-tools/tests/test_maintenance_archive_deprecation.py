"""`session-maint archive` is deprecated (D4, council pass 3).

The command writes a hand-written two-table copy (sessions and messages) beside
the source database, and nothing in StudyLoop reads that file. The supported
path is `session-maint sync-full` then `session-maint prune`, which moves whole
sessions into the full database (same schema as the hot one) and deletes from
the hot database only what it has verified there. That is not a drop-in
replacement, so the notice says how the two differ instead of claiming one.

Until the removal release the command still runs exactly as before: the
lane-4 refusal (sessions with rows the archive cannot hold stay in the
source) and the archive file's contents are unchanged by the notice.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from agent_session_tools.maintenance import _archive, app

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


def _add_note(db_path: Path, session_id: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO session_notes (session_id, notes) VALUES (?, ?)",
            (session_id, "my note"),
        )
        conn.commit()
    finally:
        conn.close()


def _archive_path(db_path: Path) -> Path:
    return db_path.parent / f"{db_path.stem}_archive.db"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ids(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM sessions")}
    finally:
        conn.close()


def _assert_notice(out: str) -> None:
    assert "'session-maint archive' is deprecated" in out
    # Plan 5 (lane Q, read-and-prove): the named replacement refuses every
    # database that holds exported evidence -- on schema >= 41 that is every
    # database with an exported session -- because `sync_to_full` copies only
    # sessions, messages and file references and would drop the evidence tier.
    # So the removal is no longer promised for "the release after"; it waits on
    # `sync-full` carrying the current schema, and the notice says why the
    # replacement will refuse the learner today instead of sending them to it.
    assert "removed in the release after the one that deprecates it" not in out
    assert "will not be removed until" in out
    assert "refuses" in out
    assert "exported evidence" in out
    assert "0.7.0" not in out
    assert "session-maint sync-full" in out
    assert "session-maint prune" in out
    # It names the difference rather than claiming a drop-in replacement.
    assert "not a drop-in replacement" in out
    assert "whole sessions" in out
    assert "verified" in out


class TestDeprecationNotice:
    def test_archive_prints_the_notice_and_still_archives(self, tmp_path, capsys):
        db_path = _current_db(tmp_path)
        _export(db_path, "old-1", _old_iso())

        assert _archive(db_path, days=30, backup=False) == 0

        _assert_notice(capsys.readouterr().out)
        assert _ids(db_path) == set()
        assert _ids(_archive_path(db_path)) == {"old-1"}

    def test_notice_is_printed_when_nothing_qualifies(self, tmp_path, capsys):
        db_path = _current_db(tmp_path)

        assert _archive(db_path, days=30, backup=False) == 0

        _assert_notice(capsys.readouterr().out)

    def test_notice_is_printed_before_a_missing_database_error(self, tmp_path, capsys):
        assert _archive(tmp_path / "nope.db", days=30, backup=False) == 1

        _assert_notice(capsys.readouterr().out)

    def test_cli_prints_the_notice_and_exits_as_before(self, tmp_path):
        db_path = _current_db(tmp_path)
        _export(db_path, "old-1", _old_iso())

        result = runner.invoke(
            app, ["archive", "--days", "30", "--db", str(db_path), "--no-backup"]
        )

        assert result.exit_code == 0, result.output
        _assert_notice(result.output)
        assert _ids(_archive_path(db_path)) == {"old-1"}

    def test_help_marks_the_command_deprecated(self):
        listing = runner.invoke(app, ["--help"], terminal_width=200)
        assert listing.exit_code == 0
        assert "deprecated" in listing.output.lower()

        own = runner.invoke(app, ["archive", "--help"], terminal_width=200)
        assert own.exit_code == 0
        assert "deprecated" in own.output.lower()
        assert "sync-full" in own.output


class TestBehaviourUnchanged:
    def test_an_existing_archive_is_untouched_when_nothing_qualifies(self, tmp_path):
        db_path = _current_db(tmp_path)
        _export(db_path, "old-1", _old_iso())
        assert _archive(db_path, days=30, backup=False) == 0
        before = _sha256(_archive_path(db_path))

        _export(db_path, "new-1", _old_iso(1))
        assert _archive(db_path, days=30, backup=False) == 0

        assert _sha256(_archive_path(db_path)) == before
        assert _ids(db_path) == {"new-1"}

    def test_lane_4_refusal_still_keeps_sessions_the_archive_cannot_hold(
        self, tmp_path, capsys
    ):
        db_path = _current_db(tmp_path)
        _export(db_path, "plain", _old_iso())
        assert _archive(db_path, days=30, backup=False) == 0
        before = _sha256(_archive_path(db_path))
        _export(db_path, "noted", _old_iso())
        _add_note(db_path, "noted")

        assert _archive(db_path, days=30, backup=False) == 0

        out = capsys.readouterr().out
        assert "Kept 1 session(s) with rows the archive cannot hold" in out
        assert _ids(db_path) == {"noted"}
        # The refused session never reached the archive, which is byte-identical.
        assert _sha256(_archive_path(db_path)) == before
        assert _ids(_archive_path(db_path)) == {"plain"}
