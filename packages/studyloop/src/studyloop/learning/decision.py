"""Shared decision engine for "what should I study now?" recommendations.

This module is the **only ranker**. Active study plans (design §3, D-5) enter
it as one plan-static read — ``PlanApplication().get_active_guidance()`` — and
leave as a *bias* on the existing scores, a synthesised candidate for an
unrepresented next milestone, and references attached to the ranked actions.
The one plan that is not plan-static is a fully-checked one (rule 9): its
completion action carries the end assessment's completion review, read through
the preview path (``assess(AssessPlan(phase="end", record=False))``) — one
call per such plan, no write, no status change (D-G). Renderers show that plan
relevance; none of them re-rank.

With no active plan the emitted JSON is byte for byte what it was before plans
existed: every additive field is omitted when empty
(``tests/golden/now_plan_no_active.json``).
"""

from __future__ import annotations

import dataclasses
import logging
import shlex
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from studyloop.cli._shared import TOPIC_KEYWORDS

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from studyloop.planning.views import (
        ActiveGuidance,
        ActivePlanGuidance,
        CompletionReview,
        MilestoneView,
        PlanSummary,
    )

logger = logging.getLogger(__name__)

EnergyLevel = Literal["low", "medium", "high"]
Modality = Literal["recall", "conversation", "hands-on", "visual", "audio"]
InterleaveMode = Literal["off", "adaptive"]
ActionType = Literal["recall", "conversation", "hands-on", "visual", "audio", "teachback"]


INTERLEAVE_RATIOS: dict[EnergyLevel, dict[str, int]] = {
    "low": {"current_or_due_repair": 80, "gentle_old_review": 20},
    "medium": {"current": 50, "due": 30, "transfer": 20},
    "high": {"current": 40, "weak_links": 30, "transfer": 30},
}

#: Design §3 rule 3 — what each self-reported energy level can carry, on the
#: 1-10 scale a plan's ``energy_floor`` uses. Below a plan's floor, *new*
#: milestone work is deferred; plan-related due recall stays eligible, and so
#: does struggle repair whose own demand (below) the energy can carry.
ENERGY_CAPABILITY: dict[EnergyLevel, int] = {"low": 3, "medium": 6, "high": 10}

EnergyDemand = Literal["low", "medium", "high"]

#: Design §5 (item 5, D-F) — the capability a struggle repair asks for, by the
#: demand class the struggle collector derives from its own row classes: a
#: ``struggling`` row seen within ``LIVE_STRUGGLE_DAYS`` is ``high`` (a live
#: struggle; hands-on repair on a low-energy day risks compounding it — rubric
#: row 3, the owner's one "no"); ``struggling`` older than that, or a row whose
#: only signal is a weak teach-back, is ``medium``; ``learning`` is ``low`` —
#: the gentle review "repair is cheaper than encoding" was always about.
#: Compared with ``ENERGY_CAPABILITY``: ``low`` (3) carries only low demand,
#: ``medium`` (6) carries every class.
ENERGY_DEMAND_CAPABILITY: dict[EnergyDemand, int] = {"high": 6, "medium": 4, "low": 0}
LIVE_STRUGGLE_DAYS = 14

#: Base score of the synthesised body-double candidate (design §5): below every
#: real candidate's *base* — due (100+), repair (70/82), cards (96+), continuity
#: (58), transfer (52), practice and a synthesised milestone (48). The day's
#: adjustments then apply to it as to any candidate, so at low energy it (30 +
#: 12 bias = 42) sits above a hands-on task that energy penalises (48 - 14 =
#: 34) and below every due and conversation candidate — the energy rule, not a
#: filter: nothing is removed from the ranking (council review 7, F2).
BODY_DOUBLE_BASE_SCORE = 30
BODY_DOUBLE_SOURCE = "body_double"

#: Rule 5 — the bias a plan-related candidate receives. Large enough to decide
#: a near-tie inside one urgency class (two due items a few days apart), small
#: enough that a clearly more-urgent unrelated candidate (a struggling repair,
#: an overdue review) still wins: a bias, never a filter.
PLAN_RELATED_BIAS = 12

#: Base score of a synthesised next-milestone candidate (rule 6) — new
#: learning, so below every due/repair class and beside practice (48); the
#: bias above then lifts it over unrelated practice and continuity.
MILESTONE_BASE_SCORE = 48
_MILESTONE_URGENCY_BONUS: dict[str, int] = {"overdue": 6, "soon": 3}

#: Sort rank of a plan's target urgency (rule 7).
_URGENCY_RANK: dict[str, int] = {"overdue": 0, "soon": 1, "later": 2, "undated": 3}

#: Source prefix of every synthesised milestone candidate: ``study_plan:<id>:<index>``.
PLAN_SOURCE_PREFIX = "study_plan:"


@dataclass(frozen=True)
class PlanRef:
    """One active plan an action advances; ``milestone_index`` when it names a milestone.

    An action can match several plans, so a recommendation carries a tuple of
    these (D-5: "retain every reference"). ``None`` means the action matched
    the plan on a topic or a finished milestone's concept — plan-related
    repair — rather than on the next milestone.
    """

    plan_id: str
    milestone_index: int | None = None

    def to_json_dict(self) -> dict:
        return {"plan_id": self.plan_id, "milestone_index": self.milestone_index}


