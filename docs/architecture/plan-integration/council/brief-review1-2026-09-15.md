# Council brief — code review 1: Phase 0 (Bug B) + Phase 1 (#8 seam, Bug A)

**Date:** 2026-09-15 · **Branch:** `fix/plan-integration-bugs`, commits `c16ffa35..101fb33b` on top of the RED
commit `3a4f6b01` and the planning commit `472f77be`. **You are one independent seat**; no other seat's
answer is visible. You have no tools — the brief is the complete evidence base.

## 0. What you are reviewing against

The work order and decisions are binding; judge the code against them, and say where they were wrong.

- **Decisions (from the arbitration):** D-1 Bug B fixed alone in `evaluate_and_record` by honouring the
  boolean. D-2 Bug A closed by the seam; `CreatePlan`, `ReplaceDocument`, `TransitionLifecycle` ship in
  #8; the route-local readiness gate is *deleted* when the route delegates; no third copy. D-3 four
  modules `planning/{errors,views,intents,application}.py`; frozen views with tuples; views serialise to
  the EXISTING `summary()`/`readiness()` key sets so REST bodies do not change; domain errors are
  exceptions with no CLI/HTTP/MCP types; `PlanNotReady` carries a `ReadinessView`; no `PartialRecording`
  exception. D-4 `overwrite` stays on `CreatePlan` (Web/CLI) — never exposed to MCP later.
- **Adapter error mapping (design §2):** `PlanNotFound`→404, `InvalidPlanId`/`InvalidField`→400,
  `PlanConflict`→409, `PlanNotReady`→422 `{"message":"plan is not ready to activate","ready":false,
  "blockers":[...],"nudges":[...]}`, `InvalidMilestone`→404.
- **Hard rules the agent worked under:** TDD (RED seen failing before code); every pre-existing assertion
  in `test_web_plans.py`, `test_cli_plan.py`, `test_planning_evaluation.py` unchanged (verified: `git diff
  3a4f6b01` on those three files is empty); `rg 'readiness\(' web/routes/plans.py` → 0 hits (verified);
  pyright 0 errors; ruff clean; full suite `4576 passed, 4 skipped`.

## 1. The agent's own report of deviations from design.md (verbatim)

1. `ImportDocument` is an eighth intent. `POST /api/plans` has a raw-markdown import branch that is also a
   create-and-activate door. Without an intent it would either stay ungated or need a route-local gate.
   Tests pin it refusing identically to the other three doors. The route now also honours `payload["plan_id"]`
   on import (previously a dead branch ignored it).
2. View field sets widened so REST bodies stay identical (D-3 outranks the sketch): `ReadinessView` carries
   `plan_id`; `MilestoneView` carries `notes`; `PlanDetail` carries `learning_records`, `resources`, the
   document's own `checkpoints` (always), and `history` (the DB log) behind `include_history` with a
   `history_limit` kwarg on `inspect`. `PlanDetail.to_json_dict()` is exactly the `GET /api/plans/{id}` body.
3. No `plans_dir` constructor argument. Directory resolution stays with `store.plans_dir()`.
4. Error class names keep the arbitration's spelling (`PlanNotFound`, not `PlanNotFoundError`) with a
   file-level `# ruff: noqa: N818` — the suffixed forms already exist in `store.py` with stdlib bases.
5. PATCH ordering: existence (404) → validate every field edit (400) → transition (400/422) → field edits →
   save. Previously the 422 readiness check preceded the title/energy/milestone 400s. Both refuse without
   writing. No test covers this combination.
6. Extra read paths migrated in Phase 1: `GET /plans/{id}/markdown`, `/history`, `GET /plans/interview`.
   Still on direct imports until Phase 2: GET/POST evaluate, PATCH field/milestone edits, toggle, DELETE
   (Web); `new`, `interview`, `evaluate`, `milestone`, `record` (CLI).

Also reported: the T1.1 RED commit carried a file-level `# pyright: reportMissingImports=false,
reportAttributeAccessIssue=false` because the pre-commit hook type-checks tests and would otherwise block
a test-before-code commit; T1.2 removed it (verified: 0 hits now).

## 2. Bug B fix — `planning/evaluation.py` diff

```diff
diff --git a/packages/studyloop/src/studyloop/planning/evaluation.py b/packages/studyloop/src/studyloop/planning/evaluation.py
index 85a812d6..a47a2f44 100644
--- a/packages/studyloop/src/studyloop/planning/evaluation.py
+++ b/packages/studyloop/src/studyloop/planning/evaluation.py
@@ -451,15 +451,23 @@ def evaluate_and_record(

     The DB write and the Markdown write are independent: either can fail
     without losing the other, and the evaluation is always returned.
+
+    ``record_checkpoint`` reports failure two ways — it swallows its own
+    errors and returns ``False`` (no database, INSERT failed), and it can still
+    raise from an import or connection fault.  Both must land in ``warnings``:
+    a caller reading an empty warning list is entitled to believe the
+    checkpoint is durably recorded.
     """
     evaluation = evaluate_plan(plan, phase, study_id=study_id)

     try:
         from .index import record_checkpoint

-        record_checkpoint(evaluation, study_id=study_id)
+        saved = record_checkpoint(evaluation, study_id=study_id)
     except Exception:
         logger.debug("checkpoint DB write failed", exc_info=True)
+        saved = False
+    if not saved:
         evaluation.warnings.append("checkpoint not saved to the database")

     if append_to_plan:
```

## 3. New modules (full source)

### `planning/errors.py`

```python
"""Domain errors raised by :class:`~studyloop.planning.application.PlanApplication`.

These carry no CLI, HTTP or MCP vocabulary. Each adapter maps them exactly
once (design §2): the Web API to a status code, the CLI to an exit code and a
message, an MCP tool to a ``ToolError``. Keeping the mapping in the adapter
is what lets the same refusal — say, "this plan is not ready to activate" —
read identically on every surface without the domain knowing any of them.

Naming: these are the names the council arbitration fixed (D-3), without the
``Error`` suffix pep8-naming asks for. The suffixed forms already exist in
:mod:`studyloop.planning.store` (``PlanNotFoundError``, ``InvalidPlanIdError``,
``PlanExistsError``) with stdlib bases, are re-exported from the same package,
and are what the store raises *to* the seam; a second family with the same
names and a different base would be a trap for every ``except`` clause.
"""

# ruff: noqa: N818

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .views import ReadinessView


class PlanError(Exception):
    """Base class for every plan-domain failure an adapter may see."""


class PlanNotFound(PlanError):
    """No plan document resolves to the given id."""


class InvalidPlanId(PlanError):
    """The id is malformed or would escape the plans directory."""


class PlanConflict(PlanError):
    """A create would clobber an existing plan id and ``overwrite`` was not set."""


class InvalidField(PlanError):
    """A supplied value is unusable: unknown status, empty title, bad phase…"""


class PlanNotReady(PlanError):
    """The resulting document would be active but fails the readiness check.

    Carries the :class:`~studyloop.planning.views.ReadinessView` so an adapter
    can show *what* blocks activation, not just that something does. Raised
    before any write, on every path that could make a plan active.
    """

    def __init__(self, readiness: ReadinessView) -> None:
        super().__init__("plan is not ready to activate")
        self.readiness = readiness


class InvalidMilestone(PlanError):
    """The milestone index does not exist on the plan."""
```

### `planning/intents.py`

```python
"""Write intents accepted by :meth:`~studyloop.planning.application.PlanApplication.apply`.

A closed union of frozen dataclasses: an adapter says *what it wants*, the
application decides whether the resulting document is allowed to exist. That
is how one readiness gate covers every door into the ``active`` state — the
adapters never see a :class:`~studyloop.planning.models.StudyPlan` to mutate.

Phase 1 ships the intents that can make a plan active (decision D-2):
create-with-status, document import, whole-document replacement and the
lifecycle transition. Field-level revision, milestone updates, deletion and
assessment follow in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class CreatePlan:
    """Draft a plan from interview ``answers`` and persist it.

    ``plan_id`` defaults to a unique slug of the title. ``overwrite`` exists for
    the Web and CLI surfaces, whose request shapes already accept it; the MCP
    ``create_study_plan`` tool never exposes it (D-4) — an agent must not be
    able to replace a learner's plan by picking the same id.
    """

    title: str
    answers: Mapping[str, object] = field(default_factory=dict)
    plan_id: str | None = None
    status: str = "draft"
    overwrite: bool = False


@dataclass(frozen=True)
class ImportDocument:
    """Persist a complete Markdown document as a *new* plan.

    The id comes from ``plan_id`` when given, else from the document's
    frontmatter, else from its title. A document whose frontmatter says
    ``active`` is held to the same readiness gate as any other create.
    """

    markdown: str
    plan_id: str | None = None
    overwrite: bool = False


@dataclass(frozen=True)
class ReplaceDocument:
    """Replace an existing plan's whole document, keeping its id and ``created``."""

    plan_id: str
    markdown: str


@dataclass(frozen=True)
class TransitionLifecycle:
    """Move a plan to another lifecycle ``status`` (``draft``, ``active``, …)."""

    plan_id: str
    status: str


PlanIntent = CreatePlan | ImportDocument | ReplaceDocument | TransitionLifecycle
```

### `planning/views.py`

