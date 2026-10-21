"""Tests for agent_session_tools.maintenance — core business logic."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


from agent_session_tools.maintenance import (
    _archive,
    _delete_old,
    _handle_duplicates,
    _reindex,
    _schema,
    _vacuum,
    create_backup,
)


# ---------------------------------------------------------------------------
# Helpers — inline fixtures (no conftest.py changes)
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal sessions database that matches the live schema (post-migrations)."""
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            project_path TEXT,
            git_branch TEXT,
            created_at TEXT,
            updated_at TEXT,
            metadata JSON,
            content_hash TEXT,
            import_fingerprint TEXT,
            session_type TEXT DEFAULT 'work'
        );

        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            parent_id TEXT,
            role TEXT NOT NULL,
            content TEXT,
            model TEXT,
            timestamp TEXT,
            metadata JSON,
            content_hash TEXT,
            seq INTEGER,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
        CREATE INDEX IF NOT EXISTS idx_sessions_source ON sessions(source);
        CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path);

        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            content,
            session_id UNINDEXED,
            role UNINDEXED,
            tokenize='porter unicode61'
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def _insert_session(
    db_path: Path,
    session_id: str,
    updated_at: str,
    source: str = "claude_code",
    project_path: str = "/test/project",
    content_hash: str | None = None,
    import_fingerprint: str | None = None,
    session_type: str = "work",
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO sessions
           (id, source, project_path, git_branch, created_at, updated_at,
            content_hash, import_fingerprint, session_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            source,
            project_path,
            "main",
            updated_at,
            updated_at,
            content_hash,
            import_fingerprint,
            session_type,
        ),
    )
    conn.commit()
    conn.close()


def _insert_message(
    db_path: Path,
    msg_id: str,
    session_id: str,
    content: str = "hello world",
    content_hash: str | None = None,
    seq: int | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO messages
           (id, session_id, parent_id, role, content, model, timestamp, content_hash, seq)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            msg_id,
            session_id,
            None,
            "user",
            content,
            None,
            "2024-01-01T10:00:00",
            content_hash,
            seq,
        ),
    )
    conn.commit()
    conn.close()


def _count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(db_path)
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    conn.close()
    return row[0]


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------


