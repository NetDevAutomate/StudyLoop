"""Read models returned by :class:`~studyloop.planning.application.PlanApplication`.

Every view is a frozen dataclass whose collections are tuples, so a value an
adapter received cannot be mutated behind another adapter's back, and
``to_json_dict()`` builds a *fresh* container on every call so one caller's
edits never leak into the next caller's response.

Field sets mirror the dicts the surfaces already emit — :meth:`StudyPlan.summary`
and :func:`~studyloop.planning.authoring.readiness` — key for key (decision
D-3). That is what keeps the existing REST bodies and CLI ``--json`` shapes
behaviour-identical when the routes and commands migrate onto the seam;
``tests/test_plan_application.py`` pins the equality.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from .authoring import readiness

if TYPE_CHECKING:
    from datetime import date

    from .evaluation import PlanEvaluation
    from .intents import LearningRecordSpec
    from .models import Checkpoint, LearningRecord, Milestone, Mission, Resource, StudyPlan


#: The leaf types an evidence seed may carry — JSON scalars. Anything else
#: (a model, a bytearray, an arbitrary object) is refused rather than stored
#: as a mutable leaf a frozen view would then be lying about.
_SEED_SCALARS = (str, int, float, bool, type(None))


def _freeze(value: object) -> object:
    """Recursively turn dicts into read-only mappings and sequences into tuples.

    Copies as it goes, so the caller's containers are never aliased, and
    raises ``TypeError`` for a leaf that is not a JSON scalar: a frozen view
    must not hold a mutable object it cannot vouch for.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, _SEED_SCALARS):
        return value
    msg = f"evidence seed values must be JSON-like; got {type(value).__name__}"
    raise TypeError(msg)


def _freeze_rows(value: object) -> object:
    """Like :func:`_freeze`, but for database rows an evaluation carries.

    The checkpoint log has always been written with ``json.dumps(...,
    default=str)`` and the CLI prints it the same way, so a non-JSON leaf
    (a ``date`` from a driver, say) is rendered — ``isoformat()`` when it has
    one, else ``str()`` — rather than refused. Refusing would turn a
    successful evaluation into a crash over one column's type.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_rows(item) for key, item in value.items()})
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(_freeze_rows(item) for item in value)
    if isinstance(value, _SEED_SCALARS):
        return value
    render = getattr(value, "isoformat", None)
    return render() if callable(render) else str(value)


def _thaw(value: object) -> object:
    """Inverse of :func:`_freeze`: fresh dicts and lists, ready for ``json.dumps``."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


_NON_WORD_RE = re.compile(r"[^\w\s]|_", re.UNICODE)


