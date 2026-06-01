"""Shared test helpers for studyloop.

This module exists because studyloop tests CANNOT use conftest.py — a pluggy
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

import asyncio
import sqlite3
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path


# A single dedicated event loop, reused for every run_async() call across the
# whole test session, running on its own background thread.
#
# WHY NOT asyncio.run(): the web-session/content-gen test fixtures call
# asyncio.run(active.release()) in setup/teardown. asyncio.run() raises
# "cannot be called from a running event loop" if ANY loop is already running
# on the calling thread. In the full suite, pytest-asyncio (asyncio_mode=strict)
# leaves a loop installed/running on the main thread after async tests, so
# every subsequent asyncio.run() in a sync fixture exploded — 35 ERRORs that
# only appeared in the full ordered run, never in isolation.
#
# WHY A PERSISTENT loop (not a fresh one per call): session/active.py and
# content/active_gen.py hold module-level ``asyncio.Lock()`` singletons. On
# Python 3.10+ an asyncio.Lock binds to the running loop on first use; reusing
# it from a different loop raises "bound to a different event loop". A single
# reused loop keeps those module locks consistently bound for the session.
#
# Running on a background thread means run_async() works regardless of whether
# the *calling* thread already has a running loop — sidestepping the conflict
# entirely.
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Return the shared background event loop, starting it on first use."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_loop.run_forever,
            name="studyloop-test-loop",
            daemon=True,
        )
        _loop_thread.start()
        return _loop


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run ``coro`` to completion on a dedicated background event loop.

    Drop-in replacement for ``asyncio.run(coro)`` in synchronous test code
    (fixtures, helpers) that is robust to an already-running loop on the
    calling thread. See the module-level comment for the full rationale.
    """
    loop = _ensure_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def make_review_db(tmp_path: Path) -> Path:
    """Create a temp SQLite DB with studyloop's review tables.

    Returns the ``db_path``.  The file is created with WAL mode and
    the review schema applied via ``ensure_tables()``.
    """
    db_path = tmp_path / "reviews.db"
    # Create the file so ensure_tables finds it
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.close()

    # Import lazily so the module can be loaded even if studyloop
    # isn't fully installed (e.g. during collection).
    from studyloop.review_db import ensure_tables

    ensure_tables(db_path)
    return db_path


def make_isolated_config(tmp_path: Path, monkeypatch) -> Path:
    """Redirect studyloop's central config paths to a temp directory.

    Patches ``studyloop.settings.CONFIG_DIR`` and
    ``studyloop.settings._CONFIG_PATH`` so all config-reading code
    hits *tmp_path* instead of ``~/.config/studyloop``.

    Returns the temp config directory (already created).
    """
    config_dir = tmp_path / ".config" / "studyloop"
    config_dir.mkdir(parents=True)
    monkeypatch.setattr("studyloop.settings.CONFIG_DIR", config_dir)
    monkeypatch.setattr("studyloop.settings._CONFIG_PATH", config_dir / "config.yaml")
    return config_dir