```python
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


def _freeze(value: object) -> object:
    """Recursively turn dicts into read-only mappings and sequences into tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(_freeze(item) for item in value)
    return value


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
    It is deep-frozen on construction and thawed into fresh lists and dicts by
    :meth:`to_json_dict`.
    """

    interview: tuple[InterviewItemView, ...]
    evidence_seed: Mapping[str, object]
    existing_plans: tuple[PlanSummary, ...]

    @classmethod
    def build(
        cls,
        *,
        interview: Iterable[Mapping[str, object]],
        seed: Mapping[str, object],
        existing_plans: Iterable[PlanSummary],
    ) -> PlanningBrief:
        frozen_seed = _freeze(seed)
        if not isinstance(frozen_seed, Mapping):  # pragma: no cover - _freeze(Mapping) is a Mapping
            msg = "evidence seed must be a mapping"
            raise TypeError(msg)
        return cls(
            interview=tuple(InterviewItemView.from_spec(item) for item in interview),
            evidence_seed=frozen_seed,
            existing_plans=tuple(existing_plans),
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "questions": [item.to_json_dict() for item in self.interview],
            "seed": _thaw(self.evidence_seed),
            "existing_plans": [plan.to_json_dict() for plan in self.existing_plans],
        }
```

### `planning/application.py`

```python
"""``PlanApplication`` — the one seam every plan adapter goes through.

Before this module, the Web routes, the CLI and the MCP tools each imported
the storage and authoring modules directly and each carried its own copy of
the policy — or forgot to. The readiness gate that refuses to activate an
unevaluable plan lived on exactly one Web route, so two other doors into the
``active`` state (create-with-status, whole-document replacement) let an
unready plan through (issue #7). Policy that lives in an adapter is policy
that exists once per adapter.

The seam fixes that by construction:

* adapters read through :meth:`browse`, :meth:`inspect` and
  :meth:`prepare_planning`, and write only through :meth:`apply` with an
  intent from :mod:`~studyloop.planning.intents`;
* :meth:`apply` runs the readiness check whenever the *resulting* document
  would be active — whichever door it came through — and raises
  :class:`~studyloop.planning.errors.PlanNotReady` before any write;
* results are frozen views (:mod:`~studyloop.planning.views`) and failures are
  domain exceptions (:mod:`~studyloop.planning.errors`) that each adapter maps
  exactly once.

Markdown stays authoritative through the store's atomic replace, and the
SQLite index refresh stays best-effort inside the store/index layer — the
seam changes who may call them, not how they work.

Directory resolution is unchanged: ``STUDYLOOP_PLANS_DIR`` or the settings
state directory, exactly as :func:`studyloop.planning.store.plans_dir` has
always resolved it. Every existing fixture isolates a test that way, so the
constructor takes no path.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, assert_never

from . import authoring, index, store
from .errors import InvalidField, InvalidPlanId, PlanConflict, PlanNotFound, PlanNotReady
from .intents import (
    CreatePlan,
    ImportDocument,
    PlanIntent,
    ReplaceDocument,
    TransitionLifecycle,
)
from .markdown import parse_plan
from .models import PLAN_STATUSES
from .views import (
    CheckpointHistoryView,
    PlanDetail,
    PlanningBrief,
    PlanSummary,
    ReadinessView,
)

if TYPE_CHECKING:
    from .models import StudyPlan

logger = logging.getLogger(__name__)


def _normalise_status(value: str) -> str:
    status = (value or "").strip().lower()
    if status not in PLAN_STATUSES:
        msg = f"status must be one of {PLAN_STATUSES}"
        raise InvalidField(msg)
    return status


class PlanApplication:
    """Application service for study plans: the only writer adapters may use."""

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def browse(self, *, status: str | None = None) -> tuple[PlanSummary, ...]:
        """Summaries of every plan, optionally one lifecycle status only.

        Order is the store's: active plans first, then ascending ``updated``,
        ties broken by id. A document that fails to parse is skipped (and
        logged) by the store rather than hiding the rest.
        """
        wanted = (status or "").strip().lower()
        if wanted and wanted not in PLAN_STATUSES:
            msg = f"status must be one of {PLAN_STATUSES}"
            raise InvalidField(msg)
        return tuple(PlanSummary.from_plan(plan) for plan in store.list_plans(status=wanted))

    def inspect(
        self,
        plan_id: str,
        *,
        include_markdown: bool = False,
        include_history: bool = False,
        history_limit: int = 20,
    ) -> PlanDetail:
        """One plan in full. Raises ``PlanNotFound`` / ``InvalidPlanId``."""
        plan = self._load(plan_id)
        markdown = store.load_plan_text(plan.plan_id) if include_markdown else None
        history = None
        if include_history:
            history = tuple(
                CheckpointHistoryView.from_row(row)
                for row in index.checkpoint_history(plan.plan_id, limit=history_limit)
            )
        return PlanDetail.from_plan(plan, markdown=markdown, history=history)

    def prepare_planning(self) -> PlanningBrief:
        """The interview, the evidence seed and the plans that already exist."""
        return PlanningBrief.build(
            interview=authoring.interview_spec(),
            seed=authoring.seed_from_history(),
            existing_plans=self.browse(),
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def apply(self, intent: PlanIntent) -> PlanDetail:
        """Carry out one intent and return the plan as it now is.

        Raises a :class:`~studyloop.planning.errors.PlanError` subclass and
        writes nothing when the intent is refused.
        """
        if isinstance(intent, CreatePlan):
            return self._create(intent)
        if isinstance(intent, ImportDocument):
            return self._import(intent)
        if isinstance(intent, ReplaceDocument):
            return self._replace(intent)
        if isinstance(intent, TransitionLifecycle):
            return self._transition(intent)
        assert_never(intent)

    def _create(self, intent: CreatePlan) -> PlanDetail:
        title = intent.title.strip()
        if not title:
            msg = "title is required"
            raise InvalidField(msg)
        # Boundary check: the Web body arrives untyped, so a JSON array can
        # reach here despite the annotation.
        if not isinstance(intent.answers, Mapping):
            msg = "answers must be an object"
            raise InvalidField(msg)
        status = _normalise_status(intent.status)
        explicit_id = (intent.plan_id or "").strip()
        try:
            plan_id = (
                store.validate_plan_id(explicit_id) if explicit_id else store.unique_plan_id(title)
            )
        except store.InvalidPlanIdError as exc:
            raise InvalidPlanId(str(exc)) from exc
        plan = authoring.draft_plan(title, dict(intent.answers), plan_id=plan_id, status=status)
        return self._persist_new(plan, overwrite=intent.overwrite)

    def _import(self, intent: ImportDocument) -> PlanDetail:
        plan = self._parse(intent.markdown, plan_id="")
        explicit_id = (intent.plan_id or "").strip()
        if explicit_id:
            plan.plan_id = explicit_id
        return self._persist_new(plan, overwrite=intent.overwrite)

    def _replace(self, intent: ReplaceDocument) -> PlanDetail:
        current = self._load(intent.plan_id)
        replacement = self._parse(intent.markdown, plan_id=current.plan_id)
        # A whole-document edit may not rename the plan or rewrite its birth
        # date: the id is the file, and ``created`` is history.
        replacement.plan_id = current.plan_id
        replacement.created = current.created
        if replacement.status == "active":
            self._assert_can_be_active(replacement)
        store.save_plan(replacement)
        return PlanDetail.from_plan(replacement)

    def _transition(self, intent: TransitionLifecycle) -> PlanDetail:
        plan = self._load(intent.plan_id)
        status = _normalise_status(intent.status)
        if status == "active":
            self._assert_can_be_active(plan)
        plan.status = status
        store.save_plan(plan)
        return PlanDetail.from_plan(plan)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _persist_new(self, plan: StudyPlan, *, overwrite: bool) -> PlanDetail:
        """Gate, then create. The gate runs first so a refusal writes nothing."""
        if plan.status == "active":
            self._assert_can_be_active(plan)
        try:
            store.create_plan(plan, overwrite=overwrite)
        except store.PlanExistsError as exc:
            raise PlanConflict(str(exc)) from exc
        except store.InvalidPlanIdError as exc:
            raise InvalidPlanId(str(exc)) from exc
        return PlanDetail.from_plan(plan)

    @staticmethod
    def _assert_can_be_active(plan: StudyPlan) -> None:
        """The single readiness gate: every path into ``active`` ends here."""
        view = ReadinessView.from_plan(plan)
        if not view.ready:
            raise PlanNotReady(view)

    @staticmethod
    def _load(plan_id: str) -> StudyPlan:
        try:
            return store.load_plan(plan_id)
        except store.PlanNotFoundError as exc:
            raise PlanNotFound(str(exc)) from exc
        except store.InvalidPlanIdError as exc:
            raise InvalidPlanId(str(exc)) from exc

    @staticmethod
    def _parse(markdown: str, *, plan_id: str) -> StudyPlan:
        """Parse a caller-supplied document; the parser is lenient, this is the last boundary."""
        try:
            return parse_plan(markdown, plan_id=plan_id)
        except Exception as exc:
            msg = f"unparseable markdown: {exc}"
            raise InvalidField(msg) from exc
```

## 4. `planning/__init__.py` diff

