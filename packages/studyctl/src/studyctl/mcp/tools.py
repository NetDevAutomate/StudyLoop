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

from studyctl.review_loader import (
    discover_directories,
    find_content_dirs,
    load_flashcards,
    load_quizzes,
)
from studyctl.services.review import get_due, get_stats, record_review
from studyctl.settings import load_settings

logger = logging.getLogger(__name__)


def _safe_course_dir(base: Path, course: str, subdir: str) -> Path:
    """Resolve a course subdirectory, preventing path traversal.

    The ``course`` parameter comes from LLM tool calls and could contain
    ``../../`` sequences. This validates the resolved path stays within base.
    """
    resolved = (base / course / subdir).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ToolError(f"Invalid course path: {course!r}")
    return resolved


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
            due = len(get_due(name))
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
        stats = get_stats(course)
        due = get_due(course)
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
        record_review(
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
        course_dir = _safe_course_dir(base, course, "flashcards")
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
        course_dir = _safe_course_dir(base, course, "quizzes")
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
        chapters_dir = _safe_course_dir(settings.content.base_path, course, "chapters")
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

    # ── Study Backlog / Session-DB Tools ─────────────────────────

    @mcp.tool()
    def get_study_backlog(
        tech_area: str | None = None,
        source: str | None = None,
        status: str = "pending",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get study backlog items with optional filters.

        Returns pending topics from the study backlog, optionally filtered
        by technology area, source (parked/struggled/manual), or status.

        Args:
            tech_area: Filter by technology (e.g. "Python", "SQL").
            source: Filter by origin ("parked", "struggled", "manual").
            status: Filter by status (default "pending").
            limit: Maximum items to return.
        """
        from studyctl.parking import get_parked_topics

        items = get_parked_topics(
            status=status,
            source=source,
            tech_area=tech_area,
        )[:limit]
        return {
            "items": items,
            "total": len(items),
            "filters": {"tech_area": tech_area, "source": source, "status": status},
        }

    @mcp.tool()
    def get_topic_suggestions(
        limit: int = 10,
        current_topic: str | None = None,
    ) -> dict[str, Any]:
        """Get AI-ranked topic suggestions based on importance and frequency.

        Ranks pending backlog topics using algorithmic scoring:
        60% agent-assessed importance + 40% frequency of appearance.
        Use this to help the student decide what to study next.

        Args:
            limit: Maximum suggestions to return.
            current_topic: Current study topic for relevance boosting.
        """
        from studyctl.logic.backlog_logic import BacklogItem, ScoringInput, score_backlog_items
        from studyctl.parking import get_parked_topics, get_topic_frequencies

        raw = get_parked_topics(status="pending")
        if not raw:
            return {"suggestions": [], "total": 0}

        frequencies = get_topic_frequencies(status="pending")
        inputs = [
            ScoringInput(
                item=BacklogItem(
                    id=t["id"],
                    question=t["question"],
                    topic_tag=t.get("topic_tag"),
                    tech_area=t.get("tech_area"),
                    source=t.get("source", "parked"),
                    context=t.get("context"),
                    parked_at=t["parked_at"],
                    session_topic=None,
                ),
                frequency=frequencies.get(t["question"], 1),
                priority=t.get("priority"),
            )
            for t in raw
        ]

        suggestions = score_backlog_items(inputs)[:limit]
        return {
            "suggestions": [
                {
                    "rank": i + 1,
                    "topic": s.item.question,
                    "tech_area": s.item.tech_area,
                    "score": s.score,
                    "priority": s.priority,
                    "frequency": s.frequency,
                    "reasoning": s.reasoning,
                    "id": s.item.id,
                }
                for i, s in enumerate(suggestions)
            ],
            "total": len(suggestions),
        }

    @mcp.tool()
    def get_study_history(
        topic: str,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get study history for a topic: sessions, progress, and scores.

        Queries study_sessions, study_progress, and teach_back_scores
        to give a comprehensive view of the student's learning journey
        on a specific topic.

        Args:
            topic: Topic name to search for.
            days: Number of days to look back (default 30).
        """
        from studyctl.history import (
            get_study_session_stats,
            get_wins,
            last_studied,
            struggle_topics,
        )

        # Session stats — filter for matching topic
        all_stats = get_study_session_stats(days=days)
        topic_stats = [s for s in all_stats if topic.lower() in s.get("topic", "").lower()]

        # Last studied date
        last = last_studied([topic.lower()])

        # Struggles
        struggles = struggle_topics(days=days)
        topic_struggles = [s for s in struggles if topic.lower() in s.get("topic", "").lower()]

        # Wins (confident/mastered concepts)
        wins = get_wins(days=days)
        topic_wins = [w for w in wins if topic.lower() in w.get("topic", "").lower()]

        return {
            "topic": topic,
            "days": days,
            "session_stats": topic_stats,
            "last_studied": last,
            "struggles": topic_struggles,
            "wins": topic_wins,
        }

    @mcp.tool()
    def record_topic_progress(
        topic_id: int,
        priority: int | None = None,
        confidence: str | None = None,
    ) -> dict[str, Any]:
        """Update a backlog topic's priority or record progress.

        Use this to set agent-assessed importance (1-5) on backlog items,
        where 5 = foundational/critical and 1 = niche/optional.

        Can also update the topic's status to 'resolved' by setting
        confidence to 'resolved'.

        Args:
            topic_id: The backlog item ID (from get_study_backlog).
            priority: Importance score (1-5). 5 = foundational.
            confidence: Set to "resolved" to mark as done.
        """
        from studyctl.parking import resolve_parked_topic, update_topic_priority

        results: dict[str, Any] = {"topic_id": topic_id}

        if priority is not None:
            if not 1 <= priority <= 5:
                raise ToolError("priority must be between 1 and 5")
            success = update_topic_priority(topic_id, priority)
            results["priority_updated"] = success

        if confidence == "resolved":
            success = resolve_parked_topic(topic_id)
            results["resolved"] = success

        return results