def normalise_match_key(text: str) -> str:
    """The key on which a plan topic or concept matches a study candidate.

    Casefold, replace punctuation (and ``_``) with spaces, collapse runs of
    whitespace, strip. ``"Data-Engineering"`` and ``"data engineering"`` are
    the same key; ``"RANK()"`` is ``"rank"``. The ``now`` ranker applies this
    same function to its candidates, so plan matching is *equality on the
    key* and never a substring test (design §3 step 4) — ``"rank"`` does not
    match ``"frank"``. Unicode is NFKC-normalised first so a full-width or
    composed form does not defeat the equality.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    spaced = _NON_WORD_RE.sub(" ", folded)
    return " ".join(spaced.split())


@dataclass(frozen=True)
class ReadinessView:
    """What still blocks a plan from being active, and what would merely help.

    Serialises to the same four keys :func:`authoring.readiness` returns, so a
    422 body or a CLI ``--json`` block reads exactly as it did before the seam.
    """

    plan_id: str
    ready: bool
    blockers: tuple[str, ...]
    nudges: tuple[str, ...]

    @classmethod
    def from_plan(cls, plan: StudyPlan) -> ReadinessView:
        check = readiness(plan)
        return cls(
            plan_id=str(check["plan_id"]),
            ready=bool(check["ready"]),
            blockers=tuple(check["blockers"]),
            nudges=tuple(check["nudges"]),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "ready": self.ready,
            "blockers": list(self.blockers),
            "nudges": list(self.nudges),
        }


@dataclass(frozen=True)
class PlanSummary:
    """Compact plan view — the :meth:`StudyPlan.summary` keys, exactly."""

    plan_id: str
    title: str
    status: str
    topics: tuple[str, ...]
    created: str
    updated: str
    target_date: str
    energy_floor: int
    review_cadence_days: int
    milestone_total: int
    milestone_done: int
    progress_pct: int
    next_milestone: str
    mission_why: str
    days_until_target: int | None
    learning_record_count: int
    checkpoint_count: int

    @classmethod
    def from_plan(cls, plan: StudyPlan, *, today: date | None = None) -> PlanSummary:
        """The summary; ``today`` pins ``days_until_target`` for frozen-clock callers.

        Defaults to the wall clock, exactly as :meth:`StudyPlan.summary` does,
        so every existing caller is unchanged. :meth:`ActivePlanGuidance.from_plan`
        passes its own effective date so the nested summary and the urgency
        bucket beside it are computed from one clock (council review 2).
        """
        nxt = plan.next_milestone()
        return cls(
            plan_id=plan.plan_id,
            title=plan.title,
            status=plan.status,
            topics=tuple(plan.topics),
            created=plan.created,
            updated=plan.updated,
            target_date=plan.target_date,
            energy_floor=plan.energy_floor,
            review_cadence_days=plan.review_cadence_days,
            milestone_total=plan.milestone_total,
            milestone_done=plan.milestone_done,
            progress_pct=plan.progress_pct,
            next_milestone=nxt.title if nxt else "",
            mission_why=plan.mission.why,
            days_until_target=plan.days_until_target(today),
            learning_record_count=len(plan.learning_records),
            checkpoint_count=len(plan.checkpoints),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "status": self.status,
            "topics": list(self.topics),
            "created": self.created,
            "updated": self.updated,
            "target_date": self.target_date,
            "energy_floor": self.energy_floor,
            "review_cadence_days": self.review_cadence_days,
            "milestone_total": self.milestone_total,
            "milestone_done": self.milestone_done,
            "progress_pct": self.progress_pct,
            "next_milestone": self.next_milestone,
            "mission_why": self.mission_why,
            "days_until_target": self.days_until_target,
            "learning_record_count": self.learning_record_count,
            "checkpoint_count": self.checkpoint_count,
        }


@dataclass(frozen=True)
class MissionView:
    why: str
    success: tuple[str, ...]
    constraints: tuple[str, ...]
    out_of_scope: tuple[str, ...]

    @classmethod
    def from_mission(cls, mission: Mission) -> MissionView:
        return cls(
            why=mission.why,
            success=tuple(mission.success),
            constraints=tuple(mission.constraints),
            out_of_scope=tuple(mission.out_of_scope),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "why": self.why,
            "success": list(self.success),
            "constraints": list(self.constraints),
            "out_of_scope": list(self.out_of_scope),
        }


@dataclass(frozen=True)
class MilestoneView:
    index: int
    title: str
    done: bool
    concepts: tuple[str, ...]
    notes: str = ""

    @classmethod
    def from_milestone(cls, index: int, milestone: Milestone) -> MilestoneView:
        return cls(
            index=index,
            title=milestone.title,
            done=milestone.done,
            concepts=tuple(milestone.concepts),
            notes=milestone.notes,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "done": self.done,
            "concepts": list(self.concepts),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LearningRecordView:
    number: int
    title: str
    body: str
    status: str

    @classmethod
    def from_record(cls, record: LearningRecord) -> LearningRecordView:
        return cls(number=record.number, title=record.title, body=record.body, status=record.status)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "status": self.status,
        }


@dataclass(frozen=True)
class ResourceView:
    label: str
    url: str
    note: str

    @classmethod
    def from_resource(cls, resource: Resource) -> ResourceView:
        return cls(label=resource.label, url=resource.url, note=resource.note)

    def to_json_dict(self) -> dict[str, Any]:
        return {"label": self.label, "url": self.url, "note": self.note}


@dataclass(frozen=True)
class CheckpointView:
    """One row of the plan document's own Checkpoints table."""

    phase: str
    verdict: str
    at: str
    summary: str
    study_id: str

    @classmethod
    def from_checkpoint(cls, checkpoint: Checkpoint) -> CheckpointView:
        return cls(
            phase=checkpoint.phase,
            verdict=checkpoint.verdict,
            at=checkpoint.at,
            summary=checkpoint.summary,
            study_id=checkpoint.study_id,
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "verdict": self.verdict,
            "at": self.at,
            "summary": self.summary,
            "study_id": self.study_id,
        }