```diff
diff --git a/packages/studyloop/src/studyloop/planning/__init__.py b/packages/studyloop/src/studyloop/planning/__init__.py
index 80387487..ce78c6e5 100644
--- a/packages/studyloop/src/studyloop/planning/__init__.py
+++ b/packages/studyloop/src/studyloop/planning/__init__.py
@@ -11,6 +11,7 @@ mission-first, learning records as ADRs, primary sources over recall.

 from __future__ import annotations

+from .application import PlanApplication
 from .authoring import (
     INTERVIEW,
     InterviewQuestion,
@@ -19,6 +20,15 @@ from .authoring import (
     readiness,
     seed_from_history,
 )
+from .errors import (
+    InvalidField,
+    InvalidMilestone,
+    InvalidPlanId,
+    PlanConflict,
+    PlanError,
+    PlanNotFound,
+    PlanNotReady,
+)
 from .evaluation import (
     CHECKPOINT_PHASES,
     ConceptEvidence,
@@ -27,6 +37,13 @@ from .evaluation import (
     evaluate_plan,
 )
 from .index import checkpoint_history, indexed_plans, reindex_all
+from .intents import (
+    CreatePlan,
+    ImportDocument,
+    PlanIntent,
+    ReplaceDocument,
+    TransitionLifecycle,
+)
 from .markdown import (
     MISSION_SUBSECTION_HEADINGS,
     PLAN_SECTION_HEADINGS,
@@ -66,6 +83,19 @@ from .store import (
     save_plan,
     unique_plan_id,
 )
+from .views import (
+    CheckpointHistoryView,
+    CheckpointView,
+    InterviewItemView,
+    LearningRecordView,
+    MilestoneView,
+    MissionView,
+    PlanDetail,
+    PlanningBrief,
+    PlanSummary,
+    ReadinessView,
+    ResourceView,
+)

 __all__ = [
     "CHECKPOINT_PHASES",
@@ -74,20 +104,44 @@ __all__ = [
     "PLAN_SECTION_HEADINGS",
     "PLAN_STATUSES",
     "Checkpoint",
+    "CheckpointHistoryView",
+    "CheckpointView",
     "ConceptEvidence",
+    "CreatePlan",
     "HerdrBackend",
+    "ImportDocument",
+    "InterviewItemView",
     "InterviewQuestion",
+    "InvalidField",
+    "InvalidMilestone",
+    "InvalidPlanId",
     "InvalidPlanIdError",
     "LearningRecord",
+    "LearningRecordView",
     "Milestone",
+    "MilestoneView",
     "Mission",
+    "MissionView",
     "Multiplexer",
+    "PlanApplication",
+    "PlanConflict",
+    "PlanDetail",
+    "PlanError",
     "PlanEvaluation",
     "PlanExistsError",
+    "PlanIntent",
+    "PlanNotFound",
     "PlanNotFoundError",
+    "PlanNotReady",
+    "PlanSummary",
+    "PlanningBrief",
+    "ReadinessView",
+    "ReplaceDocument",
     "Resource",
+    "ResourceView",
     "StudyPlan",
     "TmuxBackend",
+    "TransitionLifecycle",
     "available_backends",
     "checkpoint_history",
     "create_plan",
```

## 5. Web adapter — `web/routes/plans.py` diff