class TestCreateBackup:
    def test_backup_file_created(self, tmp_path):
        db_path = _make_db(tmp_path)
        backup_dir = tmp_path / "backups"

        with patch(
            "agent_session_tools.maintenance.get_backup_dir", return_value=backup_dir
        ):
            backup_path = create_backup(db_path)

        assert backup_path is not None
        assert backup_path.exists()
        assert backup_path.suffix == ".db"
        assert "backup_" in backup_path.name

    def test_backup_is_copy_of_source(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "s1", "2024-01-01T10:00:00")
        backup_dir = tmp_path / "backups"

        with patch(
            "agent_session_tools.maintenance.get_backup_dir", return_value=backup_dir
        ):
            backup_path = create_backup(db_path)

        assert backup_path is not None
        # Verify backup contains the same data
        conn = sqlite3.connect(backup_path)
        row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        conn.close()
        assert row[0] == 1

    def test_backup_captures_uncheckpointed_wal_data(self, tmp_path):
        """R-19c (M3 council, arbitration A2/X1 extension): a plain file
        copy of a WAL-mode database can miss committed data still sitting
        in the sibling `-wal` file. A writer's COMMIT+close alone is not
        enough to reproduce this -- SQLite opportunistically checkpoints
        when a write connection closes and nothing else is actively
        pinning the WAL, which would silently flush the row into the main
        file and make the bug invisible. A reader with an open transaction
        pins the WAL frames so the write genuinely stays WAL-only; the
        backup must still contain it.
        """
        db_path = _make_db(tmp_path)
        reader = sqlite3.connect(db_path)
        reader.execute("PRAGMA journal_mode=WAL")
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM sessions").fetchone()

        _insert_session(db_path, "wal-only", "2024-01-01T10:00:00")

        backup_dir = tmp_path / "backups"
        with patch(
            "agent_session_tools.maintenance.get_backup_dir", return_value=backup_dir
        ):
            backup_path = create_backup(db_path)
        reader.close()

        assert backup_path is not None
        backup_conn = sqlite3.connect(backup_path)
        count = backup_conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE id = 'wal-only'"
        ).fetchone()[0]
        backup_conn.close()
        assert count == 1, "the backup must include data still in the -wal file"

    def test_backup_dir_created_if_absent(self, tmp_path):
        db_path = _make_db(tmp_path)
        backup_dir = tmp_path / "deep" / "nested" / "backups"

        assert not backup_dir.exists()
        with patch(
            "agent_session_tools.maintenance.get_backup_dir", return_value=backup_dir
        ):
            create_backup(db_path)

        assert backup_dir.exists()

    def test_backup_refuses_database_over_size_limit(self, tmp_path, capsys):
        db_path = _make_db(tmp_path)
        backup_dir = tmp_path / "backups"
        config = {"database": {"backup_max_mb": 0}}

        with (
            patch("agent_session_tools.maintenance._get_config", return_value=config),
            patch(
                "agent_session_tools.maintenance.get_backup_dir",
                return_value=backup_dir,
            ),
        ):
            backup_path = create_backup(db_path)

        assert backup_path is None
        assert not backup_dir.exists()
        output = capsys.readouterr().out
        assert "Skipping full-copy backup" in output
        assert "session-maint snapshot" in output

    def test_backup_rotates_old_files_beyond_retention(self, tmp_path):
        db_path = _make_db(tmp_path)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        old_backups = [
            backup_dir / f"sessions_backup_2024010{day}_000000.db"
            for day in range(1, 4)
        ]
        for backup in old_backups:
            backup.write_text("old backup")
        unrelated = backup_dir / "other_backup_20240101_000000.db"
        unrelated.write_text("unrelated backup")
        config = {"database": {"backup_max_mb": 1024, "backup_retention": 2}}

        with (
            patch("agent_session_tools.maintenance._get_config", return_value=config),
            patch(
                "agent_session_tools.maintenance.get_backup_dir",
                return_value=backup_dir,
            ),
        ):
            backup_path = create_backup(db_path)

        assert backup_path is not None
        assert sorted(backup_dir.glob("sessions_backup_*.db")) == [
            old_backups[-1],
            backup_path,
        ]
        assert unrelated.exists()


# ---------------------------------------------------------------------------
# _vacuum
# ---------------------------------------------------------------------------