@dataclass(frozen=True)
class ActivePlanSummary:
    """What a renderer needs to show one active plan beside the recommendation."""

    plan_id: str
    title: str
    target_urgency: str
    days_until_target: int | None
    energy_floor: int
    eligible: bool
    next_milestone: str
    next_milestone_index: int | None
    milestone_done: int
    milestone_total: int
    ready: bool

    def to_json_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DeferredMilestone:
    """A next milestone the current energy cannot carry (rule 3)."""

    plan_id: str
    plan_title: str
    milestone_index: int
    title: str
    energy_floor: int
    energy_capability: int
    reason: str

    def to_json_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DeferredRepair:
    """A struggle repair the current energy cannot carry (rule 3 extended, design §5).

    Its own type, not a :class:`DeferredMilestone`: that one has a mandatory
    ``milestone_index`` and its three renderers print ``milestone N`` — a repair
    folded into it would read "milestone None" (T5.1 amendment 2). ``plan_id``
    and ``plan_title`` are set when the struggle's concept, topic or course
    matches an active plan, else ``None``: the deferral does not depend on a
    plan — a live struggle is a live struggle whether or not a plan names it.
    """

    plan_id: str | None
    plan_title: str | None
    concept: str
    topic: str
    confidence: str
    energy_demand: EnergyDemand
    required_capability: int
    energy_capability: int
    reason: str

    def to_json_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompletionAction:
    """What to do about an active plan whose every milestone is checked (rule 9).

    ``action`` is the sentence every renderer prints. Since D-G (item 4) it is
    composed from the end assessment's completion review — the three counts
    on the plan's own concepts and the proposal they imply — read through the
    preview path, ``assess(AssessPlan(phase="end", record=False))``: no write,
    no checkpoint, no status change. ``proposal`` is ``None`` when that
    assessment failed outright — the counts are then *unknown*, not zero —
    ``action`` falls back to the plan-static sentence and ``NowPlan.warnings``
    says why — and also when it was **partial** (``partial=True``, council
    review 6 F1): a reader was down, the counts are what was read so far, and
    the sentence says the review could not be completed rather than "clean".
    No renderer reads a clean slate or outstanding work into a failure. The
    engine proposes; the architect asks; the learner decides;
    ``set_study_plan_status`` is the only door to ``complete``.
    """

    plan_id: str
    plan_title: str
    action: str
    due_reviews: int = 0
    struggles: int = 0
    unverified_milestones: int = 0
    proposal: Literal["extend", "close"] | None = None
    evidence: tuple[str, ...] = ()
    partial: bool = False

    def to_json_dict(self) -> dict:
        data = asdict(self)
        data["evidence"] = list(self.evidence)
        return data


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
    plan_refs: tuple[PlanRef, ...] = ()

    def to_json_dict(self) -> dict:
        data = asdict(self)
        refs = data.pop("plan_refs")
        if refs:
            data["plan_refs"] = list(refs)
        return data


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
    active_plans: tuple[ActivePlanSummary, ...] = ()
    energy_deferred: tuple[DeferredMilestone, ...] = ()
    energy_deferred_repairs: tuple[DeferredRepair, ...] = ()
    completion_actions: tuple[CompletionAction, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_json_dict(self) -> dict:
        data = {
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
        # Additive keys only when non-empty (D-5): a learner with no active
        # plan gets the pre-plan payload, byte for byte.
        if self.active_plans:
            data["active_plans"] = [item.to_json_dict() for item in self.active_plans]
        if self.energy_deferred:
            data["energy_deferred"] = [item.to_json_dict() for item in self.energy_deferred]
        if self.energy_deferred_repairs:
            data["energy_deferred_repairs"] = [
                item.to_json_dict() for item in self.energy_deferred_repairs
            ]
        if self.completion_actions:
            data["completion_actions"] = [item.to_json_dict() for item in self.completion_actions]
        if self.warnings:
            data["warnings"] = list(self.warnings)
        return data


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
    plan_refs: tuple[PlanRef, ...] = ()

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
            plan_refs=self.plan_refs,
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


_SHELL_SPECIAL = frozenset('"\\$`!')


def _shell_word(text: str) -> str:
    """One shell argument for a command the engine *offers* the learner to run.

    Plain text keeps the double-quoted form every existing command uses (the
    golden pins it byte for byte). Text carrying a character the shell reads
    inside double quotes — ``"``, ``\\``, ``$``, a backtick, ``!`` — is
    ``shlex.quote``d instead, so a plan title or concept like
    ``SQL $(rm -rf ~) Windows`` reaches ``studyloop`` as one literal argument
    (council review 7, F1: the old ``\\"`` replacement was presentation, not
    quoting, and a pasted command executed the substitution).
    """
    if _SHELL_SPECIAL.isdisjoint(text):
        return f'"{text}"'
    return shlex.quote(text)


def _evidence_command(
    action_type: ActionType,
    concept: str,
    topic: str,
    source: str,
    *,
    energy_demand: EnergyDemand | None = None,
) -> str:
    if action_type == "teachback":
        # The door is the teach-back form the demand class stands on (design §5,
        # amendment 1; rubric row 3b reading (c)): `low` was justified by the
        # protocol's micro teach-back — one sentence, two dimensions scored —
        # so that is what a low-demand door asks for. A weak-teach-back row
        # (`medium`) re-sits the structured review it fell short on.
        review_type = "micro" if energy_demand == "low" else "structured"
        return (
            f"studyloop teachback {_shell_word(concept)} -t {_shell_word(topic)} "
            f'--score "3,3,3,3,3" --type {review_type}'
        )
    if action_type == "hands-on" and source.endswith(".json"):
        return f'studyloop practice verify {_shell_word(source)} --task 1 --notes "what passed?"'
    return f"studyloop progress {_shell_word(concept)} -t {_shell_word(topic)} -c learning"


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


def _due_progress_candidates(time_minutes: int, *, now: datetime | None = None) -> list[_Candidate]:
    """Due spaced-repetition rows as candidates.

    ``now`` is the engine's one clock read (``build_now_plan``): the collector
    counts ``days_ago`` from it rather than from a second read inside
    ``history.progress``, so the day count on a screen — and the score built
    from it — cannot disagree with the rest of the plan (receipt
    ``now-rubric-2026-09-16``, row 3c (e): a frozen engine printed a drifting
    "last seen 8 day(s) ago" for a struggle planted three days back).
    """
    from studyloop.history import spaced_repetition_due

    candidates: list[_Candidate] = []
    try:
        due_items = spaced_repetition_due(TOPIC_KEYWORDS, now=now)
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
                    # A `struggling` row is always due ("Guided repair + tiny
                    # practice") and its due item is `hands-on`: it is the
                    # struggle collector's repair, collected a second time from
                    # the same observations row. It carries the repair's demand
                    # so rule 3 defers both copies together (rubric row 3b
                    # reading (f), 2026-09-20); due recall and teach-back rows
                    # carry none and are never deferred.
                    **(
                        {
                            "energy_demand": _energy_demand(
                                confidence, item.get("last_studied"), datetime.now(UTC).date()
                            )
                        }
                        if confidence == "struggling"
                        else {}
                    ),
                },
            )
        )
    return candidates


