"""Course progress aggregation across local content and review data."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from studyctl.content.storage import list_courses
from studyctl.review_db import get_course_stats


@dataclass(frozen=True)
class ReviewProgress:
    """Review statistics for one course."""

    total_reviews: int
    unique_cards: int
    due_today: int
    mastered: int
    sessions: int
    correct_answers: int
    total_answers: int

    @property
    def accuracy(self) -> float | None:
        """Return review accuracy as a percentage, or None when no answers exist."""
        if self.total_answers == 0:
            return None
        return round(self.correct_answers / self.total_answers * 100, 1)


@dataclass(frozen=True)
class CourseProgress:
    """Progress summary for one local course directory."""

    slug: str
    title: str
    path: Path
    notebook_id: str
    source_count: int
    flashcard_files: int
    quiz_files: int
    review: ReviewProgress

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        data = asdict(self)
        data["path"] = str(self.path)
        data["review"]["accuracy"] = self.review.accuracy
        return data


@dataclass(frozen=True)
class ProgressSummary:
    """Aggregate course progress summary."""

    courses: list[CourseProgress]

    @property
    def totals(self) -> dict[str, int]:
        """Return additive totals across all courses."""
        return {
            "courses": len(self.courses),
            "sources": sum(course.source_count for course in self.courses),
            "flashcard_files": sum(course.flashcard_files for course in self.courses),
            "quiz_files": sum(course.quiz_files for course in self.courses),
            "total_reviews": sum(course.review.total_reviews for course in self.courses),
            "unique_cards": sum(course.review.unique_cards for course in self.courses),
            "due_today": sum(course.review.due_today for course in self.courses),
            "mastered": sum(course.review.mastered for course in self.courses),
            "sessions": sum(course.review.sessions for course in self.courses),
        }

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "totals": self.totals,
            "courses": [course.to_json_dict() for course in self.courses],
        }


def summarize_course_progress(
    *,
    base_path: Path,
    db_path: Path | None = None,
    course: str | None = None,
) -> ProgressSummary:
    """Summarize local content and review progress for configured courses."""
    wanted = course.lower().strip() if course else None
    courses: list[CourseProgress] = []

    for raw_course in list_courses(base_path.expanduser()):
        slug = str(raw_course["slug"])
        if wanted and slug.lower() != wanted:
            continue

        path = Path(raw_course["path"])
        metadata = raw_course.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        courses.append(
            CourseProgress(
                slug=slug,
                title=str(metadata.get("title") or slug),
                path=path,
                notebook_id=str(metadata.get("notebook_id") or ""),
                source_count=_source_count(metadata),
                flashcard_files=_count_files(path / "flashcards"),
                quiz_files=_count_files(path / "quizzes"),
                review=_review_progress(slug, db_path),
            )
        )

    return ProgressSummary(courses=courses)


def _source_count(metadata: dict[str, Any]) -> int:
    sources = metadata.get("sources", [])
    return len(sources) if isinstance(sources, list) else 0


def _count_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if child.is_file() and not child.name.startswith("."))


def _review_progress(course: str, db_path: Path | None) -> ReviewProgress:
    stats = get_course_stats(course, db_path=db_path)
    sessions, correct_answers, total_answers = _session_stats(course, db_path)
    return ReviewProgress(
        total_reviews=int(stats.get("total_reviews", 0)),
        unique_cards=int(stats.get("unique_cards", 0)),
        due_today=int(stats.get("due_today", 0)),
        mastered=int(stats.get("mastered", 0)),
        sessions=sessions,
        correct_answers=correct_answers,
        total_answers=total_answers,
    )


def _session_stats(course: str, db_path: Path | None) -> tuple[int, int, int]:
    if db_path is None or not db_path.exists():
        return (0, 0, 0)
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(correct), 0), COALESCE(SUM(total), 0)
                FROM review_sessions
                WHERE course = ?
                """,
                (course,),
            ).fetchone()
    except sqlite3.Error:
        return (0, 0, 0)
    return (int(row[0]), int(row[1]), int(row[2]))
