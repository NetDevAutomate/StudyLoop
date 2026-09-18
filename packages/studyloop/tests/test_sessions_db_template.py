"""The per-test ``sessions.db`` is a copy of one migrated template, not a bootstrap.

``studyloop.history._connection._connect`` creates the sessions database from
``SCHEMA_FILE`` and runs every migration the first time any caller opens a
path that does not exist. Fourteen test modules pointed ``STUDYLOOP_DB`` at a
fresh ``tmp_path / "sessions.db"`` per test, so each test's first write —
usually ``plan new`` indexing its document — paid that bootstrap (~60 ms and
a 1 MB file locally, 241 times across those modules). On a slow runner disk
that step is the first to stall: CI run 35350636500 timed out two ``plan
close`` seam tests at 60 s each inside ``plan new`` *creating the database*,
before ``plan close`` ran.

The fix keeps per-test isolation — ``test_plan_application.py`` (council
review 1, F6) needs "no history" to be a fact about the test, not about a
shared database — and removes the bootstrap from every test's critical path:
one template is built once per process through the production ``_connect``,
and each test receives its own copy at its own path.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

import _sessions_db_template as template_module  # pyright: ignore[reportMissingImports]
from _sessions_db_template import (  # pyright: ignore[reportMissingImports]
    seed_sessions_db,
    template_path,
)


def _schema(db: Path) -> set[tuple[str, str, str]]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT type, name, COALESCE(sql, '') FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        return {(t, n, s) for t, n, s in rows}
    finally:
        conn.close()


def _user_version(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def test_template_is_what_the_production_bootstrap_produces(tmp_path, monkeypatch) -> None:
    """Same schema, same user_version as a genuine first ``_connect`` on a fresh path."""
    from agent_session_tools.migrations import CURRENT_VERSION
    from studyloop.history import _connection

    fresh = tmp_path / "fresh" / "sessions.db"
    monkeypatch.setenv("STUDYLOOP_DB", str(fresh))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(tmp_path / "no-config.yaml"))
    conn = _connection._connect()
    assert conn is not None
    conn.close()

    template = template_path()
    assert template.is_file()
    assert _user_version(template) == CURRENT_VERSION == _user_version(fresh)
    assert _schema(template) == _schema(fresh)


def test_seed_gives_each_test_its_own_file_and_skips_the_bootstrap(
    tmp_path, monkeypatch, caplog
) -> None:
    from studyloop.history import _connection

    first = seed_sessions_db(tmp_path / "a" / "sessions.db", monkeypatch)
    second = seed_sessions_db(tmp_path / "b" / "sessions.db", monkeypatch)

    assert first != second and first.is_file() and second.is_file()
    assert os.environ["STUDYLOOP_DB"] == str(second), "the last seed wins the env var"

    with caplog.at_level("INFO", logger="studyloop.history._connection"):
        conn = _connection._connect()
    assert conn is not None
    conn.execute(
        "INSERT INTO study_sessions (id, topic, started_at) VALUES ('s1', 'sql', '2026-01-01')"
    )
    conn.commit()
    conn.close()
    assert "Created sessions DB" not in caplog.text, "a seeded path must not be bootstrapped"

    other = sqlite3.connect(first)
    try:
        assert other.execute("SELECT count(*) FROM study_sessions").fetchone()[0] == 0, (
            "a write to one test's database must not be visible from another's"
        )
    finally:
        other.close()


def test_template_is_built_once_per_process(monkeypatch) -> None:
    template_path()  # ensure built

    def must_not_rebuild():  # pragma: no cover - the assertion is that it is never called
        raise AssertionError("template rebuilt")

    monkeypatch.setattr(template_module, "_build", must_not_rebuild)
    assert template_path() == template_path()


def test_seed_copies_a_single_checkpointed_file(tmp_path, monkeypatch) -> None:
    """No ``-wal`` / ``-shm`` sidecar travels with the template or the copy."""
    template = template_path()
    assert sorted(p.name for p in template.parent.iterdir()) == ["sessions.db"]

    dest = seed_sessions_db(tmp_path / "sessions.db", monkeypatch)
    assert sorted(p.name for p in dest.parent.glob("sessions.db*")) == ["sessions.db"]
    conn = sqlite3.connect(dest)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


_FRESH_PATH_PATTERN = re.compile(
    r'setenv\(\s*"STUDYLOOP_DB"\s*,\s*str\(tmp_path\s*/\s*"sessions\.db"\)'
)


def test_no_test_module_bootstraps_a_fresh_sessions_db_per_test() -> None:
    """Lint: the pattern this module retires must not come back.

    A module that needs a database at ``tmp_path / "sessions.db"`` seeds it
    with :func:`seed_sessions_db`; a module that builds its own database (a
    drifted FTS index, a scope fixture) uses its own file name and is not
    matched.
    """
    tests_dir = Path(__file__).parent
    offenders = sorted(
        str(path.relative_to(tests_dir))
        for path in tests_dir.rglob("test_*.py")
        if path != Path(__file__) and _FRESH_PATH_PATTERN.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == [], (
        "these modules bootstrap a fresh sessions.db per test; "
        f"seed it from the template instead: {offenders}"
    )