```diff
diff --git a/packages/studyloop/src/studyloop/web/routes/plans.py b/packages/studyloop/src/studyloop/web/routes/plans.py
index ffd1de44..75483bcc 100644
--- a/packages/studyloop/src/studyloop/web/routes/plans.py
+++ b/packages/studyloop/src/studyloop/web/routes/plans.py
@@ -9,12 +9,22 @@ Write paths are deliberately narrow: create from an interview payload, patch
 metadata/milestones, toggle one milestone, and run an evaluation checkpoint.
 Free-form Markdown replacement is allowed but validated by re-parsing, so a
 malformed body is rejected instead of corrupting a plan.
+
+Policy lives in :class:`~studyloop.planning.PlanApplication`, not here. Every
+path that can make a plan active — create-with-status, document import,
+whole-document replacement, status transition — goes through ``apply`` and is
+refused by the same readiness gate with the same 422 body. This module only
+maps domain errors to status codes (design §2); it holds no rule of its own.
+
+Still on direct storage imports until Phase 2 moves them onto the seam:
+evaluation (``AssessPlan``), field/milestone PATCH (``RevisePlan``), the
+milestone toggle (``SetMilestone``) and delete (``DeletePlan``).
 """

 from __future__ import annotations

 import logging
-from typing import Annotated
+from typing import Annotated, Any

 from fastapi import APIRouter, Body, HTTPException, Query
 from fastapi.responses import PlainTextResponse
@@ -22,24 +32,27 @@ from fastapi.responses import PlainTextResponse
 from studyloop.planning import (
     CHECKPOINT_PHASES,
     PLAN_STATUSES,
-    checkpoint_history,
-    create_plan,
-    draft_plan,
+    CreatePlan,
+    ImportDocument,
+    InvalidField,
+    InvalidMilestone,
+    InvalidPlanId,
+    PlanApplication,
+    PlanConflict,
+    PlanDetail,
+    PlanError,
+    PlanIntent,
+    PlanNotFound,
+    PlanNotReady,
+    ReplaceDocument,
+    TransitionLifecycle,
     evaluate_and_record,
     evaluate_plan,
-    interview_spec,
-    list_plans,
     load_plan,
-    load_plan_text,
-    parse_plan,
-    readiness,
     save_plan,
-    seed_from_history,
-    unique_plan_id,
 )
 from studyloop.planning.store import (
     InvalidPlanIdError,
-    PlanExistsError,
     PlanNotFoundError,
     delete_plan,
 )
@@ -49,7 +62,59 @@ logger = logging.getLogger(__name__)
 router = APIRouter()


+# ---------------------------------------------------------------------------
+# Seam access and the one error mapping (design §2)
+# ---------------------------------------------------------------------------
+
+
+def _application() -> PlanApplication:
+    return PlanApplication()
+
+
+def _http_error(exc: PlanError) -> HTTPException:
+    """Map a domain refusal to its status code — the only place this happens."""
+    if isinstance(exc, PlanNotFound):
+        return HTTPException(status_code=404, detail=str(exc))
+    if isinstance(exc, InvalidPlanId | InvalidField):
+        return HTTPException(status_code=400, detail=str(exc))
+    if isinstance(exc, PlanConflict):
+        return HTTPException(status_code=409, detail=str(exc))
+    if isinstance(exc, PlanNotReady):
+        return HTTPException(
+            status_code=422,
+            detail={"message": str(exc), **exc.readiness.to_json_dict()},
+        )
+    if isinstance(exc, InvalidMilestone):
+        return HTTPException(status_code=404, detail=str(exc))
+    logger.error("unmapped plan error %s", type(exc).__name__, exc_info=exc)
+    return HTTPException(status_code=500, detail="plan operation failed")
+
+
+def _inspect(plan_id: str, **options: Any) -> PlanDetail:
+    try:
+        return _application().inspect(plan_id, **options)
+    except PlanError as exc:
+        raise _http_error(exc) from exc
+
+
+def _apply(intent: PlanIntent) -> PlanDetail:
+    try:
+        return _application().apply(intent)
+    except PlanError as exc:
+        raise _http_error(exc) from exc
+
+
+def _written(detail: PlanDetail, **flags: bool) -> dict[str, Any]:
+    """The body every successful write returns: a flag, the summary, readiness."""
+    return {
+        **flags,
+        "plan": detail.summary.to_json_dict(),
+        "readiness": detail.readiness.to_json_dict(),
+    }
+
+
 def _load_or_404(plan_id: str):
+    """Load the mutable model for the paths that Phase 2 has not migrated yet."""
     try:
         return load_plan(plan_id)
     except PlanNotFoundError as exc:
@@ -68,9 +133,12 @@ def get_plans(
     status: str = Query("", pattern="^(|draft|active|paused|complete|abandoned)$"),
 ) -> dict:
     """List plans (summaries only) for the left-pane Study Plan section."""
-    plans = list_plans(status=status)
+    try:
+        plans = _application().browse(status=status or None)
+    except PlanError as exc:  # pragma: no cover - the Query pattern already refuses
+        raise _http_error(exc) from exc
     return {
-        "plans": [plan.summary() for plan in plans],
+        "plans": [plan.to_json_dict() for plan in plans],
         "count": len(plans),
         "statuses": list(PLAN_STATUSES),
     }
@@ -79,63 +147,31 @@ def get_plans(
 @router.get("/plans/interview")
 def get_interview() -> dict:
     """Return the plan-creation interview plus data-grounded seed suggestions."""
-    return {"questions": interview_spec(), "seed": seed_from_history()}
+    brief = _application().prepare_planning().to_json_dict()
+    return {"questions": brief["questions"], "seed": brief["seed"]}


 @router.get("/plans/{plan_id}")
 def get_plan(plan_id: str) -> dict:
     """Return one plan: parsed structure, raw Markdown, and readiness."""
-    plan = _load_or_404(plan_id)
-    return {
-        "plan": plan.summary(),
-        "markdown": load_plan_text(plan.plan_id),
-        "mission": {
-            "why": plan.mission.why,
-            "success": plan.mission.success,
-            "constraints": plan.mission.constraints,
-            "out_of_scope": plan.mission.out_of_scope,
-        },
-        "milestones": [
-            {
-                "index": i,
-                "title": m.title,
-                "done": m.done,
-                "concepts": m.concepts,
-                "notes": m.notes,
-            }
-            for i, m in enumerate(plan.milestones)
-        ],
-        "learning_records": [
-            {"number": r.number, "title": r.title, "body": r.body, "status": r.status}
-            for r in plan.learning_records
-        ],
-        "resources": [{"label": r.label, "url": r.url, "note": r.note} for r in plan.resources],
-        "checkpoints": [
-            {
-                "phase": c.phase,
-                "verdict": c.verdict,
-                "at": c.at,
-                "summary": c.summary,
-                "study_id": c.study_id,
-            }
-            for c in plan.checkpoints
-        ],
-        "readiness": readiness(plan),
-    }
+    return _inspect(plan_id, include_markdown=True).to_json_dict()


 @router.get("/plans/{plan_id}/markdown", response_class=PlainTextResponse)
 def get_plan_markdown(plan_id: str) -> str:
     """Raw Markdown for a plan — the download / copy-to-agent path."""
-    _load_or_404(plan_id)
-    return load_plan_text(plan_id)
+    markdown = _inspect(plan_id, include_markdown=True).markdown
+    return markdown or ""


 @router.get("/plans/{plan_id}/history")
 def get_plan_history(plan_id: str, limit: int = Query(20, ge=1, le=200)) -> dict:
     """Durable checkpoint log from the sessions DB."""
-    _load_or_404(plan_id)
-    return {"plan_id": plan_id, "checkpoints": checkpoint_history(plan_id, limit=limit)}
+    detail = _inspect(plan_id, include_history=True, history_limit=limit)
+    return {
+        "plan_id": plan_id,
+        "checkpoints": [entry.to_json_dict() for entry in detail.history or ()],
+    }


 # ---------------------------------------------------------------------------
@@ -186,87 +222,45 @@ def post_plan(payload: Annotated[dict, Body()]) -> dict:

     ``{"markdown": "..."}`` imports a document verbatim (validated by
     re-parsing).  Otherwise ``{"title", "answers"}`` drafts one from the
-    interview, which is what the agent and the UI wizard both use.
+    interview, which is what the agent and the UI wizard both use. Either way
+    a document that would be active is readiness-gated by the seam (422).
     """
+    plan_id = str(payload.get("plan_id", "")).strip() or None
+    overwrite = bool(payload.get("overwrite", False))
     raw_markdown = payload.get("markdown")
+    intent: PlanIntent
     if raw_markdown:
-        try:
-            plan = parse_plan(str(raw_markdown))
-        except Exception as exc:
-            raise HTTPException(status_code=400, detail=f"unparseable markdown: {exc}") from exc
-        if not payload.get("plan_id") and not plan.plan_id:
-            plan.plan_id = unique_plan_id(plan.title)
+        intent = ImportDocument(markdown=str(raw_markdown), plan_id=plan_id, overwrite=overwrite)
     else:
-        title = str(payload.get("title", "")).strip()
-        if not title:
-            raise HTTPException(status_code=400, detail="title is required")
-        answers = payload.get("answers") or {}
-        if not isinstance(answers, dict):
-            raise HTTPException(status_code=400, detail="answers must be an object")
-        status = str(payload.get("status", "draft")).strip().lower()
-        if status not in PLAN_STATUSES:
-            raise HTTPException(status_code=400, detail=f"status must be one of {PLAN_STATUSES}")
-        plan = draft_plan(
-            title,
-            answers,
-            plan_id=str(payload.get("plan_id", "")).strip() or unique_plan_id(title),
-            status=status,
+        intent = CreatePlan(
+            title=str(payload.get("title", "")),
+            answers=payload.get("answers") or {},
+            plan_id=plan_id,
+            status=str(payload.get("status", "draft")),
+            overwrite=overwrite,
         )
+    return _written(_apply(intent), created=True)

-    try:
-        create_plan(plan, overwrite=bool(payload.get("overwrite", False)))
-    except PlanExistsError as exc:
-        raise HTTPException(status_code=409, detail=str(exc)) from exc
-    except InvalidPlanIdError as exc:
-        raise HTTPException(status_code=400, detail=str(exc)) from exc
-
-    return {"created": True, "plan": plan.summary(), "readiness": readiness(plan)}

+def _field_updates(payload: dict) -> dict[str, Any]:
+    """Validate the in-place field edits Phase 2 will move onto ``RevisePlan``.

-@router.patch("/plans/{plan_id}")
-def patch_plan(plan_id: str, payload: Annotated[dict, Body()]) -> dict:
-    """Update plan fields in place.
-
-    Accepts ``status``, ``title``, ``topics``, ``target_date``,
-    ``energy_floor``, ``review_cadence_days``, ``notes``, ``milestones``
-    (full replacement), and ``markdown`` (whole-document replacement).
+    Validation happens *before* any write so a bad field never lands after a
+    status change has already been saved — the same all-or-nothing the single
+    ``save_plan`` used to give.
     """
-    plan = _load_or_404(plan_id)
-
-    if "markdown" in payload:
-        try:
-            replacement = parse_plan(str(payload["markdown"]), plan_id=plan.plan_id)
-        except Exception as exc:
-            raise HTTPException(status_code=400, detail=f"unparseable markdown: {exc}") from exc
-        replacement.plan_id = plan.plan_id
-        replacement.created = plan.created
-        save_plan(replacement)
-        return {"updated": True, "plan": replacement.summary(), "readiness": readiness(replacement)}
-
-    if "status" in payload:
-        status = str(payload["status"]).strip().lower()
-        if status not in PLAN_STATUSES:
-            raise HTTPException(status_code=400, detail=f"status must be one of {PLAN_STATUSES}")
-        if status == "active":
-            check = readiness(plan)
-            if not check["ready"]:
-                raise HTTPException(
-                    status_code=422,
-                    detail={"message": "plan is not ready to activate", **check},
-                )
-        plan.status = status
-
+    updates: dict[str, Any] = {}
     if "title" in payload:
         title = str(payload["title"]).strip()
         if not title:
             raise HTTPException(status_code=400, detail="title cannot be empty")
-        plan.title = title
+        updates["title"] = title
     if "topics" in payload:
-        plan.topics = [str(t).strip() for t in payload["topics"] if str(t).strip()]
+        updates["topics"] = [str(t).strip() for t in payload["topics"] if str(t).strip()]
     if "target_date" in payload:
-        plan.target_date = str(payload["target_date"]).strip()
+        updates["target_date"] = str(payload["target_date"]).strip()
     if "notes" in payload:
-        plan.notes = str(payload["notes"])
+        updates["notes"] = str(payload["notes"])
     for field_name, lo, hi in (("energy_floor", 1, 10), ("review_cadence_days", 1, 90)):
         if field_name in payload:
             try:
@@ -275,15 +269,14 @@ def patch_plan(plan_id: str, payload: Annotated[dict, Body()]) -> dict:
                 raise HTTPException(
                     status_code=400, detail=f"{field_name} must be an integer"
                 ) from exc
-            setattr(plan, field_name, max(lo, min(hi, value)))
-
+            updates[field_name] = max(lo, min(hi, value))
     if "milestones" in payload:
         from studyloop.planning.models import Milestone

         items = payload["milestones"]
         if not isinstance(items, list):
             raise HTTPException(status_code=400, detail="milestones must be a list")
-        plan.milestones = [
+        updates["milestones"] = [
             Milestone(
                 title=str(item.get("title", "")).strip() or "Untitled milestone",
                 done=bool(item.get("done", False)),
@@ -293,9 +286,40 @@ def patch_plan(plan_id: str, payload: Annotated[dict, Body()]) -> dict:
             for item in items
             if isinstance(item, dict)
         ]
+    return updates

-    save_plan(plan)
-    return {"updated": True, "plan": plan.summary(), "readiness": readiness(plan)}
+
+@router.patch("/plans/{plan_id}")
+def patch_plan(plan_id: str, payload: Annotated[dict, Body()]) -> dict:
+    """Update plan fields in place.
+
+    Accepts ``status``, ``title``, ``topics``, ``target_date``,
+    ``energy_floor``, ``review_cadence_days``, ``notes``, ``milestones``
+    (full replacement), and ``markdown`` (whole-document replacement).
+    """
+    if "markdown" in payload:
+        replaced = _apply(ReplaceDocument(plan_id=plan_id, markdown=str(payload["markdown"])))
+        return _written(replaced, updated=True)
+
+    # Existence first (404 before any 400), then validate every field edit,
+    # then transition, then edit: nothing is written if any part of the body
+    # is unusable — the all-or-nothing the single ``save_plan`` used to give.
+    detail = _inspect(plan_id)
+    updates = _field_updates(payload)
+
+    if "status" in payload:
+        detail = _apply(TransitionLifecycle(plan_id=plan_id, status=str(payload["status"])))
+
+    if updates or "status" not in payload:
+        # Field edits, or an empty body — which is still a save, as it always
+        # was (it touches ``updated``). Phase 2 moves this onto ``RevisePlan``.
+        plan = _load_or_404(plan_id)
+        for name, value in updates.items():
+            setattr(plan, name, value)
+        save_plan(plan)
+        detail = PlanDetail.from_plan(plan)
+
+    return _written(detail, updated=True)


 @router.post("/plans/{plan_id}/milestones/{index}/toggle")
```

## 6. CLI adapter — `cli/_plan.py` diff

