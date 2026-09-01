"""Tests for the shared SQLite connection factory."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from studyloop.db import connect_db

if TYPE_CHECKING:
    from pathlib import Path


def test_connect_db_enables_foreign_keys_per_connection(tmp_path: Path) -> None:
    db = tmp_path / "fk.db"

    conn = connect_db(db)
    try:
        enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert enabled == 1

        conn.executescript(
            """
            CREATE TABLE parent (id INTEGER PRIMARY KEY);
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parent(id)
            );
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 999)")
    finally:
        conn.close()

    second = connect_db(db)
    try:
        assert second.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        second.close()


def test_connect_db_does_not_raise_when_another_connection_holds_the_write_lock(
    tmp_path: Path,
) -> None:
    """Opening a connection must not fail because someone else is mid-write.

    ``PRAGMA journal_mode`` needs a lock that SQLite refuses **immediately** with
    ``SQLITE_BUSY`` rather than honouring ``busy_timeout``. So a connection
    opened while another holds a write transaction used to raise
    ``OperationalError: database is locked`` from inside ``connect_db`` itself.

    That mattered because ``history/_connection.py`` calls ``connect_db``
    *outside* its try block, so the error escaped as an unhandled exception and
    the HTTP request became a 500 -- load-dependent, and invisible when the same
    route was exercised on its own.
    """
    db = tmp_path / "wal-race.db"

    # A plain connection leaves the file in rollback-journal mode, so connect_db
    # genuinely has a journal_mode change to make (the interesting case).
    blocker = sqlite3.connect(str(db))
    blocker.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    blocker.commit()
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO t (id) VALUES (1)")

    try:
        conn = connect_db(db)
        try:
            # Usable regardless of which journal mode the race settled on.
            assert conn.execute("SELECT 1").fetchone()[0] == 1
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        finally:
            conn.close()
    finally:
        blocker.rollback()
        blocker.close()


def test_connect_db_reaches_wal_under_parallel_first_open(tmp_path: Path) -> None:
    """Several connections opening one brand-new database all succeed.

    This is the cold-install shape: the SPA fires four API calls in parallel on
    first load and each opens its own connection, so they race to convert a file
    that does not exist yet. Every caller must get a working connection, and the
    database must end up in WAL.
    """
    db = tmp_path / "parallel-open.db"
    parallel = 8

    def _open() -> str | None:
        try:
            conn = connect_db(db)
        except Exception as exc:  # any failure here IS the regression
            return f"{type(exc).__name__}: {exc}"
        try:
            conn.execute("SELECT 1").fetchone()
            return None
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        errors = [e for e in pool.map(lambda _: _open(), range(parallel)) if e]

    assert not errors, f"{len(errors)} of {parallel} parallel opens failed: {errors[:3]}"

    check = connect_db(db)
    try:
        mode = check.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal", f"database left in {mode!r} mode, expected wal"
    finally:
        check.close()
