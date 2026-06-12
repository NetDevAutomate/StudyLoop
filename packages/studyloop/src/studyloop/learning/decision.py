"""Shared decision engine for "what should I study now?" recommendations."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal

from studyloop.cli._shared import TOPIC_KEYWORDS

EnergyLevel = Literal["low", "medium", "high"]
Modality = Literal["recall", "conversation", "hands-on", "visual", "audio"]
InterleaveMode = Literal["off", "adaptive"]
ActionType = Literal["recall", "conversation", "hands-on", "visual", "audio", "teachback"]


INTERLEAVE_RATIOS: dict[EnergyLevel, dict[str, int]] = {
    "low": {"current_or_due_repair": 80, "gentle_old_review": 20},
    "medium": {"current": 50, "due": 30, "transfer": 20},
    "high": {"current": 40, "weak_links": 30, "transfer": 30},
}


@dataclass(frozen=True)
class LearningRecommendation:
    """One concrete learning action with enough context to record evidence."""

    concept: str
    topic: str
    reason: str
    action_type: ActionType
    estimated_minutes: int
    source: str
    evidence_command: str
    score: float
    course: str | None = None
    metadata: dict[str, str | int | float | None] = field(default_factory=dict)

    def to_json_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class NowPlan:
    """Decision-engine response shared by CLI, web, and later agent surfaces."""

    energy: EnergyLevel
    time_minutes: int
    modality: Modality
    interleave: InterleaveMode
    generated_at: str
    primary: LearningRecommendation
    alternates: list[LearningRecommendation]
    interleave_ratio: dict[str, int]
    starter: bool = False

    def to_json_dict(self) -> dict:
        return {
            "energy": self.energy,
            "time_minutes": self.time_minutes,
            "modality": self.modality,
            "interleave": self.interleave,
            "generated_at": self.generated_at,
            "starter": self.starter,
            "interleave_ratio": self.interleave_ratio,
            "primary": self.primary.to_json_dict(),
            "alternates": [item.to_json_dict() for item in self.alternates],
        }


@dataclass(frozen=True)
class _Candidate:
    concept: str
    topic: str
    reason: str
    action_type: ActionType
    estimated_minutes: int
    source: str
    evidence_command: str
    score: float
    course: str | None = None
    metadata: dict[str, str | int | float | None] = field(default_factory=dict)

    def recommendation(self) -> LearningRecommendation:
        return LearningRecommendation(
            concept=self.concept,
            topic=self.topic,
            reason=self.reason,
            action_type=self.action_type,
            estimated_minutes=self.estimated_minutes,
            source=self.source,
            evidence_command=self.evidence_command,
            score=round(self.score, 2),
            course=self.course,
            metadata=self.metadata,
        )


def _estimate_minutes(action_type: ActionType, requested: int, default: int) -> int:
    floor = 5 if action_type in {"recall", "audio"} else 10
    return max(floor, min(requested, default))


def _action_for_review(review_type: str, confidence: str | None) -> ActionType:
    label = review_type.lower()
    if "teach" in label:
        return "teachback"
    if "apply" in label or confidence == "struggling":
        return "hands-on"
    return "recall"


def _evidence_command(action_type: ActionType, concept: str, topic: str, source: str) -> str:
    safe_concept = concept.replace('"', '\\"')
    safe_topic = topic.replace('"', '\\"')
    if action_type == "teachback":
        return (
            f'studyloop teachback "{safe_concept}" -t "{safe_topic}" '
            '--score "3,3,3,3,3" --type structured'
        )
    if action_type == "hands-on" and source.endswith(".json"):
        safe_source = source.replace('"', '\\"')
        return f'studyloop practice verify "{safe_source}" --task 1 --notes "what passed?"'
    return f'studyloop progress "{safe_concept}" -t "{safe_topic}" -c learning'


def _connect_progress_db():
    try:
        from studyloop.history import _connection

        return _connection._connect()
    except Exception:
        return None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def _due_progress_candidates(time_minutes: int) -> list[_Candidate]:
    from studyloop.history import spaced_repetition_due

    candidates: list[_Candidate] = []
    try:
        due_items = spaced_repetition_due(TOPIC_KEYWORDS)
    except Exception:
        return candidates

    for item in due_items:
        concept = item.get("concept")
        if not concept:
            continue
        topic = str(item.get("topic") or "study")
        confidence = item.get("confidence")
        review_type = str(item.get("review_type") or "review")
        action = _action_for_review(review_type, confidence)
        days_ago = item.get("days_ago") or 0
        teachback_score = item.get("last_teachback_score")
        score = 100 + min(int(days_ago), 30)
        if confidence == "struggling":
            score += 35
        elif confidence == "learning":
            score += 15
        if isinstance(teachback_score, int | float) and teachback_score < 14:
            score += 25
        source = f"study_progress:{topic}:{concept}"
        candidates.append(
            _Candidate(
                concept=str(concept),
                topic=topic,
                course=item.get("source_course"),
                reason=(
                    f"{review_type}; last seen {days_ago} day(s) ago"
                    + (f"; confidence is {confidence}" if confidence else "")
                ),
                action_type=action,
                estimated_minutes=_estimate_minutes(action, time_minutes, 15),
                source=source,
                evidence_command=_evidence_command(action, str(concept), topic, source),
                score=score,
                metadata={
                    "confidence": confidence,
                    "days_ago": days_ago,
                    "last_teachback_score": teachback_score,
                },
            )
        )
    return candidates


def _struggle_candidates(time_minutes: int) -> list[_Candidate]:
    conn = _connect_progress_db()
    if not conn:
        return []
    try:
        columns = _table_columns(conn, "study_progress")
        if not columns:
            return []
        select_cols = ["topic", "concept", "confidence", "last_seen", "session_count"]
        if "last_teachback_score" in columns:
            select_cols.append("last_teachback_score")
        if "source_course" in columns:
            select_cols.append("source_course")
        if "source_section" in columns:
            select_cols.append("source_section")
        rows = conn.execute(
            f"""
            SELECT {", ".join(select_cols)}
            FROM study_progress
            WHERE confidence IN ('struggling', 'learning')
               OR (last_teachback_score IS NOT NULL AND last_teachback_score < 14)
            ORDER BY
              CASE confidence
                WHEN 'struggling' THEN 0
                WHEN 'learning' THEN 1
                ELSE 2
              END,
              COALESCE(last_teachback_score, 99) ASC,
              last_seen DESC
            LIMIT 12
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    candidates: list[_Candidate] = []
    for row in rows:
        row_keys = set(row.keys())
        concept = str(row["concept"])
        topic = str(row["topic"])
        confidence = row["confidence"]
        teachback_score = (
            row["last_teachback_score"] if "last_teachback_score" in row_keys else None
        )
        action: ActionType = "hands-on" if confidence == "struggling" else "teachback"
        score = 82 if confidence == "struggling" else 70
        if isinstance(teachback_score, int | float):
            score += max(0, 14 - int(teachback_score)) * 3
        source = (
            row["source_section"]
            if "source_section" in row_keys and row["source_section"]
            else f"study_progress:{topic}:{concept}"
        )
        candidates.append(
            _Candidate(
                concept=concept,
                topic=topic,
                course=row["source_course"] if "source_course" in row_keys else None,
                reason=(
                    f"Recorded as {confidence}; repair now while the signal is fresh"
                    + (f"; last teach-back score {teachback_score}/20" if teachback_score else "")
                ),
                action_type=action,
                estimated_minutes=_estimate_minutes(action, time_minutes, 20),
                source=str(source),
                evidence_command=_evidence_command(action, concept, topic, str(source)),
                score=score,
                metadata={
                    "confidence": confidence,
                    "last_teachback_score": teachback_score,
                    "session_count": row["session_count"],
                },
            )
        )
    return candidates


