"""Tests for MCP tool implementations — called as plain Python functions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

mcp_mod = __import__("pytest").importorskip("mcp")

import pytest  # noqa: E402

from studyloop.mcp.server import mcp  # noqa: E402

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
            "studyloop.review_loader.discover_directories",
            return_value=[("test-course", tmp_path / "test-course")],
        ):
            tool = _get_tool("list_courses")
            result = tool()

        assert "courses" in result
        assert len(result["courses"]) == 1
        assert result["courses"][0]["name"] == "test-course"
        assert result["courses"][0]["flashcard_count"] == 1

    def test_reads_review_dirs_from_studyloop_config_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_path = tmp_path / "custom-config.yaml"
        course_dir = tmp_path / "course-a"
        config_path.write_text(f"review:\n  directories:\n    - {course_dir}\n")
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

        with patch("studyloop.services.review.list_course_summaries", return_value=[]) as summaries:
            tool = _get_tool("list_courses")
            result = tool()

        assert result == {"courses": []}
        summaries.assert_called_once_with([str(course_dir)])


class TestGetStudyContext:
    def test_returns_context(self) -> None:
        with (
            patch(
                "studyloop.mcp.tools.get_stats",
                return_value={
                    "total_reviews": 50,
                    "unique_cards": 20,
                    "mastered": 5,
                    "due_today": 3,
                },
            ),
            patch("studyloop.mcp.tools.get_due", return_value=[1, 2, 3]),
        ):
            tool = _get_tool("get_study_context")
            result = tool("test-course")

        assert result["due_cards"] == 3
        assert result["total_reviews"] == 50
        assert result["mastered"] == 5


class TestRecordStudyProgress:
    def test_records_review(self) -> None:
        with patch("studyloop.mcp.tools.record_review") as mock_record:
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
        from studyloop.settings import ContentConfig, Settings

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

        with patch("studyloop.mcp.tools.load_settings", return_value=fake_settings):
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
        from studyloop.settings import ContentConfig, Settings

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

        with patch("studyloop.mcp.tools.load_settings", return_value=fake_settings):
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
        from studyloop.settings import ContentConfig, Settings

        # Create a real PDF
        chapters_dir = tmp_path / "my-course" / "chapters"
        chapters_dir.mkdir(parents=True)
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello world content")
        doc.ez_save(str(chapters_dir / "ch01-intro.pdf"))
        doc.close()

        fake_settings = Settings(content=ContentConfig(base_path=tmp_path))
        with patch("studyloop.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("get_chapter_text")
            result = tool("my-course", 1)

        assert "Hello world content" in result["text"]
        assert result["title"]

    def test_missing_course_raises(self, tmp_path: Path) -> None:
        __import__("pytest").importorskip("pymupdf")
        from mcp.server.fastmcp.exceptions import ToolError

        from studyloop.settings import ContentConfig, Settings

        fake_settings = Settings(content=ContentConfig(base_path=tmp_path))
        with patch("studyloop.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("get_chapter_text")
            with pytest.raises(ToolError, match="No chapters directory"):
                tool("nonexistent", 1)

    @pytest.mark.parametrize("chapter", [0, -1, -3])
    def test_nonpositive_chapter_rejected_not_wrapped(
        self, tmp_path: Path, chapter: int
    ) -> None:
        """chapter<=0 must error, not index all_pdfs[chapter-1] from the end."""
        pymupdf = __import__("pytest").importorskip("pymupdf")
        from mcp.server.fastmcp.exceptions import ToolError

        from studyloop.settings import ContentConfig, Settings

        chapters_dir = tmp_path / "c" / "chapters"
        chapters_dir.mkdir(parents=True)
        for n in (1, 2, 3):
            doc = pymupdf.open()
            doc.new_page().insert_text((72, 72), f"chapter {n}")
            doc.ez_save(str(chapters_dir / f"ch{n:02d}.pdf"))
            doc.close()

        fake_settings = Settings(content=ContentConfig(base_path=tmp_path))
        with (
            patch("studyloop.mcp.tools.load_settings", return_value=fake_settings),
            pytest.raises(ToolError, match="not found"),
        ):
            _get_tool("get_chapter_text")("c", chapter)


class TestPathTraversal:
    """Verify that course parameters with directory traversal are rejected."""

    @pytest.fixture()
    def fake_settings(self, tmp_path: Path):
        from studyloop.settings import ContentConfig, Settings

        return Settings(content=ContentConfig(base_path=tmp_path))

    @pytest.mark.parametrize("course", ["../../etc", "../sibling", "ok/../../escape"])
    def test_flashcards_rejects_traversal(self, fake_settings, course: str) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        content = json.dumps({"title": "T", "cards": [{"front": "Q", "back": "A"}]})
        with patch("studyloop.mcp.tools.load_settings", return_value=fake_settings):
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
        with patch("studyloop.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("generate_quiz")
            with pytest.raises(ToolError, match="Invalid course path"):
                tool(course, 1, content)

    @pytest.mark.parametrize("course", ["../../etc", "../sibling"])
    def test_chapter_text_rejects_traversal(self, fake_settings, course: str) -> None:
        __import__("pytest").importorskip("pymupdf")
        from mcp.server.fastmcp.exceptions import ToolError

        with patch("studyloop.mcp.tools.load_settings", return_value=fake_settings):
            tool = _get_tool("get_chapter_text")
            with pytest.raises(ToolError, match="Invalid course path"):
                tool(course, 1)


class TestExplorerReadTools:
    """get_lesson_tree / read_lesson / search_lessons — Course Explorer parity."""

    @pytest.fixture()
    def vault_settings(self, tmp_path: Path):
        from studyloop.settings import ContentConfig, Settings

        lesson = tmp_path / "vault" / "Mosh" / "Python_Pro" / "intro.md"
        lesson.parent.mkdir(parents=True)
        lesson.write_text("# Intro\n\nA closure captures state for later use.")
        (lesson.parent / "flashcards").mkdir()  # output dir — must be hidden
        return Settings(
            content=ContentConfig(base_path=tmp_path / "vault"),
            session_db=tmp_path / "sessions.db",
        )

    def test_tree_lists_providers_and_courses(self, vault_settings) -> None:
        with patch("studyloop.mcp.tools.load_settings", return_value=vault_settings):
            result = _get_tool("get_lesson_tree")()

        assert result["providers"][0]["id"] == "Mosh"
        assert result["providers"][0]["courses"][0]["id"] == "Mosh/Python_Pro"

    def test_tree_with_course_lists_lessons(self, vault_settings) -> None:
        with patch("studyloop.mcp.tools.load_settings", return_value=vault_settings):
            result = _get_tool("get_lesson_tree")("Mosh", "Python_Pro")

        assert result["course_id"] == "Mosh/Python_Pro"
        assert result["lessons"] == [{"id": "Mosh/Python_Pro/intro", "title": "Intro"}]

    def test_tree_requires_both_or_neither(self, vault_settings) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        with (
            patch("studyloop.mcp.tools.load_settings", return_value=vault_settings),
            pytest.raises(ToolError, match="both"),
        ):
            _get_tool("get_lesson_tree")("Mosh", None)

    @pytest.mark.parametrize("provider", ["../..", "../sibling"])
    def test_tree_rejects_traversal(self, vault_settings, provider: str) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        with (
            patch("studyloop.mcp.tools.load_settings", return_value=vault_settings),
            pytest.raises(ToolError, match="Invalid course path"),
        ):
            _get_tool("get_lesson_tree")(provider, "etc")

    def test_read_lesson_returns_content(self, vault_settings) -> None:
        with patch("studyloop.mcp.tools.load_settings", return_value=vault_settings):
            result = _get_tool("read_lesson")("Mosh/Python_Pro/intro")

        assert result["lesson_id"] == "Mosh/Python_Pro/intro"
        assert "closure captures state" in result["content"]

    def test_read_lesson_rejects_traversal_to_real_file(
        self, vault_settings, tmp_path: Path
    ) -> None:
        """The escape target EXISTS — only the is_relative_to guard blocks it."""
        from mcp.server.fastmcp.exceptions import ToolError

        (tmp_path / "secret.md").write_text("outside the vault")
        with (
            patch("studyloop.mcp.tools.load_settings", return_value=vault_settings),
            pytest.raises(ToolError, match="Lesson not found"),
        ):
            _get_tool("read_lesson")("../secret")

    @pytest.mark.parametrize("lesson_id", ["Mosh/../../escape", "Mosh/Python_Pro/nope"])
    def test_read_lesson_rejects_missing(self, vault_settings, lesson_id: str) -> None:
        from mcp.server.fastmcp.exceptions import ToolError

        with (
            patch("studyloop.mcp.tools.load_settings", return_value=vault_settings),
            pytest.raises(ToolError, match="Lesson not found"),
        ):
            _get_tool("read_lesson")(lesson_id)

    def test_search_finds_lesson_body(self, vault_settings) -> None:
        # _fts_db_path imports load_settings lazily from studyloop.settings,
        # so both the tools module and the settings module need patching.
        with (
            patch("studyloop.mcp.tools.load_settings", return_value=vault_settings),
            patch("studyloop.settings.load_settings", return_value=vault_settings),
        ):
            result = _get_tool("search_lessons")("closure")

        assert result["results"], "expected at least one FTS hit"
        assert result["results"][0]["lesson_id"] == "Mosh/Python_Pro/intro"
        assert "<mark>" in result["results"][0]["excerpt"]

    def test_search_short_query_returns_empty(self, vault_settings) -> None:
        with patch("studyloop.mcp.tools.load_settings", return_value=vault_settings):
            assert _get_tool("search_lessons")("x") == {"results": []}
