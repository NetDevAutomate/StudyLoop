"""Copies of the 0600 session database are owner-only from their first byte.

F-AST-14@claude: ``create_backup`` let ``sqlite3.connect`` create the backup
under the process umask, so under the common umask 022 every rotated backup
of an owner-only database was world-readable (0644). The archive database
written by ``session-maint archive`` had the same defect. These tests run
under umask 022 and look at the destination at the moment SQLite opens it,
so a fix that chmods after the content is written still fails.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_session_tools import maintenance
from agent_session_tools.maintenance import _archive, create_backup


@pytest.fixture
def umask_022() -> Iterator[None]:
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def _current_umask() -> int:
    value = os.umask(0)
    os.umask(value)
    return value


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _owner_only_db(tmp_path: Path) -> Path:
    """A 0600 sessions database holding one session and one message."""
    db_path = tmp_path / "sessions.db"
    os.close(os.open(db_path, os.O_WRONLY | os.O_CREAT, 0o600))
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, project_path TEXT,
            git_branch TEXT, created_at TEXT, updated_at TEXT, metadata JSON,
            content_hash TEXT, import_fingerprint TEXT,
            session_type TEXT DEFAULT 'work'
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, parent_id TEXT,
            role TEXT NOT NULL, content TEXT, model TEXT, timestamp TEXT,
            metadata JSON, content_hash TEXT, seq INTEGER
        );
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            content, session_id UNINDEXED, role UNINDEXED,
            tokenize='porter unicode61'
        );
        """
    )
    conn.execute(
        "INSERT INTO sessions (id, source, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("s-old", "claude_code", old, old),
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)",
        ("m-1", "s-old", "user", "a private conversation"),
    )
    conn.commit()
    conn.close()
    assert _mode(db_path) == 0o600
    return db_path


class _ConnectSpy:
    """Record each destination's mode and size at the moment SQLite opens it."""

    def __init__(self, watch_dir: Path, real_connect) -> None:
        self.watch_dir = watch_dir
        self.real_connect = real_connect
        self.seen: dict[Path, tuple[int, int] | None] = {}

    def __call__(self, database, *args, **kwargs):
        path = Path(database)
        if path.parent == self.watch_dir and path.name != "sessions.db":
            self.seen[path] = (
                (_mode(path), path.stat().st_size) if path.exists() else None
            )
        return self.real_connect(database, *args, **kwargs)


def test_backup_is_created_0600_under_umask_022(tmp_path, umask_022, monkeypatch):
    db_path = _owner_only_db(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    spy = _ConnectSpy(backup_dir, sqlite3.connect)
    monkeypatch.setattr(maintenance.sqlite3, "connect", spy)

    with patch(
        "agent_session_tools.maintenance.get_backup_dir", return_value=backup_dir
    ):
        backup_path = create_backup(db_path)

    assert backup_path is not None
    # Owner-only and still empty when SQLite first opened it: no byte of the
    # copy ever sat in a wider-mode file.
    assert spy.seen[backup_path] == (0o600, 0)
    assert _mode(backup_path) == 0o600
    monkeypatch.undo()
    conn = sqlite3.connect(backup_path)
    assert conn.execute("SELECT content FROM messages").fetchone() == (
        "a private conversation",
    )
    conn.close()
    assert _current_umask() == 0o022


def test_backup_over_an_existing_wider_file_is_made_0600_first(
    tmp_path, umask_022, monkeypatch
):
    """Same-second re-backup reuses the timestamped name; it must tighten it."""
    db_path = _owner_only_db(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    fixed = datetime(2026, 10, 21, 18, 0, 0)
    stale = backup_dir / f"{db_path.stem}_backup_{fixed:%Y%m%d_%H%M%S}.db"
    stale.write_bytes(b"")
    stale.chmod(0o644)
    spy = _ConnectSpy(backup_dir, sqlite3.connect)
    monkeypatch.setattr(maintenance.sqlite3, "connect", spy)

    class _FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 - signature of datetime.now
            return fixed

    with (
        patch(
            "agent_session_tools.maintenance.get_backup_dir", return_value=backup_dir
        ),
        patch("agent_session_tools.maintenance.datetime", _FixedNow),
    ):
        backup_path = create_backup(db_path)

    assert backup_path == stale
    assert spy.seen[stale] == (0o600, 0)
    assert _mode(stale) == 0o600


def test_archive_db_is_created_0600_under_umask_022(tmp_path, umask_022, monkeypatch):
    db_path = _owner_only_db(tmp_path)
    archive_path = tmp_path / "sessions_archive.db"
    spy = _ConnectSpy(tmp_path, sqlite3.connect)
    monkeypatch.setattr(maintenance.sqlite3, "connect", spy)

    assert _archive(db_path, days=30, backup=False) == 0

    assert spy.seen[archive_path] == (0o600, 0)
    assert _mode(archive_path) == 0o600
    assert _current_umask() == 0o022
