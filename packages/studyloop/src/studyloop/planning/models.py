"""Dataclasses for structured study plans.

A study plan is a *file-first* artefact: the Markdown document on disk is the
source of truth, and these dataclasses are the parsed in-memory view.  The
shape is deliberately close to Matt Pocock's ``teach`` skill workspace
(mission / learning records / resources) but collapsed into one document per
plan so it renders as a single page in the web UI and stays diffable in git.

Reference: https://github.com/mattpocock/skills/tree/main/skills/productivity/teach
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

#: Plan lifecycle states. ``active`` plans are evaluated at session boundaries.
PLAN_STATUSES = ("draft", "active", "paused", "complete", "abandoned")

#: Evaluation checkpoints. A plan is assessed at each of these three moments.
CHECKPOINT_PHASES = ("start", "mid", "end")

#: Verdicts an evaluation can reach, ordered worst → best for sorting.
VERDICTS = ("stalled", "at-risk", "on-track", "complete")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Return a filesystem- and URL-safe slug for ``text``.

    Collapses any run of non-alphanumerics to a single hyphen and trims
    leading/trailing hyphens, so ``"Master Python Decorators!"`` becomes
    ``"master-python-decorators"``.
    """
    slug = _SLUG_STRIP.sub("-", text.strip().lower()).strip("-")
    return slug or "untitled-plan"


def utc_now_iso() -> str:
    """Return the current UTC time as a second-precision ISO-8601 string."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class Mission:
    """Why the learner is doing this at all.

    Grounds every downstream decision: which milestone comes next, which due
    review is actually relevant, and whether a session drifted off-plan.
    """

    why: str = ""
    success: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)

    def is_populated(self) -> bool:
        """True when the mission carries enough signal to steer teaching."""
        return bool(self.why.strip()) and bool(self.success)


@dataclass
class Goal:
    """A stable, mission-aligned outcome that milestones work toward."""

    goal_id: str
    title: str
    reason: str
    alignment_rationale: str
    status: str = "active"


@dataclass
class EvidenceRef:
    """A provenance-preserving reference to evidence owned by another store."""

    evidence_id: str
    source_kind: str
    source_native_id: str
    source_revision: str
    observed_at: str
    ingested_at: str
    tier: int
    claim_kind: str
    subject_ref: str
    provenance_digest: str


@dataclass
class EvidenceDisposition:
    """How one evidence item was treated by a learner-reviewed proposal."""

    evidence_id: str
    disposition: str
    reason: str


@dataclass
class ConceptRef:
    """A stable concept identity with a learner-facing label."""

    concept_id: str
    display_label: str


@dataclass
class ConceptRelation:
    """An explicit, reasoned relation between two concept identities."""

    source_ref: str
    target_ref: str
    relation: str
    reason: str
    decided_by: str


@dataclass
class PlanUnknown:
    """A visible gap that must not be converted into invented certainty."""

    unknown_id: str
    question: str
    impact: str
    status: str = "open"


@dataclass
class DecisionRecord:
    """An auditable learner decision about a typed plan proposal."""

    decision_id: str
    proposal_id: str
    outcome: str
    actor_kind: str
    channel: str
    reason: str
    decided_at: str


@dataclass
class Milestone:
    """One checkable step toward the mission.

    ``concepts`` are the mastery-graph concept names this milestone covers.
    They are the join key against ``study_progress`` — that is what lets an
    evaluation say "milestone 3 is claimed done but its concepts have no
    confidence evidence".
    """

    title: str
    done: bool = False
    concepts: list[str] = field(default_factory=list)
    notes: str = ""
    milestone_id: str = ""
    goal_id: str = ""

    def concept_set(self) -> set[str]:
        """Normalised (lower-cased, stripped) concept names."""
        return {c.strip().lower() for c in self.concepts if c.strip()}


@dataclass
class LearningRecord:
    """An ADR-for-learning: a non-obvious insight that changes what to teach.

    Numbered sequentially so records can cite each other and be superseded
    rather than deleted.
    """

    number: int
    title: str
    body: str = ""
    status: str = "active"


@dataclass
class Resource:
    """A high-trust external source backing the plan's knowledge."""

    label: str
    url: str = ""
    note: str = ""


