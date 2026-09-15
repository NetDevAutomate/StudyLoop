"""Write intents accepted by :meth:`~studyloop.planning.application.PlanApplication.apply`.

A closed union of frozen dataclasses: an adapter says *what it wants*, the
application decides whether the resulting document is allowed to exist. That
is how one readiness gate covers every door into the ``active`` state — the
adapters never see a :class:`~studyloop.planning.models.StudyPlan` to mutate.

Phase 1 ships the intents that can make a plan active (decision D-2):
create-with-status, document import, whole-document replacement and the
lifecycle transition. :class:`RevisePlan` was brought forward from Phase 2 by
council review 1 (finding F1): a PATCH that combines a status change with
field edits has to be *one* intent, or the seam judges the old document and
the route mutates the new one behind its back. Milestone updates, deletion and
assessment still follow in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


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


PlanIntent = CreatePlan | ImportDocument | ReplaceDocument | TransitionLifecycle | RevisePlan
