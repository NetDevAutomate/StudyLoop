"""Tests for the shared SQLite connection factory."""

from __future__ import annotations

import sqlite3
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
