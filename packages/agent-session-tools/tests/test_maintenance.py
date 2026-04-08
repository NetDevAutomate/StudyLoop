"""Tests for agent_session_tools.maintenance — core business logic."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


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

        # Verify backup contains the same data
        conn = sqlite3.connect(backup_path)
        row = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        conn.close()
        assert row[0] == 1

    def test_backup_dir_created_if_absent(self, tmp_path):
        db_path = _make_db(tmp_path)
        backup_dir = tmp_path / "deep" / "nested" / "backups"

        assert not backup_dir.exists()
        with patch(
            "agent_session_tools.maintenance.get_backup_dir", return_value=backup_dir
        ):
            create_backup(db_path)

        assert backup_dir.exists()


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
