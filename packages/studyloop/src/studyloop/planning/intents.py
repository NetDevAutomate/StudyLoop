"""Write intents accepted by :meth:`~studyloop.planning.application.PlanApplication.apply`.

A closed union of frozen dataclasses: an adapter says *what it wants*, the
application decides whether the resulting document is allowed to exist. That
is how one readiness gate covers every door into the ``active`` state — the
adapters never see a :class:`~studyloop.planning.models.StudyPlan` to mutate.

Phase 1 shipped the intents that can make a plan active (decision D-2):
create-with-status, document import, whole-document replacement and the
lifecycle transition. :class:`RevisePlan` was brought forward from Phase 2 by
council review 1 (finding F1): a PATCH that combines a status change with
field edits has to be *one* intent, or the seam judges the old document and
the route mutates the new one behind its back. Phase 2 adds the idempotent
:class:`SetMilestone`, the confirmed :class:`DeletePlan`, and
:class:`AssessPlan` — which is not a member of :data:`PlanIntent` because it
goes to :meth:`~studyloop.planning.application.PlanApplication.assess`, not
``apply``: an assessment returns an evaluation and a report on two sinks, not
the plan as it now is.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class CreatePlan:
    """Draft a plan from interview ``answers`` and persist it.

    ``plan_id`` defaults to a unique slug of the title. ``overwrite`` exists for
    the Web and CLI surfaces, whose request shapes already accept it; the MCP
    ``create_study_plan`` tool never exposes it (D-4) — an agent must not be
    able to replace a learner's plan by picking the same id.

    ``answers`` is a *snapshot*: the mapping is deep-copied at construction
    and exposed read-only, so the document the seam judges is the one the
    intent described when it was built, whatever the caller does to its own
    dict afterwards and however late the intent is applied (review-2 hazard
    "live mapping", closed by council review 3, F5). Values keep their JSON
    types — lists stay lists, dicts stay dicts — because the authoring layer
    reads them by type. A non-mapping is left as given so the seam's own
    boundary check still refuses it with ``InvalidField``.
    """

    title: str
    answers: Mapping[str, object] = field(default_factory=dict)
    plan_id: str | None = None
    status: str = "draft"
    overwrite: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.answers, Mapping):
            snapshot = MappingProxyType(copy.deepcopy(dict(self.answers)))
            object.__setattr__(self, "answers", snapshot)


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


@dataclass(frozen=True)
class LearningRecordSpec:
    """One learning record to append through :class:`RevisePlan`.

    Appending is idempotent: a record with the same ``title`` and ``body`` as
    an existing one is not added again, so an agent's retry is always safe.
    """

    title: str
    body: str = ""
    status: str = "active"


@dataclass(frozen=True)
class RevisePlan:
    """Edit a plan in place — any combination of fields, judged as one document.

    ``None`` means *leave as is*. Everything supplied is applied to one
    candidate, the candidate is readiness-checked whenever it would be active
    (whether ``status`` makes it so or the plan already is), and it is saved
    once. That is what makes ``{"status": "active", "milestones": []}`` a
    refusal rather than an activation followed by an unguarded edit, and what
    stops a field-only edit from leaving an active plan unevaluable.

    ``milestones`` replaces the whole list: each item is a mapping with
    ``title`` and optional ``done``, ``concepts`` and ``notes`` — the shape the
    Web body already carries. Numeric fields are clamped to their ranges, not
    refused, as the PATCH route has always done.

    ``why``, ``success``, ``constraints`` and ``out_of_scope`` are the mission
    (item 3b): the list fields replace the whole list like ``topics``, and a
    bare string where a list belongs is refused, not split. They exist so the
    architect can repair every blocker class :func:`~studyloop.planning.authoring.readiness`
    knows through the tool it already holds — before them the only mission
    writer was a whole-document replacement.
    """

    plan_id: str
    title: str | None = None
    topics: Sequence[str] | None = None
    target_date: str | None = None
    energy_floor: int | None = None
    review_cadence_days: int | None = None
    notes: str | None = None
    milestones: Sequence[Mapping[str, object]] | None = None
    learning_record: LearningRecordSpec | None = None
    status: str | None = None
    why: str | None = None
    success: Sequence[str] | None = None
    constraints: Sequence[str] | None = None
    out_of_scope: Sequence[str] | None = None


@dataclass(frozen=True)
class SetMilestone:
    """Set one milestone's ``done`` state — set, not toggle, so a retry is safe.

    ``index`` is the 0-based position in the plan's milestone list; anything
    the plan does not have — past the end *or negative* — is
    :class:`~studyloop.planning.errors.InvalidMilestone`, and nothing is
    written. Like every write, the resulting document is readiness-checked
    when the plan is active.
    """

    plan_id: str
    index: int
    done: bool


@dataclass(frozen=True)
class DeletePlan:
    """Delete a plan's canonical document. The checkpoint log is kept.

    Refused with :class:`~studyloop.planning.errors.InvalidField` unless
    ``confirmed`` is ``True``: deletion is the one irreversible write, so the
    caller has to say so in the intent rather than by reaching the method. An
    HTTP ``DELETE`` is its own confirmation; an MCP tool or CLI flag must pass
    it explicitly. The durable checkpoint history in the sessions database is
    deliberately retained — it is evidence about the learner, not about the
    file.
    """

    plan_id: str
    confirmed: bool = False


@dataclass(frozen=True)
class AssessPlan:
    """Evaluate a plan at a session checkpoint, optionally recording the result.

    ``record=False`` is a preview: the evaluation is computed and returned and
    *neither* sink is touched. ``record=True`` appends the checkpoint to the
    durable log in the sessions database and, when ``append_to_plan`` is
    ``True``, to the plan document's own Checkpoints table. The two writes are
    independent and each is reported on the
    :class:`~studyloop.planning.views.AssessmentResult`.
    """

    plan_id: str
    phase: str
    study_id: str = ""
    record: bool = True
    append_to_plan: bool = True


PlanIntent = (
    CreatePlan
    | ImportDocument
    | ReplaceDocument
    | TransitionLifecycle
    | RevisePlan
    | SetMilestone
    | DeletePlan
)

#: The intents whose ``apply`` returns the plan as it now is; ``DeletePlan`` is
#: the one that cannot, and returns a ``DeleteResult`` instead.
PlanDetailIntent = (
    CreatePlan | ImportDocument | ReplaceDocument | TransitionLifecycle | RevisePlan | SetMilestone
)
