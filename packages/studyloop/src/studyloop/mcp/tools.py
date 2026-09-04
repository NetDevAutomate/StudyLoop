"""MCP tool implementations for studyloop.

Each tool is registered via ``register_tools(mcp)`` and uses the
lifespan AppState for shared DB/settings access.
"""

from __future__ import annotations

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
    def record_plan_learning(
        plan_id: str, title: str, body: str = "", status: str = "active"
    ) -> dict[str, Any]:
        """Append a learning record to a study plan (the wind-down's first write).

        Record what was learned into the plan document BEFORE any second-brain
        projection is offered: the plan Markdown is the source of truth
        (ADR-0010), and a learning record that exists only in a second brain
        is a record the plan does not have.

        Idempotent: calling again with the same title and body changes nothing
        and reports created=false, so a retry is always safe.

        Args:
            plan_id: The study plan id (from `studyloop plan list`).
            title: What was learned, in one line.
            body: The record's body, as Markdown prose.
            status: Record status (default "active").
        """
        from studyloop.planning import record_learning
        from studyloop.planning.store import InvalidPlanIdError, PlanNotFoundError

        try:
            record, created = record_learning(plan_id, title, body=body, status=status)
        except (PlanNotFoundError, InvalidPlanIdError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        return {
            "plan_id": plan_id,
            "number": record.number,
            "title": record.title,
            "status": record.status,
            "created": created,
        }

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
            # Guard the lower bound: chapter is 1-indexed, so 0/negatives must
            # NOT fall through to all_pdfs[chapter-1] (Python negative indexing
            # would silently return a chapter counted from the end).
            if 1 <= chapter <= len(all_pdfs):
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
        the session's tmux/PTY resources have been torn down and
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
        # Delegated so the second-brain layer can answer the same question
        # without importing this module -- it pulls in fastmcp, an optional
        # extra, and one implementation of "which cards are due" is the point.
        from studyloop.learning.review_service import due_cards

        cards = due_cards(course=course, limit=limit)
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
        from typing import cast, get_args

        from studyloop.learning.decision import EnergyLevel, Modality, build_now_plan

        # MCP clients send plain strings; validate against the engine's
        # Literal types before forwarding so a typo ("LOW", "recal") fails
        # loudly here instead of flowing unvalidated into scoring.
        valid_energy = get_args(EnergyLevel)
        if energy not in valid_energy:
            raise ToolError(f"Invalid energy {energy!r}: choose one of {valid_energy}")
        valid_modality = get_args(Modality)
        if modality not in valid_modality:
            raise ToolError(f"Invalid modality {modality!r}: choose one of {valid_modality}")

        plan = build_now_plan(
            energy=cast("EnergyLevel", energy),
            time_minutes=time_minutes,
            modality=cast("Modality", modality),
        )
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

    # ── Course Explorer read parity (desktop MCP) ────────────────

    @mcp.tool()
    def get_lesson_tree(provider: str | None = None, course: str | None = None) -> dict[str, Any]:
        """Browse the course-material tree: providers → courses → lessons.

        With no arguments, returns the two-level provider→course tree
        (same data as the web ``GET /api/explorer/tree``). Pass
        ``provider`` and ``course`` to also list that course's lessons
        (same data as ``GET /api/explorer/courses/{id}/lessons``).

        Args:
            provider: Provider directory name (from the tree's ``id``).
            course: Course directory name. Requires ``provider``.
        """
        from studyloop.web.routes.explorer import _build_tree, _walk_lessons

        base = load_settings().content.base_path.expanduser()
        tree = _build_tree(base)
        if provider is None and course is None:
            return {"providers": tree}
        if provider is None or course is None:
            raise ToolError("Pass both 'provider' and 'course', or neither")

        course_dir = _safe_course_dir(base, provider, course)
        if not course_dir.is_dir():
            raise ToolError(f"Course not found: {provider}/{course}")
        course_id = f"{provider}/{course}"
        lessons = [
            {"id": e["lesson_id"], "title": e["title"]}
            for e in _walk_lessons(base)
            if e["course_id"] == course_id
        ]
        return {"course_id": course_id, "lessons": lessons}

    @mcp.tool()
    def read_lesson(lesson_id: str) -> dict[str, str]:
        """Read the raw markdown content of one lesson.

        Args:
            lesson_id: ``provider/course/relative/path`` (no file suffix),
                as returned by get_lesson_tree or search_lessons.
        """
        from studyloop.web.routes.explorer import resolve_lesson_path

        base = load_settings().content.base_path.expanduser().resolve()
        resolved = resolve_lesson_path(base, lesson_id)
        if resolved is None:
            raise ToolError(f"Lesson not found: {lesson_id!r}")
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return {"lesson_id": lesson_id, "content": content}

    @mcp.tool()
    def search_lessons(query: str, limit: int = 20) -> dict[str, Any]:
        """Full-text search over lesson bodies (SQLite FTS5).

        Same engine as the web ``GET /api/explorer/search`` — the query is
        treated as a literal phrase, and excerpts highlight matches with
        ``<mark>`` tags.

        Args:
            query: Search term (min 2 characters).
            limit: Maximum results to return.
        """
        from studyloop.web.routes.explorer import _fts_db_path, _fts_lock, _run_fts_search

        q = query.strip()
        if len(q) < 2:
            return {"results": []}
        base = load_settings().content.base_path.expanduser()
        with _fts_lock:
            results = _run_fts_search(_fts_db_path(), base, q, limit)
        return {"results": results}

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

    # ── Exercise sets — blank slate / completion / multiple choice ───

    def _code_payload(exercise, *, include_answers: bool) -> dict[str, Any] | None:
        """Serialise a code exercise, withholding the reference solution by default.

        Mirrors ``studyloop.web.routes.exercises._code_payload``: the point of a
        blank-slate exercise evaporates if the answer ships with the requirements.
        """
        if exercise is None:
            return None
        payload: dict[str, Any] = {
            "kind": exercise.kind,
            "title": exercise.title,
            "language": exercise.language,
            "requirements": list(exercise.requirements),
            "starter_code": exercise.starter_code,
            "scaffold_ratio": exercise.scaffold_ratio,
            "total_weight": exercise.total_weight,
            "ready": exercise.is_ready(),
            # Titles and weights only — a `check` regex is a partial answer key.
            "rubric": [{"title": c.title, "weight": c.weight} for c in exercise.rubric],
        }
        if include_answers:
            payload["reference_solution"] = exercise.reference_solution
        return payload

    def _mc_payload(questions, *, include_answers: bool) -> list[dict[str, Any]]:
        """Serialise multiple-choice questions, withholding the correct option."""
        out: list[dict[str, Any]] = []
        for question in questions:
            item: dict[str, Any] = {
                "prompt": question.prompt,
                "multi_select": question.is_multi_select,
                "answerable": question.is_answerable(),
                "choices": [
                    {"label": question.label(i), "text": c.text}
                    for i, c in enumerate(question.choices)
                ],
            }
            if include_answers:
                item["correct"] = question.correct_indexes
                item["ask"] = question.ask
                for i, choice in enumerate(question.choices):
                    item["choices"][i]["correct"] = choice.correct
                    item["choices"][i]["why"] = choice.why
            out.append(item)
        return out

    @mcp.tool()
    def exercise_list(plan_id: str = "", topic: str = "") -> dict[str, Any]:
        """List exercise sets, optionally scoped to a plan and/or topic.

        Args:
            plan_id: Filter to sets belonging to this plan.
            topic: Filter to sets matching this topic (case-insensitive).
        """
        from studyloop.planning.exercises import EXERCISE_KINDS, list_sets

        sets = list_sets(plan_id=plan_id.strip(), topic=topic.strip())
        return {
            "sets": [item.summary() for item in sets],
            "count": len(sets),
            "kinds": list(EXERCISE_KINDS),
        }

    @mcp.tool()
    def exercise_get(set_id: str, include_answers: bool = False) -> dict[str, Any]:
        """Fetch one exercise set: all three formats, plus readiness.

        Reference solutions and marked-correct choices are withheld unless
        ``include_answers`` is set — an agent that has not read the solution
        cannot leak it to the learner.

        Args:
            set_id: The exercise set id (from exercise_list or exercise_create).
            include_answers: Pass True to also receive reference solutions and
                correct-choice markers (author/grader use only).
        """
        from studyloop.planning.exercises import readiness as compute_readiness
        from studyloop.planning.exercises import (
            render_exercise_set,
            render_for_learner,
        )
        from studyloop.planning.exercises.store import ExerciseSetNotFoundError, InvalidSetIdError
        from studyloop.planning.exercises.store import load_set as load_exercise_set

        try:
            item = load_exercise_set(set_id)
        except ExerciseSetNotFoundError as exc:
            raise ToolError(str(exc)) from exc
        except InvalidSetIdError as exc:
            raise ToolError(str(exc)) from exc

        return {
            "set": item.summary(),
            "markdown": render_exercise_set(item) if include_answers else render_for_learner(item),
            "blank_slate": _code_payload(item.blank_slate, include_answers=include_answers),
            "completion": _code_payload(item.completion, include_answers=include_answers),
            "multiple_choice": _mc_payload(item.multiple_choice, include_answers=include_answers),
            "readiness": compute_readiness(item),
        }

    @mcp.tool()
    def exercise_create(
        topic: str,
        plan_id: str = "",
        concepts: list[str] | None = None,
        requirements: list[str] | None = None,
        reference_solution: str = "",
        language: str = "python",
        reveal: float = 0.4,
    ) -> dict[str, Any]:
        """Draft a new exercise set for a topic (blank slate + completion + MC scaffold).

        Nothing is invented: rubric checks and multiple-choice questions are left
        for a follow-up author pass, and the returned ``readiness`` reports exactly
        what is still missing rather than fabricating content.

        Args:
            topic: What the exercise is about. Required.
            plan_id: Owning study plan id, if any.
            concepts: Concept tags to attach (joins to study_progress).
            requirements: What a correct solution must do.
            reference_solution: Author's solution; also used to derive the
                completion exercise's starter code.
            language: Source language for the code exercises (default "python").
            reveal: Fraction of the reference solution to reveal as completion
                starter code (0.0-0.85).
        """
        from studyloop.planning.exercises import create_set, draft_exercise_set, unique_set_id
        from studyloop.planning.exercises import readiness as compute_readiness

        cleaned_topic = topic.strip()
        if not cleaned_topic:
            raise ToolError("topic is required")

        item = draft_exercise_set(
            cleaned_topic,
            plan_id=plan_id.strip(),
            set_id=unique_set_id(plan_id.strip(), cleaned_topic),
            concepts=concepts or [],
            requirements=requirements or [],
            reference_solution=reference_solution,
            language=language,
            reveal=reveal,
        )
        create_set(item)
        return {"created": True, "set": item.summary(), "readiness": compute_readiness(item)}

    @mcp.tool()
    def exercise_import(markdown: str) -> dict[str, Any]:
        """Import a hand-authored exercise document (Markdown) as a new set.

        The document is parsed and re-validated before being persisted, so a
        malformed import fails loudly here rather than saving a broken set.

        Args:
            markdown: The full exercise-set document, including its front matter.
        """
        from studyloop.planning.exercises import (
            create_set,
            parse_exercise_set,
            unique_set_id,
        )
        from studyloop.planning.exercises import readiness as compute_readiness

        cleaned = markdown.strip()
        if not cleaned:
            raise ToolError("markdown is required")

        try:
            item = parse_exercise_set(cleaned)
        except Exception as exc:
            raise ToolError(f"unparseable markdown: {exc}") from exc
        if not item.set_id:
            item.set_id = unique_set_id(item.plan_id, item.topic)

        create_set(item)
        return {"created": True, "set": item.summary(), "readiness": compute_readiness(item)}

    @mcp.tool()
    def exercise_review(
        set_id: str,
        kind: str,
        submission: str = "",
        answers: dict[str, list[int]] | None = None,
        record: bool = False,
    ) -> dict[str, Any]:
        """Score an attempt against an exercise set and return Socratic follow-ups.

        One entry point for all three formats. ``submission`` carries code for
        ``blank_slate``/``completion``; ``answers`` carries
        ``{question_index: [choice_index, ...]}`` for ``multiple_choice``. The
        returned markdown never contains the reference solution or which choice
        was correct.

        Args:
            set_id: The exercise set id.
            kind: One of "blank_slate", "completion", "multiple_choice".
            submission: Learner's code, for the two code formats.
            answers: Selected choices per question index, for multiple_choice.
            record: Set True to write the derived confidence into study_progress.
        """
        from studyloop.planning.exercises import EXERCISE_KINDS, review_submission
        from studyloop.planning.exercises import record_review as record_exercise_review
        from studyloop.planning.exercises.store import ExerciseSetNotFoundError, InvalidSetIdError
        from studyloop.planning.exercises.store import load_set as load_exercise_set

        try:
            item = load_exercise_set(set_id)
        except ExerciseSetNotFoundError as exc:
            raise ToolError(str(exc)) from exc
        except InvalidSetIdError as exc:
            raise ToolError(str(exc)) from exc

        if kind not in EXERCISE_KINDS:
            raise ToolError(f"kind must be one of {EXERCISE_KINDS}")

        parsed_answers: dict[int, list[int]] = {}
        if kind == "multiple_choice":
            for key, value in (answers or {}).items():
                try:
                    index = int(key)
                except (TypeError, ValueError) as exc:
                    raise ToolError(f"answers keys must be question indexes, got {key!r}") from exc
                selected = value if isinstance(value, list) else [value]
                try:
                    parsed_answers[index] = [int(v) for v in selected]
                except (TypeError, ValueError) as exc:
                    raise ToolError(f"answers[{index}] must be choice indexes") from exc

        try:
            review = review_submission(
                item,
                kind,
                submission=submission,
                answers=parsed_answers,
            )
        except LookupError as exc:
            raise ToolError(f"no {kind!r} exercise on set {set_id!r}: {exc}") from exc

        recorded = False
        if record:
            recorded = record_exercise_review(review, concepts=item.concepts)

        return {
            "review": review.to_dict(),
            "markdown": review.as_markdown(),
            "recorded": recorded,
        }
