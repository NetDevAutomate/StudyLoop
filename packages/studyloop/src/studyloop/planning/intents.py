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