def _due_card_candidates(time_minutes: int) -> list[_Candidate]:
    try:
        from studyloop.services.review import list_course_summaries
        from studyloop.settings import resolve_study_dirs

        summaries = list_course_summaries(resolve_study_dirs())
    except Exception:
        return []

    candidates: list[_Candidate] = []
    for summary in summaries:
        due_count = int(summary.get("due_count") or 0)
        if due_count <= 0:
            continue
        course = str(summary.get("name") or "course")
        source = f"review_db:{course}"
        candidates.append(
            _Candidate(
                concept="due review cards",
                topic=course,
                course=course,
                reason=f"{due_count} spaced-repetition card(s) are due",
                action_type="recall",
                estimated_minutes=_estimate_minutes(
                    "recall", time_minutes, min(20, 5 + due_count * 2)
                ),
                source=source,
                evidence_command=(
                    'studyloop review && studyloop progress "due review cards" '
                    f'-t "{course}" -c learning'
                ),
                score=96 + min(due_count, 20),
                metadata={"due_count": due_count},
            )
        )
    return candidates


def _practice_candidates(time_minutes: int) -> list[_Candidate]:
    try:
        from studyloop.settings import load_settings

        base = load_settings().content.base_path.expanduser()
    except Exception:
        return []
    if not base.is_dir():
        return []

    candidates: list[_Candidate] = []
    for path in sorted(base.rglob("*-practice.json"))[:20]:
        topic = path.parent.parent.name if path.parent.name == "practice" else path.parent.name
        source = str(path)
        candidates.append(
            _Candidate(
                concept=path.stem.replace("-practice", "").replace("-", " "),
                topic=topic,
                course=topic,
                reason="Hands-on practice task is available for active encoding",
                action_type="hands-on",
                estimated_minutes=_estimate_minutes("hands-on", time_minutes, 25),
                source=source,
                evidence_command=_evidence_command("hands-on", path.stem, topic, source),
                score=48,
                metadata={"practice_path": source},
            )
        )
    return candidates


