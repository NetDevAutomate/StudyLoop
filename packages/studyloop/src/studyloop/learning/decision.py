"""Shared decision engine for "what should I study now?" recommendations.

This module is the **only ranker**. Active study plans (design §3, D-5) enter
it as one plan-static read — ``PlanApplication().get_active_guidance()`` — and
leave as a *bias* on the existing scores, a synthesised candidate for an
unrepresented next milestone, and references attached to the ranked actions.
Renderers show that plan relevance; none of them re-rank.

With no active plan the emitted JSON is byte for byte what it was before plans
existed: every additive field is omitted when empty
(``tests/golden/now_plan_no_active.json``).
"""

from __future__ import annotations

import dataclasses
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from studyloop.cli._shared import TOPIC_KEYWORDS

if TYPE_CHECKING:
    from datetime import date

    from studyloop.planning.views import ActiveGuidance, ActivePlanGuidance, MilestoneView

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
#: milestone work is deferred; plan-related due recall and struggle repair
#: stay eligible, because repair is cheaper than encoding.
ENERGY_CAPABILITY: dict[EnergyLevel, int] = {"low": 3, "medium": 6, "high": 10}

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
class CompletionAction:
    """What to do about an active plan whose every milestone is checked (rule 9)."""

    plan_id: str
    plan_title: str
    action: str

    def to_json_dict(self) -> dict:
        return asdict(self)


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
        from studyloop.history import observations

        rows = [
            row
            for row in observations.rows(conn)
            if row["confidence"] in ("struggling", "learning")
            or (row.get("last_teachback_score") is not None and row["last_teachback_score"] < 14)
        ]
        rows.sort(key=lambda row: row["last_seen"], reverse=True)
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
    """One plan-static read through the seam; ``None`` when plans cannot be read at all."""
    try:
        from studyloop.planning.application import PlanApplication

        return PlanApplication().get_active_guidance(today=today)
    except Exception:
        return None


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
    done and which is represented by a completion action instead (rule 9).
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
                completions.append(
                    CompletionAction(
                        plan_id=summary.plan_id,
                        plan_title=summary.title,
                        action=plan.completion_action,
                    )
                )
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
                                    f"{plan.energy_floor}/10 — plan-related review "
                                    "and repair stay available"
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

    def attach_refs(self, candidate: _Candidate) -> _Candidate:
        """Rule 7: every matching plan, most specific milestone per plan, in plan order."""
        keys = _candidate_keys(candidate)
        refs: dict[str, int | None] = {
            ref.plan_id: ref.milestone_index for ref in candidate.plan_refs
        }
        for plan in self.matchable:
            plan_id = plan.plan.plan_id
            if not keys & frozenset(plan.match_keys):
                continue
            index = (
                plan.next_milestone.index
                if plan.next_milestone is not None and keys & _milestone_concept_keys(plan)
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


def _guarantee_plan_backed(ranked: list[_Candidate], time_minutes: int) -> list[_Candidate]:
    """Rule 8: ≥ 1 plan-backed action among primary + alternates when time permits.

    Never re-ranks the primary: the best-ranked eligible plan-backed candidate
    that fits the time window replaces the *last* alternate only. Deferred
    milestones were never synthesised, so every plan-backed candidate here is
    eligible on energy.
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
    milestones are eligible (3), matching is key equality (4), scoring is
    today's plus the plan bias (5), an unrepresented eligible milestone is
    synthesised (6), then de-duplication and reference attachment (7), the
    plan-backed guarantee (8), with fully-checked plans reported as
    completion actions rather than candidates (9).
    """
    time_minutes = max(5, min(int(time_minutes), 180))
    now = datetime.now(UTC)
    plans = _PlanContext.build(_load_guidance(now.date()), energy=energy)

    candidates = [
        *_due_card_candidates(time_minutes),
        *_due_progress_candidates(time_minutes),
        *_struggle_candidates(time_minutes),
        *_continuity_candidates(time_minutes),
        *_practice_candidates(time_minutes),
    ]
    if interleave == "adaptive" and energy != "low":
        candidates.extend(_transfer_candidates(time_minutes))
    candidates.extend(plans.milestone_candidates(candidates, time_minutes))

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
            plan_keys=plans.match_keys,
        )
    )
    if plans.matchable:
        ranked = _guarantee_plan_backed(
            [plans.attach_refs(candidate) for candidate in ranked], time_minutes
        )
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
        completion_actions=plans.completions,
        warnings=plans.warnings,
    )
