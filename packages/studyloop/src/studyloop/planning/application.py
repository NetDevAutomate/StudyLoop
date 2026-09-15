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
import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, assert_never

from . import authoring, index, store
from .errors import InvalidField, InvalidPlanId, PlanConflict, PlanNotFound, PlanNotReady
from .intents import (
    CreatePlan,
    ImportDocument,
    LearningRecordSpec,
    PlanIntent,
    ReplaceDocument,
    RevisePlan,
    TransitionLifecycle,
)
from .markdown import parse_plan
from .models import PLAN_STATUSES, LearningRecord, Milestone
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

#: ``(field, lowest, highest)`` for the two numeric plan fields. Out-of-range
#: values are clamped, not refused — the PATCH route has always done that.
_CLAMPED_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("energy_floor", 1, 10),
    ("review_cadence_days", 1, 90),
)

#: An H1-H3 line inside a learning record body would be re-parsed as a new
#: section or record on the next load and silently restructure the document.
_HEADING_LINE_RE = re.compile(r"\A#{1,3}\s")

#: Passed to the parser as the fallback id so the seam can tell "the
#: frontmatter named no id" apart from a real one and allocate a unique slug
#: itself. Deliberately fails ``store.validate_plan_id`` (spaces, brackets):
#: if it ever leaked past ``_import`` the write would be refused, not filed.
_NO_FRONTMATTER_ID = "<no frontmatter id>"


def _normalise_status(value: str) -> str:
    status = (value or "").strip().lower()
    if status not in PLAN_STATUSES:
        msg = f"status must be one of {PLAN_STATUSES}"
        raise InvalidField(msg)
    return status