```diff
diff --git a/packages/studyloop/src/studyloop/cli/_plan.py b/packages/studyloop/src/studyloop/cli/_plan.py
index 4752d7a4..45de4c1b 100644
--- a/packages/studyloop/src/studyloop/cli/_plan.py
+++ b/packages/studyloop/src/studyloop/cli/_plan.py
@@ -6,13 +6,19 @@ default human output stays readable in a terminal sidebar.

 ``plan evaluate`` prints the Markdown block by default: that is what an agent
 pastes into the conversation at each of the three session checkpoints.
+
+``list``, ``show`` and ``status`` read and write through
+:class:`~studyloop.planning.PlanApplication`, so the activation refusal here is
+the same refusal the Web API gives — same blockers, same nudges, no write.
+``new``, ``interview``, ``evaluate``, ``milestone`` and ``record`` move onto
+the seam in Phase 2 and still use the storage modules directly.
 """

 from __future__ import annotations

 import json
 from pathlib import Path
-from typing import NoReturn
+from typing import TYPE_CHECKING, NoReturn

 import click
 from rich.table import Table
@@ -20,17 +26,20 @@ from rich.table import Table
 from studyloop.cli._shared import console
 from studyloop.planning import (
     PLAN_STATUSES,
+    PlanApplication,
+    PlanError,
+    PlanNotFound,
+    PlanNotReady,
+    ReadinessView,
     StudyPlan,
+    TransitionLifecycle,
     create_plan,
     draft_plan,
     evaluate_and_record,
     evaluate_plan,
     interview_spec,
-    list_plans,
     load_plan,
-    load_plan_text,
     plans_dir,
-    readiness,
     record_learning,
     reindex_all,
     save_plan,
@@ -43,6 +52,9 @@ from studyloop.planning.store import (
     PlanNotFoundError,
 )

+if TYPE_CHECKING:
+    from studyloop.planning import PlanDetail
+

 def _fail(message: str) -> NoReturn:
     """Print an error and exit non-zero, never a traceback.
@@ -55,7 +67,22 @@ def _fail(message: str) -> NoReturn:
     raise SystemExit(1)


+def _fail_for(exc: PlanError, plan_id: str) -> NoReturn:
+    """Map a seam refusal to the CLI's message and exit code (design §2)."""
+    if isinstance(exc, PlanNotFound):
+        _fail(f"No study plan with id {plan_id!r}. Try: studyloop plan list")
+    _fail(str(exc))
+
+
+def _inspect(plan_id: str, *, include_markdown: bool = False) -> PlanDetail:
+    try:
+        return PlanApplication().inspect(plan_id, include_markdown=include_markdown)
+    except PlanError as exc:
+        _fail_for(exc, plan_id)
+
+
 def _load(plan_id: str) -> StudyPlan:
+    """Load the mutable model for the commands Phase 2 has not migrated yet."""
     try:
         return load_plan(plan_id)
     except PlanNotFoundError:
@@ -64,18 +91,25 @@ def _load(plan_id: str) -> StudyPlan:
         _fail(str(exc))


-def _print_readiness(check: dict) -> None:
+def _print_readiness(check: ReadinessView) -> None:
     """Show what still blocks activation, then what would merely improve it."""
-    if check["blockers"]:
+    if check.blockers:
         console.print("[yellow]Not ready to activate:[/yellow]")
-        for item in check["blockers"]:
+        for item in check.blockers:
             console.print(f"  [red]•[/red] {item}")
     else:
         console.print("[green]Ready to activate.[/green]")
-    for item in check["nudges"]:
+    for item in check.nudges:
         console.print(f"  [dim]• {item}[/dim]")


+def _refuse_activation(check: ReadinessView) -> NoReturn:
+    """The one way every command says no to activating an incomplete plan."""
+    console.print(f"[red]Cannot activate {check.plan_id!r} — the plan is incomplete.[/red]")
+    _print_readiness(check)
+    raise SystemExit(1)
+
+
 @click.group("plan")
 def plan_group() -> None:
     """Create, inspect, and evaluate structured study plans."""
@@ -91,9 +125,9 @@ def plan_group() -> None:
 @click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
 def plan_list(status: str | None, as_json: bool) -> None:
     """List study plans."""
-    plans = list_plans(status=status or "")
+    plans = PlanApplication().browse(status=status)
     if as_json:
-        click.echo(json.dumps([p.summary() for p in plans], indent=2))
+        click.echo(json.dumps([p.to_json_dict() for p in plans], indent=2))
         return
     if not plans:
         console.print("[dim]No study plans yet. Create one: studyloop plan new --title ...[/dim]")
@@ -106,15 +140,12 @@ def plan_list(status: str | None, as_json: bool) -> None:
     table.add_column("Progress")
     table.add_column("Next", style="dim")
     for plan in plans:
-        # Bind once: calling next_milestone() twice both re-walks the milestone
-        # list and leaves the Optional unnarrowed for the type checker.
-        nxt = plan.next_milestone()
         table.add_row(
             plan.plan_id,
             plan.title,
             plan.status,
             f"{plan.milestone_done}/{plan.milestone_total} ({plan.progress_pct}%)",
-            nxt.title if nxt else "—",
+            plan.next_milestone or "—",
         )
     console.print(table)

@@ -125,46 +156,42 @@ def plan_list(status: str | None, as_json: bool) -> None:
 @click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
 def plan_show(plan_id: str, as_markdown: bool, as_json: bool) -> None:
     """Show one study plan."""
-    plan = _load(plan_id)
+    detail = _inspect(plan_id, include_markdown=as_markdown)
     if as_markdown:
-        click.echo(load_plan_text(plan.plan_id))
+        click.echo(detail.markdown or "")
         return
     if as_json:
         click.echo(
             json.dumps(
                 {
-                    "plan": plan.summary(),
-                    "mission": {
-                        "why": plan.mission.why,
-                        "success": plan.mission.success,
-                        "constraints": plan.mission.constraints,
-                        "out_of_scope": plan.mission.out_of_scope,
-                    },
+                    "plan": detail.summary.to_json_dict(),
+                    "mission": detail.mission.to_json_dict(),
                     "milestones": [
-                        {"title": m.title, "done": m.done, "concepts": m.concepts}
-                        for m in plan.milestones
+                        {"title": m.title, "done": m.done, "concepts": list(m.concepts)}
+                        for m in detail.milestones
                     ],
-                    "readiness": readiness(plan),
+                    "readiness": detail.readiness.to_json_dict(),
                 },
                 indent=2,
             )
         )
         return

+    plan = detail.summary
     console.print(f"[bold]{plan.title}[/bold]  [dim]({plan.plan_id})[/dim]")
     console.print(f"Status: {plan.status}   Progress: {plan.milestone_done}/{plan.milestone_total}")
-    if plan.mission.why:
-        console.print(f"\n[bold]Why[/bold]\n  {plan.mission.why}")
-    if plan.milestones:
+    if detail.mission.why:
+        console.print(f"\n[bold]Why[/bold]\n  {detail.mission.why}")
+    if detail.milestones:
         console.print("\n[bold]Milestones[/bold]")
-        for index, milestone in enumerate(plan.milestones):
+        for milestone in detail.milestones:
             box = "x" if milestone.done else " "
             concepts = (
                 f"  [dim]({', '.join(milestone.concepts)})[/dim]" if milestone.concepts else ""
             )
-            console.print(f"  [{box}] {index}. {milestone.title}{concepts}")
+            console.print(f"  [{box}] {milestone.index}. {milestone.title}{concepts}")
     console.print()
-    _print_readiness(readiness(plan))
+    _print_readiness(detail.readiness)


 @plan_group.command("new")
@@ -220,12 +247,10 @@ def plan_new(
         plan_id=unique_plan_id(title),
     )

-    check = readiness(plan)
+    check = ReadinessView.from_plan(plan)
     if activate:
-        if not check["ready"]:
-            console.print(f"[red]Cannot activate {plan.plan_id!r} — the plan is incomplete.[/red]")
-            _print_readiness(check)
-            raise SystemExit(1)
+        if not check.ready:
+            _refuse_activation(check)
         plan.status = "active"

     try:
@@ -237,7 +262,10 @@ def plan_new(

     if as_json:
         click.echo(
-            json.dumps({"plan": plan.summary(), "readiness": check, "path": str(path)}, indent=2)
+            json.dumps(
+                {"plan": plan.summary(), "readiness": check.to_json_dict(), "path": str(path)},
+                indent=2,
+            )
         )
         return
     console.print(f"[green]Created[/green] {plan.plan_id} → {path}")
@@ -330,18 +358,16 @@ def plan_status(plan_id: str, status: str) -> None:
     """Change a plan's lifecycle state.

     Activation is refused while the plan is missing a mission, success
-    criteria, or milestones — an unevaluable plan must not look active.
+    criteria, or milestones — an unevaluable plan must not look active. The
+    refusal is the seam's, so it is the same one the Web API gives.
     """
-    plan = _load(plan_id)
-    if status == "active":
-        check = readiness(plan)
-        if not check["ready"]:
-            console.print(f"[red]Cannot activate {plan.plan_id!r} — the plan is incomplete.[/red]")
-            _print_readiness(check)
-            raise SystemExit(1)
-    plan.status = status
-    save_plan(plan)
-    console.print(f"[green]{plan.plan_id}[/green] → {status}")
+    try:
+        detail = PlanApplication().apply(TransitionLifecycle(plan_id=plan_id, status=status))
+    except PlanNotReady as exc:
+        _refuse_activation(exc.readiness)
+    except PlanError as exc:
+        _fail_for(exc, plan_id)
+    console.print(f"[green]{detail.summary.plan_id}[/green] → {status}")


 @plan_group.command("record")
```