class TestVacuum:
    def test_returns_0_on_success(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch("agent_session_tools.maintenance.create_backup"):
            result = _vacuum(db_path, backup=False)
        assert result == 0

    def test_returns_1_when_db_missing(self, tmp_path):
        db_path = tmp_path / "nonexistent.db"
        result = _vacuum(db_path, backup=False)
        assert result == 1

    def test_backup_called_when_requested(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch("agent_session_tools.maintenance.create_backup") as mock_backup:
            backup_path = tmp_path / "fake_backup.db"
            mock_backup.return_value = backup_path
            _vacuum(db_path, backup=True)
        mock_backup.assert_called_once_with(db_path)

    def test_backup_not_called_when_skipped(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch("agent_session_tools.maintenance.create_backup") as mock_backup:
            _vacuum(db_path, backup=False)
        mock_backup.assert_not_called()


# ---------------------------------------------------------------------------
# _schema
# ---------------------------------------------------------------------------


class TestSchema:
    def test_returns_0_on_success(self, tmp_path):
        db_path = _make_db(tmp_path)
        result = _schema(db_path)
        assert result == 0

    def test_returns_1_when_db_missing(self, tmp_path):
        db_path = tmp_path / "ghost.db"
        result = _schema(db_path)
        assert result == 1

    def test_detailed_flag_accepted(self, tmp_path):
        # detailed=True queries dbstat, which requires SQLITE_ENABLE_DBSTAT_VTAB.
        # That virtual table is not available in all builds (e.g. macOS system sqlite).
        # We only assert _schema accepts the flag; the return code varies by build.
        db_path = _make_db(tmp_path)
        result = _schema(db_path, detailed=True)
        assert result in (0, 1)  # 0 = dbstat available, 1 = dbstat missing

    def test_outputs_table_names(self, tmp_path, capsys):
        db_path = _make_db(tmp_path)
        _schema(db_path)
        captured = capsys.readouterr()
        assert "sessions" in captured.out
        assert "messages" in captured.out

    def test_outputs_summary_line(self, tmp_path, capsys):
        db_path = _make_db(tmp_path)
        _schema(db_path)
        captured = capsys.readouterr()
        assert "Summary:" in captured.out


# ---------------------------------------------------------------------------
# _reindex
# ---------------------------------------------------------------------------


class TestReindex:
    def test_returns_0_on_success(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch("agent_session_tools.maintenance.create_backup"):
            result = _reindex(db_path, backup=False)
        assert result == 0

    def test_returns_1_when_db_missing(self, tmp_path):
        db_path = tmp_path / "missing.db"
        result = _reindex(db_path, backup=False)
        assert result == 1

    def test_backup_called_when_requested(self, tmp_path):
        db_path = _make_db(tmp_path)
        with patch("agent_session_tools.maintenance.create_backup") as mock_backup:
            mock_backup.return_value = tmp_path / "bak.db"
            _reindex(db_path, backup=True)
        mock_backup.assert_called_once_with(db_path)

    def test_fts_rebuilt_with_data(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "s1", "2024-01-01T10:00:00")
        _insert_message(db_path, "m1", "s1", "test reindex content")

        with patch("agent_session_tools.maintenance.create_backup"):
            result = _reindex(db_path, backup=False)

        assert result == 0


# ---------------------------------------------------------------------------
# _archive
# ---------------------------------------------------------------------------


class TestArchive:
    def _old_date(self, days_ago: int = 100) -> str:
        return (datetime.now() - timedelta(days=days_ago)).isoformat()

    def _recent_date(self, days_ago: int = 1) -> str:
        return (datetime.now() - timedelta(days=days_ago)).isoformat()

    def test_returns_1_when_db_missing(self, tmp_path):
        db_path = tmp_path / "nope.db"
        result = _archive(db_path, days=30, backup=False)
        assert result == 1

    def test_returns_0_when_no_old_sessions(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "s1", self._recent_date())
        result = _archive(db_path, days=30, backup=False)
        assert result == 0

    def test_old_sessions_moved_to_archive(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))
        _insert_session(db_path, "new-1", self._recent_date(1))
        _insert_message(db_path, "m1", "old-1", "archived content")

        with patch("agent_session_tools.maintenance.create_backup"):
            result = _archive(db_path, days=30, backup=False)

        assert result == 0
        # old session removed from source
        assert _count(db_path, "sessions") == 1
        remaining = (
            sqlite3.connect(db_path).execute("SELECT id FROM sessions").fetchone()
        )
        assert remaining[0] == "new-1"

    def test_archive_db_created(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))

        archive_path = db_path.parent / f"{db_path.stem}_archive.db"
        assert not archive_path.exists()

        with patch("agent_session_tools.maintenance.create_backup"):
            _archive(db_path, days=30, backup=False)

        assert archive_path.exists()

    def test_messages_follow_sessions_to_archive(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))
        _insert_message(db_path, "m1", "old-1", "message text")
        _insert_message(db_path, "m2", "old-1", "another message")

        archive_path = db_path.parent / f"{db_path.stem}_archive.db"

        with patch("agent_session_tools.maintenance.create_backup"):
            _archive(db_path, days=30, backup=False)

        archive_conn = sqlite3.connect(archive_path)
        msg_count = archive_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        archive_conn.close()
        assert msg_count == 2

    def test_messages_deleted_from_source(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))
        _insert_message(db_path, "m1", "old-1", "will be gone")

        with patch("agent_session_tools.maintenance.create_backup"):
            _archive(db_path, days=30, backup=False)

        assert _count(db_path, "messages") == 0

    def test_backup_called_when_requested(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))

        with patch("agent_session_tools.maintenance.create_backup") as mock_backup:
            mock_backup.return_value = tmp_path / "bak.db"
            _archive(db_path, days=30, backup=True)

        mock_backup.assert_called_once_with(db_path)

    def test_appends_to_existing_archive(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(200))

        archive_path = db_path.parent / f"{db_path.stem}_archive.db"

        # First archive run creates the archive
        with patch("agent_session_tools.maintenance.create_backup"):
            _archive(db_path, days=30, backup=False)

        assert archive_path.exists()

        # Second session added and archived
        _insert_session(db_path, "old-2", self._old_date(150))

        with patch("agent_session_tools.maintenance.create_backup"):
            _archive(db_path, days=30, backup=False)

        archive_conn = sqlite3.connect(archive_path)
        count = archive_conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        archive_conn.close()
        assert count == 2

    def test_archive_twice_appends_second_batch(self, tmp_path):
        """F-AST-05@claude: the second run re-inserted every archived
        message into messages_fts with its existing rowid, which FTS5
        refuses, so archiving worked once per machine."""
        db_path = _make_db(tmp_path)
        archive_path = db_path.parent / f"{db_path.stem}_archive.db"
        _insert_session(db_path, "old-1", self._old_date(200))
        _insert_message(db_path, "m-1", "old-1", content="first batch")
        assert _archive(db_path, days=30, backup=False) == 0

        _insert_session(db_path, "old-2", self._old_date(150))
        _insert_message(db_path, "m-2", "old-2", content="second batch")
        assert _archive(db_path, days=30, backup=False) == 0

        assert _count(archive_path, "sessions") == 2
        assert _count(archive_path, "messages") == 2
        assert _count(archive_path, "messages_fts") == 2
        conn = sqlite3.connect(archive_path)
        hits = conn.execute(
            "SELECT session_id FROM messages_fts WHERE messages_fts MATCH 'batch'"
            " ORDER BY session_id"
        ).fetchall()
        conn.close()
        assert hits == [("old-1",), ("old-2",)]
        assert _count(db_path, "sessions") == 0

    def test_archiving_the_same_session_again_leaves_one_fts_entry(self, tmp_path):
        db_path = _make_db(tmp_path)
        archive_path = db_path.parent / f"{db_path.stem}_archive.db"
        for _ in range(2):
            _insert_session(db_path, "old-1", self._old_date(200))
            _insert_message(db_path, "m-1", "old-1", content="re-imported")
            assert _archive(db_path, days=30, backup=False) == 0

        assert _count(archive_path, "messages") == 1
        assert _count(archive_path, "messages_fts") == 1

    def test_archive_preserves_all_columns(self, tmp_path):
        """Archive must not silently drop columns added by later migrations.

        Regression test for schema drift: the archive CREATE TABLE was missing
        content_hash, import_fingerprint, session_type (sessions) and
        content_hash, seq (messages).
        """
        db_path = _make_db(tmp_path)

        _insert_session(
            db_path,
            "old-full",
            self._old_date(100),
            content_hash="abc123hash",
            import_fingerprint="fp-xyz",
            session_type="learning",
        )
        _insert_message(
            db_path,
            "msg-full",
            "old-full",
            content="test message with extra columns",
            content_hash="msghash99",
            seq=42,
        )

        archive_path = db_path.parent / f"{db_path.stem}_archive.db"

        with patch("agent_session_tools.maintenance.create_backup"):
            result = _archive(db_path, days=30, backup=False)

        assert result == 0
        assert archive_path.exists()

        archive_conn = sqlite3.connect(archive_path)
        archive_conn.row_factory = sqlite3.Row

        session = archive_conn.execute(
            "SELECT * FROM sessions WHERE id = 'old-full'"
        ).fetchone()
        assert session is not None
        assert session["content_hash"] == "abc123hash"
        assert session["import_fingerprint"] == "fp-xyz"
        assert session["session_type"] == "learning"

        msg = archive_conn.execute(
            "SELECT * FROM messages WHERE id = 'msg-full'"
        ).fetchone()
        assert msg is not None
        assert msg["content_hash"] == "msghash99"
        assert msg["seq"] == 42

        archive_conn.close()