def _string_list(value: object, *, field: str) -> list[str]:
    """A JSON array of strings, stripped and emptied of blanks; never a bare ``str``."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        msg = f"{field} must be a list"
        raise InvalidField(msg)
    return [str(item).strip() for item in value if str(item).strip()]


def _clamped_int(value: object, *, field: str, lo: int, hi: int) -> int:
    try:
        number = int(value)  # type: ignore[call-overload]  # boundary: untyped body value
    except (TypeError, ValueError) as exc:
        msg = f"{field} must be an integer"
        raise InvalidField(msg) from exc
    return max(lo, min(hi, number))


def _milestones_from(items: object) -> list[Milestone]:
    """Build the full replacement milestone list from Web-shaped mappings."""
    if isinstance(items, str) or not isinstance(items, Sequence):
        msg = "milestones must be a list"
        raise InvalidField(msg)
    milestones: list[Milestone] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        concepts = item.get("concepts") or []
        if isinstance(concepts, str):
            concepts = [concepts]
        milestones.append(
            Milestone(
                title=str(item.get("title", "")).strip() or "Untitled milestone",
                done=bool(item.get("done", False)),
                concepts=_string_list(concepts, field="concepts"),
                notes=str(item.get("notes", "")).strip(),
            )
        )
    return milestones


def _append_learning_record(plan: StudyPlan, spec: LearningRecordSpec) -> None:
    """Append ``spec`` to ``plan`` unless an identical record already exists.

    The same rules as :func:`studyloop.planning.store.record_learning` — the
    legacy writer the CLI and MCP still use until Phase 2 moves them onto
    ``RevisePlan`` — applied to the candidate in memory so the revision stays
    one save. Raises :class:`InvalidField` for an empty title or a body whose
    H1-H3 lines would restructure the document on the next parse.
    """
    title = spec.title.strip()
    if not title:
        msg = "a learning record needs a title"
        raise InvalidField(msg)
    body = spec.body.strip()
    for line in body.splitlines():
        if _HEADING_LINE_RE.match(line.strip()):
            msg = (
                "a learning record body cannot contain #, ## or ### headings "
                f"(found {line.strip()!r}); use #### or deeper, or plain prose"
            )
            raise InvalidField(msg)
    if any(r.title == title and r.body == body for r in plan.learning_records):
        return
    plan.learning_records.append(
        LearningRecord(
            number=max((r.number for r in plan.learning_records), default=0) + 1,
            title=title,
            body=body,
            status=spec.status.strip() or "active",
        )
    )


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
        markdown = self._load_text(plan.plan_id) if include_markdown else None
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
        if isinstance(intent, RevisePlan):
            return self._revise(intent)
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
        """Identity precedence: explicit ``plan_id``, else frontmatter, else a unique title slug.

        The id is settled before the readiness gate so a refusal names the
        document that would have been written. A document without an id is
        given the same collision-safe slug ``CreatePlan`` derives (``-2``,
        ``-3``… on a clash) rather than the bare title slug, which would turn
        a second import of the same title into a conflict.
        """
        plan = self._parse(intent.markdown, plan_id=_NO_FRONTMATTER_ID)
        explicit_id = (intent.plan_id or "").strip()
        if explicit_id:
            plan.plan_id = explicit_id
        elif plan.plan_id == _NO_FRONTMATTER_ID:
            plan.plan_id = store.unique_plan_id(plan.title)
        return self._persist_new(plan, overwrite=intent.overwrite)

    def _replace(self, intent: ReplaceDocument) -> PlanDetail:
        current = self._load(intent.plan_id)
        replacement = self._parse(intent.markdown, plan_id=current.plan_id)
        # A whole-document edit may not rename the plan or rewrite its birth
        # date: the id is the file (``_load`` pins it), and ``created`` is history.
        replacement.plan_id = current.plan_id
        replacement.created = current.created
        if replacement.status == "active":
            self._assert_can_be_active(replacement)
        store.save_plan(replacement)
        return PlanDetail.from_plan(replacement)

    def _transition(self, intent: TransitionLifecycle) -> PlanDetail:
        # A status change is the one-field case of a revision: same load, same
        # resulting-document gate, same single save.
        return self._revise(RevisePlan(plan_id=intent.plan_id, status=intent.status))

    def _revise(self, intent: RevisePlan) -> PlanDetail:
        """Load once, apply every supplied field, gate the result, save once.

        Order matters and is part of the contract: the plan must exist before
        any field is judged (404 before 400 on the Web); every field is
        validated before any is applied, so a bad value beside a good status
        change writes nothing; and the readiness gate sees the document as it
        *would be saved* — whichever fields put it there.
        """
        candidate = self._load(intent.plan_id)  # private to this call: it is the candidate

        status = None if intent.status is None else _normalise_status(str(intent.status))
        updates: dict[str, object] = {}
        if intent.title is not None:
            title = str(intent.title).strip()
            if not title:
                msg = "title cannot be empty"
                raise InvalidField(msg)
            updates["title"] = title
        if intent.topics is not None:
            updates["topics"] = _string_list(intent.topics, field="topics")
        if intent.target_date is not None:
            updates["target_date"] = str(intent.target_date).strip()
        if intent.notes is not None:
            updates["notes"] = str(intent.notes)
        for field, lo, hi in _CLAMPED_FIELDS:
            value = getattr(intent, field)
            if value is not None:
                updates[field] = _clamped_int(value, field=field, lo=lo, hi=hi)
        if intent.milestones is not None:
            updates["milestones"] = _milestones_from(intent.milestones)

        for field, value in updates.items():
            setattr(candidate, field, value)
        if intent.learning_record is not None:
            _append_learning_record(candidate, intent.learning_record)
        if status is not None:
            candidate.status = status

        # The gate judges the resulting document: a plan that is being
        # activated, or one that already is and has just been edited.
        if candidate.status == "active":
            self._assert_can_be_active(candidate)
        store.save_plan(candidate)  # preserves plan_id + created; bumps updated
        return PlanDetail.from_plan(candidate)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _persist_new(self, plan: StudyPlan, *, overwrite: bool) -> PlanDetail:
        """Identity, then conflict, then readiness, then create.

        The order is the contract (spec: "Duplicate id without overwrite" is a
        conflict unconditionally): a malformed id is an id error and a taken id
        is a conflict, whatever else is wrong with the incoming document. The
        readiness gate runs after both and before the write, so a refusal of
        any kind writes nothing. The store repeats the conflict check inside
        ``create_plan`` for the race between this probe and the write.
        """
        try:
            plan.plan_id = store.validate_plan_id(plan.plan_id)
            exists = store.plan_path(plan.plan_id).exists()
        except store.InvalidPlanIdError as exc:
            raise InvalidPlanId(str(exc)) from exc
        if exists and not overwrite:
            msg = f"study plan {plan.plan_id!r} already exists"
            raise PlanConflict(msg)
        if plan.status == "active":
            self._assert_can_be_active(plan)
        try:
            store.create_plan(plan, overwrite=overwrite)
        except store.PlanExistsError as exc:
            raise PlanConflict(str(exc)) from exc
        except store.InvalidPlanIdError as exc:  # pragma: no cover - validated above
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
        """Load by storage identity: the returned model is pinned to the file's id.

        The parser lets a document's frontmatter ``id`` win over the filename,
        so a hand-edited plan whose frontmatter names some other id would
        otherwise be re-saved under that other id — a second file, and the
        one the caller asked about left untouched. Every write path loads
        through here, so "the id is the file" holds on all of them (F5).
        """
        try:
            storage_id = store.validate_plan_id(plan_id)
            plan = store.load_plan(storage_id)
        except store.PlanNotFoundError as exc:
            raise PlanNotFound(str(exc)) from exc
        except store.InvalidPlanIdError as exc:
            raise InvalidPlanId(str(exc)) from exc
        plan.plan_id = storage_id
        return plan

    @staticmethod
    def _load_text(plan_id: str) -> str:
        """The raw document, with the same store-error translation as :meth:`_load`.

        Read after the parse succeeded, so a document deleted in between must
        still surface as the domain error every adapter maps (F3).
        """
        try:
            return store.load_plan_text(plan_id)
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
