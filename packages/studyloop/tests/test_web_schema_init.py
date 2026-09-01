"""Startup schema preparation — the server must not build schema mid-request."""

from __future__ import annotations

import sqlite3
from pathlib import Path  # noqa: TC003 — used at runtime in fixtures

import pytest


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


@pytest.fixture()
def temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every schema consumer at a database that does not exist yet."""
    db = tmp_path / "sessions.db"
    monkeypatch.setattr("studyloop.settings.get_db_path", lambda: db)
    monkeypatch.setattr("studyloop.parking.get_db_path", lambda: db)
    monkeypatch.setattr("studyloop.notes.get_db_path", lambda: db)
    monkeypatch.setattr("studyloop.review_db._get_db", lambda: db)
    return db


class TestPrepareSchema:
    def test_builds_every_schema_from_nothing(self, temp_db: Path) -> None:
        """One call turns an absent file into a fully-built database."""
        from studyloop.web._schema_init import prepare_schema

        assert not temp_db.exists()
        prepare_schema()

        assert temp_db.exists()
        tables = _tables(temp_db)
        # Base schema from schema.sql, plus each feature bootstrap.
        for expected in ("sessions", "study_sessions", "card_reviews", "study_notes"):
            assert expected in tables, f"{expected} missing; have {sorted(tables)}"

    def test_reaches_the_current_migration_version(self, temp_db: Path) -> None:
        """Startup prep must leave migrations fully applied, not partly.

        A first boot used to run migrations from whichever GET arrived first, so
        the version could advance while sibling requests were mid-flight.
        """
        from agent_session_tools.migrations import CURRENT_VERSION
        from studyloop.web._schema_init import prepare_schema

        prepare_schema()

        conn = sqlite3.connect(str(temp_db))
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        assert version == CURRENT_VERSION, f"expected v{CURRENT_VERSION}, got v{version}"

    def test_is_idempotent(self, temp_db: Path) -> None:
        """Called twice it must not raise — a restart re-runs it."""
        from studyloop.web._schema_init import prepare_schema

        prepare_schema()
        before = _tables(temp_db)
        prepare_schema()
        assert _tables(temp_db) == before

    def test_a_failing_step_is_logged_not_fatal(
        self, temp_db: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A broken bootstrap must not stop the server from starting.

        Falling back to lazy initialisation leaves the server exactly as it was
        before startup prep existed; refusing to boot would turn a recoverable
        condition into an outage.
        """

        def boom() -> None:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr("studyloop.notes.ensure_schema", boom)

        from studyloop.web._schema_init import prepare_schema

        with caplog.at_level("WARNING"):
            prepare_schema()  # must not raise

        assert any("notes schema" in r.getMessage() for r in caplog.records), (
            "the failure should be logged by name"
        )
        # The steps that did work still ran.
        assert "card_reviews" in _tables(temp_db)


class TestLifespanOrdering:
    def test_schema_prep_runs_before_the_reaper(self, temp_db: Path) -> None:
        """The lifespan must prepare schema first, then start the reaper."""
        import inspect

        from studyloop.web import app as app_module

        source = inspect.getsource(app_module._lifespan)
        assert "prepare_schema()" in source, "lifespan does not prepare schema"
        assert source.index("prepare_schema()") < source.index("_grace.start_reaper()"), (
            "schema prep must precede start_reaper so a slow init_db cannot "
            "overlap a reaper tick on a half-built database"
        )
