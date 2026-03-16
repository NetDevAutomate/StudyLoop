"""MCP tool implementations for studyctl.

Each tool is registered via ``register_tools(mcp)`` and uses the
lifespan AppState for shared DB/settings access.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP  # noqa: TC002 — used at runtime as param type
from mcp.server.fastmcp.exceptions import ToolError

from studyctl.review_db import (
    get_course_stats,
    get_due_cards,
    record_card_review,
)
from studyctl.review_loader import (
    discover_directories,
    find_content_dirs,
    load_flashcards,
    load_quizzes,
)
from studyctl.settings import load_settings

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """Register all studyctl MCP tools on the server."""

    @mcp.tool()
    def list_courses() -> dict[str, Any]:
        """List all available study courses with card counts and review stats.

        Returns courses discovered from the review.directories config.
        Each course has: name, card_count, quiz_count, due_count.
        """
        raw_config = {}
        config_path = Path.home() / ".config" / "studyctl" / "config.yaml"
        if config_path.exists():
            import yaml

            raw_config = yaml.safe_load(config_path.read_text()) or {}
        study_dirs = raw_config.get("review", {}).get("directories", [])

        courses = discover_directories(study_dirs)
        result = []
        for name, path in courses:
            fc_dir, quiz_dir = find_content_dirs(path)
            fc_count = len(load_flashcards(fc_dir)) if fc_dir else 0
            quiz_count = len(load_quizzes(quiz_dir)) if quiz_dir else 0
            due = len(get_due_cards(name))
            result.append(
                {
                    "name": name,
                    "card_count": fc_count,
                    "quiz_count": quiz_count,
                    "due_count": due,
                }
            )
        return {"courses": result}

    @mcp.tool()
    def get_study_context(course: str) -> dict[str, Any]:
        """Get current study state for a course — due cards, stats, weak areas.

        Use this to understand where the student is before starting a session.

        Args:
            course: Course name (as returned by list_courses).
        """
        stats = get_course_stats(course)
        due = get_due_cards(course)
        return {
            "due_cards": len(due),
            "total_reviews": stats.get("total_reviews", 0),
            "unique_cards": stats.get("unique_cards", 0),
            "mastered": stats.get("mastered", 0),
            "due_today": stats.get("due_today", 0),
        }

    @mcp.tool()
    def record_study_progress(course: str, card_hash: str, correct: bool) -> dict[str, str]:
        """Record a review result for a single card.

        Args:
            course: Course name.
            card_hash: The card's hash identifier.
            correct: Whether the student answered correctly.
        """
        record_card_review(
            course=course,
            card_type="flashcard",
            card_hash=card_hash,
            correct=correct,
        )
        return {"status": "recorded"}

    @mcp.tool()
    def generate_flashcards(course: str, chapter: int, content: str) -> dict[str, Any]:
        """Save agent-generated flashcards to a course directory.

        The content parameter should be a JSON string with the flashcard data:
        {"title": "Chapter N", "cards": [{"front": "...", "back": "..."}, ...]}

        Validates the JSON structure before writing.

        Args:
            course: Course slug (directory name under content.base_path).
            chapter: Chapter number (used in filename).
            content: JSON string with flashcard data.
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Invalid JSON: {exc}") from exc

        # Validate structure
        if not isinstance(data, dict) or "cards" not in data:
            raise ToolError("JSON must have a 'cards' array")
        if not isinstance(data["cards"], list):
            raise ToolError("'cards' must be a list")
        for i, card in enumerate(data["cards"]):
            if not isinstance(card, dict):
                raise ToolError(f"Card {i} must be an object")
            if "front" not in card or "back" not in card:
                raise ToolError(f"Card {i} missing 'front' or 'back'")

        settings = load_settings()
        base = settings.content.base_path
        course_dir = base / course / "flashcards"
        course_dir.mkdir(parents=True, exist_ok=True)

        filename = f"ch{chapter:02d}-flashcards.json"
        path = course_dir / filename
        path.write_text(json.dumps(data, indent=2))
        logger.info("Wrote %d flashcards to %s", len(data["cards"]), path)
        return {"path": str(path), "count": len(data["cards"])}

    @mcp.tool()
    def generate_quiz(course: str, chapter: int, content: str) -> dict[str, Any]:
        """Save agent-generated quiz questions to a course directory.

        The content parameter should be a JSON string with quiz data:
        {"title": "Chapter N Quiz", "questions": [{"question": "...",
        "answerOptions": [{"text": "...", "isCorrect": true}, ...]}]}

        Validates the JSON structure before writing.

        Args:
            course: Course slug (directory name under content.base_path).
            chapter: Chapter number (used in filename).
            content: JSON string with quiz data.
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Invalid JSON: {exc}") from exc

        if not isinstance(data, dict) or "questions" not in data:
            raise ToolError("JSON must have a 'questions' array")
        if not isinstance(data["questions"], list):
            raise ToolError("'questions' must be a list")
        for i, q in enumerate(data["questions"]):
            if not isinstance(q, dict):
                raise ToolError(f"Question {i} must be an object")
            if "question" not in q:
                raise ToolError(f"Question {i} missing 'question' field")
            if "answerOptions" not in q:
                raise ToolError(f"Question {i} missing 'answerOptions'")

        settings = load_settings()
        base = settings.content.base_path
        course_dir = base / course / "quizzes"
        course_dir.mkdir(parents=True, exist_ok=True)

        filename = f"ch{chapter:02d}-quiz.json"
        path = course_dir / filename
        path.write_text(json.dumps(data, indent=2))
        logger.info("Wrote %d questions to %s", len(data["questions"]), path)
        return {"path": str(path), "count": len(data["questions"])}

    @mcp.tool()
    def get_chapter_text(course: str, chapter: int) -> dict[str, str]:
        """Extract text from a chapter PDF for LLM processing.

        Requires pymupdf. Returns the chapter title and full text content.

        Args:
            course: Course slug.
            chapter: Chapter number (1-indexed).
        """
        try:
            import pymupdf
        except ImportError:
            raise ToolError(
                "pymupdf not installed. Install with: uv pip install 'studyctl[content]'"
            ) from None

        settings = load_settings()
        chapters_dir = settings.content.base_path / course / "chapters"
        if not chapters_dir.is_dir():
            raise ToolError(
                f"No chapters directory for course '{course}'. Run 'studyctl content split' first."
            )

        # Find chapter PDF by number prefix
        pattern = f"*ch{chapter:02d}*" if chapter < 100 else f"*{chapter}*"
        matches = sorted(chapters_dir.glob(f"{pattern}.pdf"))
        if not matches:
            # Try broader match
            all_pdfs = sorted(chapters_dir.glob("*.pdf"))
            if chapter <= len(all_pdfs):
                matches = [all_pdfs[chapter - 1]]
            else:
                raise ToolError(
                    f"Chapter {chapter} not found in {chapters_dir}. "
                    f"Available: {len(all_pdfs)} PDFs."
                )

        pdf_path = matches[0]
        doc = pymupdf.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()

        title = pdf_path.stem.replace("_", " ").replace("-", " ").title()
        return {"title": title, "text": text}