def _struggle_candidates(time_minutes: int) -> list[_Candidate]:
    conn = _connect_progress_db()
    if not conn:
        return []
    try:
        from studyloop.history import observations

        rows = [
            row
            for row in observations.rows(conn)
            if row["confidence"] in ("struggling", "learning")
            or (row.get("last_teachback_score") is not None and row["last_teachback_score"] < 14)
        ]
        # A legacy ``study_progress`` row can carry a NULL ``last_seen``; it sorts
        # as the oldest rather than raising and losing every struggle candidate
        # (surfaced by review 7's boundary pin; the demand derivation then reads
        # it as live, the cautious side).
        rows.sort(key=lambda row: row.get("last_seen") or "", reverse=True)
        rows.sort(
            key=lambda row: (
                {"struggling": 0, "learning": 1}.get(row["confidence"], 2),
                row.get("last_teachback_score")
                if row.get("last_teachback_score") is not None
                else 99,
            )
        )
        rows = rows[:12]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    candidates: list[_Candidate] = []
    today = datetime.now(UTC).date()
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
        # Design §5: derived once, here, from the collector's own classes; the
        # deferral, the door and every renderer read this one value.
        demand = _energy_demand(
            confidence, row.get("last_seen") if "last_seen" in row_keys else None, today
        )
        # A `learning` row is the gentle review that stays eligible at low
        # energy (design §5), not a repair: on a low-energy screen "repair now"
        # would contradict the deferred-repair line beside it (rubric row 3b
        # reading (c)). Its sentence names the one-sentence door it opens.
        reason = (
            "Recorded as learning; a gentle review keeps it fresh — one sentence, in your own words"
            if confidence == "learning"
            else f"Recorded as {confidence}; repair now while the signal is fresh"
        )
        candidates.append(
            _Candidate(
                concept=concept,
                topic=topic,
                course=row["source_course"] if "source_course" in row_keys else None,
                reason=(
                    reason
                    + (f"; last teach-back score {teachback_score}/20" if teachback_score else "")
                ),
                action_type=action,
                estimated_minutes=_estimate_minutes(action, time_minutes, 20),
                source=str(source),
                evidence_command=_evidence_command(
                    action, concept, topic, str(source), energy_demand=demand
                ),
                score=score,
                metadata={
                    "confidence": confidence,
                    "last_teachback_score": teachback_score,
                    "session_count": row["session_count"],
                    "energy_demand": demand,
                },
            )
        )
    return candidates


def _energy_demand(confidence: str | None, last_seen: object, today: date) -> EnergyDemand:
    """The capability class a repair asks for (design §5, T5.1 amendment 1).

    ``struggling`` seen within :data:`LIVE_STRUGGLE_DAYS` is a live struggle —
    ``high``; a ``struggling`` row older than that, or one the collector kept
    only for its weak teach-back, is ``medium``; ``learning`` is ``low``. An
    unreadable ``last_seen`` on a ``struggling`` row is read as live: the
    cautious side is the one the finding asks for.
    """
    if confidence == "learning":
        return "low"
    if confidence != "struggling":
        return "medium"
    seen = _days_since(last_seen, today)
    if seen is None or seen <= LIVE_STRUGGLE_DAYS:
        return "high"
    return "medium"


def _days_since(stamp: object, today: date) -> int | None:
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        return (today - datetime.fromisoformat(stamp).date()).days
    except ValueError:
        return None


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
                metadata={
                    "dependency": link.get("dependency"),
                    "relationship_status": link.get("relationship_status"),
                    "relationship_observation_id": link.get("provenance", {}).get("observation_id"),
                    "relationship_binding_sha256": link.get("provenance", {}).get("binding_sha256"),
                    "relationship_source_kind": link.get("provenance", {}).get("kind"),
                    "semantic_validation": link.get("provenance", {}).get("semantic_validation"),
                },
            )
        )
    return candidates


