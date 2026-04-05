"""Tests for MCP tool implementations — called as plain Python functions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

mcp_mod = __import__("pytest").importorskip("mcp")

import pytest  # noqa: E402

from studyctl.mcp.server import mcp  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path


# The tools are registered as closures inside register_tools().
# We access them via the FastMCP server's tool registry.


def _get_tool(name: str):
    """Get a registered tool function by name."""
    tools = mcp._tool_manager._tools
    if name not in tools:
        raise KeyError(f"Tool '{name}' not found. Available: {list(tools.keys())}")
    return tools[name].fn


class TestListCourses:
    def test_returns_courses_dict(self, tmp_path: Path) -> None:
        fc_dir = tmp_path / "test-course" / "flashcards"
        fc_dir.mkdir(parents=True)
        fc_dir.joinpath("ch01-flashcards.json").write_text(
            json.dumps({"title": "Ch1", "cards": [{"front": "Q", "back": "A"}]})
        )

        with patch(
            "studyctl.review_loader.discover_directories",
            return_value=[("test-course", tmp_path / "test-course")],
        ):
            tool = _get_tool("list_courses")
            result = tool()

        assert "courses" in result
        assert len(result["courses"]) == 1
        assert result["courses"][0]["name"] == "test-course"
        assert result["courses"][0]["flashcard_count"] == 1


class TestGetStudyContext:
    def test_returns_context(self) -> None:
        with (
            patch(
                "studyctl.mcp.tools.get_stats",
                return_value={
                    "total_reviews": 50,
                    "unique_cards": 20,
                    "mastered": 5,
                    "due_today": 3,
                },
            ),
            patch("studyctl.mcp.tools.get_due", return_value=[1, 2, 3]),
        ):
            tool = _get_tool("get_study_context")
            result = tool("test-course")

        assert result["due_cards"] == 3
        assert result["total_reviews"] == 50
        assert result["mastered"] == 5


class TestRecordStudyProgress:
    def test_records_review(self) -> None:
        with patch("studyctl.mcp.tools.record_review") as mock_record:
            tool = _get_tool("record_study_progress")
            result = tool("test-course", "abc123", True)

        mock_record.assert_called_once_with(
            course="test-course",
            card_type="flashcard",
            card_hash="abc123",
            correct=True,
        )
        assert result["status"] == "recorded"


class TestGenerateFlashcards:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        from studyctl.settings import ContentConfig, Settings

        fake_settings = Settings(content=ContentConfig(base_path=tmp_path))

        content = json.dumps(
            {
                "title": "Chapter 1",
                "cards": [
                    {"front": "What is X?", "back": "X is Y"},
                    {"front": "Why Z?", "back": "Because W"},
                ],
            }
        )

        with patch("studyctl.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("generate_flashcards")
            result = tool("my-course", 1, content)

        assert result["count"] == 2
        fc_path = tmp_path / "my-course" / "flashcards" / "ch01-flashcards.json"
        written = json.loads(fc_path.read_text())
        assert len(written["cards"]) == 2

    def test_rejects_invalid_json(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("generate_flashcards")
        with pytest.raises(ToolError, match="Invalid JSON"):
            tool("course", 1, "not json")

    def test_rejects_missing_cards(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("generate_flashcards")
        with pytest.raises(ToolError, match="'cards' array"):
            tool("course", 1, json.dumps({"title": "No cards"}))

    def test_rejects_card_without_front(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("generate_flashcards")
        content = json.dumps({"title": "T", "cards": [{"back": "only back"}]})
        with pytest.raises(ToolError, match="missing 'front' or 'back'"):
            tool("course", 1, content)


class TestGenerateQuiz:
    def test_writes_valid_quiz(self, tmp_path: Path) -> None:
        from studyctl.settings import ContentConfig, Settings

        fake_settings = Settings(content=ContentConfig(base_path=tmp_path))

        content = json.dumps(
            {
                "title": "Ch1 Quiz",
                "questions": [
                    {
                        "question": "What is X?",
                        "answerOptions": [
                            {"text": "A", "isCorrect": True},
                            {"text": "B", "isCorrect": False},
                        ],
                    }
                ],
            }
        )

        with patch("studyctl.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("generate_quiz")
            result = tool("my-course", 1, content)

        assert result["count"] == 1

    def test_rejects_missing_questions(self) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        tool = _get_tool("generate_quiz")
        with pytest.raises(ToolError, match="'questions' array"):
            tool("course", 1, json.dumps({"title": "No questions"}))


class TestGetChapterText:
    def test_extracts_text(self, tmp_path: Path) -> None:
        pymupdf = __import__("pytest").importorskip("pymupdf")
        from studyctl.settings import ContentConfig, Settings

        # Create a real PDF
        chapters_dir = tmp_path / "my-course" / "chapters"
        chapters_dir.mkdir(parents=True)
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello world content")
        doc.ez_save(str(chapters_dir / "ch01-intro.pdf"))
        doc.close()

        fake_settings = Settings(content=ContentConfig(base_path=tmp_path))
        with patch("studyctl.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("get_chapter_text")
            result = tool("my-course", 1)

        assert "Hello world content" in result["text"]
        assert result["title"]

    def test_missing_course_raises(self, tmp_path: Path) -> None:
        __import__("pytest").importorskip("pymupdf")
        from mcp.server.fastmcp.exceptions import ToolError

        from studyctl.settings import ContentConfig, Settings

        fake_settings = Settings(content=ContentConfig(base_path=tmp_path))
        with patch("studyctl.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("get_chapter_text")
            with pytest.raises(ToolError, match="No chapters directory"):
                tool("nonexistent", 1)


class TestPathTraversal:
    """Verify that course parameters with directory traversal are rejected."""

    @pytest.fixture()
    def fake_settings(self, tmp_path: Path):
        from studyctl.settings import ContentConfig, Settings

        return Settings(content=ContentConfig(base_path=tmp_path))

    @pytest.mark.parametrize("course", ["../../etc", "../sibling", "ok/../../escape"])
    def test_flashcards_rejects_traversal(self, fake_settings, course: str) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        content = json.dumps({"title": "T", "cards": [{"front": "Q", "back": "A"}]})
        with patch("studyctl.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("generate_flashcards")
            with pytest.raises(ToolError, match="Invalid course path"):
                tool(course, 1, content)

    @pytest.mark.parametrize("course", ["../../etc", "../sibling"])
    def test_quiz_rejects_traversal(self, fake_settings, course: str) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        content = json.dumps(
            {
                "title": "T",
                "questions": [
                    {
                        "question": "Q?",
                        "answerOptions": [{"text": "A", "isCorrect": True}],
                    }
                ],
            }
        )
        with patch("studyctl.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("generate_quiz")
            with pytest.raises(ToolError, match="Invalid course path"):
                tool(course, 1, content)

    @pytest.mark.parametrize("course", ["../../etc", "../sibling"])
    def test_chapter_text_rejects_traversal(self, fake_settings, course: str) -> None:
        __import__("pytest").importorskip("pymupdf")
        from mcp.server.fastmcp.exceptions import ToolError

        with patch("studyctl.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("get_chapter_text")
            with pytest.raises(ToolError, match="Invalid course path"):
                tool(course, 1)