# ---------------------------------------------------------------------------
# _delete_old
# ---------------------------------------------------------------------------


class TestDeleteOld:
    def _old_date(self, days_ago: int = 100) -> str:
        return (datetime.now() - timedelta(days=days_ago)).isoformat()

    def _recent_date(self, days_ago: int = 1) -> str:
        return (datetime.now() - timedelta(days=days_ago)).isoformat()

    def test_returns_1_when_db_missing(self, tmp_path):
        db_path = tmp_path / "nope.db"
        result = _delete_old(db_path, days=30, confirm=True, backup=False)
        assert result == 1

    def test_returns_0_when_no_old_sessions(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "s1", self._recent_date())
        result = _delete_old(db_path, days=30, confirm=True, backup=False)
        assert result == 0

    def test_returns_1_without_confirm(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))
        result = _delete_old(db_path, days=30, confirm=False, backup=False)
        assert result == 1

    def test_sessions_not_deleted_without_confirm(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))
        _delete_old(db_path, days=30, confirm=False, backup=False)
        assert _count(db_path, "sessions") == 1

    def test_old_sessions_deleted_with_confirm(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))
        _insert_session(db_path, "new-1", self._recent_date())

        with patch("agent_session_tools.maintenance.create_backup"):
            result = _delete_old(db_path, days=30, confirm=True, backup=False)

        assert result == 0
        assert _count(db_path, "sessions") == 1

    def test_messages_cascade_deleted(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))
        _insert_message(db_path, "m1", "old-1", "gone message")
        _insert_message(db_path, "m2", "old-1", "also gone")

        with patch("agent_session_tools.maintenance.create_backup"):
            _delete_old(db_path, days=30, confirm=True, backup=False)

        assert _count(db_path, "messages") == 0

    def test_recent_messages_preserved(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))
        _insert_session(db_path, "new-1", self._recent_date())
        _insert_message(db_path, "m-old", "old-1", "old msg")
        _insert_message(db_path, "m-new", "new-1", "new msg")

        with patch("agent_session_tools.maintenance.create_backup"):
            _delete_old(db_path, days=30, confirm=True, backup=False)

        assert _count(db_path, "messages") == 1
        conn = sqlite3.connect(db_path)
        msg = conn.execute("SELECT id FROM messages").fetchone()
        conn.close()
        assert msg[0] == "m-new"

    def test_backup_called_when_requested(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))

        with patch("agent_session_tools.maintenance.create_backup") as mock_backup:
            mock_backup.return_value = tmp_path / "bak.db"
            _delete_old(db_path, days=30, confirm=True, backup=True)

        mock_backup.assert_called_once_with(db_path)

    def test_backup_not_called_without_confirm(self, tmp_path):
        """Backup should not be triggered when the user hasn't confirmed deletion."""
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", self._old_date(100))

        with patch("agent_session_tools.maintenance.create_backup") as mock_backup:
            _delete_old(db_path, days=30, confirm=False, backup=True)

        mock_backup.assert_not_called()


