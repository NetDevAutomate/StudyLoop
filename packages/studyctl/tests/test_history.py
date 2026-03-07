"""Tests for history module bug fixes."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _make_db(tmp_path: Path) -> Path:
    """Create a temp SQLite DB with the study_progress table."""
    db_path = tmp_path / "sessions.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE study_progress (
            id TEXT PRIMARY KEY,
            topic TEXT,
            concept TEXT,
            confidence TEXT,
            first_seen TEXT,
            last_seen TEXT,
            session_count INTEGER,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


class TestRecordProgressCaseNormalisation:
    """Bug 1: record_progress() should normalise case for UUID generation."""

    def test_same_id_for_different_cases(self, tmp_path, monkeypatch):
        db_path = _make_db(tmp_path)

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyctl.history as hist

        monkeypatch.setattr(hist, "_connect", mock_connect)

        hist.record_progress("Python", "Decorators", "learning")
        hist.record_progress("python", "decorators", "confident")

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM study_progress").fetchall()
        conn.close()

        assert len(rows) == 1, "Different cases should map to the same row"
        # Should have been updated (session_count incremented)
        assert rows[0][6] == 2  # session_count column

    def test_strips_whitespace(self, tmp_path, monkeypatch):
        db_path = _make_db(tmp_path)

        def mock_connect():
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn

        import studyctl.history as hist

        monkeypatch.setattr(hist, "_connect", mock_connect)

        hist.record_progress("Python ", " Decorators", "learning")
        hist.record_progress("python", "decorators", "confident")

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM study_progress").fetchall()
        conn.close()

        assert len(rows) == 1


class TestGetStudyTerms:
    """Bug 2: _get_study_terms() should derive terms from config."""

    def test_returns_config_terms(self, monkeypatch):
        @dataclass
        class FakeTopic:
            name: str
            tags: list[str] = field(default_factory=list)

        fake_topics = [
            FakeTopic(name="Kafka", tags=["streaming", "events"]),
            FakeTopic(name="Flink", tags=["streaming", "realtime"]),
        ]

        import studyctl.history as hist

        monkeypatch.setattr(
            hist,
            "_get_study_terms",
            lambda: sorted(
                {t.name.lower() for t in fake_topics}
                | {tag.lower() for t in fake_topics for tag in t.tags}
            ),
        )

        terms = hist._get_study_terms()
        assert "kafka" in terms
        assert "streaming" in terms
        assert "flink" in terms
        assert "realtime" in terms

    def test_returns_fallback_when_no_config(self, monkeypatch):
        import studyctl.history as hist

        # Test fallback by making get_topics return falsy
        monkeypatch.setattr("studyctl.config.get_topics", lambda: None)
        terms = hist._get_study_terms()
        # When get_topics returns falsy, should fall back to defaults
        assert "spark" in terms
        assert "python" in terms

    def test_fallback_on_import_error(self, monkeypatch):
        import studyctl.config
        import studyctl.history as hist

        monkeypatch.setattr(
            studyctl.config,
            "get_topics",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        terms = hist._get_study_terms()
        assert "spark" in terms  # fallback list


class TestNoModuleLevelLoadSettings:
    """Bug 3: _DB_CANDIDATES should no longer exist as a module attribute."""

    def test_no_db_candidates_attribute(self):
        import studyctl.history as hist

        assert not hasattr(hist, "_DB_CANDIDATES"), (
            "_DB_CANDIDATES should not exist — load_settings() must not be called at import time"
        )

    def test_find_db_uses_settings(self, tmp_path, monkeypatch):
        db_path = tmp_path / "sessions.db"
        db_path.touch()

        @dataclass
        class FakeSettings:
            session_db: object = field(default_factory=lambda: db_path)

        import studyctl.history as hist

        monkeypatch.setattr(hist, "load_settings", lambda: FakeSettings())

        result = hist._find_db()
        assert result == db_path