@dataclass(frozen=True)
class CheckpointHistoryView:
    """One row of the durable checkpoint log in the sessions database.

    Distinct from :class:`CheckpointView`: the document table is part of the
    plan and travels with it; this log survives plan edits and deletion.
    """

    plan_id: str
    study_id: str
    phase: str
    verdict: str
    summary: str
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> CheckpointHistoryView:
        return cls(
            plan_id=str(row.get("plan_id", "")),
            study_id=str(row.get("study_id", "")),
            phase=str(row.get("phase", "")),
            verdict=str(row.get("verdict", "")),
            summary=str(row.get("summary", "")),
            created_at=str(row.get("created_at", "")),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "study_id": self.study_id,
            "phase": self.phase,
            "verdict": self.verdict,
            "summary": self.summary,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class InterviewItemView:
    """One question of the plan-creation interview, as the API and MCP see it."""

    key: str
    prompt: str
    why: str
    required: bool
    multi: bool

    @classmethod
    def from_spec(cls, item: Mapping[str, object]) -> InterviewItemView:
        return cls(
            key=str(item["key"]),
            prompt=str(item["prompt"]),
            why=str(item["why"]),
            required=bool(item["required"]),
            multi=bool(item["multi"]),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "why": self.why,
            "required": self.required,
            "multi": self.multi,
        }


@dataclass(frozen=True)
class PlanDetail:
    """One plan in full.

    ``markdown`` and ``history`` are ``None`` unless the caller asked for them
    (``inspect(include_markdown=…, include_history=…)``): the raw document and
    the database log are the two parts that cost something to fetch, and most
    callers want neither. ``checkpoints`` — the document's own table — is
    always present because it is already parsed.
    """

    summary: PlanSummary
    mission: MissionView
    milestones: tuple[MilestoneView, ...]
    learning_records: tuple[LearningRecordView, ...]
    resources: tuple[ResourceView, ...]
    checkpoints: tuple[CheckpointView, ...]
    readiness: ReadinessView
    markdown: str | None = None
    history: tuple[CheckpointHistoryView, ...] | None = None

    @classmethod
    def from_plan(
        cls,
        plan: StudyPlan,
        *,
        markdown: str | None = None,
        history: Iterable[CheckpointHistoryView] | None = None,
    ) -> PlanDetail:
        return cls(
            summary=PlanSummary.from_plan(plan),
            mission=MissionView.from_mission(plan.mission),
            milestones=tuple(
                MilestoneView.from_milestone(index, milestone)
                for index, milestone in enumerate(plan.milestones)
            ),
            learning_records=tuple(
                LearningRecordView.from_record(record) for record in plan.learning_records
            ),
            resources=tuple(ResourceView.from_resource(resource) for resource in plan.resources),
            checkpoints=tuple(
                CheckpointView.from_checkpoint(checkpoint) for checkpoint in plan.checkpoints
            ),
            readiness=ReadinessView.from_plan(plan),
            markdown=markdown,
            history=None if history is None else tuple(history),
        )

    def to_json_dict(self) -> dict[str, Any]:
        """The ``GET /api/plans/{id}`` body shape; optional parts only when present."""
        payload: dict[str, Any] = {"plan": self.summary.to_json_dict()}
        if self.markdown is not None:
            payload["markdown"] = self.markdown
        payload["mission"] = self.mission.to_json_dict()
        payload["milestones"] = [milestone.to_json_dict() for milestone in self.milestones]
        payload["learning_records"] = [record.to_json_dict() for record in self.learning_records]
        payload["resources"] = [resource.to_json_dict() for resource in self.resources]
        payload["checkpoints"] = [checkpoint.to_json_dict() for checkpoint in self.checkpoints]
        payload["readiness"] = self.readiness.to_json_dict()
        if self.history is not None:
            payload["history"] = [entry.to_json_dict() for entry in self.history]
        return payload

    def learning_record_matching(self, spec: LearningRecordSpec) -> LearningRecordView | None:
        """The record ``spec`` would be a duplicate of, or ``None``.

        Identity is the store's idempotency rule — same title and body after
        the whitespace trim the parser applies
        (:func:`studyloop.planning.store.append_learning_record`). An adapter
        that reports ``created`` asks this before and after the revision
        instead of carrying its own copy of that rule.
        """
        title, body = spec.title.strip(), spec.body.strip()
        for record in self.learning_records:
            if record.title == title and record.body == body:
                return record
        return None


@dataclass(frozen=True)
class PlanningBrief:
    """Everything an architect needs before the first interview question.

    ``evidence_seed`` is what the databases already suggest the learner should
    plan for — data about the learner, never instructions to the agent (D-10).
    It is deep-frozen and defensively copied *on construction* — by
    ``__post_init__``, so the generated constructor gives the same guarantee
    as :meth:`build` — and thawed into fresh lists and dicts by
    :meth:`to_json_dict`. A seed holding anything but JSON-like values is a
    ``TypeError``.
    """

    interview: tuple[InterviewItemView, ...]
    evidence_seed: Mapping[str, object]
    existing_plans: tuple[PlanSummary, ...]

    def __post_init__(self) -> None:
        frozen_seed = _freeze(self.evidence_seed)
        if not isinstance(frozen_seed, Mapping):
            msg = "evidence seed must be a mapping"
            raise TypeError(msg)
        # ``frozen=True`` blocks ordinary assignment; this is the sanctioned
        # way for a frozen dataclass to normalise its own fields.
        object.__setattr__(self, "evidence_seed", frozen_seed)
        object.__setattr__(self, "interview", tuple(self.interview))
        object.__setattr__(self, "existing_plans", tuple(self.existing_plans))

    @classmethod
    def build(
        cls,
        *,
        interview: Iterable[Mapping[str, object]],
        seed: Mapping[str, object],
        existing_plans: Iterable[PlanSummary],
    ) -> PlanningBrief:
        """Convenience factory from the authoring module's plain dicts."""
        return cls(
            interview=tuple(InterviewItemView.from_spec(item) for item in interview),
            evidence_seed=seed,
            existing_plans=tuple(existing_plans),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "questions": [item.to_json_dict() for item in self.interview],
            "seed": _thaw(self.evidence_seed),
            "existing_plans": [plan.to_json_dict() for plan in self.existing_plans],
        }


# ---------------------------------------------------------------------------
# Phase 2 views: deletion, assessment, active-plan guidance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeleteResult:
    """The outcome of a confirmed ``DeletePlan``.

    A ``PlanDetail`` describes a plan as it now is; a deleted plan has no "now",
    so ``apply`` returns this instead (council review 1, GPT hazard table). The
    canonical document and its derived index row are gone; the durable
    checkpoint log in the sessions database is retained by design.
    """

    plan_id: str

    def to_json_dict(self) -> dict[str, Any]:
        return {"deleted": True, "plan_id": self.plan_id}


SinkStatus = Literal["not_requested", "saved", "failed"]
TargetUrgency = Literal["overdue", "soon", "later", "undated"]

#: Days-until-target at or below which a target date is ``soon``.
SOON_WITHIN_DAYS = 7


@dataclass(frozen=True)
class PlanEvaluationView:
    """A frozen :class:`~studyloop.planning.evaluation.PlanEvaluation`.

    Field for field the same as the mutable evaluation, with tuples for lists
    and read-only mappings for database rows, plus ``markdown`` — the block an
    agent pastes into the conversation, rendered once at construction so no
    caller needs the mutable object to print it. :meth:`to_json_dict` returns
    exactly ``PlanEvaluation.to_dict()``, so the REST body and the CLI
    ``--json`` shape do not change when the adapters delegate (D-3).
    """

    plan_id: str
    plan_title: str
    phase: str
    verdict: str
    headline: str
    at: str
    study_id: str
    progress_pct: int
    milestone_total: int
    milestone_done: int
    next_milestone: str
    next_concepts: tuple[str, ...]
    days_since_activity: int | None
    days_until_target: int | None
    due_reviews: tuple[Mapping[str, object], ...]
    struggles: tuple[Mapping[str, object], ...]
    concept_evidence: tuple[Mapping[str, object], ...]
    unverified_milestones: tuple[str, ...]
    drift_topics: tuple[str, ...]
    recommendations: tuple[str, ...]
    warnings: tuple[str, ...]
    markdown: str

    @classmethod
    def from_evaluation(cls, evaluation: PlanEvaluation) -> PlanEvaluationView:
        data = evaluation.to_dict()
        return cls(
            plan_id=str(data["plan_id"]),
            plan_title=str(data["plan_title"]),
            phase=str(data["phase"]),
            verdict=str(data["verdict"]),
            headline=str(data["headline"]),
            at=str(data["at"]),
            study_id=str(data["study_id"]),
            progress_pct=int(data["progress_pct"]),
            milestone_total=int(data["milestone_total"]),
            milestone_done=int(data["milestone_done"]),
            next_milestone=str(data["next_milestone"]),
            next_concepts=tuple(str(item) for item in data["next_concepts"]),
            days_since_activity=data["days_since_activity"],
            days_until_target=data["days_until_target"],
            due_reviews=_rows(data["due_reviews"]),
            struggles=_rows(data["struggles"]),
            concept_evidence=_rows(data["concept_evidence"]),
            unverified_milestones=tuple(str(item) for item in data["unverified_milestones"]),
            drift_topics=tuple(str(item) for item in data["drift_topics"]),
            recommendations=tuple(str(item) for item in data["recommendations"]),
            warnings=tuple(str(item) for item in data["warnings"]),
            markdown=evaluation.as_markdown(),
        )

    def to_json_dict(self) -> dict[str, Any]:
        """``PlanEvaluation.to_dict()``, key for key, in fresh containers."""
        return {
            "plan_id": self.plan_id,
            "plan_title": self.plan_title,
            "phase": self.phase,
            "verdict": self.verdict,
            "headline": self.headline,
            "at": self.at,
            "study_id": self.study_id,
            "progress_pct": self.progress_pct,
            "milestone_total": self.milestone_total,
            "milestone_done": self.milestone_done,
            "next_milestone": self.next_milestone,
            "next_concepts": list(self.next_concepts),
            "days_since_activity": self.days_since_activity,
            "days_until_target": self.days_until_target,
            "due_reviews": _thaw(self.due_reviews),
            "struggles": _thaw(self.struggles),
            "concept_evidence": _thaw(self.concept_evidence),
            "unverified_milestones": list(self.unverified_milestones),
            "drift_topics": list(self.drift_topics),
            "recommendations": list(self.recommendations),
            "warnings": list(self.warnings),
        }


def _rows(items: object) -> tuple[Mapping[str, object], ...]:
    frozen = _freeze_rows(items)
    if not isinstance(frozen, tuple):  # pragma: no cover - to_dict() always yields lists here
        msg = "evaluation rows must be a list"
        raise TypeError(msg)
    return tuple(row for row in frozen if isinstance(row, Mapping))


@dataclass(frozen=True)
class AssessmentResult:
    """What ``assess`` did: the evaluation, and the fate of each requested sink.

    ``db_write`` is the durable checkpoint log; ``document_write`` is the plan
    document's own Checkpoints table. Each is ``not_requested`` (a preview, or
    ``append_to_plan=False``), ``saved`` or ``failed`` — the two are
    independent (D-1), and a failure is a *reported outcome*, never an
    exception, because the evaluation itself succeeded and the caller is
    entitled to it. ``warnings`` is the evaluation's full warning list,
    recording warnings included, so a caller that only ever read
    ``evaluation.warnings`` sees the same strings.
    """

    evaluation: PlanEvaluationView
    db_write: SinkStatus
    document_write: SinkStatus
    warnings: tuple[str, ...]

    @property
    def recording_complete(self) -> bool:
        """``True`` when every *requested* sink was saved.

        Vacuously true for a preview: nothing was asked for, so nothing is
        missing. Adapters that print "recorded" check ``record`` themselves.
        """
        return "failed" not in (self.db_write, self.document_write)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "evaluation": self.evaluation.to_json_dict(),
            "markdown": self.evaluation.markdown,
            "db_write": self.db_write,
            "document_write": self.document_write,
            "recording_complete": self.recording_complete,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ActivePlanGuidance:
    """What the ``now`` ranker needs to know about one active plan (D-5).

    Plan-static: computed from the document alone, no session-history scan.
    ``match_keys`` are :func:`normalise_match_key` over the topics and every
    milestone's concepts, done or not — a due review on a finished milestone's
    concept is still plan-related repair. ``next_milestone`` is the first
    unchecked one. ``completion_action`` replaces a study candidate when every
    milestone is ticked (design §3 step 9). ``warnings`` name defects in this
    document that the guidance worked around rather than raised.

    ``readiness`` is the same :class:`ReadinessView` every write is judged by.
    An active plan that fails it (a hand-edited or pre-gate document with no
    mission) is still active and still listed — the ranker decides, not this
    read — but every ``SetMilestone``, ``RevisePlan`` or recorded assessment on
    it will be ``PlanNotReady`` until it is paused or repaired, and the ranker
    must be able to see that here rather than by a second ``inspect`` per plan
    (council review 2).
    """

    plan: PlanSummary
    readiness: ReadinessView
    next_milestone: MilestoneView | None
    match_keys: frozenset[str]
    target_urgency: TargetUrgency
    energy_floor: int
    completion_action: str | None
    warnings: tuple[str, ...]

    @classmethod
    def from_plan(cls, plan: StudyPlan, *, today: date | None = None) -> ActivePlanGuidance:
        """Build the entry; ``today`` is the one effective date for the whole payload.

        ``target_urgency`` and the nested summary's ``days_until_target`` are
        both computed from it (council review 2, GPT F6): a frozen-clock read
        must not say "soon" beside a day count taken from the wall clock.
        ``None`` means the wall clock, resolved once here so both agree.
        """
        effective_today = today or datetime.now(UTC).date()
        warnings: list[str] = []
        keys = {normalise_match_key(topic) for topic in plan.topics}
        for milestone in plan.milestones:
            keys.update(normalise_match_key(concept) for concept in milestone.concepts)
        keys.discard("")

        next_view = next(
            (
                MilestoneView.from_milestone(index, milestone)
                for index, milestone in enumerate(plan.milestones)
                if not milestone.done
            ),
            None,
        )

        if not plan.milestones:
            warnings.append(f"active plan {plan.plan_id!r} has no milestones")
        if not keys:
            warnings.append(
                f"active plan {plan.plan_id!r} names no topics or concepts — nothing can match it"
            )

        days = plan.days_until_target(effective_today)
        if plan.target_date and days is None:
            warnings.append(
                f"target_date {plan.target_date!r} on {plan.plan_id!r} is not a date; "
                "treated as undated"
            )
        urgency: TargetUrgency
        if days is None:
            urgency = "undated"
        elif days < 0:
            urgency = "overdue"
        elif days <= SOON_WITHIN_DAYS:
            urgency = "soon"
        else:
            urgency = "later"

        completion = None
        if plan.milestones and next_view is None:
            completion = (
                f"Every milestone of {plan.title!r} is checked off — close the plan "
                "or extend it with a follow-on mission."
            )

        return cls(
            plan=PlanSummary.from_plan(plan, today=effective_today),
            readiness=ReadinessView.from_plan(plan),
            next_milestone=next_view,
            match_keys=frozenset(keys),
            target_urgency=urgency,
            energy_floor=plan.energy_floor,
            completion_action=completion,
            warnings=tuple(warnings),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_json_dict(),
            "readiness": self.readiness.to_json_dict(),
            "next_milestone": (
                None if self.next_milestone is None else self.next_milestone.to_json_dict()
            ),
            "match_keys": sorted(self.match_keys),
            "target_urgency": self.target_urgency,
            "energy_floor": self.energy_floor,
            "completion_action": self.completion_action,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ActiveGuidance:
    """Every active plan's guidance, ordered by plan id, plus collection warnings.

    A collection, never a singleton: several plans may be active at once.
    ``warnings`` at this level name documents that could not be represented
    at all — an unparseable file the store skipped, say — so the ranker knows
    its picture is incomplete rather than believing there is nothing there.
    """

    plans: tuple[ActivePlanGuidance, ...]
    warnings: tuple[str, ...]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "plans": [plan.to_json_dict() for plan in self.plans],
            "warnings": list(self.warnings),
        }
