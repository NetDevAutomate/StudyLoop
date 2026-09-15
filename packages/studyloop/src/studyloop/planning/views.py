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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from .authoring import readiness

if TYPE_CHECKING:
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


def _thaw(value: object) -> object:
    """Inverse of :func:`_freeze`: fresh dicts and lists, ready for ``json.dumps``."""
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


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
    def from_plan(cls, plan: StudyPlan) -> PlanSummary:
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
            days_until_target=plan.days_until_target(),
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
