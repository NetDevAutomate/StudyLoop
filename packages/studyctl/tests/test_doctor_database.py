"""Tests for doctor database checks."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest


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
        from studyctl.doctor.database import check_review_db

        with patch("studyctl.doctor.database._get_review_db_path", return_value=db_path):
            results = check_review_db()
        assert results[0].status == "pass"

    def test_missing_db(self, tmp_path: Path):
        from studyctl.doctor.database import check_review_db

        missing = tmp_path / "nope.db"
        with patch("studyctl.doctor.database._get_review_db_path", return_value=missing):
            results = check_review_db()
        assert results[0].status == "warn"

    def test_corrupt_db(self, tmp_path: Path):
        from studyctl.doctor.database import check_review_db

        bad = tmp_path / "bad.db"
        bad.write_bytes(b"not a sqlite db")
        with patch("studyctl.doctor.database._get_review_db_path", return_value=bad):
            results = check_review_db()
        assert results[0].status == "fail"


class TestSessionsDbCheck:
    def test_not_installed(self):
        from studyctl.doctor.database import check_sessions_db

        with patch("importlib.util.find_spec", return_value=None):
            results = check_sessions_db()
        assert results[0].status == "info"
        assert "not installed" in results[0].message.lower()

    def test_installed_db_exists(self, tmp_path: Path):
        from studyctl.doctor.database import check_sessions_db

        db = tmp_path / "sessions.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY)")
        conn.close()

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("studyctl.doctor.database._get_sessions_db_path", return_value=db),
        ):
            results = check_sessions_db()
        assert results[0].status == "pass"

    def test_installed_db_missing(self, tmp_path: Path):
        from studyctl.doctor.database import check_sessions_db

        missing = tmp_path / "nope.db"
        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("studyctl.doctor.database._get_sessions_db_path", return_value=missing),
        ):
            results = check_sessions_db()
        assert results[0].status == "warn"
