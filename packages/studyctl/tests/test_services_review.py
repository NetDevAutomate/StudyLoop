"""Tests for services/review.py — delegation layer between CLI/web and data layer.

Exercises the uncovered paths: list_course_summaries, get_cards, get_wrong.
All storage/DB calls are monkeypatched to keep tests fast and hermetic.

No conftest.py (pluggy conflict) — all fixtures are inline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.services import review as svc

# ---------------------------------------------------------------------------
# get_cards
# ---------------------------------------------------------------------------


class TestGetCards:
    def test_returns_empty_when_no_content_dirs(self, tmp_path: Path) -> None:
        """get_cards returns empty lists when no flashcards/quizzes dirs exist."""
        course_dir = tmp_path / "empty-course"
        course_dir.mkdir()

        with patch("studyctl.review_loader.find_content_dirs", return_value=(None, None)):
            flashcards, quizzes = svc.get_cards("empty-course", course_dir)

        assert flashcards == []
        assert quizzes == []

    def test_returns_flashcards_when_fc_dir_exists(self, tmp_path: Path) -> None:
        """get_cards loads flashcards when flashcards dir is found."""
        fc_dir = tmp_path / "flashcards"
        fc_dir.mkdir()

        fake_cards = [MagicMock(), MagicMock()]

        with (
            patch(
                "studyctl.review_loader.find_content_dirs",
                return_value=(fc_dir, None),
            ),
            patch("studyctl.review_loader.load_flashcards", return_value=fake_cards),
        ):
            flashcards, quizzes = svc.get_cards("my-course", tmp_path)

        assert len(flashcards) == 2
        assert quizzes == []

    def test_returns_quizzes_when_quiz_dir_exists(self, tmp_path: Path) -> None:
        """get_cards loads quizzes when quizzes dir is found."""
        quiz_dir = tmp_path / "quizzes"
        quiz_dir.mkdir()

        fake_quizzes = [MagicMock()]

        with (
            patch(
                "studyctl.review_loader.find_content_dirs",
                return_value=(None, quiz_dir),
            ),
            patch("studyctl.review_loader.load_quizzes", return_value=fake_quizzes),
        ):
            flashcards, quizzes = svc.get_cards("my-course", tmp_path)

        assert flashcards == []
        assert len(quizzes) == 1

    def test_returns_both_when_both_dirs_exist(self, tmp_path: Path) -> None:
        """get_cards loads both flashcards and quizzes when both dirs exist."""
        fc_dir = tmp_path / "flashcards"
        quiz_dir = tmp_path / "quizzes"
        fc_dir.mkdir()
        quiz_dir.mkdir()

        fake_cards = [MagicMock(), MagicMock(), MagicMock()]
        fake_quizzes = [MagicMock(), MagicMock()]

        with (
            patch(
                "studyctl.review_loader.find_content_dirs",
                return_value=(fc_dir, quiz_dir),
            ),
            patch("studyctl.review_loader.load_flashcards", return_value=fake_cards),
            patch("studyctl.review_loader.load_quizzes", return_value=fake_quizzes),
        ):
            flashcards, quizzes = svc.get_cards("my-course", tmp_path)

        assert len(flashcards) == 3
        assert len(quizzes) == 2


# ---------------------------------------------------------------------------
# get_wrong
# ---------------------------------------------------------------------------


class TestGetWrong:
    def test_returns_empty_set_when_no_reviews(self) -> None:
        """get_wrong returns an empty set when no wrong answers exist."""
        with patch("studyctl.review_db.get_wrong_hashes", return_value=set()):
            result = svc.get_wrong("my-course")
        assert result == set()

    def test_returns_wrong_hashes(self) -> None:
        """get_wrong returns the set of wrong card hashes."""
        expected = {"abc123def", "xyz789abc"}  # pragma: allowlist secret
        with patch("studyctl.review_db.get_wrong_hashes", return_value=expected):
            result = svc.get_wrong("my-course")
        assert result == expected

    def test_passes_course_to_get_wrong_hashes(self) -> None:
        """get_wrong passes the course argument to review_db."""
        with patch("studyctl.review_db.get_wrong_hashes", return_value=set()) as mock:
            svc.get_wrong("specific-course")
        mock.assert_called_once_with(course="specific-course")


# ---------------------------------------------------------------------------
# list_course_summaries
# ---------------------------------------------------------------------------


class TestListCourseSummaries:
    def test_returns_empty_for_no_courses(self) -> None:
        """list_course_summaries returns empty list when no courses are found."""
        with patch("studyctl.review_loader.discover_directories", return_value=[]):
            result = svc.list_course_summaries(["/some/dir"])
        assert result == []

    def test_aggregates_course_data(self, tmp_path: Path) -> None:
        """list_course_summaries combines card counts, due count, and stats."""
        course_dir = tmp_path / "python"
        fc_dir = course_dir / "flashcards"
        quiz_dir = course_dir / "quizzes"
        fc_dir.mkdir(parents=True)
        quiz_dir.mkdir(parents=True)

        fake_cards = [MagicMock(), MagicMock()]
        fake_quizzes = [MagicMock()]
        fake_due = [MagicMock(), MagicMock()]
        fake_stats = {"total_reviews": 10, "mastered": 3, "due_today": 2}

        with (
            patch(
                "studyctl.review_loader.discover_directories",
                return_value=[("python", course_dir)],
            ),
            patch(
                "studyctl.review_loader.find_content_dirs",
                return_value=(fc_dir, quiz_dir),
            ),
            patch("studyctl.review_loader.load_flashcards", return_value=fake_cards),
            patch("studyctl.review_loader.load_quizzes", return_value=fake_quizzes),
            patch("studyctl.review_db.get_due_cards", return_value=fake_due),
            patch("studyctl.review_db.get_course_stats", return_value=fake_stats),
        ):
            result = svc.list_course_summaries([str(tmp_path)])

        assert len(result) == 1
        course = result[0]
        assert course["name"] == "python"
        assert course["flashcard_count"] == 2
        assert course["quiz_count"] == 1
        assert course["due_count"] == 2
        assert course["total_reviews"] == 10
        assert course["mastered"] == 3

    def test_handles_course_with_no_content_dirs(self, tmp_path: Path) -> None:
        """list_course_summaries handles courses with no flashcards/quizzes dirs."""
        course_dir = tmp_path / "empty-course"
        course_dir.mkdir()

        with (
            patch(
                "studyctl.review_loader.discover_directories",
                return_value=[("empty-course", course_dir)],
            ),
            patch(
                "studyctl.review_loader.find_content_dirs",
                return_value=(None, None),
            ),
            patch("studyctl.review_db.get_due_cards", return_value=[]),
            patch(
                "studyctl.review_db.get_course_stats",
                return_value={"total_reviews": 0, "mastered": 0},
            ),
        ):
            result = svc.list_course_summaries([str(tmp_path)])

        assert len(result) == 1
        assert result[0]["flashcard_count"] == 0
        assert result[0]["quiz_count"] == 0


# ---------------------------------------------------------------------------
# record_review (delegation check)
# ---------------------------------------------------------------------------


class TestRecordReview:
    def test_delegates_to_review_db(self) -> None:
        """record_review passes all arguments to review_db.record_card_review."""
        with patch("studyctl.review_db.record_card_review") as mock:
            svc.record_review(
                course="python",
                card_type="flashcard",
                card_hash="abc123",
                correct=True,
                response_time_ms=500,
            )
        mock.assert_called_once_with(
            course="python",
            card_type="flashcard",
            card_hash="abc123",
            correct=True,
            response_time_ms=500,
        )

    def test_delegates_without_response_time(self) -> None:
        """record_review works without optional response_time_ms."""
        with patch("studyctl.review_db.record_card_review") as mock:
            svc.record_review(
                course="networking",
                card_type="quiz",
                card_hash="xyz789",
                correct=False,
            )
        mock.assert_called_once_with(
            course="networking",
            card_type="quiz",
            card_hash="xyz789",
            correct=False,
            response_time_ms=None,
        )


# ---------------------------------------------------------------------------
# get_stats / get_due (delegation check)
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_delegates_to_review_db(self) -> None:
        """get_stats passes course argument to review_db.get_course_stats."""
        expected = {"total_reviews": 42, "mastered": 7, "due_today": 3}
        with patch("studyctl.review_db.get_course_stats", return_value=expected) as mock:
            result = svc.get_stats("python-course")
        mock.assert_called_once_with(course="python-course")
        assert result == expected


class TestGetDue:
    def test_delegates_to_review_db(self) -> None:
        """get_due passes course argument to review_db.get_due_cards."""
        fake_cards = [MagicMock(), MagicMock()]
        with patch("studyctl.review_db.get_due_cards", return_value=fake_cards) as mock:
            result = svc.get_due("networking-course")
        mock.assert_called_once_with(course="networking-course")
        assert result is fake_cards