# ---------------------------------------------------------------------------
# R-20: cutoff must be real UTC, not naive local time. updated_at is
# UTC-sourced (exporters/claude.py, exporters/codex.py); a naive
# datetime.now() cutoff shifts the delete/archive boundary by the machine's
# local UTC offset. Runs the boundary case under two non-UTC zones.
# ---------------------------------------------------------------------------


@pytest.fixture
def _restore_tz():
    original = os.environ.get("TZ")

    def _set(tz: str) -> None:
        os.environ["TZ"] = tz
        time.tzset()

    yield _set

    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


class TestDeleteOldUtcCutoff:
    @pytest.mark.parametrize("tz", ["Pacific/Auckland", "America/Los_Angeles"])
    def test_minute_inside_kept_minute_outside_deleted(self, tz, tmp_path, _restore_tz):
        db_path = _make_db(tmp_path)
        days = 1
        cutoff_instant = datetime.now(UTC) - timedelta(days=days)
        inside = (cutoff_instant + timedelta(minutes=1)).isoformat()
        outside = (cutoff_instant - timedelta(minutes=1)).isoformat()

        _insert_session(db_path, "s-in", inside)
        _insert_session(db_path, "s-out", outside)

        _restore_tz(tz)
        with patch("agent_session_tools.maintenance.create_backup"):
            _delete_old(db_path, days=days, confirm=True, backup=False)

        remaining = {
            r[0] for r in sqlite3.connect(db_path).execute("SELECT id FROM sessions")
        }
        assert "s-in" in remaining, (
            f"a session 1 minute inside the UTC cutoff must survive under TZ={tz}"
        )
        assert "s-out" not in remaining, (
            f"a session 1 minute outside the UTC cutoff must be deleted under TZ={tz}"
        )