## 7. New tests (full source)

### `tests/test_plan_application.py`

```python
"""``PlanApplication`` — the one seam every plan adapter must go through.

These tests are written against the seam's contract (design §1, decisions
D-2/D-3/D-4), not against any adapter: the same invariants hold whether the
caller is the Web API, the CLI, or an MCP tool.

The load-bearing invariant is *activation is readiness-gated on every entry
path*: create-with-status, whole-document replacement, document import and a
lifecycle transition all refuse to produce an active-but-unready plan, all
raise the same ``PlanNotReady`` carrying the same ``ReadinessView``, and none
of them writes anything before refusing.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from studyloop.planning import store
from studyloop.planning.application import PlanApplication
from studyloop.planning.errors import (
    InvalidField,
    InvalidPlanId,
    PlanConflict,
    PlanNotFound,
    PlanNotReady,
)
from studyloop.planning.intents import (
    CreatePlan,
    ImportDocument,
    ReplaceDocument,
    TransitionLifecycle,
)
from studyloop.planning.models import Milestone, Mission, StudyPlan
from studyloop.planning.views import PlanDetail, PlanSummary, ReadinessView


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture
def app() -> PlanApplication:
    return PlanApplication()


READY_ANSWERS: dict[str, object] = {
    "why": "Ship analytics queries without help",
    "success": ["Write a RANK() query unaided"],
    "topics": ["sql"],
    "out_of_scope": ["Query planner internals"],
    "milestones": [
        {"title": "OVER clause", "concepts": ["window function"]},
        {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
    ],
    "resources": [{"label": "PostgreSQL docs", "url": "https://www.postgresql.org/docs/"}],
}


def _ready_plan(plan_id: str, *, status: str = "draft", updated: str = "") -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title=plan_id.replace("-", " ").title(),
        status=status,
        topics=["sql"],
        mission=Mission(why="Because", success=["Do a thing"]),
        milestones=[Milestone(title="Step one", concepts=["thing"])],
    )
    if updated:
        plan.updated = updated
        plan.created = updated
    return plan


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------


def test_browse_filters_by_status_deterministically(app: PlanApplication) -> None:
    # Three documents whose on-disk order (alphabetical) differs from the
    # order the seam must return: active first, then ascending ``updated``,
    # then plan id — the same key ``store.list_plans`` has always used, so the
    # Web list and the CLI table do not reorder when they migrate.
    store.create_plan(_ready_plan("a-newest-draft", updated="2026-03-01T00:00:00+00:00"))
    store.create_plan(_ready_plan("b-oldest-draft", updated="2026-01-01T00:00:00+00:00"))
    store.create_plan(_ready_plan("c-active", status="active", updated="2026-02-01T00:00:00+00:00"))

    everything = app.browse()
    assert [p.plan_id for p in everything] == ["c-active", "b-oldest-draft", "a-newest-draft"]
    assert all(isinstance(p, PlanSummary) for p in everything)

    drafts = app.browse(status="draft")
    assert [p.plan_id for p in drafts] == ["b-oldest-draft", "a-newest-draft"]
    assert app.browse(status="draft") == drafts, "repeat calls must not reorder"
    assert [p.plan_id for p in app.browse(status="active")] == ["c-active"]
    assert app.browse(status="paused") == ()


def test_browse_rejects_an_unknown_status(app: PlanApplication) -> None:
    with pytest.raises(InvalidField):
        app.browse(status="bogus")


def test_inspect_unknown_id_raises_plan_not_found(app: PlanApplication) -> None:
    with pytest.raises(PlanNotFound):
        app.inspect("nothing-here")


def test_inspect_traversal_id_raises_invalid_plan_id(app: PlanApplication) -> None:
    with pytest.raises(InvalidPlanId):
        app.inspect("../../etc/passwd")


def test_inspect_carries_markdown_and_history_only_on_request(app: PlanApplication) -> None:
    store.create_plan(_ready_plan("demo"))

    bare = app.inspect("demo")
    assert isinstance(bare, PlanDetail)
    assert bare.markdown is None
    assert bare.history is None
    assert bare.summary.plan_id == "demo"
    assert bare.readiness.ready is True
    assert [m.title for m in bare.milestones] == ["Step one"]

    full = app.inspect("demo", include_markdown=True, include_history=True)
    assert full.markdown is not None and full.markdown.startswith("---")
    assert full.history == ()  # nothing recorded yet, but the log was asked for


# ---------------------------------------------------------------------------
# Activation is readiness-gated on EVERY entry path (D-2)
# ---------------------------------------------------------------------------


def test_create_unready_active_raises_plan_not_ready(app: PlanApplication) -> None:
    with pytest.raises(PlanNotReady) as caught:
        app.apply(CreatePlan(title="Vague", answers={}, status="active"))

    refusal = caught.value.readiness
    assert isinstance(refusal, ReadinessView)
    assert refusal.ready is False
    assert refusal.blockers
    # Refused before any write: no document, no id claimed.
    assert store.list_plan_ids() == []
    assert app.browse(status="active") == ()


def test_transition_unready_to_active_raises_plan_not_ready(app: PlanApplication) -> None:
    app.apply(CreatePlan(title="Vague", answers={}))

    with pytest.raises(PlanNotReady) as caught:
        app.apply(TransitionLifecycle(plan_id="vague", status="active"))

    assert caught.value.readiness.ready is False
    assert app.inspect("vague").summary.status == "draft"


def test_replace_unready_active_document_raises_and_does_not_persist(
    app: PlanApplication,
) -> None:
    app.apply(CreatePlan(title="SQL Window Functions", answers=READY_ANSWERS))
    before = store.load_plan_text("sql-window-functions")

    head, _, _body = before.partition("\n## Milestones")
    unready_active = head.replace("status: draft", "status: active") + "\n"

    with pytest.raises(PlanNotReady) as caught:
        app.apply(ReplaceDocument(plan_id="sql-window-functions", markdown=unready_active))

    assert caught.value.readiness.ready is False
    assert store.load_plan_text("sql-window-functions") == before, "document must be untouched"
    detail = app.inspect("sql-window-functions")
    assert detail.summary.status == "draft"
    assert detail.summary.milestone_total == 2


def test_import_unready_active_document_raises_plan_not_ready(app: PlanApplication) -> None:
    doc = (
        "---\nid: imported\ntitle: Imported Plan\nstatus: active\n---\n\n"
        "# Imported Plan\n\n## Milestones\n\n_No milestones yet._\n"
    )
    with pytest.raises(PlanNotReady) as caught:
        app.apply(ImportDocument(markdown=doc))

    assert caught.value.readiness.ready is False
    assert store.list_plan_ids() == []


def test_import_document_keeps_its_frontmatter_id_and_stays_draft(app: PlanApplication) -> None:
    doc = (
        "---\nid: imported\ntitle: Imported Plan\nstatus: draft\n---\n\n"
        "# Imported Plan\n\n## Milestones\n\n- [ ] **Step** `(concepts: x)`\n"
    )
    detail = app.apply(ImportDocument(markdown=doc))
    assert detail.summary.plan_id == "imported"
    assert detail.summary.status == "draft"
    assert store.list_plan_ids() == ["imported"]


def test_create_transition_replace_refusal_payload_is_identical(app: PlanApplication) -> None:
    # Door 1: create-with-status.
    with pytest.raises(PlanNotReady) as via_create:
        app.apply(CreatePlan(title="Vague", answers={}, plan_id="vague", status="active"))

    # Door 2: lifecycle transition on the same (now persisted) draft.
    app.apply(CreatePlan(title="Vague", answers={}, plan_id="vague"))
    with pytest.raises(PlanNotReady) as via_transition:
        app.apply(TransitionLifecycle(plan_id="vague", status="active"))

    # Door 3: whole-document replacement whose frontmatter says active.
    active_doc = store.load_plan_text("vague").replace("status: draft", "status: active")
    with pytest.raises(PlanNotReady) as via_replace:
        app.apply(ReplaceDocument(plan_id="vague", markdown=active_doc))

    # Door 4: importing that same document as a new plan.
    with pytest.raises(PlanNotReady) as via_import:
        app.apply(ImportDocument(markdown=active_doc, plan_id="vague-2"))

    payloads = [
        exc.value.readiness.to_json_dict()
        for exc in (via_create, via_transition, via_replace, via_import)
    ]
    # The import carries its own id; everything else about the refusal is the
    # same three blockers and the same nudges, in the same order.
    for payload in payloads:
        payload.pop("plan_id")
    assert payloads[0] == payloads[1] == payloads[2] == payloads[3]
    assert payloads[0]["ready"] is False
    assert len(payloads[0]["blockers"]) == 3
    assert str(via_create.value) == "plan is not ready to activate"

    # And still nothing is active.
    assert app.browse(status="active") == ()


# ---------------------------------------------------------------------------
# Writes that are allowed
# ---------------------------------------------------------------------------


def test_replace_preserves_id_and_created(app: PlanApplication) -> None:
    created = app.apply(CreatePlan(title="SQL Window Functions", answers=READY_ANSWERS))
    original_created = created.summary.created
    doc = store.load_plan_text("sql-window-functions")

    # A hand-edit that tries to rename the plan and rewrite its birth date,
    # and also makes a legitimate content change.
    edited = (
        doc.replace("id: sql-window-functions", "id: something-else")
        .replace(f"created: {original_created}", "created: 1999-01-01T00:00:00+00:00")
        .replace("OVER clause", "OVER clause (edited)")
    )
    detail = app.apply(ReplaceDocument(plan_id="sql-window-functions", markdown=edited))

    assert detail.summary.plan_id == "sql-window-functions"
    assert detail.summary.created == original_created
    assert detail.milestones[0].title == "OVER clause (edited)"
    on_disk = store.load_plan("sql-window-functions")
    assert on_disk.plan_id == "sql-window-functions"
    assert on_disk.created == original_created
    assert store.list_plan_ids() == ["sql-window-functions"], "no second document appeared"


def test_multiple_ready_active_plans_are_valid(app: PlanApplication) -> None:
    first = app.apply(CreatePlan(title="First", answers=READY_ANSWERS, status="active"))
    second = app.apply(CreatePlan(title="Second", answers=READY_ANSWERS, status="active"))
    assert first.summary.status == second.summary.status == "active"

    third = app.apply(CreatePlan(title="Third", answers=READY_ANSWERS))
    activated = app.apply(TransitionLifecycle(plan_id=third.summary.plan_id, status="active"))
    assert activated.summary.status == "active"

    assert sorted(p.plan_id for p in app.browse(status="active")) == ["first", "second", "third"]


def test_create_duplicate_id_without_overwrite_raises_conflict(app: PlanApplication) -> None:
    app.apply(CreatePlan(title="Demo", answers=READY_ANSWERS, plan_id="demo"))

    with pytest.raises(PlanConflict):
        app.apply(CreatePlan(title="Demo again", answers=READY_ANSWERS, plan_id="demo"))
    assert app.inspect("demo").summary.title == "Demo", "the refused create changed nothing"

    replaced = app.apply(
        CreatePlan(title="Demo again", answers=READY_ANSWERS, plan_id="demo", overwrite=True)
    )
    assert replaced.summary.title == "Demo again"
    assert store.list_plan_ids() == ["demo"]


def test_create_without_an_explicit_id_derives_a_unique_one(app: PlanApplication) -> None:
    first = app.apply(CreatePlan(title="Glue ETL", answers=READY_ANSWERS))
    second = app.apply(CreatePlan(title="Glue ETL", answers=READY_ANSWERS))
    assert first.summary.plan_id == "glue-etl"
    assert second.summary.plan_id == "glue-etl-2"


@pytest.mark.parametrize(
    "intent",
    [
        CreatePlan(title="   ", answers={}),
        CreatePlan(title="X", answers=["nope"]),  # type: ignore[arg-type]  # boundary check
        CreatePlan(title="X", answers={}, status="banana"),
        CreatePlan(title="X", answers={}, plan_id="../etc/passwd"),
    ],
    ids=["empty-title", "answers-not-a-mapping", "unknown-status", "traversal-id"],
)
def test_malformed_create_is_refused_before_any_write(
    app: PlanApplication, intent: CreatePlan
) -> None:
    with pytest.raises((InvalidField, InvalidPlanId)):
        app.apply(intent)
    assert store.list_plan_ids() == []


def test_transition_to_an_unknown_status_raises_invalid_field(app: PlanApplication) -> None:
    app.apply(CreatePlan(title="Demo", answers=READY_ANSWERS))
    with pytest.raises(InvalidField):
        app.apply(TransitionLifecycle(plan_id="demo", status="banana"))
    with pytest.raises(PlanNotFound):
        app.apply(TransitionLifecycle(plan_id="missing", status="paused"))


# ---------------------------------------------------------------------------
# Planning brief
# ---------------------------------------------------------------------------


def test_prepare_planning_returns_interview_seed_and_summaries(
    app: PlanApplication, monkeypatch
) -> None:
    from studyloop.planning import application as application_module
    from studyloop.planning.authoring import interview_spec

    fake_seed = {
        "struggling_topics": [{"topic": "joins", "last_seen": "2026-09-01"}],
        "due_concepts": [],
        "recurring_questions": [],
        "configured_topics": ["sql"],
        "notes": ["fixture"],
    }
    monkeypatch.setattr(application_module.authoring, "seed_from_history", lambda: fake_seed)
    app.apply(CreatePlan(title="Existing", answers=READY_ANSWERS))

    brief = app.prepare_planning()

    assert [q.key for q in brief.interview] == [q["key"] for q in interview_spec()]
    # Deep-frozen: the seed's lists arrive as tuples, its dicts read-only.
    assert set(brief.evidence_seed) == set(fake_seed)
    assert isinstance(brief.evidence_seed["struggling_topics"], tuple)
    with pytest.raises(TypeError):
        brief.evidence_seed["notes"] = []  # type: ignore[index]  # read-only mapping
    assert [p.plan_id for p in brief.existing_plans] == ["existing"]

    payload = brief.to_json_dict()
    assert payload["questions"] == interview_spec()
    assert payload["seed"] == fake_seed
    assert payload["seed"]["struggling_topics"][0]["topic"] == "joins"
    assert payload["existing_plans"][0]["plan_id"] == "existing"
    json.dumps(payload)  # nothing un-serialisable leaked through


# ---------------------------------------------------------------------------
# Views: frozen, tuple-only, and serialising to the existing key sets (D-3)
# ---------------------------------------------------------------------------


def test_summary_and_readiness_views_match_the_legacy_dicts_exactly() -> None:
    """The REST bodies must not change when the routes migrate (D-3)."""
    from studyloop.planning.authoring import readiness

    for plan in (_ready_plan("ready-one"), StudyPlan(plan_id="vague", title="Vague")):
        assert PlanSummary.from_plan(plan).to_json_dict() == plan.summary()
        assert ReadinessView.from_plan(plan).to_json_dict() == readiness(plan)


def test_views_are_immutable_and_json_fresh(app: PlanApplication) -> None:
    detail = app.apply(CreatePlan(title="SQL Window Functions", answers=READY_ANSWERS))

    for view in (detail, detail.summary, detail.readiness, detail.milestones[0]):
        # A frozen dataclass refuses every assignment, field or not.
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(view, "title", "mutated")  # noqa: B010
    assert isinstance(detail.summary.topics, tuple)
    assert isinstance(detail.readiness.blockers, tuple)
    assert isinstance(detail.milestones, tuple)
    assert isinstance(detail.milestones[0].concepts, tuple)

    first = detail.to_json_dict()
    second = detail.to_json_dict()
    assert first == second
    assert first is not second
    assert first["plan"] is not second["plan"]
    assert first["milestones"] is not second["milestones"]

    # Mutating one caller's copy must not leak into the next caller's.
    first["plan"]["topics"].append("leaked")
    first["milestones"][0]["concepts"].append("leaked")
    first["readiness"]["blockers"].append("leaked")
    assert detail.to_json_dict() == second

    json.dumps(first)
```

