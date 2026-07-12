"""MCP tool implementations for studyloop.

Each tool is registered via ``register_tools(mcp)`` and uses the
lifespan AppState for shared DB/settings access.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP  # noqa: TC002 — used at runtime as param type
from mcp.server.fastmcp.exceptions import ToolError

from studyloop.services.review import get_due, get_stats, record_review
from studyloop.settings import load_settings

if TYPE_CHECKING:
    from pathlib import Path

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
    """Register all studyloop MCP tools on the server."""

    @mcp.tool()
    def list_courses() -> dict[str, Any]:
        """List all available study courses with card counts and review stats.

        Returns courses discovered from the review.directories config.
        Each course has: name, card_count, quiz_count, due_count.
        """
        from studyloop.services.review import list_course_summaries
        from studyloop.settings import resolve_study_dirs

        # Falls back to content.base_path when review.directories is unset.
        study_dirs = resolve_study_dirs()

        return {"courses": list_course_summaries(study_dirs)}

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
                "pymupdf not installed. Install with: uv pip install 'studyloop[content]'"
            ) from None

        settings = load_settings()
        chapters_dir = _safe_course_dir(settings.content.base_path, course, "chapters")
        if not chapters_dir.is_dir():
            raise ToolError(
                f"No chapters directory for course '{course}'. Run 'studyloop content split' first."
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
            page_text = page.get_text()
            if not isinstance(page_text, str):
                raise ToolError(f"Could not extract text from {pdf_path.name}")
            text += page_text
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
        from studyloop.parking import get_parked_topics

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
        from studyloop.logic.backlog_logic import BacklogItem, ScoringInput, score_backlog_items
        from studyloop.parking import get_parked_topics, get_topic_frequencies

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
        from studyloop.history import (
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

    # ── §1.10 agent-native parity (web-picker equivalents) ───────

    @mcp.tool()
    def list_session_options() -> dict[str, Any]:
        """List selectable study targets for starting a session.

        Mirrors the web picker's ``GET /api/session/options`` response so
        an agent driving studyloop has access to the same vendor /
        course / lesson / agent surface the browser does. Use this
        before asking the learner what to study, or to validate a
        user-supplied target against available content.

        Returns a dict with keys ``session_types``, ``topics``,
        ``vendors``, ``courses``, ``lessons``, ``agents``. Each
        collection is a list of dicts with ``label``/``value``/
        ``kind``; courses and lessons carry a ``parent`` field that
        links them back up the cascade (course.parent = vendor.value,
        lesson.parent = course.value).
        """
        from studyloop.web.routes.session import (
            _agent_options,
        )
        from studyloop.web.routes.session._options import _get_indexed_target_options

        targets = _get_indexed_target_options()
        return {**targets, "agents": _agent_options()}

    @mcp.tool()
    def end_session() -> dict[str, Any]:
        """End the currently-active study session, if any.

        Idempotent: calling this with no active session returns
        ``{"ended": False, "topic": None}`` rather than raising. Agents
        can safely call this in a cleanup path without first checking
        state.

        Returns ``{"ended": True, "topic": <resolved topic>}`` after
        the session's tmux/ttyd/PTY resources have been torn down and
        the IPC files cleared.
        """
        from studyloop.session.cleanup import end_session_common
        from studyloop.web.routes.session import read_session_state

        state = read_session_state()
        if not state.get("study_session_id"):
            return {"ended": False, "topic": None}
        topic = end_session_common(state)
        return {"ended": True, "topic": topic}

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
        from studyloop.parking import resolve_parked_topic, update_topic_priority

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

    # ── §log_topic — mid-session learning signal recorder ────────

    valid_statuses = frozenset({"learning", "struggling", "insight", "win", "parked"})
    confidence_map: dict[str, str] = {
        "struggling": "struggling",
        "learning": "learning",
        "win": "confident",
        "insight": "confident",
    }

    @mcp.tool()
    def log_topic(topic: str, status: str, note: str = "") -> dict[str, str]:
        """Record a topic the user is learning/struggling with this session.

        Writes to session-topics.md (so it's counted at session end) AND, for
        learning-signal statuses, to study_progress (the spaced-repetition store).
        Call this during a session whenever the user clearly struggles with,
        learns, or has an insight about a concept — especially after 2+ rounds
        without breakthrough (status='struggling').

        Args:
            topic: The concept or topic the user is engaging with.
            status: One of 'learning', 'struggling', 'insight', 'win', 'parked'.
            note: Optional free-text note (e.g. what exactly confused them).
        """
        from studyloop.history import record_progress
        from studyloop.session_state import append_topic

        if status not in valid_statuses:
            allowed = ", ".join(sorted(valid_statuses))
            raise ToolError(f"Invalid status {status!r}. Allowed: {allowed}")

        time_str = datetime.now().strftime("%H:%M")
        append_topic(time_str, topic, status, note)

        confidence = confidence_map.get(status)
        if confidence is not None:
            try:
                record_progress(
                    topic=topic,
                    concept=topic,
                    confidence=confidence,
                    notes=note or None,
                )
            except Exception:
                logger.exception(
                    "log_topic: record_progress failed for topic=%r status=%r — continuing",
                    topic,
                    status,
                )

        return {"logged": "true", "topic": topic, "status": status}

    # ── Review loop + lifecycle parity ───────────────────────────

    @mcp.tool()
    def get_due_cards(course: str | None = None, limit: int = 20) -> dict[str, Any]:
        """Get cards due for spaced-repetition review.

        If ``course`` is given, returns due cards for that course only.
        Otherwise aggregates due cards across every discovered course
        (via list_courses' underlying summary logic).

        Args:
            course: Course name. Omit to aggregate across all courses.
            limit: Maximum cards to return.
        """
        from studyloop.services.review import list_course_summaries
        from studyloop.settings import resolve_study_dirs

        if course is not None:
            due = get_due(course)
            cards = [{"course": course, **dataclasses.asdict(c)} for c in due]
        else:
            cards = []
            for summary in list_course_summaries(resolve_study_dirs()):
                name = summary["name"]
                cards.extend({"course": name, **dataclasses.asdict(c)} for c in get_due(name))

        cards = cards[:limit]
        return {"due_cards": cards, "count": len(cards)}

    @mcp.tool()
    def log_review_outcome(
        course: str,
        card_type: str,
        card_hash: str,
        correct: bool,
        response_time_ms: int | None = None,
    ) -> dict[str, Any]:
        """Record the outcome of reviewing a single card.

        Args:
            course: Course name.
            card_type: Either "flashcard" or "quiz".
            card_hash: The card's hash identifier (from get_due_cards).
            correct: Whether the student answered correctly.
            response_time_ms: Optional response time in milliseconds.
        """
        if card_type not in {"flashcard", "quiz"}:
            raise ToolError(f"card_type must be 'flashcard' or 'quiz', got {card_type!r}")

        record_review(
            course=course,
            card_type=card_type,
            card_hash=card_hash,
            correct=correct,
            response_time_ms=response_time_ms,
        )
        return {
            "status": "logged",
            "course": course,
            "card_hash": card_hash,
            "correct": correct,
        }

    @mcp.tool()
    def get_next_action(
        energy: str = "medium",
        time_minutes: int = 25,
        modality: str = "recall",
    ) -> dict[str, Any]:
        """Get the recommended next study action ("what should I do now?").

        Delegates to the same decision engine the web ``/api/now`` endpoint
        uses, so agents and the browser get identical recommendations.

        Args:
            energy: "low", "medium", or "high".
            time_minutes: Minutes available for this study action.
            modality: "recall", "conversation", "hands-on", "visual", or "audio".
        """
        from studyloop.learning.decision import build_now_plan

        plan = build_now_plan(energy=energy, time_minutes=time_minutes, modality=modality)
        return plan.to_json_dict()

    @mcp.tool()
    def get_active_topics() -> dict[str, Any]:
        """Get the active study backlog topics, capped at the AuDHD 3-topic limit.

        Splits the pending backlog into an "active" set (the first
        ``MAX_ACTIVE_TOPICS`` items) and the remaining "backlog", matching
        the same active-topic rule enforced by ``studyloop doctor``.
        """
        from studyloop.parking import get_parked_topics
        from studyloop.settings import MAX_ACTIVE_TOPICS

        pending = get_parked_topics(status="pending")
        active = pending[:MAX_ACTIVE_TOPICS]
        return {
            "active": active,
            "active_count": len(active),
            "backlog_count": max(0, len(pending) - MAX_ACTIVE_TOPICS),
            "max_active": MAX_ACTIVE_TOPICS,
        }

    @mcp.tool()
    def log_struggle(
        question: str,
        topic_tag: str | None = None,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Record a topic the student struggled with, for later study.

        Args:
            question: The question or concept the student struggled with.
            topic_tag: Optional short tag for the topic.
            context: Optional free-text context about the struggle.
        """
        from studyloop.parking import park_topic

        row_id = park_topic(question, topic_tag=topic_tag, context=context, source="struggled")
        return {"status": "logged", "id": row_id}
