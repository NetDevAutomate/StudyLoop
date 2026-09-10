"""Tests for doctor database checks."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest


class TestSessionsDbPathResolution:
    """The doctor must check the database the app actually uses.

    Regression guard: this resolver used to import a module that had been
    renamed away (``agent_session_tools.config``), so its hardcoded fallback
    ran unconditionally and the check reported on the default path regardless
    of configuration.
    """

    def test_honours_configured_session_db(self, tmp_path: Path, monkeypatch) -> None:
        from studyloop.doctor.database import _get_sessions_db_path

        configured = tmp_path / "elsewhere" / "sessions.db"
        config_path = tmp_path / "config.yaml"
        config_path.write_text(f"session_db: {configured}\n")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

        assert _get_sessions_db_path() == configured

    def test_does_not_return_hardcoded_default_under_isolation(self) -> None:
        from studyloop.doctor.database import _get_sessions_db_path
        from studyloop.settings import CONFIG_DIR

        assert _get_sessions_db_path() != CONFIG_DIR / "sessions.db"


class TestReviewDbCheck:
    @pytest.fixture()
    def db_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "reviews.db"
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE card_reviews (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE review_sessions (id INTEGER PRIMARY KEY)")
        conn.close()
        return p

    def test_healthy_db(self, db_path: Path):
        from studyloop.doctor.database import check_review_db

        with patch("studyloop.doctor.database._get_review_db_path", return_value=db_path):
            results = check_review_db()
        assert results[0].status == "pass"

    def test_missing_db(self, tmp_path: Path):
        from studyloop.doctor.database import check_review_db

        missing = tmp_path / "nope.db"
        with patch("studyloop.doctor.database._get_review_db_path", return_value=missing):
            results = check_review_db()
        assert results[0].status == "warn"

    def test_corrupt_db(self, tmp_path: Path):
        from studyloop.doctor.database import check_review_db

        bad = tmp_path / "bad.db"
        bad.write_bytes(b"not a sqlite db")
        with patch("studyloop.doctor.database._get_review_db_path", return_value=bad):
            results = check_review_db()
        assert results[0].status == "fail"


class TestSessionsDbCheck:
    def test_not_installed(self):
        from studyloop.doctor.database import check_sessions_db

        with patch("importlib.util.find_spec", return_value=None):
            results = check_sessions_db()
        assert results[0].status == "info"
        assert "not installed" in results[0].message.lower()

    def test_installed_db_exists(self, tmp_path: Path):
        from studyloop.doctor.database import check_sessions_db

        db = tmp_path / "sessions.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY)")
        conn.close()

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("studyloop.doctor.database._get_sessions_db_path", return_value=db),
        ):
            results = check_sessions_db()
        assert results[0].status == "pass"

    def test_installed_db_missing(self, tmp_path: Path):
        from studyloop.doctor.database import check_sessions_db

        missing = tmp_path / "nope.db"
        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("studyloop.doctor.database._get_sessions_db_path", return_value=missing),
        ):
            results = check_sessions_db()
        assert results[0].status == "warn"


class TestLegacySourceVisibility:
    """Retired-source rows are hidden at the read paths but never deleted.

    Hidden *and* silent is what makes a learner think their history vanished, so
    doctor states the scoping explicitly. The row is ``info``: a fact with no
    remedy, which must not move the exit code or trigger ``--fix``.
    """

    @staticmethod
    def _build_db(path: Path, sources: dict[str, int]) -> Path:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, source TEXT)")
        for source, count in sources.items():
            conn.executemany(
                "INSERT INTO sessions (source) VALUES (?)",
                [(source,)] * count,
            )
        conn.commit()
        conn.close()
        return path

    @staticmethod
    def _legacy_row(results):
        rows = [r for r in results if r.name == "legacy-sources"]
        assert len(rows) == 1, f"expected exactly one legacy-sources row, got {len(rows)}"
        return rows[0]

    def _run(self, db: Path):
        from studyloop.doctor.database import check_sessions_db

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("studyloop.doctor.database._get_sessions_db_path", return_value=db),
        ):
            return check_sessions_db()

    def test_reports_retired_sources_with_counts(self, tmp_path: Path):
        db = self._build_db(
            tmp_path / "sessions.db",
            {
                # supported: must not be counted as retired
                "claude_code": 2,
                "kiro_cli": 2,
                # retired: adapters that no longer exist in the tree
                "repoprompt": 5,
                "aider": 3,
                "gemini_cli": 1,
            },
        )
        row = self._legacy_row(self._run(db))

        assert row.status == "info"
        assert row.category == "database"
        assert row.fix_auto is False
        assert "9 sessions in 3 retired sources" in row.message
        assert "hidden from search, not deleted" in row.message
        # Descending by count, so the biggest offender leads.
        assert "repoprompt 5, aider 3, gemini_cli 1" in row.message
        # Supported labels are never named as retired.
        assert "claude_code" not in row.message
        assert "kiro_cli" not in row.message
        assert "Nothing to fix" in row.fix_hint

    def test_passes_when_every_source_is_supported(self, tmp_path: Path):
        from studyloop.harnesses import SESSION_SOURCE_BY_HARNESS

        supported = dict.fromkeys(SESSION_SOURCE_BY_HARNESS.values(), 1)
        # study_mentor is written by tutor-checkpoint: a first-party source, not
        # a harness, so it is absent from SESSION_SOURCE_BY_HARNESS yet supported.
        supported["study_mentor"] = 1
        db = self._build_db(tmp_path / "sessions.db", supported)
        row = self._legacy_row(self._run(db))

        assert row.status == "pass"
        assert row.message == "no legacy-source sessions"

    def test_no_row_when_sessions_table_absent(self, tmp_path: Path):
        db = tmp_path / "sessions.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.close()

        results = self._run(db)
        # A fresh DB must not grow a second failure row — the existing
        # sessions_db check already speaks for a DB that is missing or unusable.
        assert [r for r in results if r.name == "legacy-sources"] == []

    def test_null_source_rows_are_counted_as_hidden(self, tmp_path: Path):
        """The read paths admit `source IN (...)`; a NULL source never matches, so
        it is hidden -- and doctor must say so, not silently skip it."""
        db = tmp_path / "sessions.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, source TEXT)")
        conn.executemany(
            "INSERT INTO sessions (source) VALUES (?)",
            [("kiro_cli",), (None,), (None,)],
        )
        conn.commit()
        conn.close()

        row = self._legacy_row(self._run(db))
        assert row.status == "info"
        assert "2 sessions in 1 retired source" in row.message
        assert "(null) 2" in row.message

    def test_info_row_does_not_affect_exit_code_or_fixes(self, tmp_path: Path):
        from studyloop.cli._doctor import _apply_fixes, _compute_exit_code

        db = self._build_db(tmp_path / "sessions.db", {"claude_code": 1, "aider": 4})
        row = self._legacy_row(self._run(db))

        assert _compute_exit_code([row]) == 0
        assert _apply_fixes([row]) == []
