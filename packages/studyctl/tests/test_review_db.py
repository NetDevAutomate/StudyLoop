"""Tests for studyctl.review_db — spaced repetition tracking."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Create a temporary sessions.db with required tables."""
    path = tmp_path / "sessions.db"
    # Create the file so ensure_tables can connect
    conn = sqlite3.connect(path)
    conn.close()
    return path


class TestEnsureTables:
    def test_creates_card_reviews_table(self, db_path: Path) -> None:
        from studyctl.review_db import ensure_tables

        ensure_tables(db_path)
        conn = sqlite3.connect(db_path)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "card_reviews" in tables
        assert "review_sessions" in tables

    def test_idempotent(self, db_path: Path) -> None:
        from studyctl.review_db import ensure_tables

        ensure_tables(db_path)
        ensure_tables(db_path)  # Should not raise


class TestRecordCardReview:
    def test_records_correct_answer(self, db_path: Path) -> None:
        from studyctl.review_db import record_card_review

        record_card_review("ZTM-DE", "flashcard", "hash123", True, db_path=db_path)

        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM card_reviews").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][4] == 1  # correct = True

    def test_records_incorrect_answer(self, db_path: Path) -> None:
        from studyctl.review_db import record_card_review

        record_card_review("ZTM-DE", "quiz", "hash456", False, db_path=db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT correct, interval_days FROM card_reviews").fetchone()
        conn.close()
        assert row[0] == 0  # correct = False
        assert row[1] == 1  # interval reset to 1

    def test_spaced_repetition_increases_interval(self, db_path: Path) -> None:
        from studyctl.review_db import record_card_review

        # First correct review: interval stays at 1 * 2.5 = 2
        record_card_review("ZTM-DE", "flashcard", "hash789", True, db_path=db_path)
        conn = sqlite3.connect(db_path)
        row1 = conn.execute(
            "SELECT interval_days, ease_factor FROM card_reviews ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        # Second correct review: interval increases
        record_card_review("ZTM-DE", "flashcard", "hash789", True, db_path=db_path)
        conn = sqlite3.connect(db_path)
        row2 = conn.execute(
            "SELECT interval_days, ease_factor FROM card_reviews ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        assert row2[0] > row1[0]  # interval increased
        assert row2[1] >= row1[1]  # ease increased or same

    def test_incorrect_resets_interval(self, db_path: Path) -> None:
        from studyctl.review_db import record_card_review

        # Build up interval
        record_card_review("ZTM-DE", "flashcard", "hashX", True, db_path=db_path)
        record_card_review("ZTM-DE", "flashcard", "hashX", True, db_path=db_path)

        # Get interval before incorrect
        conn = sqlite3.connect(db_path)
        before = conn.execute(
            "SELECT interval_days FROM card_reviews ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()

        # Incorrect answer
        record_card_review("ZTM-DE", "flashcard", "hashX", False, db_path=db_path)
        conn = sqlite3.connect(db_path)
        after = conn.execute(
            "SELECT interval_days FROM card_reviews ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()

        assert before > 1
        assert after == 1  # Reset


class TestRecordSession:
    def test_records_session(self, db_path: Path) -> None:
        from studyctl.review_db import record_session

        record_session("ZTM-DE", "flashcards", 20, 15, 300, db_path=db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT * FROM review_sessions").fetchone()
        conn.close()
        assert row[1] == "ZTM-DE"
        assert row[2] == "flashcards"
        assert row[3] == 20
        assert row[4] == 15


class TestGetCourseStats:
    def test_empty_db(self, db_path: Path) -> None:
        from studyctl.review_db import ensure_tables, get_course_stats

        ensure_tables(db_path)
        stats = get_course_stats("ZTM-DE", db_path=db_path)
        assert stats["total_reviews"] == 0
        assert stats["unique_cards"] == 0

    def test_with_reviews(self, db_path: Path) -> None:
        from studyctl.review_db import get_course_stats, record_card_review

        record_card_review("ZTM-DE", "flashcard", "h1", True, db_path=db_path)
        record_card_review("ZTM-DE", "flashcard", "h2", False, db_path=db_path)
        record_card_review("ZTM-DE", "flashcard", "h1", True, db_path=db_path)

        stats = get_course_stats("ZTM-DE", db_path=db_path)
        assert stats["total_reviews"] == 3
        assert stats["unique_cards"] == 2


class TestGetWrongHashes:
    def test_returns_wrong_from_last_session(self, db_path: Path) -> None:
        from studyctl.review_db import get_wrong_hashes, record_card_review, record_session

        record_session("ZTM-DE", "quiz", 5, 3, db_path=db_path)
        record_card_review("ZTM-DE", "quiz", "wrong1", False, db_path=db_path)
        record_card_review("ZTM-DE", "quiz", "right1", True, db_path=db_path)

        wrong = get_wrong_hashes("ZTM-DE", db_path=db_path)
        assert "wrong1" in wrong
        assert "right1" not in wrong

    def test_empty_db(self, db_path: Path) -> None:
        from studyctl.review_db import ensure_tables, get_wrong_hashes

        ensure_tables(db_path)
        assert get_wrong_hashes("ZTM-DE", db_path=db_path) == set()