# ---------------------------------------------------------------------------
# F-AST-03@sol: create_backup returns None when it refuses (the backup_max_mb
# size guard). A command whose backup was requested must then change nothing,
# as sync.py's pull already does ("refusing to import without a backup").
# ---------------------------------------------------------------------------


def _old_iso(days_ago: int = 100) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


class TestRequestedBackupRefused:
    def _db_with_old_session(self, tmp_path: Path) -> Path:
        db_path = _make_db(tmp_path)
        _insert_session(db_path, "old-1", _old_iso())
        _insert_message(db_path, "m-1", "old-1")
        return db_path

    def test_delete_changes_nothing(self, tmp_path):
        db_path = self._db_with_old_session(tmp_path)
        with patch(
            "agent_session_tools.maintenance.create_backup", return_value=None
        ) as mock_backup:
            rc = _delete_old(db_path, days=30, confirm=True, backup=True)
        mock_backup.assert_called_once_with(db_path)
        assert rc == 1
        assert _count(db_path, "sessions") == 1
        assert _count(db_path, "messages") == 1

    def test_archive_changes_nothing(self, tmp_path):
        db_path = self._db_with_old_session(tmp_path)
        archive_path = db_path.parent / f"{db_path.stem}_archive.db"
        with patch(
            "agent_session_tools.maintenance.create_backup", return_value=None
        ) as mock_backup:
            rc = _archive(db_path, days=30, backup=True)
        mock_backup.assert_called_once_with(db_path)
        assert rc == 1
        assert _count(db_path, "sessions") == 1
        assert _count(db_path, "messages") == 1
        assert not archive_path.exists()

    def test_vacuum_changes_nothing(self, tmp_path):
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.executemany(
            "INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)",
            [(f"m-{i}", "s", "user", "x" * 4000) for i in range(200)],
        )
        conn.commit()
        conn.execute("DELETE FROM messages")
        conn.commit()
        conn.close()
        size_with_free_pages = db_path.stat().st_size

        with patch("agent_session_tools.maintenance.create_backup", return_value=None):
            rc = _vacuum(db_path, backup=True)
        assert rc == 1
        assert db_path.stat().st_size == size_with_free_pages
        # Control: the same database does shrink when no backup is requested.
        assert _vacuum(db_path, backup=False) == 0
        assert db_path.stat().st_size < size_with_free_pages

    def test_reindex_changes_nothing(self, tmp_path):
        db_path = self._db_with_old_session(tmp_path)
        assert _count(db_path, "messages_fts") == 0  # drifted: never indexed
        with patch("agent_session_tools.maintenance.create_backup", return_value=None):
            rc = _reindex(db_path, backup=True)
        assert rc == 1
        assert _count(db_path, "messages_fts") == 0


# ---------------------------------------------------------------------------
# F-AST-06@claude: a session with no timestamp is of unknown age, not "older
# than N days". Kiro v1 conversations are exported with created_at and
# updated_at both NULL (exporters/kiro.py, the use_v2 branch).
# ---------------------------------------------------------------------------


def _insert_session_dates(
    db_path: Path, session_id: str, created_at: str | None, updated_at: str | None
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO sessions (id, source, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, "kiro", created_at, updated_at),
    )
    conn.commit()
    conn.close()


