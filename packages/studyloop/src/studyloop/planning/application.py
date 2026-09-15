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
