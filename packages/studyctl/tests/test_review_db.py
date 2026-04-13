"""Tests for studyctl.review_db — spaced repetition tracking."""

from __future__ import annotations

import sqlite3
from pathlib import Path  # noqa: TC003 — used at runtime in fixtures

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
    def test_bootstraps_missing_db_file(self, tmp_path: Path) -> None:
        from studyctl.review_db import ensure_tables

        path = tmp_path / "nested" / "sessions.db"
        ensure_tables(path)

        assert path.exists()
        conn = sqlite3.connect(path)
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        assert "card_reviews" in tables
        assert "review_sessions" in tables

    def test_creates_card_reviews_table(self, db_path: Path) -> None:
        from studyctl.review_db import ensure_tables

        ensure_tables(db_path)
        conn = sqlite3.connect(db_path)
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
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

    def test_schedule_history_is_isolated_per_course(self, db_path: Path) -> None:
        from studyctl.review_db import record_card_review

        shared_hash = "shared-hash"

        record_card_review("Course-A", "flashcard", shared_hash, True, db_path=db_path)
        record_card_review("Course-A", "flashcard", shared_hash, True, db_path=db_path)
        record_card_review("Course-B", "flashcard", shared_hash, True, db_path=db_path)

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT course, interval_days FROM card_reviews WHERE card_hash = ? ORDER BY id ASC",
            (shared_hash,),
        ).fetchall()
        conn.close()

        assert rows[0] == ("Course-A", 2)
        assert rows[1] == ("Course-A", 5)
        assert rows[2] == ("Course-B", 2)


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


class TestGetDueCards:
    def test_empty_db(self, db_path: Path) -> None:
        from studyctl.review_db import ensure_tables, get_due_cards

        ensure_tables(db_path)
        assert get_due_cards("ZTM-DE", db_path=db_path) == []

    def test_returns_most_recent_review_data(self, db_path: Path) -> None:
        """Verify ROW_NUMBER window function picks the latest review per card."""
        from studyctl.review_db import ensure_tables, get_due_cards

        ensure_tables(db_path)
        conn = sqlite3.connect(db_path)

        # Insert two reviews for the same card: first incorrect, then correct
        conn.execute(
            "INSERT INTO card_reviews "
            "(course, card_type, card_hash, correct, reviewed_at, "
            "ease_factor, interval_days, next_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ZTM-DE", "flashcard", "abc123", 0, "2026-01-01T00:00:00", 2.3, 1, "2026-01-02"),
        )
        conn.execute(
            "INSERT INTO card_reviews "
            "(course, card_type, card_hash, correct, reviewed_at, "
            "ease_factor, interval_days, next_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ZTM-DE", "flashcard", "abc123", 1, "2026-01-02T00:00:00", 2.5, 3, "2026-01-05"),
        )
        conn.commit()
        conn.close()

        # Due date far in the future — get_due_cards needs next_review <= today
        # Set next_review to past to make it due
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE card_reviews SET next_review = '2020-01-01'")
        conn.commit()
        conn.close()

        due = get_due_cards("ZTM-DE", db_path=db_path)
        assert len(due) == 1
        card = due[0]
        # Must return the LATEST review (correct=True, ease=2.5, interval=3)
        assert card.last_correct is True
        assert card.ease_factor == 2.5
        assert card.interval_days == 3
        assert card.review_count == 2

    def test_filters_by_course(self, db_path: Path) -> None:
        from studyctl.review_db import ensure_tables, get_due_cards

        ensure_tables(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO card_reviews "
            "(course, card_type, card_hash, correct, reviewed_at, "
            "ease_factor, interval_days, next_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("ZTM-DE", "flashcard", "h1", 1, "2026-01-01T00:00:00", 2.5, 1, "2020-01-01"),
        )
        conn.execute(
            "INSERT INTO card_reviews "
            "(course, card_type, card_hash, correct, reviewed_at, "
            "ease_factor, interval_days, next_review) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("OTHER", "flashcard", "h2", 1, "2026-01-01T00:00:00", 2.5, 1, "2020-01-01"),
        )
        conn.commit()
        conn.close()

        due = get_due_cards("ZTM-DE", db_path=db_path)
        assert len(due) == 1
        assert due[0].card_hash == "h1"


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