def _session_ids(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    ids = {r[0] for r in conn.execute("SELECT id FROM sessions")}
    conn.close()
    return ids


class TestUndatedSessionsAreNotOld:
    def _seed(self, db_path: Path) -> None:
        _insert_session_dates(db_path, "undated", None, None)
        _insert_session_dates(db_path, "created-old", _old_iso(100), None)
        _insert_session_dates(db_path, "created-recent", _old_iso(1), None)
        _insert_session_dates(db_path, "message-dated-old", None, None)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp)"
            " VALUES (?, ?, ?, ?, ?)",
            ("m-old", "message-dated-old", "user", "hi", _old_iso(100)),
        )
        conn.commit()
        conn.close()

    def test_delete_old_keeps_undated_sessions(self, tmp_path, capsys):
        db_path = _make_db(tmp_path)
        self._seed(db_path)

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 0

        assert _session_ids(db_path) == {"undated", "created-recent"}
        assert "1 session(s) with no timestamp" in capsys.readouterr().out

    def test_archive_keeps_undated_sessions(self, tmp_path, capsys):
        db_path = _make_db(tmp_path)
        self._seed(db_path)

        assert _archive(db_path, days=30, backup=False) == 0

        assert _session_ids(db_path) == {"undated", "created-recent"}
        archive_path = db_path.parent / f"{db_path.stem}_archive.db"
        assert _session_ids(archive_path) == {"created-old", "message-dated-old"}
        assert "1 session(s) with no timestamp" in capsys.readouterr().out

    def test_only_undated_sessions_means_nothing_to_do(self, tmp_path):
        db_path = _make_db(tmp_path)
        _insert_session_dates(db_path, "undated", None, None)

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 0
        assert _archive(db_path, days=30, backup=False) == 0
        assert _session_ids(db_path) == {"undated"}


# ---------------------------------------------------------------------------
# F-AST-04@sol / F-AST-02@sol: on a current-schema database (lifecycle tables,
# schema 41+) a permanent delete must leave a tombstone so the next export
# cannot re-import the session, and neither delete nor archive may leave
# dependent rows (notes, tags, file references, learner records) orphaned.
# ---------------------------------------------------------------------------


def _current_db(tmp_path: Path) -> Path:
    from agent_session_tools.export_sessions import init_db

    db_path = tmp_path / "sessions.db"
    init_db(str(db_path)).close()
    return db_path


def _export(db_path: Path, session_id: str, when: str) -> None:
    """Write one session + message through the exporters' own write path."""
    from agent_session_tools.exporters.base import ExportStats, commit_batch

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
    conn.close()


def _add_note_tag_and_file_reference(db_path: Path, session_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO session_notes (session_id, notes) VALUES (?, ?)",
        (session_id, "my note"),
    )
    conn.execute(
        "INSERT INTO session_tags (session_id, tag) VALUES (?, ?)", (session_id, "t")
    )
    conn.execute(
        "INSERT INTO file_references (session_id, message_id, file_path, tool_name)"
        " VALUES (?, ?, ?, ?)",
        (session_id, f"{session_id}-m1", "/x.py", "Read"),
    )
    conn.commit()
    conn.close()


def _orphans(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    return rows


class TestCurrentSchemaDelete:
    def test_delete_writes_a_tombstone_so_the_next_export_cannot_reimport(
        self, tmp_path
    ):
        db_path = _current_db(tmp_path)
        _export(db_path, "old-1", _old_iso(100))

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 0
        assert _session_ids(db_path) == set()

        # The native transcript is still on disk; the next export sees it.
        _export(db_path, "old-1", _old_iso(100))
        assert _session_ids(db_path) == set()

    def test_delete_leaves_no_orphaned_dependents(self, tmp_path):
        db_path = _current_db(tmp_path)
        _export(db_path, "old-1", _old_iso(100))
        _add_note_tag_and_file_reference(db_path, "old-1")

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 0

        assert _orphans(db_path) == []
        for table in ("session_notes", "session_tags", "file_references"):
            assert _count(db_path, table) == 0

    def test_delete_keeps_a_session_that_owns_learner_records(self, tmp_path, capsys):
        """A tombstone forgets the learner records a session owns; prune keeps
        such sessions (tiering._anchored_session_ids), and so does delete."""
        db_path = _current_db(tmp_path)
        _export(db_path, "old-1", _old_iso(100))
        _export(db_path, "old-2", _old_iso(100))
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO study_sessions (id, session_id, topic, started_at)"
            " VALUES (?, ?, ?, ?)",
            ("study-1", "old-1", "sql", _old_iso(100)),
        )
        conn.commit()
        conn.close()

        assert _delete_old(db_path, days=30, confirm=True, backup=False) == 0

        assert _session_ids(db_path) == {"old-1"}
        assert _count(db_path, "study_sessions") == 1
        assert "1 session(s) that own learner records" in capsys.readouterr().out


