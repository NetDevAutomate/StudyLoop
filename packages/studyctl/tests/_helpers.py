"""Shared test helpers for studyctl.

This module exists because studyctl tests CANNOT use conftest.py — a pluggy
namespace conflict occurs when both workspace packages are collected from
the root.  See docs/TESTING.md for the full explanation.

Import these functions in your test files and wrap them in @pytest.fixture
decorators as needed.  They are regular functions, NOT pytest fixtures, so
they won't trigger any pluggy interaction.

Usage::

    from _helpers import make_review_db, make_isolated_config

    @pytest.fixture()
    def review_db(tmp_path):
        return make_review_db(tmp_path)

    @pytest.fixture(autouse=True)
    def isolated_config(tmp_path, monkeypatch):
        return make_isolated_config(tmp_path, monkeypatch)
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def make_review_db(tmp_path: Path) -> Path:
    """Create a temp SQLite DB with studyctl's review tables.

    Returns the ``db_path``.  The file is created with WAL mode and
    the review schema applied via ``ensure_tables()``.
    """
    db_path = tmp_path / "reviews.db"
    # Create the file so ensure_tables finds it
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.close()

    # Import lazily so the module can be loaded even if studyctl
    # isn't fully installed (e.g. during collection).
    from studyctl.review_db import ensure_tables

    ensure_tables(db_path)
    return db_path


def make_isolated_config(tmp_path: Path, monkeypatch) -> Path:
    """Redirect studyctl's central config paths to a temp directory.

    Patches ``studyctl.settings.CONFIG_DIR`` and
    ``studyctl.settings._CONFIG_PATH`` so all config-reading code
    hits *tmp_path* instead of ``~/.config/studyctl``.

    Returns the temp config directory (already created).
    """
    config_dir = tmp_path / ".config" / "studyctl"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr("studyctl.settings.CONFIG_DIR", config_dir)
    monkeypatch.setattr("studyctl.settings._CONFIG_PATH", config_dir / "config.yaml")
    return config_dir