### `tests/test_plan_surface_parity.py`

```python
"""Cross-surface parity: the CLI and the Web API refuse activation identically.

Issue #7's invariant is that activation is readiness-gated on *every* entry
path. The seam makes that true by construction; this file checks it from the
outside, the way a learner or an agent would meet it — one refusal through
``studyloop plan status … active``, one through ``PATCH /api/plans/{id}`` —
and asserts the two are the same refusal: the same blockers in the same
order, the same nudges, and no write on either side.
"""

from __future__ import annotations

import json
import re

import pytest

pytest.importorskip("fastapi")

from click.testing import CliRunner
from fastapi.testclient import TestClient

from studyloop.cli import cli
from studyloop.planning import store
from studyloop.web.app import create_app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture
def web() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def shell() -> CliRunner:
    return CliRunner()


def _terminal_bullets(output: str) -> list[str]:
    """The ``•`` lines the CLI prints under "Not ready to activate:", de-styled."""
    bullets: list[str] = []
    for line in _ANSI.sub("", output).splitlines():
        stripped = line.strip()
        if stripped.startswith("•"):
            bullets.append(stripped[1:].strip())
    return bullets


def test_activation_refusal_is_identical_via_cli_and_web(web: TestClient, shell: CliRunner) -> None:
    # One unready draft, created through the Web so both surfaces see the
    # same document.
    created = web.post("/api/plans", json={"title": "Vague", "answers": {}})
    assert created.status_code == 201, created.text
    plan_id = created.json()["plan"]["plan_id"]
    document_before = store.load_plan_text(plan_id)

    # --- Web: PATCH status ------------------------------------------------
    via_web = web.patch(f"/api/plans/{plan_id}", json={"status": "active"})
    assert via_web.status_code == 422, via_web.text
    web_detail = via_web.json()["detail"]
    assert web_detail["message"] == "plan is not ready to activate"
    assert web_detail["ready"] is False
    assert web_detail["plan_id"] == plan_id

    # --- CLI: plan status … active ----------------------------------------
    via_cli = shell.invoke(cli, ["plan", "status", plan_id, "active"])
    assert via_cli.exit_code == 1, via_cli.output
    assert "Cannot activate" in via_cli.output
    assert "Traceback" not in via_cli.output

    # Same blockers, same nudges, same order: the CLI prints blockers then
    # nudges as bullets, so the bullet list is the Web body's two lists joined.
    assert _terminal_bullets(via_cli.output) == web_detail["blockers"] + web_detail["nudges"]
    assert web_detail["blockers"], "the fixture must actually be unready"

    # --- No mutation on either side ---------------------------------------
    assert store.load_plan_text(plan_id) == document_before
    shown = json.loads(shell.invoke(cli, ["plan", "show", plan_id, "--json"]).output)
    assert shown["plan"]["status"] == "draft"
    # And the readiness the CLI reports afterwards is the Web refusal, minus
    # the HTTP-only message key.
    assert shown["readiness"] == {k: v for k, v in web_detail.items() if k != "message"}
    assert web.get("/api/plans", params={"status": "active"}).json()["count"] == 0


def test_every_web_door_into_active_refuses_with_the_same_body(web: TestClient) -> None:
    """Create-with-status, document replacement and status transition agree."""
    refused_create = web.post(
        "/api/plans", json={"title": "Vague", "status": "active", "answers": {}, "plan_id": "vague"}
    )
    assert refused_create.status_code == 422, refused_create.text
    assert store.list_plan_ids() == []

    draft = web.post("/api/plans", json={"title": "Vague", "answers": {}, "plan_id": "vague"})
    assert draft.status_code == 201, draft.text

    refused_transition = web.patch("/api/plans/vague", json={"status": "active"})
    assert refused_transition.status_code == 422, refused_transition.text

    active_doc = store.load_plan_text("vague").replace("status: draft", "status: active")
    refused_replace = web.patch("/api/plans/vague", json={"markdown": active_doc})
    assert refused_replace.status_code == 422, refused_replace.text

    refused_import = web.post("/api/plans", json={"markdown": active_doc, "plan_id": "vague-2"})
    assert refused_import.status_code == 422, refused_import.text

    bodies = [
        r.json()["detail"]
        for r in (refused_create, refused_transition, refused_replace, refused_import)
    ]
    for body in bodies:
        body.pop("plan_id")  # the import names its own id; everything else must match
    assert bodies[0] == bodies[1] == bodies[2] == bodies[3]
    assert bodies[0]["message"] == "plan is not ready to activate"

    assert store.list_plan_ids() == ["vague"]
    assert web.get("/api/plans/vague").json()["plan"]["status"] == "draft"
```