class TestCurrentSchemaArchive:
    def test_archive_keeps_sessions_whose_dependents_it_cannot_hold(
        self, tmp_path, capsys
    ):
        db_path = _current_db(tmp_path)
        archive_path = db_path.parent / f"{db_path.stem}_archive.db"
        _export(db_path, "plain", _old_iso(100))
        _export(db_path, "noted", _old_iso(100))
        _add_note_tag_and_file_reference(db_path, "noted")

        assert _archive(db_path, days=30, backup=False) == 0

        assert _orphans(db_path) == []
        assert _session_ids(db_path) == {"noted"}
        assert _session_ids(archive_path) == {"plain"}
        assert _count(db_path, "session_notes") == 1
        out = capsys.readouterr().out
        assert "Kept 1 session(s) with rows the archive cannot hold" in out
        assert "session-maint sync-full" in out


# ---------------------------------------------------------------------------
# _handle_duplicates
# ---------------------------------------------------------------------------


class TestHandleDuplicates:
    """Tests for the deduplication orchestration wrapper."""

    def test_returns_1_when_db_missing(self, tmp_path):
        db_path = tmp_path / "nope.db"
        result = _handle_duplicates(db_path)
        assert result == 1

    def test_list_mode_calls_list_all_duplicates(self, tmp_path):
        db_path = _make_db(tmp_path)

        with patch("agent_session_tools.maintenance.list_all_duplicates") as mock_list:
            result = _handle_duplicates(db_path, threshold=0.8)

        assert result == 0
        mock_list.assert_called_once()

    def test_auto_merge_calls_auto_merge_safe(self, tmp_path):
        db_path = _make_db(tmp_path)

        with patch(
            "agent_session_tools.maintenance.auto_merge_safe_duplicates"
        ) as mock_auto:
            mock_auto.return_value = {
                "groups_merged": 0,
                "messages_moved": 0,
                "sessions_removed": 0,
            }
            result = _handle_duplicates(db_path, auto_merge=True)

        assert result == 0
        mock_auto.assert_called_once()
        # Verify it used the 0.95 high-confidence threshold
        call_kwargs = mock_auto.call_args
        assert (
            call_kwargs.kwargs.get(
                "min_similarity",
                call_kwargs.args[1] if len(call_kwargs.args) > 1 else None,
            )
            == 0.95
        )

    def test_manual_merge_calls_merge_duplicates(self, tmp_path):
        db_path = _make_db(tmp_path)
        merge_ids = ["primary-id", "dup-id-1", "dup-id-2"]

        with patch("agent_session_tools.maintenance.merge_duplicates") as mock_merge:
            mock_merge.return_value = {"messages_moved": 5, "sessions_removed": 2}
            result = _handle_duplicates(db_path, merge_ids=merge_ids)

        assert result == 0
        mock_merge.assert_called_once()
        call_args = mock_merge.call_args
        # First positional arg is conn, second is primary_id, third is duplicate_ids
        assert call_args.args[1] == "primary-id"
        assert call_args.args[2] == ["dup-id-1", "dup-id-2"]

    def test_auto_merge_reports_when_groups_merged(self, tmp_path, capsys):
        db_path = _make_db(tmp_path)

        with patch(
            "agent_session_tools.maintenance.auto_merge_safe_duplicates"
        ) as mock_auto:
            mock_auto.return_value = {
                "groups_merged": 3,
                "messages_moved": 12,
                "sessions_removed": 3,
            }
            _handle_duplicates(db_path, auto_merge=True)

        captured = capsys.readouterr()
        assert "3" in captured.out

    def test_auto_merge_reports_none_found(self, tmp_path, capsys):
        db_path = _make_db(tmp_path)

        with patch(
            "agent_session_tools.maintenance.auto_merge_safe_duplicates"
        ) as mock_auto:
            mock_auto.return_value = {
                "groups_merged": 0,
                "messages_moved": 0,
                "sessions_removed": 0,
            }
            _handle_duplicates(db_path, auto_merge=True)

        captured = capsys.readouterr()
        assert "No high-similarity" in captured.out

    def test_connection_closed_on_db_not_found(self, tmp_path):
        """Verify we fail fast and don't leave open connections."""
        db_path = tmp_path / "ghost.db"
        # Should not raise; just return 1
        result = _handle_duplicates(db_path)
        assert result == 1