def _continuity_candidates(time_minutes: int) -> list[_Candidate]:
    try:
        from studyloop.history import get_last_session_summary

        summary = get_last_session_summary()
    except Exception:
        return []
    if not summary:
        return []

    candidates: list[_Candidate] = []
    for item in summary.get("concepts_in_progress") or []:
        concept = str(item.get("concept") or "").strip()
        topic = str(item.get("topic") or "study").strip()
        if not concept:
            continue
        source = f"last_session:{topic}:{concept}"
        candidates.append(
            _Candidate(
                concept=concept,
                topic=topic,
                reason="Continuity from the last session reduces task-start friction",
                action_type="conversation",
                estimated_minutes=_estimate_minutes("conversation", time_minutes, 15),
                source=source,
                evidence_command=_evidence_command("conversation", concept, topic, source),
                score=58,
                metadata={"confidence": item.get("confidence")},
            )
        )
    return candidates


def _transfer_candidates(time_minutes: int) -> list[_Candidate]:
    try:
        from studyloop.learning.mastery import weak_links_for_topic

        weak_links = []
        for topic in TOPIC_KEYWORDS:
            weak_links.extend(weak_links_for_topic(topic)[:2])
    except Exception:
        return []

    candidates: list[_Candidate] = []
    for link in weak_links[:6]:
        concept = str(link.get("concept") or link.get("target_concept") or "weak link")
        topic = str(link.get("topic") or "study")
        source = str(link.get("source") or f"concept_dependencies:{topic}:{concept}")
        candidates.append(
            _Candidate(
                concept=concept,
                topic=topic,
                reason=str(link.get("reason") or "Weak prerequisite link is blocking transfer"),
                action_type="visual",
                estimated_minutes=_estimate_minutes("visual", time_minutes, 20),
                source=source,
                evidence_command=_evidence_command("visual", concept, topic, source),
                score=52,
                metadata={"dependency": link.get("dependency")},
            )
        )
    return candidates