def _starter_candidate(time_minutes: int, *, after_deferral: bool = False) -> _Candidate:
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
    # "No learning evidence" would be false when evidence exists and today's
    # energy deferred all of it (design §5); say what happened instead. The
    # golden world has nothing to defer, so its sentence is unchanged.
    reason = (
        "Today's energy deferred the repair work it cannot carry; "
        "start with one small retrieval signal instead"
        if after_deferral
        else "No learning evidence found yet; start by creating one small retrieval signal"
    )
    return _Candidate(
        concept="one tiny recall loop",
        topic=topic,
        course=topic,
        reason=reason,
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


def _focus_topics() -> list[str]:
    """Current focus topics (attention filter), best-effort."""
    try:
        from studyloop.focus import get_focus

        return get_focus().topics
    except Exception:
        return []


def _score_candidates(
    candidates: list[_Candidate],
    *,
    energy: EnergyLevel,
    modality: Modality,
    interleave: InterleaveMode,
    plan_keys: frozenset[str] = frozenset(),
) -> list[_Candidate]:
    last_topic = _last_focus_topic(candidates)
    focus_topics = _focus_topics()
    scored: list[_Candidate] = []
    for candidate in candidates:
        score = candidate.score
        if focus_topics:
            from studyloop.focus import matches_focus

            if matches_focus(candidate.topic, focus_topics) or (
                candidate.course and matches_focus(candidate.course, focus_topics)
            ):
                score += 22
            else:
                # Out-of-focus work still surfaces when nothing in-focus is
                # due, but focus wins ties decisively.
                score -= 12
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
        # Design §3 rule 5: plan-related beats unrelated inside one urgency
        # class; a globally more-urgent unrelated candidate still wins.
        if candidate.plan_refs or (plan_keys and _candidate_keys(candidate) & plan_keys):
            score += PLAN_RELATED_BIAS

        scored.append(dataclasses.replace(candidate, score=score))
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


# ---------------------------------------------------------------------------
# Active study plans (design §3, D-5)
# ---------------------------------------------------------------------------


def _match_key(text: str) -> str:
    """The seam's normalisation — casefold, punctuation to spaces — applied here too.

    Imported lazily like every other collaborator in this module: the
    planning package reaches back into ``studyloop.learning`` for its concept
    filter, so a module-level import would be a cycle.
    """
    from studyloop.planning.views import normalise_match_key

    return normalise_match_key(text)


def _candidate_keys(candidate: _Candidate) -> frozenset[str]:
    """The keys on which a candidate can equal a plan: its concept, topic and course."""
    keys = {_match_key(candidate.concept), _match_key(candidate.topic)}
    if candidate.course:
        keys.add(_match_key(candidate.course))
    keys.discard("")
    return frozenset(keys)


def _load_guidance(today: date) -> ActiveGuidance | None:
    """One plan-static read through the seam; ``None`` when plans cannot be read at all.

    The recommendation must never fail because of the plans (spec rule 1), so
    every exception degrades to the one learner-facing warning the caller
    emits — but it is logged with its traceback first, so a programming error
    in the seam cannot hide behind "could not be read" (council review 3, F9).
    """
    try:
        from studyloop.planning.application import PlanApplication

        return PlanApplication().get_active_guidance(today=today)
    except Exception:
        logger.warning("study plans could not be read; recommending without them", exc_info=True)
        return None


def _review_completion(plan_id: str) -> tuple[CompletionReview | None, tuple[str, ...]]:
    """The end assessment's completion review for one fully-checked plan (rule 9, D-G).

    The preview path — ``AssessPlan(phase="end", record=False)`` — so the
    document, its status and the checkpoint log are untouched; exactly one
    call per fully-checked plan per ``build_now_plan``. A failure degrades to
    ``None`` plus one learner-facing warning naming the plan (the
    recommendation never fails on a plan), logged with its traceback first so
    a programming error cannot hide behind it, as :func:`_load_guidance` does.
    The evaluation's own data-gap warnings travel back prefixed with the plan
    id: a count read while one of its readers was unavailable is partial, and
    the learner should know that rather than read it as zero.
    """
    try:
        from studyloop.planning import AssessPlan, CompletionReview
        from studyloop.planning.application import PlanApplication

        result = PlanApplication().assess(AssessPlan(plan_id=plan_id, phase="end", record=False))
    except Exception as exc:
        logger.warning(
            "active plan %r could not be assessed for completion", plan_id, exc_info=True
        )
        return None, (
            f"active plan {plan_id!r} could not be assessed for completion ({exc}); "
            "shown without its counts",
        )
    gaps = tuple(f"active plan {plan_id!r}: {warning}" for warning in result.warnings)
    return CompletionReview.from_evaluation(result.evaluation), gaps


def _completion_sentence(plan_id: str, title: str, review: CompletionReview) -> str:
    """The completion action's sentence, composed from the review's proposal (D-G).

    Names the proposal and the three counts, then the one door to acting on
    it — ``studyloop plan close <id>``, where the architect walks the evidence
    with the learner. Spoken by the recap as well as printed, so no markup.
    """

    def plural(count: int, noun: str) -> str:
        return f"{count} {noun}{'' if count == 1 else 's'}"

    counts = (
        f"{plural(review.due_reviews, 'due review')}, {plural(review.struggles, 'struggle')} and "
        f"{plural(review.unverified_milestones, 'unverified milestone')} on its concepts"
    )
    if review.partial:
        return (
            f"Every milestone of {title!r} is checked off, but the closing review is partial — "
            f"one of its readers was unavailable, so it could not propose; read so far: {counts}. "
            f"Walk what was read with the architect: studyloop plan close {plan_id}."
        )
    if review.proposal == "close":
        return (
            f"Every milestone of {title!r} is checked off and the closing review is clean — "
            "it proposes closing the plan. Close it with the architect when you agree: "
            f"studyloop plan close {plan_id}."
        )
    return (
        f"Every milestone of {title!r} is checked off, and the closing review proposes "
        f"extending the plan — {counts}. Walk the evidence with the architect: "
        f"studyloop plan close {plan_id}."
    )


def _completion_action(
    summary: PlanSummary, fallback: str, review: CompletionReview | None
) -> CompletionAction:
    """Rule 9's entry: the reviewed action, or the plan-static sentence when unassessed."""
    if review is None:
        return CompletionAction(plan_id=summary.plan_id, plan_title=summary.title, action=fallback)
    return CompletionAction(
        plan_id=summary.plan_id,
        plan_title=summary.title,
        action=_completion_sentence(summary.plan_id, summary.title, review),
        due_reviews=review.due_reviews,
        struggles=review.struggles,
        unverified_milestones=review.unverified_milestones,
        proposal=review.proposal,
        evidence=review.evidence,
        partial=review.partial,
    )


def _milestone_concept_keys(plan: ActivePlanGuidance) -> frozenset[str]:
    if plan.next_milestone is None:
        return frozenset()
    return frozenset(_match_key(concept) for concept in plan.next_milestone.concepts) - {""}


def _order_plans(plans: tuple[ActivePlanGuidance, ...]) -> list[ActivePlanGuidance]:
    """Rule 7 order: target urgency, then most recent update, then plan id.

    Three stable passes, least significant first, because ``updated`` is a
    string that cannot be negated inside one key.
    """
    ordered = sorted(plans, key=lambda item: item.plan.plan_id)
    ordered.sort(key=lambda item: item.plan.updated, reverse=True)
    ordered.sort(key=lambda item: _URGENCY_RANK.get(item.target_urgency, len(_URGENCY_RANK)))
    return ordered


@dataclass(frozen=True)
class _PlanContext:
    """Everything one ``build_now_plan`` call derived from the active plans.

    ``matchable`` are the plans that may bias and be referenced by a
    candidate: every active plan except a fully-checked one, whose work is
    done and which is represented by a completion action instead (rule 9) —
    the one entry built from a second seam read, the end assessment's preview
    (:func:`_review_completion`), so it can propose ``extend`` or ``close``
    from evidence rather than either way (D-G).
    ``synthesise`` are the plans whose next milestone may become a
    candidate when nothing collected represents it (rule 6): ready, with a
    next milestone, and within the energy capability (rule 3).
    """

    matchable: tuple[ActivePlanGuidance, ...]
    synthesise: tuple[ActivePlanGuidance, ...]
    match_keys: frozenset[str]
    summaries: tuple[ActivePlanSummary, ...]
    deferred: tuple[DeferredMilestone, ...]
    completions: tuple[CompletionAction, ...]
    warnings: tuple[str, ...]

    @classmethod
    def empty(cls, *warnings: str) -> _PlanContext:
        return cls(
            matchable=(),
            synthesise=(),
            match_keys=frozenset(),
            summaries=(),
            deferred=(),
            completions=(),
            warnings=tuple(warnings),
        )

    @classmethod
    def build(cls, guidance: ActiveGuidance | None, *, energy: EnergyLevel) -> _PlanContext:
        if guidance is None:
            return cls.empty("study plans could not be read; recommending without them")
        if not guidance.plans:
            return cls.empty(*guidance.warnings)

        capability = ENERGY_CAPABILITY[energy]
        matchable: list[ActivePlanGuidance] = []
        synthesise: list[ActivePlanGuidance] = []
        keys: set[str] = set()
        summaries: list[ActivePlanSummary] = []
        deferred: list[DeferredMilestone] = []
        completions: list[CompletionAction] = []
        warnings: list[str] = list(guidance.warnings)

        for plan in _order_plans(guidance.plans):
            summary = plan.plan
            warnings.extend(plan.warnings)
            next_milestone = plan.next_milestone
            ready = plan.readiness.ready
            if not ready:
                blockers = "; ".join(plan.readiness.blockers) or "not ready"
                warnings.append(
                    f"active plan {summary.plan_id!r} is not ready ({blockers}) — "
                    "pause or repair it before recording milestones on it"
                )

            eligible = False
            if plan.completion_action:
                review, notes = _review_completion(summary.plan_id)
                warnings.extend(notes)
                completions.append(_completion_action(summary, plan.completion_action, review))
            else:
                matchable.append(plan)
                keys.update(plan.match_keys)
                if next_milestone is not None and ready:
                    if capability >= plan.energy_floor:
                        eligible = True
                        synthesise.append(plan)
                    else:
                        deferred.append(
                            DeferredMilestone(
                                plan_id=summary.plan_id,
                                plan_title=summary.title,
                                milestone_index=next_milestone.index,
                                title=next_milestone.title,
                                energy_floor=plan.energy_floor,
                                energy_capability=capability,
                                reason=(
                                    f"{energy} energy carries {capability}/10; "
                                    f"{summary.title!r} asks for at least "
                                    f"{plan.energy_floor}/10 — due recall and gentle "
                                    "review stay available"
                                ),
                            )
                        )

            summaries.append(
                ActivePlanSummary(
                    plan_id=summary.plan_id,
                    title=summary.title,
                    target_urgency=plan.target_urgency,
                    days_until_target=summary.days_until_target,
                    energy_floor=plan.energy_floor,
                    eligible=eligible,
                    next_milestone=next_milestone.title if next_milestone else "",
                    next_milestone_index=next_milestone.index if next_milestone else None,
                    milestone_done=summary.milestone_done,
                    milestone_total=summary.milestone_total,
                    ready=ready,
                )
            )

        return cls(
            matchable=tuple(matchable),
            synthesise=tuple(synthesise),
            match_keys=frozenset(keys),
            summaries=tuple(summaries),
            deferred=tuple(deferred),
            completions=tuple(completions),
            warnings=tuple(warnings),
        )

    def milestone_candidates(
        self, candidates: list[_Candidate], time_minutes: int
    ) -> list[_Candidate]:
        """Rule 6: one candidate per eligible plan whose next milestone nothing represents."""
        present = [_candidate_keys(candidate) for candidate in candidates]
        synthesised: list[_Candidate] = []
        for plan in self.synthesise:
            milestone = plan.next_milestone
            if milestone is None:  # pragma: no cover — ``synthesise`` only holds plans with one
                continue
            concept_keys = _milestone_concept_keys(plan)
            if concept_keys and any(keys & concept_keys for keys in present):
                continue
            synthesised.append(_milestone_candidate(plan, milestone, time_minutes))
        return synthesised

    def first_match(self, candidate: _Candidate) -> ActivePlanGuidance | None:
        """The first matchable plan (plan order) this candidate's keys equal, if any."""
        keys = _candidate_keys(candidate)
        for plan in self.matchable:
            if keys & frozenset(plan.match_keys):
                return plan
        return None

    def is_plan_related(self, candidate: _Candidate) -> bool:
        """Rule 5's test, before scoring: a ref already attached, or a key match."""
        return bool(candidate.plan_refs) or self.first_match(candidate) is not None

    def attach_refs(self, candidate: _Candidate) -> _Candidate:
        """Rule 7: every matching plan, most specific milestone per plan, in plan order.

        The next milestone is named only for an *eligible* plan — ready and
        within the energy capability, i.e. one in ``synthesise``. For a plan
        whose milestone is energy-deferred (rule 3) or whose document is
        active-but-unready (review-2 G1: the seam would refuse to tick it), a
        match on that milestone's concept is plan-related repair, ``None`` —
        so one payload never says "advances milestone 2" beside "milestone 2
        is deferred" or beside the blockers (council review 3, F1).
        """
        keys = _candidate_keys(candidate)
        eligible = {plan.plan.plan_id for plan in self.synthesise}
        refs: dict[str, int | None] = {
            ref.plan_id: ref.milestone_index for ref in candidate.plan_refs
        }
        for plan in self.matchable:
            plan_id = plan.plan.plan_id
            if not keys & frozenset(plan.match_keys):
                continue
            index = (
                plan.next_milestone.index
                if plan_id in eligible
                and plan.next_milestone is not None
                and keys & _milestone_concept_keys(plan)
                else None
            )
            if refs.get(plan_id) is None:
                refs[plan_id] = index
        if not refs:
            return candidate
        ordered = tuple(
            PlanRef(plan.plan.plan_id, refs[plan.plan.plan_id])
            for plan in self.matchable
            if plan.plan.plan_id in refs
        )
        return dataclasses.replace(candidate, plan_refs=ordered)


def _milestone_candidate(
    plan: ActivePlanGuidance, milestone: MilestoneView, time_minutes: int
) -> _Candidate:
    """The synthesised candidate for a plan's next milestone (rule 6)."""
    summary = plan.plan
    concept = next((item.strip() for item in milestone.concepts if item.strip()), milestone.title)
    topic = summary.topics[0] if summary.topics else "study"
    source = f"{PLAN_SOURCE_PREFIX}{summary.plan_id}:{milestone.index}"
    days = summary.days_until_target
    if plan.target_urgency == "overdue":
        target_note = "; the plan's target date has passed"
    elif days == 0:
        target_note = "; the plan's target date is today"
    elif days is not None:
        target_note = f"; target date in {days} day(s)"
    else:
        target_note = ""
    reason = (
        f"Next milestone {milestone.index + 1}/{summary.milestone_total} of plan "
        f"{summary.title!r}: {milestone.title}{target_note}"
    )
    return _Candidate(
        concept=concept,
        topic=topic,
        course=None,
        reason=reason,
        action_type="conversation",
        estimated_minutes=_estimate_minutes("conversation", time_minutes, 20),
        source=source,
        evidence_command=_evidence_command("conversation", concept, topic, source),
        score=MILESTONE_BASE_SCORE + _MILESTONE_URGENCY_BONUS.get(plan.target_urgency, 0),
        metadata={
            "plan_id": summary.plan_id,
            "milestone_index": milestone.index,
            "milestone": milestone.title,
            "target_urgency": plan.target_urgency,
            "energy_floor": plan.energy_floor,
        },
        plan_refs=(PlanRef(summary.plan_id, milestone.index),),
    )


def _defer_repairs(
    candidates: list[_Candidate], *, energy: EnergyLevel, plans: _PlanContext
) -> tuple[list[_Candidate], tuple[DeferredRepair, ...]]:
    """Rule 3 extended (design §5): repair above its own energy demand is deferred like new work.

    Only a candidate carrying ``energy_demand`` is judged: the struggle
    collector's repairs, and the due collector's copy of a ``struggling`` row —
    the same repair, collected twice, named once. Due recall and teach-back rows
    carry no demand and are never deferred whatever their confidence says; a
    ``learning`` repair (``low`` demand) is always carried. Plan-independent:
    the entry names the plan when one matches, else ``None``.
    """
    capability = ENERGY_CAPABILITY[energy]
    kept: list[_Candidate] = []
    deferred: list[DeferredRepair] = []
    named: set[tuple[str, str]] = set()
    for candidate in candidates:
        demand = candidate.metadata.get("energy_demand")
        if demand not in ENERGY_DEMAND_CAPABILITY:
            kept.append(candidate)
            continue
        required = ENERGY_DEMAND_CAPABILITY[demand]
        if capability >= required:
            kept.append(candidate)
            continue
        # The same struggling row reaches here twice — the struggle collector's
        # repair and the due collector's "Guided repair + tiny practice" copy.
        # Both are deferred; the learner reads one line for the concept.
        key = (candidate.topic.lower(), candidate.concept.lower())
        if key in named:
            continue
        named.add(key)
        plan = plans.first_match(candidate)
        confidence = str(candidate.metadata.get("confidence") or "struggling")
        if demand == "high":
            what = "a live struggle"
        elif confidence == "struggling":
            what = "an older struggle"
        else:
            what = "a weak teach-back"
        deferred.append(
            DeferredRepair(
                plan_id=plan.plan.plan_id if plan is not None else None,
                plan_title=plan.plan.title if plan is not None else None,
                concept=candidate.concept,
                topic=candidate.topic,
                confidence=confidence,
                energy_demand=demand,
                required_capability=required,
                energy_capability=capability,
                reason=(
                    f"{energy} energy carries {capability}/10; repairing "
                    f"{candidate.concept!r} ({what}) asks for at least {required}/10 — "
                    "deferred like new work; due recall and gentle review stay available"
                ),
            )
        )
    return kept, tuple(deferred)


def _resolve_lesson(concepts: Sequence[str]) -> tuple[str, str, str, str] | None:
    """The indexed lesson the first move should name, or ``None``.

    Returns ``(lesson_id, title, course, concept)`` — the concept being the one
    the index matched, not the first one asked, so the sentence can say what the
    match rests on.
    Asks the explorer's own FTS — the path MCP ``search_lessons`` takes — one
    short query per concept of the deferred milestone, in order, stopping at the
    first hit. The concepts and nothing else: rubric 3c (c), measured on the
    owner's real vault 2026-09-21, showed that falling back to the milestone's
    title or the plan's topics always names a lesson — the wrong one ("Frames"
    hit a PySpark data-frames lab; "sql" hit an SQL bootcamp introduction). A
    deliberate-but-wrong lesson on a low-energy day is worse than an honest
    "nothing matches yet", so the wider steps are not taken.

    ``course`` is the hit's own ``course_id`` humanised exactly as the explorer's
    course list shows it (``_humanise`` of the course directory) — the evidence
    the sentence states beside the lesson (rubric 3c (d2)), so a lexical match
    into the wrong course reads as one at a glance. A hit that lacks its course
    or its title is skipped, never named: a lesson is named with its evidence or
    not at all.

    ``None`` is a *searched* miss. An index that cannot be consulted (no content
    base, a locked db) raises instead of answering ``None``, so the caller can
    tell the two apart and never claims "no indexed lesson mentions X" about an
    index it did not read. Imported lazily: the engine does not import the web
    layer at module load. Tests plant a lesson by replacing this seam, or the
    explorer's search function beneath it.
    """
    from studyloop.settings import load_settings
    from studyloop.web.routes import explorer

    base = load_settings().content.base_path.expanduser()
    with explorer._fts_lock:
        for concept in concepts:
            q = concept.strip()
            if len(q) < _MIN_QUERY_CHARS:
                # The explorer refuses shorter queries. The sentence builder filters
                # these out BEFORE asking (review 8, F3); this guard only keeps a
                # direct caller from sending a query the index would reject.
                continue
            # Council review 8: a handful of rows, not one — "a hit lacking its
            # course or its title is skipped" means the ROW is skipped and the
            # first well-formed hit beneath it is named, not the whole concept.
            rows = explorer._run_fts_search(explorer._fts_db_path(), base, q, _FTS_ROWS_PER_CONCEPT)
            for row in rows:
                lesson_id = str(row.get("lesson_id") or "").strip()
                title = str(row.get("title") or "").strip()
                course_id = str(row.get("course_id") or "").strip()
                course_dir = course_id.rsplit("/", 1)[-1] if course_id else ""
                if lesson_id and title and course_dir:
                    return lesson_id, title, explorer._humanise(course_dir), q
    return None


#: Rows fetched per concept by the seam: enough to step past a malformed top row,
#: few enough that one ``now`` never scans a result page.
_FTS_ROWS_PER_CONCEPT = 3


def _first_move(
    plan: ActivePlanGuidance, plans: _PlanContext
) -> tuple[str, str | None, str | None] | None:
    """Issue #30: one tiny, passive first move on the deferred material.

    The owner's note beside rubric row 3b (a): a sit-with session must not be a
    blank page — "open the Frames lesson and read it, nothing more". Derived
    from stored facts only: the plan's deferred next milestone (a body double
    is synthesised only when every matchable ready plan's next milestone is
    deferred — an eligible one would have been synthesised as a plan-related
    candidate and suppressed it — so the milestone is always there to draw on)
    and, when the content index resolves the milestone's own concepts, the lesson
    the learner can actually open (rubric 3c (b): a deliberate lesson whenever the
    vault holds one). Reading only, at the capability the day carries: never an
    exercise, never a Socratic round. Returns ``(sentence, lesson_id, lesson_title)``.

    A named lesson states its EVIDENCE (rubric 3c (d2), owner 2026-09-21 — "I
    would likely still open it in case there was some link being enforced"): a
    named lesson carries implied authority, so a wrong one is followed, not merely
    doubted. The sentence therefore names the course the lesson belongs to and
    the concept the match rests on — ``Open “<lesson>” from <Course> — the match
    is the word “<concept>” — and read for ten minutes, nothing more.`` — so a
    lexical match into the wrong course (a Python plan's "decorators" resolving
    to a TypeScript lesson) is judgeable from the sentence, not by opening it.

    When no lesson is named, the sentence names the milestone AND says why
    (rubric 3c (c)), so it carries information instead of vagueness and points at
    the fix — a lesson, or a concept name on the milestone, not a better search:

    * searched, nothing matched — ``… — no indexed lesson mentions “<concept>” yet.``
    * the milestone names no concept — ``… — this milestone names no concept to
      look up yet.`` (the index is not asked; asking it with the title is the
      rejected chain)
    * the index could not be read — the plain sentence, with no claim about an
      index that was never consulted; a failed refinement is not a warning.

    ``None`` only when the plan has no deferred milestone, which the invariant
    above rules out.
    """
    summary = plan.plan
    deferred = next((d for d in plans.deferred if d.plan_id == summary.plan_id), None)
    if deferred is None:
        return None
    concepts = _clean_concepts(plan.next_milestone.concepts if plan.next_milestone else ())
    return _first_move_sentence(concepts, material=deferred.title, tail="nothing more")


def _clean_concepts(concepts: Sequence[str]) -> tuple[str, ...]:
    """Stripped, de-duplicated, in order — what the resolver is asked."""
    cleaned: list[str] = []
    for concept in concepts:
        c = concept.strip()
        if c and c not in cleaned:
            cleaned.append(c)
    return tuple(cleaned)


def _first_move_sentence(
    concepts: Sequence[str], *, material: str, tail: str
) -> tuple[str, str | None, str | None]:
    """One sentence, two moves: the sit-with's (``tail="nothing more"``) and the
    warm-up's (``tail="then start …"``, rubric 3c (e1)). Same evidence rule for a
    named lesson, same three honest shapes when none is named; only what the
    move is FOR differs, and the tail says it. Returns ``(sentence, lesson_id,
    lesson_title)``; the lead-in ("First move, if you want one:") belongs to the
    renderers (rubric 3c (d1)), so the sentence carries none.
    """
    stem = f"Open your {material} material and read for ten minutes, {tail}"
    if not concepts:
        return f"{stem} — this milestone names no concept to look up yet.", None, None
    # Council review 8, astra F3: the explorer's search refuses queries under two
    # characters, so a one-character concept ("C", "R") is UNSEARCHABLE — never a
    # searched miss. It is named as too short; only searched concepts are named in
    # a miss, so "no indexed lesson mentions X" is said of searches that ran.
    searchable = tuple(c for c in concepts if len(c) >= _MIN_QUERY_CHARS)
    too_short = tuple(c for c in concepts if len(c) < _MIN_QUERY_CHARS)
    if not searchable:
        named = " or ".join(f"“{c}”" for c in too_short)
        verb = "is" if len(too_short) == 1 else "are"
        return f"{stem} — {named} {verb} too short for the index to look up.", None, None
    try:
        hit = _resolve_lesson(searchable)
    except Exception:
        logger.debug("first move: lesson index unavailable, naming the material", exc_info=True)
        return f"{stem}.", None, None
    if hit is not None:
        lesson_id, title, course, matched = hit
        kind = "phrase" if " " in matched.strip() else "word"
        return (
            f"Open “{title}” from {course} — the match is the {kind} “{matched}” — "
            f"and read for ten minutes, {tail}.",
            lesson_id,
            title,
        )
    named = " or ".join(f"“{c}”" for c in searchable)
    return f"{stem} — no indexed lesson mentions {named} yet.", None, None


#: The explorer's FTS search refuses shorter queries (``search_lessons``: "min 2
#: characters"); the seam and the sentence builder agree on this one number.
_MIN_QUERY_CHARS = 2


def _first_move_metadata(
    sentence: str | None, lesson_id: str | None, lesson_title: str | None
) -> dict[str, str | int | float | None]:
    """The move's carriage: ``first_move`` and, when a lesson resolved, its id and
    title beside it so a renderer opens it in StudyLoop's own frame without parsing
    the sentence. Empty when there is no move, so a payload adds nothing."""
    if not sentence:
        return {}
    carried: dict[str, str | int | float | None] = {"first_move": sentence}
    if lesson_id:
        carried["first_move_lesson_id"] = lesson_id
        if lesson_title:
            carried["first_move_lesson_title"] = lesson_title
    return carried


#: The actions a warm-up ramps into (rubric 3c (e1)). Never ``recall``: reading the
#: lesson before a retrieval test defeats the test (row 3b (b): familiar recall
#: leads as it is). Never ``visual``/``audio``: those are already passive.
_WARM_UP_ACTIONS: frozenset[str] = frozenset({"hands-on", "conversation", "teachback"})


def _warm_up(primary: _Candidate, plans: _PlanContext) -> tuple[str, str | None, str | None] | None:
    """Rubric 3c (e1), owner 2026-09-21 ("no, offer the move at medium energy too",
    taking the steer): a plan-related ACTIVE primary carries one first move on ITS
    OWN material, worded as a ramp into the task.

    The low-energy move is the sit-with's whole action and ends "nothing more";
    printed beneath a task the day CAN carry, that sentence would tell the learner
    two contradictory things and the passive one is the easier to take (the 3b (d)
    mistake). The warm-up ends "then start …" and lowers the first step of the
    primary instead of competing with it.

    Scope: the primary only (one move); never the body double (it has its own);
    never a candidate off every plan (so the no-plan golden is byte-identical);
    never recall, visual or audio (:data:`_WARM_UP_ACTIONS`). Material, in order
    of what the primary IS: a demand-marked row (``energy_demand`` in its
    metadata — every struggle row carries one) asks the resolver its own concept
    and ends "then start the repair", or "then start the review" for a
    ``learning`` row, whose own reason names a gentle review (row 3b (c)); a
    plan milestone (a ref naming the eligible
    next milestone) asks that milestone's own concepts and ends "then start the
    milestone"; any other plan-related active item asks its concept and ends
    "then start on “<concept>”". Same evidence sentence, same honest no-lesson
    shapes as the sit-with move (:func:`_first_move_sentence`).
    """
    if primary.source == BODY_DOUBLE_SOURCE or not primary.plan_refs:
        return None
    if primary.action_type not in _WARM_UP_ACTIONS:
        return None
    concept = primary.concept.strip()
    if concept and "energy_demand" in primary.metadata:
        # Every struggle row carries energy_demand; only a ``struggling`` one is a
        # repair. A ``learning`` row is the gentle review its own reason names
        # (row 3b (c)), so the ramp ends where that reason does, not at a repair.
        what = "review" if primary.metadata.get("confidence") == "learning" else "repair"
        return _first_move_sentence(
            (concept,), material=f"“{concept}”", tail=f"then start the {what}"
        )
    ref = next((r for r in primary.plan_refs if r.milestone_index is not None), None)
    if ref is not None:
        plan = next((p for p in plans.matchable if p.plan.plan_id == ref.plan_id), None)
        milestone = plan.next_milestone if plan is not None else None
        if milestone is not None and milestone.index == ref.milestone_index:
            return _first_move_sentence(
                _clean_concepts(milestone.concepts),
                material=milestone.title,
                tail="then start the milestone",
            )
    if not concept:
        # Council review 8 (grok 🔵): a candidate is plan-related by its concept,
        # its topic OR its course, so a blank-concept active item can get here.
        # The repair and generic tails name and search the concept; with none
        # there is nothing to name and nothing to search — no warm-up.
        return None
    return _first_move_sentence(
        (concept,), material=f"“{concept}”", tail=f"then start on “{concept}”"
    )


def _body_double_candidate(
    plans: _PlanContext,
    candidates: list[_Candidate],
    deferred_repairs: tuple[DeferredRepair, ...],
    *,
    energy: EnergyLevel,
    time_minutes: int,
) -> _Candidate | None:
    """Design §5's floor: nothing plan-related fits and an active plan exists → sit with it.

    One ``source="body_double"`` conversation candidate, base below every real
    candidate's base and then scored like any other (a proposal, not a filter —
    see ``BODY_DOUBLE_BASE_SCORE``), ``plan_refs`` ``(plan, None)`` for
    every matchable plan, reason naming what it stands in for, and the co-study
    session door as its command (T5.1 amendment 3): ``_evidence_command`` has
    no branch for it and would answer with a progress *write*, not a door.
    """
    if not plans.matchable or any(plans.is_plan_related(c) for c in candidates):
        return None
    # An active-but-unready plan is matched but never synthesised (spec rule 8);
    # the body double is a synthesis, so only ready plans are sat with. The
    # warning beside it already says "pause or repair".
    ready_plans = [plan for plan in plans.matchable if plan.readiness.ready]
    named = [plan.plan for plan in ready_plans]
    if not named:
        return None
    first = named[0]
    first_move, first_move_lesson_id, first_move_lesson_title = _first_move(
        ready_plans[0], plans
    ) or (None, None, None)
    titles = " and ".join(plan.title for plan in named)
    items = [
        f"milestone {d.milestone_index + 1} “{d.title}” of {d.plan_title}" for d in plans.deferred
    ] + [f"repair of “{d.concept}”" for d in deferred_repairs]
    deferred_note = f" — deferred: {'; '.join(items)}" if items else ""
    # The framework's naming rule: never name a struggle without an adjacent
    # strength — so lead with the progress the plan document records, and only
    # when there is some (a strength is never invented).
    done = [plan for plan in named if plan.milestone_done]
    progress_note = (
        " ".join(
            f"{plan.milestone_done} of {plan.milestone_total} milestones of {plan.title} done."
            for plan in done
        )
        + " "
        if done
        else ""
    )
    topic = first.topics[0] if first.topics else "study"
    return _Candidate(
        concept=f"Sit with {first.title}" if len(named) == 1 else "Sit with your plans",
        topic=topic,
        course=None,
        reason=(
            f"{progress_note}Nothing plan-related fits {energy} energy today{deferred_note}. "
            f"Sit with {titles} instead: a body-double session — you drive; the companion "
            "stays quiet unless you ask."
        ),
        action_type="conversation",
        estimated_minutes=_estimate_minutes("conversation", time_minutes, 25),
        source=BODY_DOUBLE_SOURCE,
        evidence_command=f"studyloop study {_shell_word(first.title)} --mode co-study",
        score=BODY_DOUBLE_BASE_SCORE,
        metadata={
            "plan_id": first.plan_id,
            "deferred_milestones": len(plans.deferred),
            "deferred_repairs": len(deferred_repairs),
            # Issue #30: additive — the no-plan golden never sees it. The move lives in
            # metadata and nowhere else (rubric 3c (d)): the reason explains the
            # recommendation, the move is an action beside the door, and every
            # renderer (CLI, Today card, MCP get_next_action) reads this field — so
            # the sentence appears once on a 3/10 screen instead of closing the
            # reason and then repeating as its own line. Rubric 3c (b): the lesson
            # the move names rides beside it as id + title, so nothing parses the
            # sentence; absent when the index held nothing relevant.
            **_first_move_metadata(first_move, first_move_lesson_id, first_move_lesson_title),
        },
        plan_refs=tuple(PlanRef(plan.plan_id, None) for plan in named),
    )


def _guarantee_plan_backed(ranked: list[_Candidate], time_minutes: int) -> list[_Candidate]:
    """Rule 8: ≥ 1 plan-backed action among primary + alternates when time permits.

    Never re-ranks the primary: the best-ranked plan-backed candidate that
    fits the time window replaces the *last* alternate only. "Plan-backed"
    is any candidate carrying a ``PlanRef`` — a synthesised or represented
    next milestone of an eligible plan, or plan-related repair
    (``milestone_index=None``) on a deferred or unready one; rule 3 keeps that
    repair eligible below the energy floor, and deferred milestones are never
    synthesised, so nothing here advertises work the energy cannot carry.
    """
    if len(ranked) <= 3 or any(candidate.plan_refs for candidate in ranked[:3]):
        return ranked
    for position in range(3, len(ranked)):
        candidate = ranked[position]
        if candidate.plan_refs and candidate.estimated_minutes <= time_minutes:
            return [
                *ranked[:2],
                candidate,
                *ranked[2:position],
                *ranked[position + 1 :],
            ]
    return ranked


def build_now_plan(
    *,
    energy: EnergyLevel = "medium",
    time_minutes: int = 25,
    modality: Modality = "recall",
    interleave: InterleaveMode = "off",
) -> NowPlan:
    """Return the best current study action plus two alternatives.

    Order of operations is design §3's: guidance is read once (1), candidates
    are collected as before (2), the energy capability decides which next
    milestones are eligible and — since design §5 — which struggle repairs
    are carried, the rest deferred beside them (3), matching is key equality
    (4), scoring is today's plus the plan bias (5), an unrepresented eligible
    milestone is synthesised (6) — and when nothing plan-related fits an
    active plan, one body-double proposal is (§5) — then de-duplication and
    reference attachment (7), the plan-backed guarantee (8), with
    fully-checked plans reported as completion actions rather than
    candidates (9).
    """
    time_minutes = max(5, min(int(time_minutes), 180))
    now = datetime.now(UTC)
    plans = _PlanContext.build(_load_guidance(now.date()), energy=energy)

    candidates = [
        *_due_card_candidates(time_minutes),
        *_due_progress_candidates(time_minutes, now=now),
        *_struggle_candidates(time_minutes),
        *_continuity_candidates(time_minutes),
        *_practice_candidates(time_minutes),
    ]
    if interleave == "adaptive" and energy != "low":
        candidates.extend(_transfer_candidates(time_minutes))
    # Rule 3 extended: before rule 6 reads what is "represented", so a deferred
    # repair does not stand in for the milestone it can no longer carry.
    candidates, deferred_repairs = _defer_repairs(candidates, energy=energy, plans=plans)
    candidates.extend(plans.milestone_candidates(candidates, time_minutes))
    body_double = _body_double_candidate(
        plans, candidates, deferred_repairs, energy=energy, time_minutes=time_minutes
    )
    if body_double is not None:
        candidates.append(body_double)

    starter = False
    if not candidates:
        candidates = [_starter_candidate(time_minutes, after_deferral=bool(deferred_repairs))]
        starter = True

    ranked = _dedupe(
        _score_candidates(
            candidates,
            energy=energy,
            modality=modality,
            interleave=interleave,
            plan_keys=plans.match_keys,
        )
    )
    if plans.matchable:
        ranked = _guarantee_plan_backed(
            [plans.attach_refs(candidate) for candidate in ranked], time_minutes
        )
    # Rubric 3c (e1): the primary — and only the primary — of a plan-related
    # active kind carries one warm-up on its own material. After the guarantee,
    # so it rides on the recommendation the learner actually sees.
    warm_up = _warm_up(ranked[0], plans)
    if warm_up is not None:
        ranked = [
            dataclasses.replace(
                ranked[0], metadata={**ranked[0].metadata, **_first_move_metadata(*warm_up)}
            ),
            *ranked[1:],
        ]
    primary = ranked[0].recommendation()
    alternates = [item.recommendation() for item in ranked[1:3]]
    return NowPlan(
        energy=energy,
        time_minutes=time_minutes,
        modality=modality,
        interleave=interleave,
        generated_at=now.isoformat(),
        starter=starter,
        primary=primary,
        alternates=alternates,
        interleave_ratio=INTERLEAVE_RATIOS[energy] if interleave == "adaptive" else {},
        active_plans=plans.summaries,
        energy_deferred=plans.deferred,
        energy_deferred_repairs=deferred_repairs,
        completion_actions=plans.completions,
        warnings=plans.warnings,
    )