@dataclass
class Checkpoint:
    """A recorded evaluation of the plan at a session boundary."""

    phase: str
    verdict: str
    at: str
    summary: str = ""
    study_id: str = ""

    def __post_init__(self) -> None:
        if self.phase not in CHECKPOINT_PHASES:
            msg = f"phase must be one of {CHECKPOINT_PHASES}, got {self.phase!r}"
            raise ValueError(msg)


@dataclass
class StudyPlan:
    """A complete study plan, parsed from its Markdown document."""

    plan_id: str
    title: str
    status: str = "draft"
    created: str = field(default_factory=utc_now_iso)
    updated: str = field(default_factory=utc_now_iso)
    topics: list[str] = field(default_factory=list)
    energy_floor: int = 3
    target_date: str = ""
    review_cadence_days: int = 3
    mission: Mission = field(default_factory=Mission)
    milestones: list[Milestone] = field(default_factory=list)
    learning_records: list[LearningRecord] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    notes: str = ""
    schema_version: int = 2
    document_revision: int = 1
    structure_revision: int = 1
    document_digest: str = ""
    structure_digest: str = ""
    brief_context_digest: str = ""
    goals: list[Goal] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    evidence_dispositions: list[EvidenceDisposition] = field(default_factory=list)
    concepts: list[ConceptRef] = field(default_factory=list)
    concept_relations: list[ConceptRelation] = field(default_factory=list)
    unknowns: list[PlanUnknown] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in PLAN_STATUSES:
            msg = f"status must be one of {PLAN_STATUSES}, got {self.status!r}"
            raise ValueError(msg)
        if not self.plan_id:
            self.plan_id = slugify(self.title)

    # -- derived views -----------------------------------------------------

    @property
    def milestone_total(self) -> int:
        return len(self.milestones)

    @property
    def milestone_done(self) -> int:
        return sum(1 for m in self.milestones if m.done)

    @property
    def progress_pct(self) -> int:
        """Completion as a whole percentage (0 when there are no milestones)."""
        if not self.milestones:
            return 0
        return round(100 * self.milestone_done / self.milestone_total)

    def next_milestone(self) -> Milestone | None:
        """The first unchecked milestone — the zone of proximal development."""
        for milestone in self.milestones:
            if not milestone.done:
                return milestone
        return None

    def all_concepts(self) -> list[str]:
        """Every concept named by any milestone, de-duplicated, order-stable."""
        seen: dict[str, None] = {}
        for milestone in self.milestones:
            for concept in milestone.concepts:
                cleaned = concept.strip()
                if cleaned and cleaned.lower() not in {k.lower() for k in seen}:
                    seen[cleaned] = None
        return list(seen)

    def keywords(self) -> list[str]:
        """Topic + concept keywords used to match sessions and progress rows."""
        words = [t.strip() for t in self.topics if t.strip()]
        words.extend(self.all_concepts())
        return words

    def days_until_target(self, today: date | None = None) -> int | None:
        """Days remaining until ``target_date``, or None when unset/invalid."""
        if not self.target_date:
            return None
        try:
            target = date.fromisoformat(self.target_date[:10])
        except ValueError:
            return None
        return (target - (today or datetime.now(UTC).date())).days

    def summary(self) -> dict:
        """Compact dict for list views and API payloads."""
        nxt = self.next_milestone()
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
            "next_milestone": nxt.title if nxt else "",
            "mission_why": self.mission.why,
            "days_until_target": self.days_until_target(),
            "learning_record_count": len(self.learning_records),
            "checkpoint_count": len(self.checkpoints),
        }