def _starter_candidate(time_minutes: int) -> _Candidate:
    try:
        from studyloop.topics import get_topics

        topics = get_topics()
    except Exception:
        topics = []
    if topics:
        topic = topics[0].name
        display = topics[0].display_name
    else:
        topic = "python"
        display = "Python"
    return _Candidate(
        concept="one tiny recall loop",
        topic=topic,
        course=topic,
        reason="No learning evidence found yet; start by creating one small retrieval signal",
        action_type="recall",
        estimated_minutes=_estimate_minutes("recall", time_minutes, 10),
        source="starter",
        evidence_command=f'studyloop progress "one tiny recall loop" -t "{topic}" -c learning',
        score=10,
        metadata={"display_name": display},
    )


def _last_focus_topic(candidates: list[_Candidate]) -> str | None:
    for candidate in candidates:
        if candidate.source.startswith("last_session:"):
            return candidate.topic
    return None


def _modality_matches(candidate: _Candidate, modality: Modality) -> bool:
    if modality == candidate.action_type:
        return True
    if modality == "visual" and candidate.action_type == "visual":
        return True
    if modality == "hands-on" and candidate.action_type == "hands-on":
        return True
    if modality == "conversation" and candidate.action_type in {"conversation", "teachback"}:
        return True
    return modality == "recall" and candidate.action_type in {"recall", "teachback"}


def _score_candidates(
    candidates: list[_Candidate],
    *,
    energy: EnergyLevel,
    modality: Modality,
    interleave: InterleaveMode,
) -> list[_Candidate]:
    last_topic = _last_focus_topic(candidates)
    scored: list[_Candidate] = []
    for candidate in candidates:
        score = candidate.score
        if _modality_matches(candidate, modality):
            score += 18
        if modality == "audio":
            score += 8 if candidate.action_type in {"recall", "conversation"} else -5
        if energy == "low":
            if candidate.action_type in {"hands-on", "visual"}:
                score -= 14
            if last_topic and candidate.topic != last_topic:
                score -= 28
        elif energy == "high":
            if candidate.action_type in {"hands-on", "visual", "teachback"}:
                score += 10
        if interleave == "adaptive":
            if energy == "low" and candidate.action_type == "visual":
                score -= 25
            elif energy in {"medium", "high"} and candidate.action_type == "visual":
                score += 8 if energy == "medium" else 16

        scored.append(
            _Candidate(
                concept=candidate.concept,
                topic=candidate.topic,
                course=candidate.course,
                reason=candidate.reason,
                action_type=candidate.action_type,
                estimated_minutes=candidate.estimated_minutes,
                source=candidate.source,
                evidence_command=candidate.evidence_command,
                score=score,
                metadata=candidate.metadata,
            )
        )
    return scored


def _dedupe(candidates: list[_Candidate]) -> list[_Candidate]:
    seen: set[tuple[str, str, str]] = set()
    result: list[_Candidate] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        key = (
            candidate.topic.lower(),
            candidate.concept.lower(),
            candidate.action_type,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def build_now_plan(
    *,
    energy: EnergyLevel = "medium",
    time_minutes: int = 25,
    modality: Modality = "recall",
    interleave: InterleaveMode = "off",
) -> NowPlan:
    """Return the best current study action plus two alternatives."""
    time_minutes = max(5, min(int(time_minutes), 180))

    candidates = [
        *_due_card_candidates(time_minutes),
        *_due_progress_candidates(time_minutes),
        *_struggle_candidates(time_minutes),
        *_continuity_candidates(time_minutes),
        *_practice_candidates(time_minutes),
    ]
    if interleave == "adaptive" and energy != "low":
        candidates.extend(_transfer_candidates(time_minutes))

    starter = False
    if not candidates:
        candidates = [_starter_candidate(time_minutes)]
        starter = True

    ranked = _dedupe(
        _score_candidates(
            candidates,
            energy=energy,
            modality=modality,
            interleave=interleave,
        )
    )
    primary = ranked[0].recommendation()
    alternates = [item.recommendation() for item in ranked[1:3]]
    return NowPlan(
        energy=energy,
        time_minutes=time_minutes,
        modality=modality,
        interleave=interleave,
        generated_at=datetime.now(UTC).isoformat(),
        starter=starter,
        primary=primary,
        alternates=alternates,
        interleave_ratio=INTERLEAVE_RATIOS[energy] if interleave == "adaptive" else {},
    )