## 8. Delta spec — `specs/web-ui/spec.md` (the other two follow the same shape)

```markdown
## ADDED Requirements

### Requirement: Activation is readiness-gated on every entry path
Every Web API path that can leave a study plan in the `active` state SHALL
delegate to `PlanApplication.apply` and SHALL be refused by the seam's single
readiness gate when the *resulting* document has no mission `why`, no success
criteria, or no milestones. The routes in `web/routes/plans.py` SHALL hold no
readiness check of their own (`rg 'readiness\(' web/routes/plans.py` → 0 hits).
A refusal SHALL be `422` with the body
`{"message": "plan is not ready to activate", "plan_id", "ready": false,
"blockers": [...], "nudges": [...]}` — the same body the `PATCH` status path
has always returned — and SHALL persist nothing: no document is created,
replaced or re-saved before the gate runs.

#### Scenario: Create with status active on an unready plan
- **WHEN** `POST /api/plans` is called with `{"title": "Vague", "status": "active", "answers": {}}`
- **THEN** the response is `422` whose `detail.ready` is `false` and
  `detail.blockers` is non-empty, no document is written, and
  `GET /api/plans?status=active` reports `count == 0`

#### Scenario: Whole-document replacement whose frontmatter says active
- **WHEN** `PATCH /api/plans/{id}` is called with `{"markdown": ...}` where the
  document's frontmatter has `status: active` and the Milestones section is
  empty
- **THEN** the response is `422` with `detail.ready == false`, and the stored
  document is byte-identical to what it was before the request (status still
  `draft`, milestone count unchanged)

#### Scenario: Status transition to active on an unready plan
- **WHEN** `PATCH /api/plans/{id}` is called with `{"status": "active"}` on a
  plan whose readiness reports blockers
- **THEN** the response is `422` with `detail.ready == false`, and
  `GET /api/plans/{id}` still reports `status == "draft"`

#### Scenario: Raw-markdown import whose frontmatter says active
- **WHEN** `POST /api/plans` is called with `{"markdown": ...}` whose
  frontmatter has `status: active` and which has no milestones
- **THEN** the response is `422` with `detail.ready == false` and no document
  is written

#### Scenario: Every door returns the same refusal
- **WHEN** the same unready document is refused via create-with-status, status
  transition, document replacement and raw-markdown import
- **THEN** the four `422` bodies are equal apart from `plan_id`, with the same
  blockers and nudges in the same order

#### Scenario: A ready plan still activates on every door
- **WHEN** a plan with a mission `why`, at least one success criterion and at
  least one milestone is created with `status: active`, or transitioned to
  `active`, or replaced by a document whose frontmatter says `active`
- **THEN** the response is `201` (create) or `200` (patch) and the plan's
  `status` is `active`; several plans MAY be active at once

### Requirement: Plan routes map seam errors to HTTP status codes in one place
`web/routes/plans.py` SHALL translate `PlanError` subclasses exactly once:
`PlanNotFound` → `404`, `InvalidPlanId` and `InvalidField` → `400`,
`PlanConflict` → `409`, `PlanNotReady` → `422` (body above),
`InvalidMilestone` → `404`. Response bodies for list, detail, create, patch and
interview SHALL be unchanged from the pre-seam routes: summaries carry the
`StudyPlan.summary()` key set and readiness blocks carry the
`authoring.readiness()` key set.

#### Scenario: Duplicate id without overwrite
- **WHEN** `POST /api/plans` names a `plan_id` that already exists and does
  not set `"overwrite": true`
- **THEN** the response is `409` and the existing plan is unchanged

#### Scenario: Unknown plan on a write
- **WHEN** `PATCH /api/plans/{id}` is called for an id with no document
- **THEN** the response is `404` before any field of the body is validated
```

## 9. Public doc change — `docs/study-plans.md` diff

```diff
diff --git a/docs/study-plans.md b/docs/study-plans.md
index 10558420..477b4259 100644
--- a/docs/study-plans.md
+++ b/docs/study-plans.md
@@ -71,6 +71,18 @@ Milestone checkboxes update the Markdown plan itself. Activation is refused when
 the plan has no mission, success criteria, or milestones, because an empty active
 plan would create noise rather than direction.

+## Activation
+
+A plan becomes **active** only once it can be evaluated: it needs a mission
+*why*, at least one success criterion, and at least one milestone. That check
+runs on every route into the active state — creating a plan as active, changing
+its status, replacing its whole document, or importing a document whose
+frontmatter already says `active` — and it is the same check whichever surface
+you use. The Web UI answers a refusal with the list of blockers; the CLI prints
+the same list and exits non-zero. Nothing is written when activation is refused,
+so a plan never appears active while it cannot be tracked. More than one plan can
+be active at a time.
+
 ## Build a plan with the study-plan-architect

 Instead of filling in the form yourself, be interviewed. The
```

## 10. Deliverables — numbered H2 sections, in this order

1. **Verdict:** ACCEPT / ACCEPT-WITH-CORRECTIONS / REJECT for merging Phase 0 + 1 as the base of Phase 2,
   with the single sentence that decides it.
2. **Findings**, each with severity 🔴 defect (wrong behaviour or a bug), 🟡 must-fix-before-Phase-2
   (design/contract violation, missing test, unsafe pattern), 🔵 should-fix (style, naming, clarity),
   💡 note. For each: file:line or function, what is wrong, why it matters, the concrete fix, and the
   RED test that would pin it. Check specifically: (a) does any door into `status == "active"` still bypass
   `readiness`? (b) is every view genuinely immutable (no `list`/`dict` fields; `to_json_dict` returns fresh
   containers)? (c) do any views leak a mutable `StudyPlan`/`Mission`/`Milestone`? (d) exception mapping
   completeness in both adapters; (e) `ReplaceDocument`/`ImportDocument` id + created preservation and the
   `plan_id` mismatch case; (f) atomicity — is anything persisted before validation fails? (g) type-hint
   quality and pyright soundness of the `isinstance` + `assert_never` dispatch; (h) test quality — assert
   through the public seam, no private helpers, fixtures isolated, no order dependence; (i) whether the six
   deviations are correct calls — accept or reverse each, with reason.
3. **Spec/doc review:** does the delta spec's requirement + scenarios match what the code does, exactly?
   Is the `docs/study-plans.md` paragraph accurate and bounded (no claims beyond shipped behaviour)?
4. **Phase 2 hazards** you can see from this base: what `RevisePlan`/`SetMilestone`/`DeletePlan`/`assess`
   /`get_active_guidance` will trip over in these views/intents as written.
5. **Process finding:** the RED-commit pyright directive. Recommend one: (i) keep the per-file directive
   convention for RED commits; (ii) exempt `tests/` from the hook's pyright; (iii) squash RED+GREEN into one
   commit; (iv) other. One paragraph, with the trade-off.

Be concrete over complete: a file:line and a test name beat a paragraph.
