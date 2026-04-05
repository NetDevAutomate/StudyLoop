"""Tests for briefing_logic — pure functions, no mocking needed for most tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from studyctl.logic.briefing_logic import (
    BriefingData,
    ContentContext,
    ReviewContext,
    format_study_briefing,
)

# ---------------------------------------------------------------------------
# format_study_briefing — review section
# ---------------------------------------------------------------------------


class TestFormatReviewSection:
    def test_includes_review_section_when_present(self):
        data = BriefingData(
            topic_name="Python",
            review=ReviewContext(due_count=5, mastered_count=12, total_reviews=100),
        )
        result = format_study_briefing(data)
        assert "### Review Status" in result
        assert "Due for review: **5**" in result
        assert "Mastered" in result

    def test_omits_review_data_when_none(self):
        """When review is None, shows graceful degradation message, not a crash."""
        data = BriefingData(topic_name="Python", review=None)
        result = format_study_briefing(data)
        assert "### Review Status" in result
        assert "unavailable" in result.lower()
        # Should NOT show specific counts
        assert "Due for review:" not in result

    def test_shows_struggling_count_when_nonzero(self):
        data = BriefingData(
            topic_name="Python",
            review=ReviewContext(due_count=10, struggling_count=3),
        )
        result = format_study_briefing(data)
        assert "Struggling: **3**" in result
        assert "prioritise" in result

    def test_omits_struggling_line_when_zero(self):
        data = BriefingData(
            topic_name="Python",
            review=ReviewContext(due_count=5, struggling_count=0),
        )
        result = format_study_briefing(data)
        assert "Struggling" not in result

    def test_includes_flashcard_and_quiz_counts(self):
        data = BriefingData(
            topic_name="SQL",
            review=ReviewContext(flashcard_count=20, quiz_count=5),
        )
        result = format_study_briefing(data)
        assert "Flashcards loaded: 20" in result
        assert "Quiz questions loaded: 5" in result


# ---------------------------------------------------------------------------
# format_study_briefing — content section
# ---------------------------------------------------------------------------


class TestFormatContentSection:
    def test_includes_content_section_when_present(self):
        data = BriefingData(
            topic_name="Python",
            content=ContentContext(chapter_count=8, obsidian_path="/path/to/Python"),
        )
        result = format_study_briefing(data)
        assert "### Content Inventory" in result
        assert "Chapters: 8" in result

    def test_shows_content_gap_hint_when_no_chapters(self):
        data = BriefingData(
            topic_name="Python",
            content=ContentContext(chapter_count=0),
        )
        result = format_study_briefing(data)
        assert "studyctl content split" in result

    def test_shows_no_content_dir_when_content_none(self):
        data = BriefingData(topic_name="Python", content=None)
        result = format_study_briefing(data)
        assert "### Content Inventory" in result
        assert "No content directory found" in result


# ---------------------------------------------------------------------------
# format_study_briefing — backlog and gaps
# ---------------------------------------------------------------------------


class TestFormatBacklogAndGaps:
    def test_includes_backlog_items(self):
        data = BriefingData(
            topic_name="Python",
            backlog_items=["Understand decorators", "Practice generators"],
        )
        result = format_study_briefing(data)
        assert "### Study Backlog" in result
        assert "Understand decorators" in result
        assert "Practice generators" in result

    def test_backlog_capped_at_10(self):
        items = [f"item-{i}" for i in range(15)]
        data = BriefingData(topic_name="Python", backlog_items=items)
        result = format_study_briefing(data)
        assert "and 5 more" in result

    def test_omits_backlog_section_when_empty(self):
        data = BriefingData(topic_name="Python", backlog_items=[])
        result = format_study_briefing(data)
        assert "### Study Backlog" not in result

    def test_includes_gaps(self):
        data = BriefingData(
            topic_name="Python",
            gaps=["No quiz questions for chapter 3"],
        )
        result = format_study_briefing(data)
        assert "### Content Gaps" in result
        assert "No quiz questions for chapter 3" in result


# ---------------------------------------------------------------------------
# format_study_briefing — degradation and edge cases
# ---------------------------------------------------------------------------


class TestFormatDegradation:
    def test_shows_degraded_warning_when_assembly_warnings_present(self):
        data = BriefingData(
            topic_name="Python",
            assembly_warnings=["Review stats unavailable", "Content inventory unavailable"],
        )
        result = format_study_briefing(data)
        assert "Partial Briefing" in result
        assert "Review stats unavailable" in result

    def test_is_degraded_property_true_when_warnings(self):
        data = BriefingData(
            topic_name="Python",
            assembly_warnings=["Something failed"],
        )
        assert data.is_degraded is True

    def test_is_degraded_property_false_when_no_warnings(self):
        data = BriefingData(topic_name="Python")
        assert data.is_degraded is False

    def test_returns_empty_string_for_empty_topic_name(self):
        data = BriefingData(topic_name="")
        result = format_study_briefing(data)
        assert result == ""

    def test_works_with_all_none_contexts(self):
        """Full degradation — all optional fields None — should not raise."""
        data = BriefingData(
            topic_name="Python",
            review=None,
            content=None,
            assembly_warnings=["Review stats unavailable", "Content inventory unavailable"],
        )
        result = format_study_briefing(data)
        assert "## Study Briefing: Python" in result
        assert "unavailable" in result.lower()

    def test_includes_topic_name_in_heading(self):
        data = BriefingData(topic_name="Data Engineering")
        result = format_study_briefing(data)
        assert "## Study Briefing: Data Engineering" in result


# ---------------------------------------------------------------------------
# _gather_review_context integration (via mock at service layer)
# ---------------------------------------------------------------------------


class TestGatherReviewContext:
    def test_returns_none_on_db_error(self):
        """Gatherer returns None when get_stats raises — DB missing/corrupt."""
        with patch("studyctl.services.review.get_stats", side_effect=RuntimeError("DB down")):
            # Import the gatherer from the CLI module
            from studyctl.cli._study import _gather_review_context

            result = _gather_review_context("python")
            assert result is None

    def test_returns_review_context_on_success(self):
        mock_card = MagicMock()
        mock_card.last_correct = False  # struggling card

        with (
            patch(
                "studyctl.services.review.get_stats",
                return_value={
                    "mastered": 5,
                    "total_reviews": 50,
                    "flashcard_count": 20,
                    "quiz_count": 3,
                },
            ),
            patch("studyctl.services.review.get_due", return_value=[mock_card, mock_card]),
        ):
            from studyctl.cli._study import _gather_review_context

            result = _gather_review_context("python")
            assert result is not None
            assert result.due_count == 2
            assert result.struggling_count == 2  # both cards last_correct=False
            assert result.mastered_count == 5
            assert result.total_reviews == 50
