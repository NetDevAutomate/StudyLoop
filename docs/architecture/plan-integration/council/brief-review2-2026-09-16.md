# Council brief — code review 2: Phase 2 (#9) of the plan-integration programme

**Date:** 2026-09-16 · **Branch:** `fix/plan-integration-bugs`, commits `a4862301..b42d3b36` (Phase 2 only; Phase
0+1 and the review-1 corrections were accepted in `review-1-arbitration-2026-09-15.md`). **You are one
independent seat**; no other seat's answer is visible. You have no tools — the brief is the complete
evidence base. The implementing agent ran unattended overnight; your findings gate Phase 3.

## 0. What you are reviewing against

- **Decisions (binding):** D-2 every door into `active` passes the seam's one readiness gate, judged on the
  *resulting* document, before any write; D-3 four modules `planning/{errors,views,intents,application}.py`,
  frozen tuple-only views serialising to the existing key sets, domain errors without CLI/HTTP/MCP
  vocabulary, **no `PartialRecording` exception**; D-1 the two checkpoint sinks are independent and a
  failed one is reported; D-6 adapters (`studyloop/cli`, `studyloop/web/routes`, `studyloop/mcp`) may not
  import `planning.store|index|authoring|evaluation`; D-5 `get_active_guidance()` is the plan-static read the
  `now` ranker will consume in Phase 3 — **nothing consumes it yet**.
- **Phase 2 work order (tasks.md T2.1–T2.5):** intents `SetMilestone(plan_id, index, done)` (idempotent;
  `InvalidMilestone` for an index the plan lacks, negative included; resulting-document readiness when the
  plan is active), `DeletePlan(plan_id, confirmed=False)` (`InvalidField` unless confirmed; canonical
  document deleted; checkpoint history retained; `apply()` returns an explicit frozen `DeleteResult`),
  `AssessPlan(...)` with `assess() -> AssessmentResult` (frozen evaluation view; `db_write` /
  `document_write` ∈ `not_requested|saved|failed`; `record=False` writes neither sink; reuse
  `evaluate_and_record` / `evaluate_plan`, no second checkpoint writer), `get_active_guidance() ->
  ActiveGuidance` (one entry per active plan; next unchecked milestone; `match_keys` = casefolded,
  punctuation-stripped topics + milestone concepts; `target_urgency` overdue/soon(≤7)/later/undated; energy
  floor; completion action when every milestone is done; warnings for malformed documents; deterministic
  order by plan id). Migrate the remaining Web (POST evaluate → assess, toggle → SetMilestone, DELETE →
  DeletePlan), CLI (`new` incl. `--activate` → `CreatePlan(status=…)`, `interview`, `evaluate`, `milestone`,
  `record`) and MCP (`record_plan_learning` → `RevisePlan(learning_record=…)`, the only `tools.py` edit)
  paths; fold the learning-record validation into ONE place. Architecture guard test per design §6 with a
  planted-violation test. Delta specs. Archify diagram.
- **Hard rules:** TDD (RED committed and seen failing before code); `test_web_plans.py`, `test_cli_plan.py`,
  `test_planning_evaluation.py` byte-identical to `3a4f6b01` (verified: diffs empty); assertions in
  `test_plan_record.py` and `test_planning_store.py` unchanged (verified: 0 changed `assert` lines); pyright
  0; ruff clean; full suite `4730 passed, 4 skipped` exit 0; plan-filtered `637 passed`; the `rg` invariant
  over the three adapter packages → 0 hits; `node --test` JS suite 106 passed.
- **Review-1 hazards the seats named for this phase** (GPT Astra §4, Grok, qwen): `SetMilestone` must define
  negative-index semantics and be the first raiser of `InvalidMilestone`; `DeletePlan` needs an explicit
  frozen result because `PlanDetail` cannot represent deletion; `assess` must put Bug B's warning on a frozen
  view and not return the mutable `PlanEvaluation.warnings` list; `get_active_guidance` must return
  deterministic guidance for ALL active plans, not a singleton, and treat plan content as data not
  instructions; intents are frozen but `CreatePlan.answers` is a live mapping (not addressed this phase —
  say whether it must be); `PlanApplication` is uninjectable (tests hit the filesystem via `PLANS_DIR_ENV`);
  adapters must catch `PlanError`, never the store's error family.

## 1. Commits (oldest last), each RED before its GREEN

```text
b42d3b36 fix(web-ui): plans panel shows a partial checkpoint recording instead of "Recorded"
9d37fc21 test(web-ui): RED — plans panel relays a partial checkpoint recording
be4638df docs(architecture): Archify spec for the plan seam; tick Phase 2 tasks with shas and receipts
dcb11771 docs(spec): Phase 2 deltas — idempotent milestone set, confirmed delete, sink-reported recording, guidance view
5693e35c test(architecture): guard — adapters import study plans only through the seam (D-6)
45ea1fce refactor(mcp): record_plan_learning applies RevisePlan(learning_record=…) through the seam
95d74a84 test(mcp): RED — record_plan_learning is one RevisePlan through the seam
6251e930 refactor(cli): every plan command goes through the seam; no storage imports remain
8fed6129 test(cli): RED — plan new/interview/evaluate/milestone/record/reindex through the seam
da0026f9 refactor(web): evaluate, milestone toggle and DELETE go through the seam
ccfe1d17 test(web): RED — plan routes report both recording sinks, set milestones, delete confirmed
fed155c1 feat(planning): SetMilestone, DeletePlan, assess(), get_active_guidance() on the seam
9285260a test(planning): RED — Phase 2 seam contract for SetMilestone, DeletePlan, assess, guidance
```


## 2. The agent's own report of deviations from design §1 (verbatim)

1. `apply()` returns `DeleteResult` for `DeletePlan` and `PlanDetail` for everything else, typed with
   `@overload`; `PlanDetailIntent` names the non-delete union. `AssessPlan` is **not** a member of
   `PlanIntent` — it goes to `assess()`, because an assessment returns an evaluation plus a sink report, not
   the plan as it now is.
2. `PlanApplication.reindex() -> int` added so `studyloop plan reindex` needs no `index` import (D-6).
3. `get_active_guidance(*, today: date | None = None)` — keyword-only `today` for frozen-clock callers /
   deterministic urgency tests; defaults to the real UTC date. `PlanSummary.days_until_target` inside the
   guidance still uses the real date (documented).
4. The learning-record rule's single copy is the **store's** (`store.append_learning_record(plan, title,
   body=, status=)`, pure, on an in-memory plan; `record_learning` wraps it and saves only when created so
   the byte-level no-op holds). The seam's duplicate is deleted and `_revise` calls the store's function,
   translating `ValueError` → `InvalidField`. Rationale: the store cannot import the seam. Tests
   `test_learning_record_validation_is_the_stores_single_copy` pins the delegation.
5. `PlanDetail.learning_record_matching(spec)` added so CLI/MCP report `created` by asking the view before
   and after the revision instead of carrying the identity rule (`strip()` equality on title and body).
6. Web `POST /plans/{id}/evaluate` body gains `db_write`, `document_write` and an honest `recorded`
   (`recording_complete`); status stays `201` on a partial recording. The route's own phase check is
   deleted (the seam's `InvalidField` → 400, after 404). The plans panel JS shows "Partially recorded …
   database: failed, document: saved" when `recorded` is false (RED `9d37fc21` → GREEN `b42d3b36`).
7. CLI `plan evaluate --record` prints "Checkpoint recorded." only when every sink saved, else
   "Checkpoint partially recorded — database: …, document: …", exit 0.
8. `InvalidMilestone` message is `No milestone at index N (plan has M)` (capitalised, unlike the other seam
   messages) so the frozen CLI assertion `"No milestone at index 99" in output` survives `_fail_for`'s
   `No such milestone on 'id': …` wrapper. Web 404 detail changes text (status unchanged).
9. `AssessmentResult.recording_complete` is `"failed" not in (db_write, document_write)` — vacuously true
   for a preview. `AssessmentResult.warnings` is the evaluation's full warning list (recording warnings
   included), not just the recording ones.
10. `PlanEvaluationView` freezes database rows leniently (`isoformat()`/`str()` for a non-JSON leaf) rather
    than raising like `PlanningBrief`'s `_freeze`, because the checkpoint payload and the CLI already use
    `default=str`.
11. `cli/_exercise.py` (`exercise from-milestone`) and `cli/_brain.py` (`_selected_plan_ids`) were also
    migrated (→ `inspect` / `browse`): the guard would otherwise fail on them. `plans_dir` remains the one
    store re-export an adapter may import (`plan path`; the "Created <id> → <path>" line), listed as
    allowed in the guard.
12. **Owner's-eye item:** `tests/test_plan_record.py`'s `_seed` fixture now builds a *ready* active plan
    (success criterion + a milestone). Assertions are byte-identical. The old fixture created an active
    plan with no success criteria or milestones directly through the store — a shape no seam door can
    produce — and the CLI/MCP record paths now run the resulting-document gate (review-1 F1b, spec
    wording "in-place revision of fields or milestones … refused when the resulting document has no
    mission why, no success criteria, or no milestones"). **Consequence:** a legacy or hand-edited active
    plan that is unready has `plan record`, `plan milestone` and `record_plan_learning` refused with the
    blockers until it is paused or repaired. The agent applied the decided invariant consistently rather
    than carving an exception; it asks the council whether that is the right call for the wind-down's
    "record first" step (ADR-0010) on legacy documents, or whether writes that cannot change readiness
    (`SetMilestone`, a learning-record-only `RevisePlan`) should skip the gate.
13. Parser finding, out of scope: the milestone concepts regex stops at the first `)`, so a concept
    literally containing parentheses (`RANK()`) does not round-trip.

## 3. New/changed seam modules (full source)

### `planning/intents.py`
```python
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
```

### `planning/errors.py` (unchanged this phase, for reference)
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

* adapters read through :meth:`browse`, :meth:`inspect`,
  :meth:`prepare_planning` and :meth:`get_active_guidance`, write only
  through :meth:`apply` with an intent from :mod:`~studyloop.planning.intents`,
  and evaluate through :meth:`assess`;
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
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, assert_never, overload

from . import authoring, evaluation, index, store
from .errors import (
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    PlanConflict,
    PlanNotFound,
    PlanNotReady,
)
from .intents import (
    AssessPlan,
    CreatePlan,
    DeletePlan,
    ImportDocument,
    LearningRecordSpec,
    PlanDetailIntent,
    PlanIntent,
    ReplaceDocument,
    RevisePlan,
    SetMilestone,
    TransitionLifecycle,
)
from .markdown import parse_plan
from .models import CHECKPOINT_PHASES, PLAN_STATUSES, Milestone
from .views import (
    ActiveGuidance,
    ActivePlanGuidance,
    AssessmentResult,
    CheckpointHistoryView,
    DeleteResult,
    PlanDetail,
    PlanEvaluationView,
    PlanningBrief,
    PlanSummary,
    ReadinessView,
    SinkStatus,
)

if TYPE_CHECKING:
    from datetime import date

    from .models import StudyPlan

logger = logging.getLogger(__name__)

#: ``(field, lowest, highest)`` for the two numeric plan fields. Out-of-range
#: values are clamped, not refused — the PATCH route has always done that.
_CLAMPED_FIELDS: tuple[tuple[str, int, int], ...] = (
    ("energy_floor", 1, 10),
    ("review_cadence_days", 1, 90),
)

#: The two recording warnings ``evaluate_and_record`` appends (Phase 0 / Bug B).
#: ``assess`` reads them back into the structured sink report; the strings
#: themselves stay in ``warnings`` for callers that only ever read those.
_DB_WARNING = "checkpoint not saved to the database"
_DOCUMENT_WARNING = "checkpoint not appended to the plan document"

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
    """Apply the store's learning-record rule to the revision candidate.

    One copy of the rule — :func:`studyloop.planning.store.append_learning_record`
    — reached from here and from the store's own ``record_learning``. Applied
    to the candidate in memory so the record lands in the revision's single
    save; the store's ``ValueError`` (empty title, H1-H3 lines in the body)
    becomes the seam's :class:`InvalidField`.
    """
    try:
        store.append_learning_record(plan, spec.title, body=spec.body, status=spec.status)
    except ValueError as exc:
        raise InvalidField(str(exc)) from exc


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

    def get_active_guidance(self, *, today: date | None = None) -> ActiveGuidance:
        """One :class:`ActivePlanGuidance` per active plan, ordered by plan id.

        Plan-static and cheap — the documents are parsed once and no session
        history is read — so the ``now`` ranker (design §3, D-5) can call it
        on every request. ``today`` pins the target-date urgency for tests and
        frozen-clock callers; it defaults to the real UTC date.

        A document the store could not parse is named in the collection's
        ``warnings`` rather than silently absent, and a parseable-but-odd
        active plan (no milestones, a target date that is not a date) is
        represented with per-plan warnings rather than raised on.
        """
        parsed = store.list_plans()
        seen = {plan.plan_id for plan in parsed}
        warnings = tuple(
            f"study plan {plan_id!r} could not be parsed and is not represented"
            for plan_id in store.list_plan_ids()
            if plan_id not in seen
        )
        plans = tuple(
            ActivePlanGuidance.from_plan(plan, today=today)
            for plan in sorted(parsed, key=lambda plan: plan.plan_id)
            if plan.status == "active"
        )
        return ActiveGuidance(plans=plans, warnings=warnings)

    def reindex(self) -> int:
        """Rebuild the derived SQLite index from the documents. Returns rows written.

        The index is a cache the store refreshes best-effort on every save;
        this is the recovery path when that refresh failed or the database
        was rebuilt. Exposed here so ``studyloop plan reindex`` does not need
        to import the index module (D-6).
        """
        return index.reindex_all()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    @overload
    def apply(self, intent: DeletePlan) -> DeleteResult: ...

    @overload
    def apply(self, intent: PlanDetailIntent) -> PlanDetail: ...

    def apply(self, intent: PlanIntent) -> PlanDetail | DeleteResult:
        """Carry out one intent and return the plan as it now is.

        ``DeletePlan`` is the exception: there is no "now" for a deleted plan,
        so it returns a :class:`DeleteResult`. Raises a
        :class:`~studyloop.planning.errors.PlanError` subclass and writes
        nothing when the intent is refused.
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
        if isinstance(intent, SetMilestone):
            return self._set_milestone(intent)
        if isinstance(intent, DeletePlan):
            return self._delete(intent)
        assert_never(intent)

    def assess(self, intent: AssessPlan) -> AssessmentResult:
        """Evaluate a plan at a checkpoint and report what was recorded where.

        ``record=False`` calls :func:`~studyloop.planning.evaluation.evaluate_plan`
        and touches nothing. ``record=True`` calls the Phase-0
        :func:`~studyloop.planning.evaluation.evaluate_and_record` — the one
        checkpoint writer; this method adds no second — and reads its two
        recording warnings back into ``db_write`` / ``document_write``. A
        failed sink is an outcome on the result, never an exception: the
        evaluation succeeded and the caller gets it (D-1, D-3).
        """
        plan = self._load(intent.plan_id)  # 404 before 400: the plan before the phase
        phase = (intent.phase or "").strip().lower()
        if phase not in CHECKPOINT_PHASES:
            msg = f"phase must be one of {CHECKPOINT_PHASES}"
            raise InvalidField(msg)
        study_id = (intent.study_id or "").strip()

        if not intent.record:
            result = evaluation.evaluate_plan(plan, phase, study_id=study_id)
            return AssessmentResult(
                evaluation=PlanEvaluationView.from_evaluation(result),
                db_write="not_requested",
                document_write="not_requested",
                warnings=tuple(result.warnings),
            )

        result = evaluation.evaluate_and_record(
            plan, phase, study_id=study_id, append_to_plan=intent.append_to_plan
        )
        db_write: SinkStatus = "failed" if _DB_WARNING in result.warnings else "saved"
        document_write: SinkStatus
        if not intent.append_to_plan:
            document_write = "not_requested"
        elif _DOCUMENT_WARNING in result.warnings:
            document_write = "failed"
        else:
            document_write = "saved"
        return AssessmentResult(
            evaluation=PlanEvaluationView.from_evaluation(result),
            db_write=db_write,
            document_write=document_write,
            warnings=tuple(result.warnings),
        )

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

    def _set_milestone(self, intent: SetMilestone) -> PlanDetail:
        """Set one milestone's state on the loaded candidate; one gate, one save.

        Set, not toggle: applying the same intent twice leaves the same
        document, so a retried call is safe. A negative index is refused
        rather than read as Python's "from the end" — a milestone index is a
        position in the plan, not a list trick.
        """
        candidate = self._load(intent.plan_id)
        total = len(candidate.milestones)
        if not 0 <= intent.index < total:
            msg = f"No milestone at index {intent.index} (plan has {total})"
            raise InvalidMilestone(msg)
        candidate.milestones[intent.index].done = bool(intent.done)
        if candidate.status == "active":
            self._assert_can_be_active(candidate)
        store.save_plan(candidate)
        return PlanDetail.from_plan(candidate)

    def _delete(self, intent: DeletePlan) -> DeleteResult:
        """Remove the canonical document; keep the durable checkpoint log.

        The plan must exist before the confirmation is judged (404 before
        400, like every write), and an unconfirmed intent writes nothing.
        The store's ``delete_plan`` also drops the derived index row and
        deliberately leaves ``study_plan_checkpoints`` alone: the log is
        evidence about the learner's sessions, not about the file.
        """
        plan = self._load(intent.plan_id)
        if not intent.confirmed:
            msg = f"deleting {plan.plan_id!r} requires confirmed=True"
            raise InvalidField(msg)
        try:
            deleted = store.delete_plan(plan.plan_id)
        except store.InvalidPlanIdError as exc:  # pragma: no cover - validated by _load
            raise InvalidPlanId(str(exc)) from exc
        if not deleted:  # vanished between the load and the unlink
            msg = f"no study plan with id {plan.plan_id!r}"
            raise PlanNotFound(msg)
        return DeleteResult(plan_id=plan.plan_id)

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
```

### `planning/views.py` — diff vs `a4862301` (the Phase 1 views are unchanged above the fold)
```diff
diff --git a/packages/studyloop/src/studyloop/planning/views.py b/packages/studyloop/src/studyloop/planning/views.py
index df7cb0ac..e316d2ef 100644
--- a/packages/studyloop/src/studyloop/planning/views.py
+++ b/packages/studyloop/src/studyloop/planning/views.py
@@ -14,14 +14,20 @@ behaviour-identical when the routes and commands migrate onto the seam;

 from __future__ import annotations

+import re
+import unicodedata
 from collections.abc import Iterable, Mapping
 from dataclasses import dataclass
 from types import MappingProxyType
-from typing import TYPE_CHECKING, Any
+from typing import TYPE_CHECKING, Any, Literal

 from .authoring import readiness

 if TYPE_CHECKING:
+    from datetime import date
+
+    from .evaluation import PlanEvaluation
+    from .intents import LearningRecordSpec
     from .models import Checkpoint, LearningRecord, Milestone, Mission, Resource, StudyPlan


@@ -48,6 +54,25 @@ def _freeze(value: object) -> object:
     raise TypeError(msg)


+def _freeze_rows(value: object) -> object:
+    """Like :func:`_freeze`, but for database rows an evaluation carries.
+
+    The checkpoint log has always been written with ``json.dumps(...,
+    default=str)`` and the CLI prints it the same way, so a non-JSON leaf
+    (a ``date`` from a driver, say) is rendered — ``isoformat()`` when it has
+    one, else ``str()`` — rather than refused. Refusing would turn a
+    successful evaluation into a crash over one column's type.
+    """
+    if isinstance(value, Mapping):
+        return MappingProxyType({str(key): _freeze_rows(item) for key, item in value.items()})
+    if isinstance(value, list | tuple | set | frozenset):
+        return tuple(_freeze_rows(item) for item in value)
+    if isinstance(value, _SEED_SCALARS):
+        return value
+    render = getattr(value, "isoformat", None)
+    return render() if callable(render) else str(value)
+
+
 def _thaw(value: object) -> object:
     """Inverse of :func:`_freeze`: fresh dicts and lists, ready for ``json.dumps``."""
     if isinstance(value, Mapping):
@@ -57,6 +82,25 @@ def _thaw(value: object) -> object:
     return value


+_NON_WORD_RE = re.compile(r"[^\w\s]|_", re.UNICODE)
+
+
+def normalise_match_key(text: str) -> str:
+    """The key on which a plan topic or concept matches a study candidate.
+
+    Casefold, replace punctuation (and ``_``) with spaces, collapse runs of
+    whitespace, strip. ``"Data-Engineering"`` and ``"data engineering"`` are
+    the same key; ``"RANK()"`` is ``"rank"``. The ``now`` ranker applies this
+    same function to its candidates, so plan matching is *equality on the
+    key* and never a substring test (design §3 step 4) — ``"rank"`` does not
+    match ``"frank"``. Unicode is NFKC-normalised first so a full-width or
+    composed form does not defeat the equality.
+    """
+    folded = unicodedata.normalize("NFKC", text).casefold()
+    spaced = _NON_WORD_RE.sub(" ", folded)
+    return " ".join(spaced.split())
+
+
 @dataclass(frozen=True)
 class ReadinessView:
     """What still blocks a plan from being active, and what would merely help.
@@ -403,6 +447,21 @@ class PlanDetail:
             payload["history"] = [entry.to_json_dict() for entry in self.history]
         return payload

+    def learning_record_matching(self, spec: LearningRecordSpec) -> LearningRecordView | None:
+        """The record ``spec`` would be a duplicate of, or ``None``.
+
+        Identity is the store's idempotency rule — same title and body after
+        the whitespace trim the parser applies
+        (:func:`studyloop.planning.store.append_learning_record`). An adapter
+        that reports ``created`` asks this before and after the revision
+        instead of carrying its own copy of that rule.
+        """
+        title, body = spec.title.strip(), spec.body.strip()
+        for record in self.learning_records:
+            if record.title == title and record.body == body:
+                return record
+        return None
+

 @dataclass(frozen=True)
 class PlanningBrief:
@@ -453,3 +512,280 @@ class PlanningBrief:
             "seed": _thaw(self.evidence_seed),
             "existing_plans": [plan.to_json_dict() for plan in self.existing_plans],
         }
+
+
+# ---------------------------------------------------------------------------
+# Phase 2 views: deletion, assessment, active-plan guidance
+# ---------------------------------------------------------------------------
+
+
+@dataclass(frozen=True)
+class DeleteResult:
+    """The outcome of a confirmed ``DeletePlan``.
+
+    A ``PlanDetail`` describes a plan as it now is; a deleted plan has no "now",
+    so ``apply`` returns this instead (council review 1, GPT hazard table). The
+    canonical document and its derived index row are gone; the durable
+    checkpoint log in the sessions database is retained by design.
+    """
+
+    plan_id: str
+
+    def to_json_dict(self) -> dict[str, Any]:
+        return {"deleted": True, "plan_id": self.plan_id}
+
+
+SinkStatus = Literal["not_requested", "saved", "failed"]
+TargetUrgency = Literal["overdue", "soon", "later", "undated"]
+
+#: Days-until-target at or below which a target date is ``soon``.
+SOON_WITHIN_DAYS = 7
+
+
+@dataclass(frozen=True)
+class PlanEvaluationView:
+    """A frozen :class:`~studyloop.planning.evaluation.PlanEvaluation`.
+
+    Field for field the same as the mutable evaluation, with tuples for lists
+    and read-only mappings for database rows, plus ``markdown`` — the block an
+    agent pastes into the conversation, rendered once at construction so no
+    caller needs the mutable object to print it. :meth:`to_json_dict` returns
+    exactly ``PlanEvaluation.to_dict()``, so the REST body and the CLI
+    ``--json`` shape do not change when the adapters delegate (D-3).
+    """
+
+    plan_id: str
+    plan_title: str
+    phase: str
+    verdict: str
+    headline: str
+    at: str
+    study_id: str
+    progress_pct: int
+    milestone_total: int
+    milestone_done: int
+    next_milestone: str
+    next_concepts: tuple[str, ...]
+    days_since_activity: int | None
+    days_until_target: int | None
+    due_reviews: tuple[Mapping[str, object], ...]
+    struggles: tuple[Mapping[str, object], ...]
+    concept_evidence: tuple[Mapping[str, object], ...]
+    unverified_milestones: tuple[str, ...]
+    drift_topics: tuple[str, ...]
+    recommendations: tuple[str, ...]
+    warnings: tuple[str, ...]
+    markdown: str
+
+    @classmethod
+    def from_evaluation(cls, evaluation: PlanEvaluation) -> PlanEvaluationView:
+        data = evaluation.to_dict()
+        return cls(
+            plan_id=str(data["plan_id"]),
+            plan_title=str(data["plan_title"]),
+            phase=str(data["phase"]),
+            verdict=str(data["verdict"]),
+            headline=str(data["headline"]),
+            at=str(data["at"]),
+            study_id=str(data["study_id"]),
+            progress_pct=int(data["progress_pct"]),
+            milestone_total=int(data["milestone_total"]),
+            milestone_done=int(data["milestone_done"]),
+            next_milestone=str(data["next_milestone"]),
+            next_concepts=tuple(str(item) for item in data["next_concepts"]),
+            days_since_activity=data["days_since_activity"],
+            days_until_target=data["days_until_target"],
+            due_reviews=_rows(data["due_reviews"]),
+            struggles=_rows(data["struggles"]),
+            concept_evidence=_rows(data["concept_evidence"]),
+            unverified_milestones=tuple(str(item) for item in data["unverified_milestones"]),
+            drift_topics=tuple(str(item) for item in data["drift_topics"]),
+            recommendations=tuple(str(item) for item in data["recommendations"]),
+            warnings=tuple(str(item) for item in data["warnings"]),
+            markdown=evaluation.as_markdown(),
+        )
+
+    def to_json_dict(self) -> dict[str, Any]:
+        """``PlanEvaluation.to_dict()``, key for key, in fresh containers."""
+        return {
+            "plan_id": self.plan_id,
+            "plan_title": self.plan_title,
+            "phase": self.phase,
+            "verdict": self.verdict,
+            "headline": self.headline,
+            "at": self.at,
+            "study_id": self.study_id,
+            "progress_pct": self.progress_pct,
+            "milestone_total": self.milestone_total,
+            "milestone_done": self.milestone_done,
+            "next_milestone": self.next_milestone,
+            "next_concepts": list(self.next_concepts),
+            "days_since_activity": self.days_since_activity,
+            "days_until_target": self.days_until_target,
+            "due_reviews": _thaw(self.due_reviews),
+            "struggles": _thaw(self.struggles),
+            "concept_evidence": _thaw(self.concept_evidence),
+            "unverified_milestones": list(self.unverified_milestones),
+            "drift_topics": list(self.drift_topics),
+            "recommendations": list(self.recommendations),
+            "warnings": list(self.warnings),
+        }
+
+
+def _rows(items: object) -> tuple[Mapping[str, object], ...]:
+    frozen = _freeze_rows(items)
+    if not isinstance(frozen, tuple):  # pragma: no cover - to_dict() always yields lists here
+        msg = "evaluation rows must be a list"
+        raise TypeError(msg)
+    return tuple(row for row in frozen if isinstance(row, Mapping))
+
+
+@dataclass(frozen=True)
+class AssessmentResult:
+    """What ``assess`` did: the evaluation, and the fate of each requested sink.
+
+    ``db_write`` is the durable checkpoint log; ``document_write`` is the plan
+    document's own Checkpoints table. Each is ``not_requested`` (a preview, or
+    ``append_to_plan=False``), ``saved`` or ``failed`` — the two are
+    independent (D-1), and a failure is a *reported outcome*, never an
+    exception, because the evaluation itself succeeded and the caller is
+    entitled to it. ``warnings`` is the evaluation's full warning list,
+    recording warnings included, so a caller that only ever read
+    ``evaluation.warnings`` sees the same strings.
+    """
+
+    evaluation: PlanEvaluationView
+    db_write: SinkStatus
+    document_write: SinkStatus
+    warnings: tuple[str, ...]
+
+    @property
+    def recording_complete(self) -> bool:
+        """``True`` when every *requested* sink was saved.
+
+        Vacuously true for a preview: nothing was asked for, so nothing is
+        missing. Adapters that print "recorded" check ``record`` themselves.
+        """
+        return "failed" not in (self.db_write, self.document_write)
+
+    def to_json_dict(self) -> dict[str, Any]:
+        return {
+            "evaluation": self.evaluation.to_json_dict(),
+            "markdown": self.evaluation.markdown,
+            "db_write": self.db_write,
+            "document_write": self.document_write,
+            "recording_complete": self.recording_complete,
+            "warnings": list(self.warnings),
+        }
+
+
+@dataclass(frozen=True)
+class ActivePlanGuidance:
+    """What the ``now`` ranker needs to know about one active plan (D-5).
+
+    Plan-static: computed from the document alone, no session-history scan.
+    ``match_keys`` are :func:`normalise_match_key` over the topics and every
+    milestone's concepts, done or not — a due review on a finished milestone's
+    concept is still plan-related repair. ``next_milestone`` is the first
+    unchecked one. ``completion_action`` replaces a study candidate when every
+    milestone is ticked (design §3 step 9). ``warnings`` name defects in this
+    document that the guidance worked around rather than raised.
+    """
+
+    plan: PlanSummary
+    next_milestone: MilestoneView | None
+    match_keys: frozenset[str]
+    target_urgency: TargetUrgency
+    energy_floor: int
+    completion_action: str | None
+    warnings: tuple[str, ...]
+
+    @classmethod
+    def from_plan(cls, plan: StudyPlan, *, today: date | None = None) -> ActivePlanGuidance:
+        warnings: list[str] = []
+        keys = {normalise_match_key(topic) for topic in plan.topics}
+        for milestone in plan.milestones:
+            keys.update(normalise_match_key(concept) for concept in milestone.concepts)
+        keys.discard("")
+
+        next_view = next(
+            (
+                MilestoneView.from_milestone(index, milestone)
+                for index, milestone in enumerate(plan.milestones)
+                if not milestone.done
+            ),
+            None,
+        )
+
+        if not plan.milestones:
+            warnings.append(f"active plan {plan.plan_id!r} has no milestones")
+        if not keys:
+            warnings.append(
+                f"active plan {plan.plan_id!r} names no topics or concepts — nothing can match it"
+            )
+
+        days = plan.days_until_target(today)
+        if plan.target_date and days is None:
+            warnings.append(
+                f"target_date {plan.target_date!r} on {plan.plan_id!r} is not a date; "
+                "treated as undated"
+            )
+        urgency: TargetUrgency
+        if days is None:
+            urgency = "undated"
+        elif days < 0:
+            urgency = "overdue"
+        elif days <= SOON_WITHIN_DAYS:
+            urgency = "soon"
+        else:
+            urgency = "later"
+
+        completion = None
+        if plan.milestones and next_view is None:
+            completion = (
+                f"Every milestone of {plan.title!r} is checked off — close the plan "
+                "or extend it with a follow-on mission."
+            )
+
+        return cls(
+            plan=PlanSummary.from_plan(plan),
+            next_milestone=next_view,
+            match_keys=frozenset(keys),
+            target_urgency=urgency,
+            energy_floor=plan.energy_floor,
+            completion_action=completion,
+            warnings=tuple(warnings),
+        )
+
+    def to_json_dict(self) -> dict[str, Any]:
+        return {
+            "plan": self.plan.to_json_dict(),
+            "next_milestone": (
+                None if self.next_milestone is None else self.next_milestone.to_json_dict()
+            ),
+            "match_keys": sorted(self.match_keys),
+            "target_urgency": self.target_urgency,
+            "energy_floor": self.energy_floor,
+            "completion_action": self.completion_action,
+            "warnings": list(self.warnings),
+        }
+
+
+@dataclass(frozen=True)
+class ActiveGuidance:
+    """Every active plan's guidance, ordered by plan id, plus collection warnings.
+
+    A collection, never a singleton: several plans may be active at once.
+    ``warnings`` at this level name documents that could not be represented
+    at all — an unparseable file the store skipped, say — so the ranker knows
+    its picture is incomplete rather than believing there is nothing there.
+    """
+
+    plans: tuple[ActivePlanGuidance, ...]
+    warnings: tuple[str, ...]
+
+    def to_json_dict(self) -> dict[str, Any]:
+        return {
+            "plans": [plan.to_json_dict() for plan in self.plans],
+            "warnings": list(self.warnings),
+        }
```

### `planning/store.py` — diff vs `a4862301`
```diff
diff --git a/packages/studyloop/src/studyloop/planning/store.py b/packages/studyloop/src/studyloop/planning/store.py
index 37d3a0a8..ab6ca045 100644
--- a/packages/studyloop/src/studyloop/planning/store.py
+++ b/packages/studyloop/src/studyloop/planning/store.py
@@ -201,44 +201,38 @@ def unique_plan_id(title: str) -> str:
     return candidate


-def record_learning(
-    plan_id: str,
+def append_learning_record(
+    plan: StudyPlan,
     title: str,
     *,
     body: str = "",
     status: str = "active",
 ) -> tuple[LearningRecord, bool]:
-    """Append a learning record to ``plan_id``. Returns ``(record, created)``.
-
-    The R-93 writer: before this, :class:`LearningRecord` was constructed in
-    exactly one place — the Markdown parser — so a record existed only if the
-    learner typed it into the plan document by hand, and an xTiles wind-down's
-    learning record lived only in xTiles (inverting ADR-0010).
+    """Append a learning record to ``plan`` in memory. Returns ``(record, created)``.

-    Parse → append → :func:`save_plan`, never an append of raw Markdown:
-    ``save_plan`` re-renders the whole document through ``render_plan``, so the
-    on-disk shape cannot drift from the renderer that the projection and
-    template guards already pin (``### LR-0004 — Title`` is the renderer's
-    business, not this function's).
+    The one copy of the learning-record rule. :func:`record_learning` wraps it
+    for the load-then-save case; ``PlanApplication`` applies it to a revision
+    candidate so the record lands in the revision's single save. Both callers
+    get the same validation and the same idempotency, because there is only
+    one function to disagree with.

     Idempotent the same way the vault writer is: re-recording an existing
     record (same title and body, case-preserved, whitespace-trimmed the way the
     parser trims) is a no-op that returns ``(existing, False)`` and leaves the
-    file's bytes untouched. Numbering is ``max(existing) + 1`` so records can
-    cite each other and be superseded rather than renumbered.
-
-    Raises :class:`PlanNotFoundError` / :class:`InvalidPlanIdError` from the
-    load, and :class:`ValueError` for an empty title.
+    plan untouched. Numbering is ``max(existing) + 1`` so records can cite each
+    other and be superseded rather than renumbered.
+
+    Raises :class:`ValueError` for an empty title, and for a body whose H1-H3
+    lines would be re-parsed as new sections or new records on the next load
+    (``_split_sections`` / ``_subsection_items`` split on them, and
+    ``_subsection_items`` does not honour code fences), silently corrupting
+    the document's structure. Refuse rather than mangle; H4+ is safe prose.
     """
     title = title.strip()
     if not title:
         msg = "a learning record needs a title"
         raise ValueError(msg)
     body = body.strip()
-    # H1-H3 lines in a body would be re-parsed as new sections or new records
-    # on the next load (_split_sections / _subsection_items split on them, and
-    # _subsection_items does not honour code fences), silently corrupting the
-    # document's structure. Refuse rather than mangle; H4+ is safe prose.
     for line in body.splitlines():
         if re.match(r"\A#{1,3}\s", line.strip()):
             msg = (
@@ -248,7 +242,6 @@ def record_learning(
             raise ValueError(msg)
     status = status.strip() or "active"

-    plan = load_plan(plan_id)
     for existing in plan.learning_records:
         if existing.title == title and existing.body == body:
             return existing, False
@@ -260,5 +253,35 @@ def record_learning(
         status=status,
     )
     plan.learning_records.append(record)
-    save_plan(plan)
     return record, True
+
+
+def record_learning(
+    plan_id: str,
+    title: str,
+    *,
+    body: str = "",
+    status: str = "active",
+) -> tuple[LearningRecord, bool]:
+    """Append a learning record to ``plan_id``. Returns ``(record, created)``.
+
+    The R-93 writer: before this, :class:`LearningRecord` was constructed in
+    exactly one place — the Markdown parser — so a record existed only if the
+    learner typed it into the plan document by hand, and an xTiles wind-down's
+    learning record lived only in xTiles (inverting ADR-0010).
+
+    Parse → :func:`append_learning_record` → :func:`save_plan`, never an append
+    of raw Markdown: ``save_plan`` re-renders the whole document through
+    ``render_plan``, so the on-disk shape cannot drift from the renderer that
+    the projection and template guards already pin (``### LR-0004 — Title`` is
+    the renderer's business, not this function's). A duplicate record leaves
+    the file's bytes untouched.
+
+    Raises :class:`PlanNotFoundError` / :class:`InvalidPlanIdError` from the
+    load, and :class:`ValueError` from the rule.
+    """
+    plan = load_plan(plan_id)
+    record, created = append_learning_record(plan, title, body=body, status=status)
+    if created:
+        save_plan(plan)
+    return record, created
```

### `planning/__init__.py` — diff vs `a4862301`
```diff
diff --git a/packages/studyloop/src/studyloop/planning/__init__.py b/packages/studyloop/src/studyloop/planning/__init__.py
index 5e78b2ba..ba976afa 100644
--- a/packages/studyloop/src/studyloop/planning/__init__.py
+++ b/packages/studyloop/src/studyloop/planning/__init__.py
@@ -38,12 +38,16 @@ from .evaluation import (
 )
 from .index import checkpoint_history, indexed_plans, reindex_all
 from .intents import (
+    AssessPlan,
     CreatePlan,
+    DeletePlan,
     ImportDocument,
     LearningRecordSpec,
+    PlanDetailIntent,
     PlanIntent,
     ReplaceDocument,
     RevisePlan,
+    SetMilestone,
     TransitionLifecycle,
 )
 from .markdown import (
@@ -86,17 +90,23 @@ from .store import (
     unique_plan_id,
 )
 from .views import (
+    ActiveGuidance,
+    ActivePlanGuidance,
+    AssessmentResult,
     CheckpointHistoryView,
     CheckpointView,
+    DeleteResult,
     InterviewItemView,
     LearningRecordView,
     MilestoneView,
     MissionView,
     PlanDetail,
+    PlanEvaluationView,
     PlanningBrief,
     PlanSummary,
     ReadinessView,
     ResourceView,
+    normalise_match_key,
 )

 __all__ = [
@@ -105,11 +115,17 @@ __all__ = [
     "MISSION_SUBSECTION_HEADINGS",
     "PLAN_SECTION_HEADINGS",
     "PLAN_STATUSES",
+    "ActiveGuidance",
+    "ActivePlanGuidance",
+    "AssessPlan",
+    "AssessmentResult",
     "Checkpoint",
     "CheckpointHistoryView",
     "CheckpointView",
     "ConceptEvidence",
     "CreatePlan",
+    "DeletePlan",
+    "DeleteResult",
     "HerdrBackend",
     "ImportDocument",
     "InterviewItemView",
@@ -129,8 +145,10 @@ __all__ = [
     "PlanApplication",
     "PlanConflict",
     "PlanDetail",
+    "PlanDetailIntent",
     "PlanError",
     "PlanEvaluation",
+    "PlanEvaluationView",
     "PlanExistsError",
     "PlanIntent",
     "PlanNotFound",
@@ -143,6 +161,7 @@ __all__ = [
     "Resource",
     "ResourceView",
     "RevisePlan",
+    "SetMilestone",
     "StudyPlan",
     "TmuxBackend",
     "TransitionLifecycle",
@@ -159,6 +178,7 @@ __all__ = [
     "list_plans",
     "load_plan",
     "load_plan_text",
+    "normalise_match_key",
     "parse_plan",
     "plan_path",
     "plans_dir",
```


## 4. Adapters (full source of the two files that changed most; diff for the MCP tool and the two small CLI edits)

### `web/routes/plans.py`
```python
"""Study-plan API routes.

Read paths serve both the parsed summary (for list rendering) and the raw
Markdown (for the client-side ``marked → DOMPurify → hljs/mermaid`` pipeline the
Course Explorer already uses), so the plan renders as a proper document rather
than a bespoke widget.

Write paths are deliberately narrow: create from an interview payload, patch
metadata/milestones, set one milestone, run an evaluation checkpoint, delete.
Free-form Markdown replacement is allowed but validated by re-parsing, so a
malformed body is rejected instead of corrupting a plan.

Policy lives in :class:`~studyloop.planning.PlanApplication`, not here. Every
path that can make a plan active — create-with-status, document import,
whole-document replacement, status transition, and any in-place revision of a
plan that is or becomes active — goes through ``apply`` and is refused by the
same readiness gate with the same 422 body. Evaluation goes through ``assess``
and reports both recording sinks; the milestone checkbox is an idempotent
``SetMilestone``; ``DELETE`` is a confirmed ``DeletePlan`` — the HTTP verb is
the confirmation this route contract has always had. This module only maps
domain errors to status codes (design §2) and translates bodies; it holds no
rule of its own and imports no storage module (D-6).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse

from studyloop.planning import (
    PLAN_STATUSES,
    AssessmentResult,
    AssessPlan,
    CreatePlan,
    DeletePlan,
    ImportDocument,
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    PlanApplication,
    PlanConflict,
    PlanDetail,
    PlanDetailIntent,
    PlanError,
    PlanIntent,
    PlanNotFound,
    PlanNotReady,
    ReplaceDocument,
    RevisePlan,
    SetMilestone,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Seam access and the one error mapping (design §2)
# ---------------------------------------------------------------------------


def _application() -> PlanApplication:
    return PlanApplication()


def _http_error(exc: PlanError) -> HTTPException:
    """Map a domain refusal to its status code — the only place this happens."""
    if isinstance(exc, PlanNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvalidPlanId | InvalidField):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, PlanConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, PlanNotReady):
        return HTTPException(
            status_code=422,
            detail={"message": str(exc), **exc.readiness.to_json_dict()},
        )
    if isinstance(exc, InvalidMilestone):
        return HTTPException(status_code=404, detail=str(exc))
    logger.error("unmapped plan error %s", type(exc).__name__, exc_info=exc)
    return HTTPException(status_code=500, detail="plan operation failed")


def _inspect(plan_id: str, **options: Any) -> PlanDetail:
    try:
        return _application().inspect(plan_id, **options)
    except PlanError as exc:
        raise _http_error(exc) from exc


def _apply(intent: PlanDetailIntent) -> PlanDetail:
    try:
        return _application().apply(intent)
    except PlanError as exc:
        raise _http_error(exc) from exc


def _assess(intent: AssessPlan) -> AssessmentResult:
    try:
        return _application().assess(intent)
    except PlanError as exc:
        raise _http_error(exc) from exc


def _written(detail: PlanDetail, **flags: bool) -> dict[str, Any]:
    """The body every successful write returns: a flag, the summary, readiness."""
    return {
        **flags,
        "plan": detail.summary.to_json_dict(),
        "readiness": detail.readiness.to_json_dict(),
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/plans")
def get_plans(
    status: str = Query("", pattern="^(|draft|active|paused|complete|abandoned)$"),
) -> dict:
    """List plans (summaries only) for the left-pane Study Plan section."""
    try:
        plans = _application().browse(status=status or None)
    except PlanError as exc:  # pragma: no cover - the Query pattern already refuses
        raise _http_error(exc) from exc
    return {
        "plans": [plan.to_json_dict() for plan in plans],
        "count": len(plans),
        "statuses": list(PLAN_STATUSES),
    }


@router.get("/plans/interview")
def get_interview() -> dict:
    """Return the plan-creation interview plus data-grounded seed suggestions."""
    brief = _application().prepare_planning().to_json_dict()
    return {"questions": brief["questions"], "seed": brief["seed"]}


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str) -> dict:
    """Return one plan: parsed structure, raw Markdown, and readiness."""
    return _inspect(plan_id, include_markdown=True).to_json_dict()


@router.get("/plans/{plan_id}/markdown", response_class=PlainTextResponse)
def get_plan_markdown(plan_id: str) -> str:
    """Raw Markdown for a plan — the download / copy-to-agent path."""
    markdown = _inspect(plan_id, include_markdown=True).markdown
    return markdown or ""


@router.get("/plans/{plan_id}/history")
def get_plan_history(plan_id: str, limit: int = Query(20, ge=1, le=200)) -> dict:
    """Durable checkpoint log from the sessions DB."""
    detail = _inspect(plan_id, include_history=True, history_limit=limit)
    return {
        "plan_id": plan_id,
        "checkpoints": [entry.to_json_dict() for entry in detail.history or ()],
    }


# ---------------------------------------------------------------------------
# Evaluation — the three session checkpoints
# ---------------------------------------------------------------------------


@router.get("/plans/{plan_id}/evaluate")
def preview_evaluation(
    plan_id: str,
    phase: str = Query("start", pattern="^(start|mid|end)$"),
) -> dict:
    """Evaluate without recording — safe to poll from the UI."""
    result = _assess(AssessPlan(plan_id=plan_id, phase=phase, record=False))
    return {"evaluation": result.evaluation.to_json_dict(), "markdown": result.evaluation.markdown}


@router.post("/plans/{plan_id}/evaluate", status_code=201)
def record_evaluation(plan_id: str, payload: Annotated[dict | None, Body()] = None) -> dict:
    """Run and record a checkpoint (DB log + appended to the plan document).

    ``recorded`` is honest: ``true`` only when every requested sink was saved.
    The two sinks are reported individually so a client can tell "the plan
    document has the row but the database does not" from the reverse, instead
    of reading a bare ``true`` that Bug B (issue #7) showed could be a lie.
    """
    payload = payload or {}
    result = _assess(
        AssessPlan(
            plan_id=plan_id,
            phase=str(payload.get("phase", "start")),
            study_id=str(payload.get("study_id", "")),
            record=True,
            append_to_plan=bool(payload.get("append_to_plan", True)),
        )
    )
    return {
        "recorded": result.recording_complete,
        "db_write": result.db_write,
        "document_write": result.document_write,
        "evaluation": result.evaluation.to_json_dict(),
        "markdown": result.evaluation.markdown,
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


@router.post("/plans", status_code=201)
def post_plan(payload: Annotated[dict, Body()]) -> dict:
    """Create a plan from interview answers, or from raw Markdown.

    ``{"markdown": "..."}`` imports a document verbatim (validated by
    re-parsing).  Otherwise ``{"title", "answers"}`` drafts one from the
    interview, which is what the agent and the UI wizard both use. Either way
    a document that would be active is readiness-gated by the seam (422).
    """
    plan_id = str(payload.get("plan_id", "")).strip() or None
    overwrite = bool(payload.get("overwrite", False))
    raw_markdown = payload.get("markdown")
    intent: PlanIntent
    if raw_markdown:
        intent = ImportDocument(markdown=str(raw_markdown), plan_id=plan_id, overwrite=overwrite)
    else:
        intent = CreatePlan(
            title=str(payload.get("title", "")),
            answers=payload.get("answers") or {},
            plan_id=plan_id,
            status=str(payload.get("status", "draft")),
            overwrite=overwrite,
        )
    return _written(_apply(intent), created=True)


@router.patch("/plans/{plan_id}")
def patch_plan(plan_id: str, payload: Annotated[dict, Body()]) -> dict:
    """Update plan fields in place.

    Accepts ``status``, ``title``, ``topics``, ``target_date``,
    ``energy_floor``, ``review_cadence_days``, ``notes``, ``milestones``
    (full replacement), and ``markdown`` (whole-document replacement).

    The non-Markdown body is *one* ``RevisePlan``: the seam loads the plan
    once, applies every supplied field, judges the resulting document — so
    ``{"status": "active", "milestones": []}`` is refused, and a field-only
    edit cannot leave an active plan unevaluable — and saves once. The route
    translates the body; it validates and writes nothing itself.
    """
    if "markdown" in payload:
        replaced = _apply(ReplaceDocument(plan_id=plan_id, markdown=str(payload["markdown"])))
        return _written(replaced, updated=True)

    # ``None`` is "leave as is" for the seam, and a key that is absent from the
    # body is exactly that. (A key explicitly set to ``null`` reads the same.)
    revision = RevisePlan(
        plan_id=plan_id,
        title=payload.get("title"),
        topics=payload.get("topics"),
        target_date=payload.get("target_date"),
        energy_floor=payload.get("energy_floor"),
        review_cadence_days=payload.get("review_cadence_days"),
        notes=payload.get("notes"),
        milestones=payload.get("milestones"),
        status=payload.get("status"),
    )
    return _written(_apply(revision), updated=True)


@router.post("/plans/{plan_id}/milestones/{index}/toggle")
def toggle_milestone(plan_id: str, index: int) -> dict:
    """Flip one milestone's done state — the checkbox in the plan view.

    The route reads the current state and asks the seam to *set* its
    opposite: ``SetMilestone`` is idempotent, so a retried request cannot
    flip the box twice, and the index check is the seam's — an index the plan
    does not have is ``InvalidMilestone`` (404), never a route-side rule.
    """
    current = _inspect(plan_id)
    already_done = any(m.index == index and m.done for m in current.milestones)
    updated = _apply(SetMilestone(plan_id=plan_id, index=index, done=not already_done))
    return {
        "updated": True,
        "index": index,
        "done": updated.milestones[index].done,
        "plan": updated.summary.to_json_dict(),
    }


@router.delete("/plans/{plan_id}")
def remove_plan(plan_id: str) -> dict:
    """Delete a plan document. Checkpoint history is intentionally retained.

    The ``DELETE`` verb is the confirmation this route has always required, so
    the intent is applied confirmed; the seam still refuses an unknown id
    (404) or a malformed one (400) before anything is removed.
    """
    try:
        result = _application().apply(DeletePlan(plan_id=plan_id, confirmed=True))
    except PlanError as exc:
        raise _http_error(exc) from exc
    return result.to_json_dict()
```

### `cli/_plan.py`
```python
"""Study plan command group.

The agent-facing surface for study plans. Every command has a ``--json``
form because a Socratic mentor agent drives these programmatically, while the
default human output stays readable in a terminal sidebar.

``plan evaluate`` prints the Markdown block by default: that is what an agent
pastes into the conversation at each of the three session checkpoints.

Every command reads and writes through
:class:`~studyloop.planning.PlanApplication` — ``browse`` / ``inspect`` /
``prepare_planning`` to read, ``apply`` with an intent to write, ``assess`` to
evaluate — so the activation refusal here is the same refusal the Web API
gives (same blockers, same nudges, no write), a milestone set is idempotent,
and a recorded checkpoint reports both of its sinks. This module maps domain
errors to exit codes and messages (design §2) and formats output; it holds no
plan rule of its own and imports no storage module (D-6).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import click
from rich.table import Table

from studyloop.cli._shared import console
from studyloop.planning import (
    PLAN_STATUSES,
    AssessPlan,
    CreatePlan,
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    LearningRecordSpec,
    PlanApplication,
    PlanConflict,
    PlanError,
    PlanNotFound,
    PlanNotReady,
    ReadinessView,
    RevisePlan,
    SetMilestone,
    TransitionLifecycle,
    plans_dir,
)

if TYPE_CHECKING:
    from studyloop.planning import AssessmentResult, PlanDetail, PlanDetailIntent


def _fail(message: str) -> NoReturn:
    """Print an error and exit non-zero, never a traceback.

    Typed ``NoReturn`` so callers like :func:`_inspect` are provably
    non-optional — otherwise every use site has to defend against a ``None``
    that can never actually arrive.
    """
    console.print(f"[red]{message}[/red]")
    raise SystemExit(1)


def _fail_for(exc: PlanError, plan_id: str) -> NoReturn:
    """Map a seam refusal to the CLI's message and exit code (design §2).

    Every domain error has its own line, so an agent reading the output can
    tell a missing plan from a taken id from a bad value without parsing the
    seam's exception text. The final ``_fail`` is the safety net for a
    ``PlanError`` subclass this mapping has not met yet.
    """
    if isinstance(exc, PlanNotFound):
        _fail(f"No study plan with id {plan_id!r}. Try: studyloop plan list")
    if isinstance(exc, PlanNotReady):
        _refuse_activation(exc.readiness)
    if isinstance(exc, PlanConflict):
        _fail(f"A study plan with id {plan_id!r} already exists. Choose another id.")
    if isinstance(exc, InvalidPlanId):
        _fail(f"Invalid plan id {plan_id!r}: {exc}")
    if isinstance(exc, InvalidField):
        _fail(f"Invalid value: {exc}")
    if isinstance(exc, InvalidMilestone):
        _fail(f"No such milestone on {plan_id!r}: {exc}")
    _fail(str(exc))


def _inspect(plan_id: str, *, include_markdown: bool = False) -> PlanDetail:
    try:
        return PlanApplication().inspect(plan_id, include_markdown=include_markdown)
    except PlanError as exc:
        _fail_for(exc, plan_id)


def _apply(intent: PlanDetailIntent) -> PlanDetail:
    """Apply one intent, mapping any refusal to the one-line failure."""
    try:
        return PlanApplication().apply(intent)
    except PlanError as exc:
        _fail_for(exc, intent.plan_id or "")


def _assess(intent: AssessPlan) -> AssessmentResult:
    try:
        return PlanApplication().assess(intent)
    except PlanError as exc:
        _fail_for(exc, intent.plan_id)


def _print_readiness(check: ReadinessView) -> None:
    """Show what still blocks activation, then what would merely improve it."""
    if check.blockers:
        console.print("[yellow]Not ready to activate:[/yellow]")
        for item in check.blockers:
            console.print(f"  [red]•[/red] {item}")
    else:
        console.print("[green]Ready to activate.[/green]")
    for item in check.nudges:
        console.print(f"  [dim]• {item}[/dim]")


def _refuse_activation(check: ReadinessView) -> NoReturn:
    """The one way every command says no to activating an incomplete plan."""
    console.print(f"[red]Cannot activate {check.plan_id!r} — the plan is incomplete.[/red]")
    _print_readiness(check)
    raise SystemExit(1)


@click.group("plan")
def plan_group() -> None:
    """Create, inspect, and evaluate structured study plans."""


@plan_group.command("list")
@click.option(
    "--status",
    type=click.Choice(PLAN_STATUSES),
    default=None,
    help="Only show plans in this state.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_list(status: str | None, as_json: bool) -> None:
    """List study plans."""
    try:
        plans = PlanApplication().browse(status=status)
    except PlanError as exc:
        _fail_for(exc, status or "")
    if as_json:
        click.echo(json.dumps([p.to_json_dict() for p in plans], indent=2))
        return
    if not plans:
        console.print("[dim]No study plans yet. Create one: studyloop plan new --title ...[/dim]")
        return

    table = Table(title="Study Plans")
    table.add_column("ID", style="bold")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Progress")
    table.add_column("Next", style="dim")
    for plan in plans:
        table.add_row(
            plan.plan_id,
            plan.title,
            plan.status,
            f"{plan.milestone_done}/{plan.milestone_total} ({plan.progress_pct}%)",
            plan.next_milestone or "—",
        )
    console.print(table)


@plan_group.command("show")
@click.argument("plan_id")
@click.option("--markdown", "as_markdown", is_flag=True, help="Print the raw document.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_show(plan_id: str, as_markdown: bool, as_json: bool) -> None:
    """Show one study plan."""
    detail = _inspect(plan_id, include_markdown=as_markdown)
    if as_markdown:
        click.echo(detail.markdown or "")
        return
    if as_json:
        click.echo(
            json.dumps(
                {
                    "plan": detail.summary.to_json_dict(),
                    "mission": detail.mission.to_json_dict(),
                    "milestones": [
                        {"title": m.title, "done": m.done, "concepts": list(m.concepts)}
                        for m in detail.milestones
                    ],
                    "readiness": detail.readiness.to_json_dict(),
                },
                indent=2,
            )
        )
        return

    plan = detail.summary
    console.print(f"[bold]{plan.title}[/bold]  [dim]({plan.plan_id})[/dim]")
    console.print(f"Status: {plan.status}   Progress: {plan.milestone_done}/{plan.milestone_total}")
    if detail.mission.why:
        console.print(f"\n[bold]Why[/bold]\n  {detail.mission.why}")
    if detail.milestones:
        console.print("\n[bold]Milestones[/bold]")
        for milestone in detail.milestones:
            box = "x" if milestone.done else " "
            concepts = (
                f"  [dim]({', '.join(milestone.concepts)})[/dim]" if milestone.concepts else ""
            )
            console.print(f"  [{box}] {milestone.index}. {milestone.title}{concepts}")
    console.print()
    _print_readiness(detail.readiness)


@plan_group.command("new")
@click.option("--title", required=True, help="Plan title.")
@click.option("--why", default="", help="The mission: what changes once this is learned.")
@click.option("--topic", "topics", multiple=True, help="Topic (repeatable).")
@click.option("--success", "success", multiple=True, help="Success criterion (repeatable).")
@click.option(
    "--milestone",
    "milestones",
    multiple=True,
    help="Milestone, optionally 'Title (concepts: a, b)' (repeatable).",
)
@click.option("--constraint", "constraints", multiple=True, help="Constraint (repeatable).")
@click.option("--out-of-scope", "out_of_scope", multiple=True, help="Excluded topic (repeatable).")
@click.option("--resource", "resources", multiple=True, help="Source URL or label (repeatable).")
@click.option("--target-date", default="", help="Target date (YYYY-MM-DD).")
@click.option("--energy-floor", type=int, default=3, show_default=True, help="Minimum energy 1-10.")
@click.option("--activate", is_flag=True, help="Activate immediately (refused if incomplete).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_new(
    title: str,
    why: str,
    topics: tuple[str, ...],
    success: tuple[str, ...],
    milestones: tuple[str, ...],
    constraints: tuple[str, ...],
    out_of_scope: tuple[str, ...],
    resources: tuple[str, ...],
    target_date: str,
    energy_floor: int,
    activate: bool,
    as_json: bool,
) -> None:
    """Create a study plan.

    Omitted answers are left explicitly blank in the document rather than
    invented, and ``readiness`` reports what is still missing. ``--activate``
    is the same ``CreatePlan`` with ``status="active"``: the seam judges the
    resulting document and refuses — writing nothing — when it is incomplete,
    exactly as ``plan status <id> active`` and the Web API do.
    """
    detail = _apply(
        CreatePlan(
            title=title,
            answers={
                "why": why,
                "success": list(success),
                "topics": list(topics),
                "constraints": list(constraints),
                "out_of_scope": list(out_of_scope),
                "milestones": list(milestones),
                "resources": list(resources),
                "target_date": target_date,
                "energy_floor": energy_floor,
            },
            status="active" if activate else "draft",
        )
    )
    # Plans live as ``<id>.md`` in the plans directory (``studyloop plan
    # path``); the path is shown as a convenience for the learner, not read.
    path = plans_dir() / f"{detail.summary.plan_id}.md"

    if as_json:
        click.echo(
            json.dumps(
                {
                    "plan": detail.summary.to_json_dict(),
                    "readiness": detail.readiness.to_json_dict(),
                    "path": str(path),
                },
                indent=2,
            )
        )
        return
    console.print(f"[green]Created[/green] {detail.summary.plan_id} → {path}")
    _print_readiness(detail.readiness)


@plan_group.command("interview")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_interview(as_json: bool) -> None:
    """Print the plan-creation interview and evidence-based seed suggestions.

    An agent calls this to learn what to ask, and what the databases already
    suggest the learner should plan for.
    """
    brief = PlanApplication().prepare_planning()
    seed = brief.to_json_dict()["seed"]
    if as_json:
        questions = brief.to_json_dict()["questions"]
        click.echo(json.dumps({"questions": questions, "seed": seed}, indent=2))
        return

    console.print("[bold]Plan interview[/bold] — work through these in order.\n")
    for index, question in enumerate(brief.interview, 1):
        flag = "" if question.required else " [dim](optional)[/dim]"
        console.print(f"{index}. {question.prompt}{flag}")
        console.print(f"   [dim]{question.why}[/dim]")

    if seed.get("struggling_topics"):
        console.print("\n[bold]Struggling recently[/bold]")
        for item in seed["struggling_topics"]:
            console.print(f"  • {item['topic']}")
    if seed.get("due_concepts"):
        console.print("\n[bold]Due for review[/bold]")
        for item in seed["due_concepts"]:
            console.print(f"  • {item.get('concept') or item.get('topic')}")
    for note in seed.get("notes", []):
        console.print(f"  [dim]{note}[/dim]")


@plan_group.command("evaluate")
@click.argument("plan_id")
@click.option(
    "--phase",
    type=click.Choice(["start", "mid", "end"]),
    default="start",
    show_default=True,
    help="Which session checkpoint this is.",
)
@click.option("--record", is_flag=True, help="Persist the checkpoint and append it to the plan.")
@click.option("--study-id", default="", help="Session id to attribute the checkpoint to.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_evaluate(plan_id: str, phase: str, record: bool, study_id: str, as_json: bool) -> None:
    """Evaluate a plan against your study and session history.

    With ``--record`` the checkpoint goes to the durable log and to the plan
    document; each write is reported on its own, so a failed database write
    is named rather than hidden behind "recorded".
    """
    result = _assess(AssessPlan(plan_id=plan_id, phase=phase, study_id=study_id, record=record))
    if as_json:
        click.echo(json.dumps(result.evaluation.to_json_dict(), indent=2, default=str))
        return
    click.echo(result.evaluation.markdown)
    if not record:
        return
    if result.recording_complete:
        console.print("[green]Checkpoint recorded.[/green]")
    else:
        console.print(
            "[yellow]Checkpoint partially recorded — "
            f"database: {result.db_write}, document: {result.document_write}[/yellow]"
        )


@plan_group.command("milestone")
@click.argument("plan_id")
@click.argument("index", type=int)
@click.option("--done/--undone", "done", default=None, help="Set explicitly instead of toggling.")
def plan_milestone(plan_id: str, index: int, done: bool | None) -> None:
    """Toggle (or set) a milestone's completion state.

    Either way the write is one idempotent ``SetMilestone``: with a flag the
    state is set as asked (running it twice is safe); without one the current
    state is read and its opposite is set. An index the plan does not have —
    past the end or negative — is refused by the seam.
    """
    if done is None:
        current = _inspect(plan_id)
        done = not any(m.index == index and m.done for m in current.milestones)
    detail = _apply(SetMilestone(plan_id=plan_id, index=index, done=done))
    milestone = detail.milestones[index]
    state = "done" if milestone.done else "not done"
    console.print(
        f"[green]{milestone.title}[/green] → {state}  "
        f"({detail.summary.milestone_done}/{detail.summary.milestone_total}, "
        f"{detail.summary.progress_pct}%)"
    )


@plan_group.command("status")
@click.argument("plan_id")
@click.argument("status", type=click.Choice(PLAN_STATUSES))
def plan_status(plan_id: str, status: str) -> None:
    """Change a plan's lifecycle state.

    Activation is refused while the plan is missing a mission, success
    criteria, or milestones — an unevaluable plan must not look active. The
    refusal is the seam's, so it is the same one the Web API gives.
    """
    detail = _apply(TransitionLifecycle(plan_id=plan_id, status=status))
    console.print(f"[green]{detail.summary.plan_id}[/green] → {status}")


@plan_group.command("record")
@click.argument("plan_id")
@click.option("--title", required=True, help="What was learned, in one line.")
@click.option("--body", default="", help="The record's body, as Markdown prose.")
@click.option(
    "--body-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Read the body from a file instead of --body.",
)
@click.option(
    "--status",
    default="active",
    show_default=True,
    help="Record status (e.g. active, superseded).",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def plan_record(
    plan_id: str, title: str, body: str, body_file: str | None, status: str, as_json: bool
) -> None:
    """Append a learning record to a plan — the wind-down's 'record first' step.

    One ``RevisePlan`` carrying the record: the seam parses the document,
    appends through the store's single learning-record rule, and re-renders
    the whole file, so the on-disk shape stays the renderer's business
    (ADR-0010). Re-running with the same title and body adds nothing, which
    makes it safe for an agent to retry; ``created`` says which happened.
    """
    if body and body_file:
        _fail("Pass --body or --body-file, not both.")
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8")
    spec = LearningRecordSpec(title=title, body=body, status=status)
    before = _inspect(plan_id)  # maps not-found/invalid-id to the friendly failure
    detail = _apply(RevisePlan(plan_id=plan_id, learning_record=spec))
    record = detail.learning_record_matching(spec)
    if record is None:  # pragma: no cover - the seam just appended or matched it
        _fail(f"Learning record {spec.title!r} was not persisted on {plan_id!r}.")
    created = before.learning_record_matching(spec) is None
    if as_json:
        click.echo(
            json.dumps(
                {
                    "plan_id": detail.summary.plan_id,
                    "number": record.number,
                    "title": record.title,
                    "status": record.status,
                    "created": created,
                },
                indent=2,
            )
        )
        return
    verb = "recorded" if created else "already recorded (no change)"
    console.print(f"[green]LR-{record.number:04d}[/green] — {record.title}: {verb}")


@plan_group.command("reindex")
def plan_reindex() -> None:
    """Rebuild the derived plan index in the sessions DB from the documents."""
    count = PlanApplication().reindex()
    console.print(f"[green]Reindexed[/green] {count} plan(s).")


@plan_group.command("architect")
@click.option(
    "--agent",
    "-a",
    help="AI agent to launch (auto-detects if omitted).",
)
@click.pass_context
def plan_architect(ctx: click.Context, agent: str | None) -> None:
    """Start a study-plan-architect session.

    Convenience alias for ``studyloop study --mode plan-architect``, pinned to
    the topic "Study plan" so the interview-and-evaluate mentor never needs a
    topic of its own -- it is the same launch machinery every other mode uses,
    never a second launch path.
    """
    from studyloop.cli._study import study

    ctx.invoke(
        study,
        topic="Study plan",
        agent=agent,
        mode="plan-architect",
        timer=None,
        energy=5,
        web=False,
        lan=False,
        password="",
        resume=False,
        end_session=False,
    )


@plan_group.command("path")
def plan_path_cmd() -> None:
    """Print the directory holding plan documents."""
    click.echo(str(plans_dir()))
```

### `mcp/tools.py` — diff vs `a4862301`
```diff
diff --git a/packages/studyloop/src/studyloop/mcp/tools.py b/packages/studyloop/src/studyloop/mcp/tools.py
index ba6bc7c5..6083ec4f 100644
--- a/packages/studyloop/src/studyloop/mcp/tools.py
+++ b/packages/studyloop/src/studyloop/mcp/tools.py
@@ -145,19 +145,37 @@ def register_tools(mcp: FastMCP, *, include_exercises: bool = False) -> None:
             body: The record's body, as Markdown prose.
             status: Record status (default "active").
         """
-        from studyloop.planning import record_learning
-        from studyloop.planning.store import InvalidPlanIdError, PlanNotFoundError
+        from studyloop.planning import (
+            LearningRecordSpec,
+            PlanApplication,
+            PlanError,
+            PlanNotReady,
+            RevisePlan,
+        )

+        # One RevisePlan through the seam: the store's single learning-record
+        # rule and the resulting-document gate both apply, and every refusal is
+        # a domain error mapped here — a not-ready plan names its blockers so
+        # the agent can tell the learner what to fix (design §2).
+        spec = LearningRecordSpec(title=title, body=body, status=status)
+        plans = PlanApplication()
         try:
-            record, created = record_learning(plan_id, title, body=body, status=status)
-        except (PlanNotFoundError, InvalidPlanIdError, ValueError) as exc:
+            before = plans.inspect(plan_id)
+            detail = plans.apply(RevisePlan(plan_id=plan_id, learning_record=spec))
+        except PlanNotReady as exc:
+            blockers = "; ".join(exc.readiness.blockers)
+            raise ToolError(f"{exc}: {blockers}") from exc
+        except PlanError as exc:
             raise ToolError(str(exc)) from exc
+        record = detail.learning_record_matching(spec)
+        if record is None:  # pragma: no cover - the seam just appended or matched it
+            raise ToolError(f"learning record {spec.title!r} was not persisted on {plan_id!r}")
         return {
-            "plan_id": plan_id,
+            "plan_id": detail.summary.plan_id,
             "number": record.number,
             "title": record.title,
             "status": record.status,
-            "created": created,
+            "created": before.learning_record_matching(spec) is None,
         }

     @tool()
```

### `cli/_exercise.py`, `cli/_brain.py` — diff vs `a4862301`
```diff
diff --git a/packages/studyloop/src/studyloop/cli/_exercise.py b/packages/studyloop/src/studyloop/cli/_exercise.py
index c08b2787..77dfcc41 100644
--- a/packages/studyloop/src/studyloop/cli/_exercise.py
+++ b/packages/studyloop/src/studyloop/cli/_exercise.py
@@ -241,25 +241,24 @@ def exercise_from_milestone(plan_id: str, index: int | None, as_json: bool) -> N
     plan uses against ``study_progress`` — so the exercise, the milestone, and
     the confidence evidence all name the same thing.
     """
-    from studyloop.planning import load_plan
-    from studyloop.planning.store import InvalidPlanIdError, PlanNotFoundError
+    from studyloop.planning import PlanApplication, PlanError

     try:
-        plan = load_plan(plan_id)
-    except (PlanNotFoundError, InvalidPlanIdError) as exc:
+        detail = PlanApplication().inspect(plan_id)
+    except PlanError as exc:
         _fail(str(exc))

-    if not plan.milestones:
+    if not detail.milestones:
         _fail(f"Plan {plan_id!r} has no milestones to build exercises from.")
     if index is None:
-        milestone = plan.next_milestone() or plan.milestones[0]
-    elif 0 <= index < len(plan.milestones):
-        milestone = plan.milestones[index]
+        milestone = next((m for m in detail.milestones if not m.done), detail.milestones[0])
+    elif 0 <= index < len(detail.milestones):
+        milestone = detail.milestones[index]
     else:
-        _fail(f"No milestone at index {index} (plan has {len(plan.milestones)}).")
+        _fail(f"No milestone at index {index} (plan has {len(detail.milestones)}).")

-    item = from_milestone(plan.plan_id, milestone.title, milestone.concepts)
-    item.set_id = unique_set_id(plan.plan_id, item.topic)
+    item = from_milestone(detail.summary.plan_id, milestone.title, list(milestone.concepts))
+    item.set_id = unique_set_id(detail.summary.plan_id, item.topic)
     try:
         path = create_set(item)
     except (ExerciseSetExistsError, InvalidSetIdError) as exc:
diff --git a/packages/studyloop/src/studyloop/cli/_brain.py b/packages/studyloop/src/studyloop/cli/_brain.py
index aebf6179..db1a7a83 100644
--- a/packages/studyloop/src/studyloop/cli/_brain.py
+++ b/packages/studyloop/src/studyloop/cli/_brain.py
@@ -295,11 +295,12 @@ def _selected_plan_ids(
         return []
     if plan_ids:
         return list(plan_ids)
-    from studyloop.planning import list_plans
+    from studyloop.planning import PlanApplication

+    plans = PlanApplication()
     if publish_all:
-        return [plan.plan_id for plan in list_plans()]
-    return [plan.plan_id for plan in list_plans(status="active")]
+        return [plan.plan_id for plan in plans.browse()]
+    return [plan.plan_id for plan in plans.browse(status="active")]


 def _publish(backend, plan_ids: list[str], *, today: bool) -> list[PublishResult]:
```

### `web/static/js/components/plans-panel.js` — diff vs `a4862301`
```diff
diff --git a/packages/studyloop/src/studyloop/web/static/js/components/plans-panel.js b/packages/studyloop/src/studyloop/web/static/js/components/plans-panel.js
index 53721398..dfd602e8 100644
--- a/packages/studyloop/src/studyloop/web/static/js/components/plans-panel.js
+++ b/packages/studyloop/src/studyloop/web/static/js/components/plans-panel.js
@@ -42,7 +42,7 @@
  *                                learning_records, resources, checkpoints,
  *                                readiness}
  *   GET    /api/plans/{id}/evaluate?phase=…          {evaluation, markdown}
- *   POST   /api/plans/{id}/evaluate  201             {recorded, evaluation, …}
+ *   POST   /api/plans/{id}/evaluate  201             {recorded, db_write, document_write, evaluation, …}
  *   POST   /api/plans                201             {created, plan, readiness}
  *   PATCH  /api/plans/{id}           422 on refusal  detail={message, blockers…}
  *   POST   /api/plans/{id}/milestones/{i}/toggle     {updated, index, done, plan}
@@ -705,9 +705,19 @@ export const plansStore = {
       await this._fetchDetail(planId, epoch);
       if (epoch !== this._epoch) return;
       const verdict = this.evaluation?.verdict || '';
-      this.recordStatus = verdict
-        ? `Recorded ${phase} checkpoint \u2014 ${verdict}`
-        : `Recorded ${phase} checkpoint`;
+      if (data.recorded === false) {
+        /* The server reports each sink (Phase 2 seam); a failed database
+           write still returns the evaluation, so this is a status the
+           learner must see, not an error banner that hides the verdict. */
+        this.recordStatus =
+          `Partially recorded ${phase} checkpoint \u2014 ` +
+          `database: ${data.db_write ?? 'unknown'}, document: ${data.document_write ?? 'unknown'}` +
+          (verdict ? ` (${verdict})` : '');
+      } else {
+        this.recordStatus = verdict
+          ? `Recorded ${phase} checkpoint \u2014 ${verdict}`
+          : `Recorded ${phase} checkpoint`;
+      }
     } catch (e) {
       if (epoch === this._epoch) this.error = `Network error: ${e.message ?? e}`;
     } finally {
```


## 5. New tests (full source)

### `tests/test_plan_application_mutations.py`
```python
"""``PlanApplication`` Phase 2: milestone set, confirmed delete, assessment.

Contract tests for the intents that Phase 1 left to Phase 2 (design §1,
tasks T2.1/T2.2). Same rule as ``test_plan_application.py``: these assert the
seam's behaviour, not any adapter's, so the same invariants hold from the Web
API, the CLI and the MCP tools.

* ``SetMilestone`` is idempotent, refuses an index the plan does not have
  (negative included) with ``InvalidMilestone``, and — like every write —
  judges the *resulting* document when the plan is active.
* ``DeletePlan`` needs ``confirmed=True`` (``InvalidField`` otherwise), removes
  the canonical document, keeps the durable checkpoint log, and returns an
  explicit frozen ``DeleteResult``: a ``PlanDetail`` cannot describe a plan
  that no longer exists (council review 1, GPT hazard table).
* ``assess`` wraps the Phase-0 ``evaluate_and_record`` / ``evaluate_plan`` and
  reports the two sinks independently on a frozen ``AssessmentResult`` — no
  second checkpoint writer, no ``PartialRecording`` exception (D-1, D-3).
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from studyloop.planning import index as index_module
from studyloop.planning import store
from studyloop.planning.application import PlanApplication
from studyloop.planning.errors import (
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    PlanNotFound,
    PlanNotReady,
)
from studyloop.planning.intents import (
    AssessPlan,
    DeletePlan,
    LearningRecordSpec,
    RevisePlan,
    SetMilestone,
)
from studyloop.planning.models import Milestone, Mission, StudyPlan
from studyloop.planning.views import (
    AssessmentResult,
    DeleteResult,
    PlanDetail,
)

DB_WARNING = "checkpoint not saved to the database"
DOCUMENT_WARNING = "checkpoint not appended to the plan document"


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    """A fresh checkpoint database per test (council review 1, F6)."""
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))
    return tmp_path / "sessions.db"


@pytest.fixture
def app() -> PlanApplication:
    return PlanApplication()


def _plan(plan_id: str = "demo", *, status: str = "draft", milestones: int = 2) -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title=plan_id.replace("-", " ").title(),
        status=status,
        topics=["sql"],
        mission=Mission(why="Because", success=["Do a thing"]),
        milestones=[
            Milestone(title=f"Step {n}", concepts=[f"concept-{n}"])
            for n in range(1, milestones + 1)
        ],
    )
    store.create_plan(plan)
    return plan


def _count_saves(monkeypatch) -> list[int]:
    calls: list[int] = []
    real_save = store.save_plan

    def counting_save(plan, **kwargs):
        calls.append(1)
        return real_save(plan, **kwargs)

    monkeypatch.setattr(store, "save_plan", counting_save)
    return calls


def _document_checkpoints(plan_id: str) -> list[str]:
    return [checkpoint.phase for checkpoint in store.load_plan(plan_id).checkpoints]


def _database_checkpoints(plan_id: str) -> list[str]:
    return [str(row["phase"]) for row in index_module.checkpoint_history(plan_id)]


# ---------------------------------------------------------------------------
# SetMilestone
# ---------------------------------------------------------------------------


def test_set_milestone_done_is_idempotent(app: PlanApplication, monkeypatch) -> None:
    _plan("demo")
    saves = _count_saves(monkeypatch)

    first = app.apply(SetMilestone(plan_id="demo", index=0, done=True))
    assert isinstance(first, PlanDetail)
    assert first.milestones[0].done is True
    assert first.milestones[1].done is False
    assert first.summary.milestone_done == 1
    assert first.summary.progress_pct == 50
    assert len(saves) == 1, "a milestone set is one write"

    # Setting the same state again is a no-op on the document's meaning: the
    # milestone is still done, nothing else moved, and a retry is always safe.
    again = app.apply(SetMilestone(plan_id="demo", index=0, done=True))
    assert again.milestones[0].done is True
    assert again.summary.milestone_done == 1
    assert [m.done for m in again.milestones] == [m.done for m in first.milestones]
    assert store.load_plan("demo").milestones[0].done is True

    # And it can be undone explicitly — set, not toggled.
    undone = app.apply(SetMilestone(plan_id="demo", index=0, done=False))
    assert undone.milestones[0].done is False
    assert undone.summary.milestone_done == 0
    assert store.load_plan("demo").milestones[0].done is False


@pytest.mark.parametrize("index", [2, 42], ids=["one-past-the-end", "far-out"])
def test_set_unknown_milestone_raises_invalid_milestone(
    app: PlanApplication, monkeypatch, index: int
) -> None:
    _plan("demo", milestones=2)
    before = store.load_plan_text("demo")
    saves = _count_saves(monkeypatch)

    with pytest.raises(InvalidMilestone) as caught:
        app.apply(SetMilestone(plan_id="demo", index=index, done=True))

    assert str(index) in str(caught.value)
    assert saves == [], "a refused set writes nothing"
    assert store.load_plan_text("demo") == before


def test_set_milestone_negative_index_raises(app: PlanApplication, monkeypatch) -> None:
    """``-1`` would silently address the last milestone if the seam indexed
    the list directly; the contract is that a milestone index is 0-based and
    non-negative, and anything else is the same refusal as an index past the
    end (council review 1, GPT hazard table)."""
    _plan("demo", milestones=2)
    before = store.load_plan_text("demo")
    saves = _count_saves(monkeypatch)

    with pytest.raises(InvalidMilestone):
        app.apply(SetMilestone(plan_id="demo", index=-1, done=True))

    assert saves == []
    assert store.load_plan_text("demo") == before
    assert [m.done for m in app.inspect("demo").milestones] == [False, False]


def test_set_milestone_unknown_plan_raises_not_found_before_index(app: PlanApplication) -> None:
    with pytest.raises(PlanNotFound):
        app.apply(SetMilestone(plan_id="missing", index=99, done=True))


def test_set_milestone_on_unready_active_document_is_refused(
    app: PlanApplication, isolated_plans_dir, monkeypatch
) -> None:
    """The resulting-document rule applies to every write. A hand-edited
    active plan that has lost its mission is unready; ticking a milestone on
    it would re-save an active-but-unready document, so it is refused with
    the same ``PlanNotReady`` every other door raises, and nothing is written."""
    store.plans_dir()
    (isolated_plans_dir / "hand-edited.md").write_text(
        "---\nid: hand-edited\ntitle: Hand Edited\nstatus: active\n---\n\n"
        "# Hand Edited\n\n## Milestones\n\n- [ ] **Step** `(concepts: x)`\n",
        encoding="utf-8",
    )
    before = store.load_plan_text("hand-edited")
    saves = _count_saves(monkeypatch)

    with pytest.raises(PlanNotReady) as caught:
        app.apply(SetMilestone(plan_id="hand-edited", index=0, done=True))

    assert caught.value.readiness.ready is False
    assert saves == []
    assert store.load_plan_text("hand-edited") == before


def test_set_milestone_preserves_id_created_and_other_fields(app: PlanApplication) -> None:
    plan = _plan("stable")
    detail = app.apply(SetMilestone(plan_id="stable", index=1, done=True))
    assert detail.summary.plan_id == "stable"
    assert detail.summary.created == plan.created
    assert detail.summary.title == "Stable"
    assert [m.title for m in detail.milestones] == ["Step 1", "Step 2"]
    assert [m.concepts for m in detail.milestones] == [("concept-1",), ("concept-2",)]
    assert store.list_plan_ids() == ["stable"]


# ---------------------------------------------------------------------------
# DeletePlan
# ---------------------------------------------------------------------------


def test_delete_without_confirm_raises_invalid_field(app: PlanApplication) -> None:
    _plan("demo")
    before = store.load_plan_text("demo")

    with pytest.raises(InvalidField):
        app.apply(DeletePlan(plan_id="demo"))
    with pytest.raises(InvalidField):
        app.apply(DeletePlan(plan_id="demo", confirmed=False))

    assert store.load_plan_text("demo") == before
    assert store.list_plan_ids() == ["demo"]


def test_delete_returns_delete_result_and_document_gone(app: PlanApplication) -> None:
    _plan("demo")

    result = app.apply(DeletePlan(plan_id="demo", confirmed=True))

    assert isinstance(result, DeleteResult)
    assert not isinstance(result, PlanDetail)
    assert result.plan_id == "demo"
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(result, "plan_id", "other")  # noqa: B010
    assert result.to_json_dict() == {"deleted": True, "plan_id": "demo"}
    assert result.to_json_dict() is not result.to_json_dict()

    assert store.list_plan_ids() == []
    with pytest.raises(PlanNotFound):
        app.inspect("demo")
    with pytest.raises(PlanNotFound):
        app.apply(DeletePlan(plan_id="demo", confirmed=True))
    # The derived index row goes with the document.
    assert [row["plan_id"] for row in index_module.indexed_plans()] == []


def test_delete_retains_checkpoint_history(app: PlanApplication) -> None:
    _plan("demo")
    recorded = app.assess(AssessPlan(plan_id="demo", phase="start", study_id="sess-1", record=True))
    assert recorded.db_write == "saved"
    assert _database_checkpoints("demo") == ["start"]

    app.apply(DeletePlan(plan_id="demo", confirmed=True))

    assert store.list_plan_ids() == []
    history = index_module.checkpoint_history("demo")
    assert [row["phase"] for row in history] == ["start"], "the durable log survives deletion"
    assert history[0]["study_id"] == "sess-1"


def test_delete_unknown_plan_raises_not_found_and_traversal_id_is_invalid(
    app: PlanApplication,
) -> None:
    with pytest.raises(PlanNotFound):
        app.apply(DeletePlan(plan_id="missing", confirmed=True))
    with pytest.raises(InvalidPlanId):
        app.apply(DeletePlan(plan_id="../escape", confirmed=True))


# ---------------------------------------------------------------------------
# AssessPlan / assess
# ---------------------------------------------------------------------------


def test_assess_preview_writes_neither_sink(app: PlanApplication, monkeypatch) -> None:
    _plan("demo")
    saves = _count_saves(monkeypatch)

    def must_not_be_called(evaluation, *, study_id=""):
        raise AssertionError("preview must not touch the checkpoint log")

    monkeypatch.setattr(index_module, "record_checkpoint", must_not_be_called)

    result = app.assess(AssessPlan(plan_id="demo", phase="mid", record=False))

    assert isinstance(result, AssessmentResult)
    assert result.db_write == "not_requested"
    assert result.document_write == "not_requested"
    assert result.recording_complete is True, "nothing was requested, so nothing is incomplete"
    assert result.evaluation.phase == "mid"
    assert result.evaluation.plan_id == "demo"
    assert result.evaluation.verdict in {"on-track", "at-risk", "stalled", "complete"}
    assert DB_WARNING not in result.warnings
    assert DOCUMENT_WARNING not in result.warnings
    assert saves == []
    assert _document_checkpoints("demo") == []
    assert _database_checkpoints("demo") == []


def test_assess_record_true_reports_both_sinks_saved(app: PlanApplication) -> None:
    _plan("demo")

    result = app.assess(AssessPlan(plan_id="demo", phase="end", study_id="sess-9"))

    assert result.db_write == "saved"
    assert result.document_write == "saved"
    assert result.recording_complete is True
    assert DB_WARNING not in result.warnings
    assert DOCUMENT_WARNING not in result.warnings
    assert result.evaluation.study_id == "sess-9"
    assert _document_checkpoints("demo") == ["end"]
    assert _database_checkpoints("demo") == ["end"]
    assert index_module.checkpoint_history("demo")[0]["study_id"] == "sess-9"
    # The seam's view of the plan agrees: the document table has the row.
    assert [c.phase for c in app.inspect("demo").checkpoints] == ["end"]


def test_assess_db_failure_reports_failed_sink_and_returns_evaluation(
    app: PlanApplication, monkeypatch
) -> None:
    _plan("demo")
    monkeypatch.setattr(index_module, "record_checkpoint", lambda evaluation, *, study_id="": False)

    result = app.assess(AssessPlan(plan_id="demo", phase="start"))

    assert result.db_write == "failed"
    assert result.document_write == "saved"
    assert result.recording_complete is False
    assert DB_WARNING in result.warnings
    assert DOCUMENT_WARNING not in result.warnings
    assert DB_WARNING in result.evaluation.warnings
    assert result.evaluation.verdict in {"on-track", "at-risk", "stalled", "complete"}
    assert _document_checkpoints("demo") == ["start"], "the document sink was still written"
    assert _database_checkpoints("demo") == []


def test_assess_document_failure_reported_independently(app: PlanApplication, monkeypatch) -> None:
    _plan("demo")

    def refuse_write(plan, **kwargs):
        msg = "read-only file system"
        raise OSError(msg)

    monkeypatch.setattr(store, "save_plan", refuse_write)

    result = app.assess(AssessPlan(plan_id="demo", phase="start"))

    assert result.db_write == "saved", "the database sink succeeded on its own"
    assert result.document_write == "failed"
    assert result.recording_complete is False
    assert DOCUMENT_WARNING in result.warnings
    assert DB_WARNING not in result.warnings
    assert _database_checkpoints("demo") == ["start"]
    assert _document_checkpoints("demo") == [], "the on-disk document is unchanged"


def test_assess_append_to_plan_false_leaves_document_sink_not_requested(
    app: PlanApplication,
) -> None:
    _plan("demo")
    result = app.assess(AssessPlan(plan_id="demo", phase="start", append_to_plan=False))
    assert result.db_write == "saved"
    assert result.document_write == "not_requested"
    assert result.recording_complete is True
    assert _document_checkpoints("demo") == []
    assert _database_checkpoints("demo") == ["start"]


def test_assess_unknown_plan_and_bad_phase(app: PlanApplication) -> None:
    # 404 before 400: the plan must exist before the phase is judged.
    with pytest.raises(PlanNotFound):
        app.assess(AssessPlan(plan_id="missing", phase="nope"))
    _plan("demo")
    with pytest.raises(InvalidField):
        app.assess(AssessPlan(plan_id="demo", phase="nope"))
    assert _document_checkpoints("demo") == []
    assert _database_checkpoints("demo") == []


def test_assessment_result_is_frozen_and_matches_the_legacy_evaluation_dict(
    app: PlanApplication,
) -> None:
    """The Web body ``{"evaluation": evaluation.to_dict(), "markdown":
    evaluation.as_markdown()}`` must not change when the route delegates
    (D-3): the view serialises to the same dict and carries the same rendering."""
    from studyloop.planning.evaluation import evaluate_plan

    _plan("demo")
    result = app.assess(AssessPlan(plan_id="demo", phase="start", record=False))
    legacy = evaluate_plan(store.load_plan("demo"), "start")

    payload = result.evaluation.to_json_dict()
    # ``at`` is a timestamp taken at evaluation time; everything else is the
    # same computation over the same document and database.
    legacy_dict = legacy.to_dict()
    payload.pop("at")
    legacy_dict.pop("at")
    assert payload == legacy_dict
    assert result.evaluation.markdown.startswith("### Plan checkpoint — Demo (start)")
    assert result.evaluation.markdown.splitlines()[0] == legacy.as_markdown().splitlines()[0]

    for view in (result, result.evaluation):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(view, "phase", "end")  # noqa: B010
    assert isinstance(result.warnings, tuple)
    assert isinstance(result.evaluation.recommendations, tuple)
    assert isinstance(result.evaluation.warnings, tuple)

    first = result.evaluation.to_json_dict()
    second = result.evaluation.to_json_dict()
    assert first == second
    assert first is not second
    first["recommendations"].append("leaked")
    assert result.evaluation.to_json_dict() == second
    json.dumps(first, default=str)


# ---------------------------------------------------------------------------
# Browse over a directory holding a malformed document
# ---------------------------------------------------------------------------


def test_malformed_plan_browse_matches_store_list(app: PlanApplication, isolated_plans_dir) -> None:
    """One unparseable file must not hide the others, and the seam must show
    exactly what the store shows — no more (the broken file is not invented),
    no less (the good plans are not dropped)."""
    _plan("good")
    _plan("also-good", status="active")
    store.plans_dir()
    # The frontmatter parser falls back to a naive key/value reader, so a
    # document has to be genuinely unreadable to be skipped: bytes that are not
    # UTF-8 at all.
    (isolated_plans_dir / "broken.md").write_bytes(b"\xff\xfe not a text file")

    browsed = [p.plan_id for p in app.browse()]

    assert browsed == [p.plan_id for p in store.list_plans()]
    assert browsed == ["also-good", "good"]
    assert "broken" in store.list_plan_ids(), "the file is still on disk"
    assert [p.plan_id for p in app.browse(status="active")] == ["also-good"]


# ---------------------------------------------------------------------------
# Learning records: one rule, owned by the store, reached through the seam
# ---------------------------------------------------------------------------


def test_learning_record_validation_is_the_stores_single_copy(
    app: PlanApplication, monkeypatch
) -> None:
    """The seam appends a learning record by calling the store's rule on the
    candidate — it does not carry a second copy of the title/heading checks.
    Swap the store's function and the seam follows it."""
    _plan("demo")

    def refuse(plan, title, *, body="", status="active"):
        msg = "the store said no"
        raise ValueError(msg)

    monkeypatch.setattr(store, "append_learning_record", refuse)

    with pytest.raises(InvalidField, match="the store said no"):
        app.apply(RevisePlan(plan_id="demo", learning_record=LearningRecordSpec(title="Fine")))
    assert app.inspect("demo").learning_records == ()


def test_plan_detail_finds_the_learning_record_a_spec_would_match(app: PlanApplication) -> None:
    """Adapters that report ``created`` need to know whether a record already
    existed before they applied the revision; the view answers with the same
    stripped title-and-body identity the store's idempotency rule uses."""
    _plan("demo")
    spec = LearningRecordSpec(title="  Window frames default to RANGE ", body=" Not ROWS. ")

    before = app.inspect("demo")
    assert before.learning_record_matching(spec) is None

    after = app.apply(RevisePlan(plan_id="demo", learning_record=spec))
    found = after.learning_record_matching(spec)
    assert found is not None
    assert (found.number, found.title, found.body) == (
        1,
        "Window frames default to RANGE",
        "Not ROWS.",
    )
    assert (
        after.learning_record_matching(
            LearningRecordSpec(title="Window frames default to RANGE", body="Different body")
        )
        is None
    )


# ---------------------------------------------------------------------------
# Reindex: the one index writer an adapter may still reach, through the seam
# ---------------------------------------------------------------------------


def test_reindex_rebuilds_the_derived_index_and_returns_the_count(app: PlanApplication) -> None:
    _plan("one")
    _plan("two", status="active")
    count = app.reindex()
    assert count == 2
    assert sorted(row["plan_id"] for row in index_module.indexed_plans()) == ["one", "two"]
```

### `tests/test_plan_guidance.py`
```python
"""``PlanApplication.get_active_guidance`` — the plan-static read the ``now``
engine consumes (design §1, §3; decision D-5).

One ``ActivePlanGuidance`` per *active* plan, in a deterministic order, with
everything the ranker needs precomputed: the next unchecked milestone, the
normalised match keys (topics plus every milestone concept), the target-date
urgency bucket, the energy floor, and — for a plan whose every milestone is
ticked — a completion action instead of a study candidate. Malformed documents
become warnings, never exceptions: the ranker must always get an answer.

Several plans may be active at once (public doc, council review 1), so the
view is a collection and never an arbitrary singleton.

Phase 3 (#10) wires this into ``decision.py``; nothing consumes it yet.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, date, datetime, timedelta

import pytest

from studyloop.planning import store
from studyloop.planning.application import PlanApplication
from studyloop.planning.models import Milestone, Mission, StudyPlan
from studyloop.planning.views import (
    ActiveGuidance,
    ActivePlanGuidance,
    MilestoneView,
    PlanSummary,
    normalise_match_key,
)

TODAY = date(2026, 9, 16)


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture
def app() -> PlanApplication:
    return PlanApplication()


def _active(
    plan_id: str,
    *,
    topics: list[str] | None = None,
    milestones: list[Milestone] | None = None,
    target_date: str = "",
    energy_floor: int = 3,
    status: str = "active",
) -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title=plan_id.replace("-", " ").title(),
        status=status,
        topics=topics if topics is not None else ["sql"],
        energy_floor=energy_floor,
        target_date=target_date,
        mission=Mission(why="Because", success=["Do a thing"]),
        milestones=(
            milestones
            if milestones is not None
            else [Milestone(title="Step one", concepts=["window function"])]
        ),
    )
    store.create_plan(plan)
    return plan


def _guidance(app: PlanApplication, *, today: date | None = TODAY) -> ActiveGuidance:
    return app.get_active_guidance(today=today)


# ---------------------------------------------------------------------------


def test_active_guidance_one_per_active_plan_with_match_keys_and_urgency(
    app: PlanApplication,
) -> None:
    _active(
        "sql-windows",
        topics=["SQL", "Data-Engineering"],
        milestones=[
            Milestone(title="OVER clause", done=True, concepts=["Window-Function"]),
            Milestone(title="Ranking", concepts=["RANK vs DENSE_RANK", "dense rank"]),
            Milestone(title="Frames", concepts=["window frame"]),
        ],
        target_date=(TODAY + timedelta(days=30)).isoformat(),
        energy_floor=6,
    )
    _active("glue-etl", topics=["glue"], target_date=(TODAY - timedelta(days=2)).isoformat())
    _active("a-draft", status="draft")
    _active("paused-one", status="paused")

    guidance = _guidance(app)

    assert isinstance(guidance, ActiveGuidance)
    assert guidance.warnings == ()
    assert [g.plan.plan_id for g in guidance.plans] == ["glue-etl", "sql-windows"]
    assert all(isinstance(g, ActivePlanGuidance) for g in guidance.plans)

    sql = guidance.plans[1]
    assert isinstance(sql.plan, PlanSummary)
    assert sql.plan.status == "active"
    assert isinstance(sql.next_milestone, MilestoneView)
    assert (sql.next_milestone.index, sql.next_milestone.title) == (1, "Ranking")
    assert sql.next_milestone.concepts == ("RANK vs DENSE_RANK", "dense rank")
    # Topics and every milestone's concepts — done or not — casefolded with
    # punctuation stripped, so a candidate topic "data-engineering" or a due
    # concept "Window Function" matches by equality, never by substring.
    assert sql.match_keys == frozenset(
        {
            "sql",
            "data engineering",
            "window function",
            "rank vs dense rank",
            "dense rank",
            "window frame",
        }
    )
    assert isinstance(sql.match_keys, frozenset)
    assert sql.target_urgency == "later"
    assert sql.energy_floor == 6
    assert sql.completion_action is None
    assert sql.warnings == ()

    glue = guidance.plans[0]
    assert glue.target_urgency == "overdue"
    assert glue.energy_floor == 3
    assert glue.match_keys == frozenset({"glue", "window function"})
    assert glue.next_milestone is not None and glue.next_milestone.index == 0


def test_active_guidance_orders_by_plan_id_and_skips_non_active(app: PlanApplication) -> None:
    # Store order is active-first then ``updated``; guidance order is the plan
    # id, so the ranker's output is stable across edits.
    _active("zeta", target_date="")
    _active("alpha")
    _active("mid")
    for status in ("draft", "paused", "complete", "abandoned"):
        _active(f"{status}-plan", status=status)

    guidance = _guidance(app)

    assert [g.plan.plan_id for g in guidance.plans] == ["alpha", "mid", "zeta"]
    assert guidance == _guidance(app), "repeat calls return equal views"
    assert all(g.plan.status == "active" for g in guidance.plans)


def test_active_guidance_empty_when_nothing_is_active(app: PlanApplication) -> None:
    _active("draft-only", status="draft")
    guidance = _guidance(app)
    assert guidance.plans == ()
    assert guidance.warnings == ()
    assert guidance.to_json_dict() == {"plans": [], "warnings": []}


def test_active_guidance_completion_action_when_all_done(app: PlanApplication) -> None:
    _active(
        "finished",
        milestones=[
            Milestone(title="One", done=True, concepts=["a"]),
            Milestone(title="Two", done=True, concepts=["b"]),
        ],
    )
    _active("in-flight")

    guidance = _guidance(app)
    finished, in_flight = guidance.plans

    assert finished.plan.plan_id == "finished"
    assert finished.next_milestone is None
    assert finished.completion_action is not None
    assert "Finished" in finished.completion_action
    assert finished.match_keys == frozenset({"sql", "a", "b"})
    assert in_flight.completion_action is None
    assert in_flight.next_milestone is not None


@pytest.mark.parametrize(
    ("target_offset_days", "expected"),
    [
        (-30, "overdue"),
        (-1, "overdue"),
        (0, "soon"),
        (1, "soon"),
        (7, "soon"),
        (8, "later"),
        (90, "later"),
        (None, "undated"),
    ],
    ids=["month-ago", "yesterday", "today", "tomorrow", "week", "eight-days", "quarter", "unset"],
)
def test_active_guidance_target_urgency_buckets(
    app: PlanApplication, target_offset_days: int | None, expected: str
) -> None:
    target = "" if target_offset_days is None else (TODAY + timedelta(days=target_offset_days))
    _active("dated", target_date=target.isoformat() if isinstance(target, date) else "")

    (only,) = _guidance(app).plans

    assert only.target_urgency == expected
    assert only.warnings == ()


def test_active_guidance_defaults_to_the_real_today(app: PlanApplication) -> None:
    real_today = datetime.now(UTC).date()
    _active("dated", target_date=(real_today + timedelta(days=60)).isoformat())
    (only,) = _guidance(app, today=None).plans
    assert only.target_urgency == "later"


def test_active_guidance_warns_on_malformed_documents(
    app: PlanApplication, isolated_plans_dir
) -> None:
    """A hand-edited active plan with no milestones, an unparseable target
    date, and an unparseable document beside it: the ranker still gets a
    view, and every defect is named rather than raised or silently dropped."""
    store.plans_dir()
    (isolated_plans_dir / "no-milestones.md").write_text(
        "---\nid: no-milestones\ntitle: No Milestones\nstatus: active\n"
        "target_date: someday\n---\n\n# No Milestones\n\n## Mission\n\n### Why\n\nBecause.\n",
        encoding="utf-8",
    )
    (isolated_plans_dir / "broken.md").write_bytes(b"\xff\xfe not a text file")
    _active("healthy")

    guidance = _guidance(app)

    assert [g.plan.plan_id for g in guidance.plans] == ["healthy", "no-milestones"]
    assert any("broken" in warning for warning in guidance.warnings)

    degraded = guidance.plans[1]
    assert degraded.next_milestone is None
    assert degraded.completion_action is None, "nothing to complete when nothing was planned"
    assert degraded.target_urgency == "undated"
    assert any("milestone" in warning for warning in degraded.warnings)
    assert any("someday" in warning for warning in degraded.warnings)
    assert guidance.plans[0].warnings == ()


def test_active_guidance_views_are_frozen_and_json_fresh(app: PlanApplication) -> None:
    _active("demo", target_date=(TODAY + timedelta(days=3)).isoformat())
    guidance = _guidance(app)
    (only,) = guidance.plans

    for view in (guidance, only):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(view, "warnings", ("mutated",))  # noqa: B010
    assert isinstance(guidance.plans, tuple)
    assert isinstance(only.warnings, tuple)

    first = guidance.to_json_dict()
    second = guidance.to_json_dict()
    assert first == second
    assert first is not second
    assert first["plans"][0]["plan"]["plan_id"] == "demo"
    assert first["plans"][0]["next_milestone"]["index"] == 0
    assert sorted(first["plans"][0]["match_keys"]) == ["sql", "window function"]
    assert first["plans"][0]["target_urgency"] == "soon"
    assert first["plans"][0]["energy_floor"] == 3
    assert first["plans"][0]["completion_action"] is None
    first["plans"][0]["match_keys"].append("leaked")
    first["plans"][0]["plan"]["topics"].append("leaked")
    assert guidance.to_json_dict() == second
    json.dumps(first)


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("SQL", "sql"),
        ("Data-Engineering", "data engineering"),
        ("Window-Function", "window function"),
        ("RANK()", "rank"),
        ("  dbt  ", "dbt"),
        ("Straße", "strasse"),
        ("a.b_c", "a b c"),
        ("!!!", ""),
    ],
)
def test_normalise_match_key(raw: str, key: str) -> None:
    """Casefold, replace punctuation with spaces, collapse whitespace. The
    ranker applies the same function to its candidates, so matching is
    equality on this key and never a substring test (design §3 step 4)."""
    assert normalise_match_key(raw) == key
```

### `tests/test_architecture_plan_seam.py`
```python
"""Architecture guard: adapters reach study plans only through the seam (D-6).

Design §6. Policy that lives in an adapter is policy that exists once per
adapter — issue #7's readiness gate lived on one Web route and missed two
other doors into ``active``. The seam fixes that by construction *only if
adapters cannot go round it*, so this test parses every module under the
three adapter packages and fails on any import that reaches the storage,
index, authoring or evaluation layer directly:

* ``import studyloop.planning.store`` / ``from studyloop.planning.store import …``
  (and ``.index``, ``.authoring``, ``.evaluation``), relative forms resolved;
* ``from studyloop.planning import <name>`` where ``<name>`` is one of the
  explicitly listed writers/readers those four modules contribute to the
  package namespace — ``save_plan``, ``load_plan``, ``evaluate_and_record``,
  ``readiness``… — or one of the submodules themselves;
* ``import studyloop.planning`` / ``from studyloop import planning`` — a
  whole-package handle defeats the name check;
* a string constant naming a forbidden module (``importlib.import_module``).

Allowed: ``studyloop.planning.application|views|intents|errors``, and from
``studyloop.planning`` itself the re-exported view/intent/error names,
``PlanApplication``, the read-only constants (``PLAN_STATUSES``,
``CHECKPOINT_PHASES``, ``INTERVIEW``) and ``plans_dir`` — a location
resolver with no plan read or write behind it, used by ``studyloop plan
path``.

A second test plants ``from studyloop.planning.store import save_plan`` into a
temp copy of a real adapter module and asserts the checker rejects it, so a
green run is evidence the checker sees what it claims to. A third asserts the
explicit name list cannot rot: every callable or class ``studyloop.planning``
re-exports from the four modules must be listed (or explicitly allowed).

Out of scope, by construction: attribute access on an already-imported
allowed name, and imports built from non-literal strings.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

import studyloop

SRC_ROOT = Path(studyloop.__file__).resolve().parent.parent  # …/src
ADAPTER_PACKAGES = ("studyloop.cli", "studyloop.web.routes", "studyloop.mcp")

FORBIDDEN_MODULES = (
    "studyloop.planning.store",
    "studyloop.planning.index",
    "studyloop.planning.authoring",
    "studyloop.planning.evaluation",
)
ALLOWED_MODULES = (
    "studyloop.planning.application",
    "studyloop.planning.views",
    "studyloop.planning.intents",
    "studyloop.planning.errors",
)

#: Names ``studyloop.planning`` re-exports from the four forbidden modules. An
#: adapter importing one of these from the package has reached round the seam
#: exactly as surely as importing the module. Listed explicitly (design §6);
#: ``test_forbidden_name_list_covers_every_reexport`` keeps it honest.
FORBIDDEN_PACKAGE_NAMES = frozenset(
    {
        # the submodules themselves, as names
        "store",
        "index",
        "authoring",
        "evaluation",
        # store — document reads and writes, id allocation, the store error family
        "append_learning_record",
        "create_plan",
        "delete_plan",
        "list_plan_ids",
        "list_plans",
        "load_plan",
        "load_plan_text",
        "plan_path",
        "record_learning",
        "save_plan",
        "unique_plan_id",
        "InvalidPlanIdError",
        "PlanExistsError",
        "PlanNotFoundError",
        # index — the derived cache and the checkpoint log
        "checkpoint_history",
        "indexed_plans",
        "reindex_all",
        # authoring — the readiness policy, drafting, the interview and the seed
        "draft_plan",
        "interview_spec",
        "readiness",
        "seed_from_history",
        "InterviewQuestion",
        # evaluation — the checkpoint writer and its mutable result models
        "evaluate_and_record",
        "evaluate_plan",
        "PlanEvaluation",
        "ConceptEvidence",
    }
)

#: Re-exports that live in a forbidden module but carry no plan read or write.
ALLOWED_PACKAGE_NAMES = frozenset({"plans_dir"})


@dataclass(frozen=True)
class Violation:
    path: str
    lineno: int
    statement: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: {self.statement}  — {self.reason}"


def _module_name_for(path: Path) -> str:
    relative = path.resolve().relative_to(SRC_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(module_name: str, is_package: bool, level: int, target: str | None) -> str:
    """Turn ``from ..x import y`` inside ``module_name`` into an absolute module."""
    base = module_name.split(".")
    if not is_package:
        base = base[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    prefix = ".".join(base)
    if not target:
        return prefix
    return f"{prefix}.{target}" if prefix else target


def _is_forbidden_module(name: str) -> bool:
    return any(name == root or name.startswith(root + ".") for root in FORBIDDEN_MODULES)


def _check_module(path: Path, *, module_name: str | None = None) -> list[Violation]:
    """Every seam-bypassing import in one file (see the module docstring)."""
    module_name = module_name or _module_name_for(path)
    is_package = path.name == "__init__.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    out: list[Violation] = []

    def flag(node: ast.AST, reason: str) -> None:
        lineno = getattr(node, "lineno", 0)
        statement = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ast.dump(node)
        out.append(Violation(str(path), lineno, statement, reason))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    flag(node, f"imports {alias.name!r} directly; go through PlanApplication")
                elif alias.name == "studyloop.planning":
                    flag(node, "a whole-package handle reaches every storage module")
        elif isinstance(node, ast.ImportFrom):
            target = (
                _resolve_relative(module_name, is_package, node.level, node.module)
                if node.level
                else (node.module or "")
            )
            if _is_forbidden_module(target):
                flag(node, f"imports from {target!r} directly; go through PlanApplication")
            elif target == "studyloop.planning":
                for alias in node.names:
                    if alias.name in FORBIDDEN_PACKAGE_NAMES:
                        flag(
                            node,
                            f"{alias.name!r} is a store/index/authoring/evaluation name "
                            "re-exported by the package; go through PlanApplication",
                        )
            elif target == "studyloop" and any(a.name == "planning" for a in node.names):
                flag(node, "a whole-package handle reaches every storage module")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _is_forbidden_module(node.value)
        ):
            flag(node, f"names {node.value!r} as a string (dynamic import)")
    return out


def _adapter_files() -> list[Path]:
    files: list[Path] = []
    for package in ADAPTER_PACKAGES:
        root = SRC_ROOT.joinpath(*package.split("."))
        assert root.is_dir(), root
        files.extend(sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts))
    return files


def check_adapters() -> tuple[list[Path], list[Violation]]:
    files = _adapter_files()
    violations = [violation for path in files for violation in _check_module(path)]
    return files, violations


# ---------------------------------------------------------------------------


def test_adapters_import_plans_only_through_the_seam() -> None:
    files, violations = check_adapters()

    scanned = {str(p.relative_to(SRC_ROOT)) for p in files}
    for must_see in (
        "studyloop/cli/_plan.py",
        "studyloop/web/routes/plans.py",
        "studyloop/mcp/tools.py",
    ):
        assert must_see in scanned, f"the guard did not scan {must_see}"
    assert len(files) > 30, "the guard scanned suspiciously few adapter modules"

    assert violations == [], "seam bypass:\n" + "\n".join(str(v) for v in violations)


@pytest.mark.parametrize(
    "planted",
    [
        "from studyloop.planning.store import save_plan",
        "from studyloop.planning.index import record_checkpoint",
        "from studyloop.planning.authoring import readiness",
        "from studyloop.planning.evaluation import evaluate_and_record",
        "import studyloop.planning.store as plan_store",
        "from studyloop.planning import load_plan",
        "from studyloop.planning import store",
        "from studyloop.planning import PlanApplication, save_plan",
        "from ...planning.store import save_plan",
        "from ...planning import readiness",
        "import studyloop.planning",
        "from studyloop import planning",
        'store_module = __import__("studyloop.planning.store")',
        "def later():\n    from studyloop.planning import create_plan\n    return create_plan",
    ],
    ids=[
        "store-module",
        "index-module",
        "authoring-module",
        "evaluation-module",
        "import-as",
        "package-name",
        "package-submodule",
        "mixed-allowed-and-forbidden",
        "relative-module",
        "relative-package-name",
        "whole-package",
        "from-studyloop-import-planning",
        "dynamic-string",
        "nested-in-function",
    ],
)
def test_planted_violation_is_rejected(tmp_path, planted: str) -> None:
    """Plant a bypass into a copy of a real adapter and prove the checker sees it."""
    original = SRC_ROOT / "studyloop" / "web" / "routes" / "plans.py"
    assert _check_module(original) == [], "the fixture module must itself be clean"

    copy = tmp_path / "plans.py"
    shutil.copy(original, copy)
    copy.write_text(copy.read_text(encoding="utf-8") + "\n" + planted + "\n", encoding="utf-8")

    violations = _check_module(copy, module_name="studyloop.web.routes.plans")

    assert violations, f"planted bypass not detected: {planted!r}"
    assert all(
        "PlanApplication" in v.reason or "package" in v.reason or "string" in v.reason
        for v in violations
    ), violations


@pytest.mark.parametrize(
    "allowed",
    [
        "from studyloop.planning import PlanApplication, RevisePlan, PlanError, PlanDetail",
        "from studyloop.planning import PLAN_STATUSES, CHECKPOINT_PHASES, INTERVIEW, plans_dir",
        "from studyloop.planning.views import ActiveGuidance",
        "from studyloop.planning.intents import SetMilestone",
        "from studyloop.planning.errors import PlanNotReady",
        "from studyloop.planning.application import PlanApplication",
        "from studyloop.planning.exercises import list_sets",
        "from studyloop.planning.exercises.store import ExerciseSetNotFoundError",
    ],
)
def test_allowed_imports_are_not_flagged(tmp_path, allowed: str) -> None:
    copy = tmp_path / "plans.py"
    shutil.copy(SRC_ROOT / "studyloop" / "web" / "routes" / "plans.py", copy)
    copy.write_text(copy.read_text(encoding="utf-8") + "\n" + allowed + "\n", encoding="utf-8")
    assert _check_module(copy, module_name="studyloop.web.routes.plans") == []


def test_forbidden_name_list_covers_every_reexport() -> None:
    """The explicit list must name every callable/class the package re-exports
    from the four forbidden modules — a new store writer added to
    ``planning/__init__.py`` cannot slip past the guard unlisted."""
    package = importlib.import_module("studyloop.planning")
    reexported: set[str] = set()
    for name in package.__all__:
        obj = getattr(package, name)
        module = getattr(obj, "__module__", None)
        if not (inspect.isfunction(obj) or inspect.isclass(obj)) or module is None:
            continue
        if module in FORBIDDEN_MODULES:
            reexported.add(name)

    unlisted = reexported - FORBIDDEN_PACKAGE_NAMES - ALLOWED_PACKAGE_NAMES
    assert not unlisted, f"re-exported from a forbidden module but not listed: {sorted(unlisted)}"
    assert not (FORBIDDEN_PACKAGE_NAMES & ALLOWED_PACKAGE_NAMES)
    assert not (ALLOWED_MODULES and set(ALLOWED_MODULES) & set(FORBIDDEN_MODULES))
```

### `tests/test_web_plans_seam.py`
```python
"""Web plan routes that Phase 2 moved onto the seam: evaluate, toggle, delete.

``tests/test_web_plans.py`` is frozen at its pre-seam assertions (its bodies
must not change: D-3). This file pins what is *new* once those routes
delegate to ``PlanApplication``:

* ``POST /plans/{id}/evaluate`` reports each recording sink and an honest
  ``recorded`` — Bug B (issue #7) was a bare ``true`` over a failed write;
* the milestone checkbox is an idempotent ``SetMilestone`` behind the route,
  so a retried request cannot flip a box twice;
* ``DELETE`` is a confirmed ``DeletePlan``: the document and its index row go,
  the durable checkpoint log stays.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from studyloop.planning import PlanApplication, store
from studyloop.planning import index as index_module
from studyloop.web.app import create_app


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


PAYLOAD = {
    "title": "SQL Window Functions",
    "answers": {
        "why": "Ship analytics queries without help",
        "success": ["Write a RANK() query unaided"],
        "topics": ["sql"],
        "milestones": [
            {"title": "OVER clause", "concepts": ["window function"]},
            {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
        ],
    },
}


def _create(client: TestClient) -> str:
    response = client.post("/api/plans", json=PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["plan"]["plan_id"]


# --- evaluate: both sinks reported, ``recorded`` is honest ---


def test_record_reports_both_sinks_saved(client: TestClient) -> None:
    plan_id = _create(client)
    body = client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "start"}).json()
    assert body["recorded"] is True
    assert body["db_write"] == "saved"
    assert body["document_write"] == "saved"
    assert body["evaluation"]["phase"] == "start"
    assert "Plan checkpoint" in body["markdown"]


def test_record_with_failed_database_write_reports_it_instead_of_lying(
    client: TestClient, monkeypatch
) -> None:
    plan_id = _create(client)
    monkeypatch.setattr(index_module, "record_checkpoint", lambda evaluation, *, study_id="": False)

    response = client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "mid"})

    assert response.status_code == 201, "the evaluation itself succeeded and is returned"
    body = response.json()
    assert body["recorded"] is False
    assert body["db_write"] == "failed"
    assert body["document_write"] == "saved"
    assert "checkpoint not saved to the database" in body["evaluation"]["warnings"]
    fetched = client.get(f"/api/plans/{plan_id}").json()
    assert [c["phase"] for c in fetched["checkpoints"]] == ["mid"], "the document sink was written"


def test_record_without_append_reports_document_sink_not_requested(client: TestClient) -> None:
    plan_id = _create(client)
    body = client.post(
        f"/api/plans/{plan_id}/evaluate", json={"phase": "end", "append_to_plan": False}
    ).json()
    assert body["recorded"] is True
    assert body["db_write"] == "saved"
    assert body["document_write"] == "not_requested"
    assert client.get(f"/api/plans/{plan_id}").json()["checkpoints"] == []
    assert client.get(f"/api/plans/{plan_id}/history").json()["checkpoints"]


def test_preview_is_a_seam_assessment_that_writes_nothing(client: TestClient, monkeypatch) -> None:
    plan_id = _create(client)

    def must_not_be_called(evaluation, *, study_id=""):
        raise AssertionError("a preview must not touch the checkpoint log")

    monkeypatch.setattr(index_module, "record_checkpoint", must_not_be_called)
    body = client.get(f"/api/plans/{plan_id}/evaluate", params={"phase": "end"}).json()
    assert body["evaluation"]["phase"] == "end"
    assert client.get(f"/api/plans/{plan_id}").json()["checkpoints"] == []
    assert client.get(f"/api/plans/{plan_id}/history").json()["checkpoints"] == []


def test_record_unknown_phase_is_the_seams_400_after_the_404(client: TestClient) -> None:
    assert client.post("/api/plans/nope/evaluate", json={"phase": "nope"}).status_code == 404
    plan_id = _create(client)
    assert client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "nope"}).status_code == 400


# --- toggle: an idempotent set behind the checkbox ---


def test_toggle_is_a_set_milestone_behind_the_route(client: TestClient, monkeypatch) -> None:
    plan_id = _create(client)
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)

    first = client.post(f"/api/plans/{plan_id}/milestones/1/toggle").json()
    assert first["done"] is True
    assert first["plan"]["milestone_done"] == 1
    (intent,) = seen
    assert type(intent).__name__ == "SetMilestone"
    assert (intent.plan_id, intent.index, intent.done) == (plan_id, 1, True)  # type: ignore[attr-defined]

    second = client.post(f"/api/plans/{plan_id}/milestones/1/toggle").json()
    assert second["done"] is False
    assert seen[1].done is False  # type: ignore[attr-defined]


@pytest.mark.parametrize("index", [42, -1])
def test_toggle_out_of_range_is_the_seams_404_and_writes_nothing(
    client: TestClient, index: int
) -> None:
    plan_id = _create(client)
    before = client.get(f"/api/plans/{plan_id}/markdown").text
    assert client.post(f"/api/plans/{plan_id}/milestones/{index}/toggle").status_code == 404
    assert client.get(f"/api/plans/{plan_id}/markdown").text == before


# --- delete: confirmed by the verb, history retained ---


def test_delete_is_a_confirmed_delete_plan_that_keeps_history(
    client: TestClient, monkeypatch
) -> None:
    plan_id = _create(client)
    assert client.post(f"/api/plans/{plan_id}/evaluate", json={"phase": "start"}).json()["recorded"]
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)

    response = client.delete(f"/api/plans/{plan_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "plan_id": plan_id}
    (intent,) = seen
    assert type(intent).__name__ == "DeletePlan"
    assert intent.confirmed is True  # type: ignore[attr-defined]
    assert client.get(f"/api/plans/{plan_id}").status_code == 404
    assert client.delete(f"/api/plans/{plan_id}").status_code == 404
    assert [row["phase"] for row in index_module.checkpoint_history(plan_id)] == ["start"]
    assert [row["plan_id"] for row in index_module.indexed_plans()] == []


def test_delete_malformed_id_is_the_seams_400(client: TestClient) -> None:
    # A space fails the store's id grammar; the seam raises InvalidPlanId and the
    # route maps it — the same 400 every other route gives a malformed id.
    assert client.delete("/api/plans/not%20an%20id").status_code == 400
```

### `tests/test_cli_plan_seam.py`
```python
"""CLI plan commands that Phase 2 moved onto the seam.

``tests/test_cli_plan.py`` is frozen at its pre-seam assertions (exit codes
and ``--json`` shapes are the agent contract: D-3). This file pins what is
*new* once ``new``, ``interview``, ``evaluate``, ``milestone``, ``record`` and
``reindex`` — and the two other CLI readers of plans, ``exercise
from-milestone`` and ``brain publish`` — delegate to ``PlanApplication``:

* ``plan new --activate`` is one ``CreatePlan(status="active")`` judged by the
  seam's gate — council review 1 (Grok) found the command still drafted,
  gated and wrote itself, a second policy site D-2 forbids;
* ``plan evaluate --record`` tells the truth about both sinks;
* ``plan milestone`` is an idempotent ``SetMilestone``; a negative index is
  refused like one past the end;
* ``plan record`` is ``RevisePlan(learning_record=...)`` and still reports
  ``created`` honestly on a retry.

Spies replace ``PlanApplication`` methods to prove *which* seam call a command
makes; the round trips through the real seam prove the output.
"""

from __future__ import annotations

import json
import re

import pytest
from click.testing import CliRunner

from studyloop.cli import cli
from studyloop.planning import (
    CreatePlan,
    PlanApplication,
    PlanNotReady,
    ReadinessView,
    RevisePlan,
    SetMilestone,
    StudyPlan,
    store,
)
from studyloop.planning import index as index_module

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


READY = [
    "--why",
    "Own the nightly pipeline",
    "--success",
    "Deploy unaided",
    "--topic",
    "data-engineering",
    "--milestone",
    "Job anatomy (concepts: glue job)",
    "--milestone",
    "Transform (concepts: dynamicframe)",
]


def _spy_apply(monkeypatch) -> list[object]:
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)
    return seen


# --- plan new ---


def test_new_is_one_create_plan_intent_with_the_requested_status(runner, monkeypatch) -> None:
    seen = _spy_apply(monkeypatch)

    result = runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY, "--activate"])

    assert result.exit_code == 0, result.output
    (intent,) = seen
    assert isinstance(intent, CreatePlan)
    assert intent.status == "active"
    assert intent.title == "Glue ETL"
    assert intent.plan_id is None, "the seam derives the unique id"
    assert intent.answers["milestones"] == [
        "Job anatomy (concepts: glue job)",
        "Transform (concepts: dynamicframe)",
    ]
    assert store.load_plan("glue-etl").status == "active"
    assert "Ready to activate" in _ANSI.sub("", result.output)


def test_new_without_activate_is_a_draft_create(runner, monkeypatch) -> None:
    seen = _spy_apply(monkeypatch)
    result = runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    assert result.exit_code == 0, result.output
    (intent,) = seen
    assert isinstance(intent, CreatePlan)
    assert intent.status == "draft"
    assert store.load_plan("glue-etl").status == "draft"


def test_new_activate_refusal_is_the_seams_and_writes_nothing(runner, monkeypatch) -> None:
    """The refusal a learner sees is the seam's PlanNotReady — no route-local
    readiness check remains in the command — and no document exists after."""
    seen = _spy_apply(monkeypatch)

    result = runner.invoke(cli, ["plan", "new", "--title", "Empty", "--activate"])

    assert result.exit_code == 1
    clean = _ANSI.sub("", result.output)
    assert "Cannot activate 'empty'" in clean
    assert "Mission" in clean
    assert "Traceback" not in clean
    (intent,) = seen
    assert isinstance(intent, CreatePlan) and intent.status == "active"
    assert store.list_plan_ids() == [], "refused before any write"


def test_new_refusal_text_comes_from_the_seam_exception(runner, monkeypatch) -> None:
    readiness = ReadinessView.from_plan(StudyPlan(plan_id="empty", title="Empty"))

    def refuse(self, intent):
        raise PlanNotReady(readiness)

    monkeypatch.setattr(PlanApplication, "apply", refuse)
    result = runner.invoke(cli, ["plan", "new", "--title", "Empty", "--activate"])
    assert result.exit_code == 1
    clean = _ANSI.sub("", result.output)
    assert "Cannot activate 'empty'" in clean
    for blocker in readiness.blockers:
        assert blocker in clean


def test_new_json_shape_keeps_plan_readiness_and_path(runner, isolated_plans_dir) -> None:
    result = runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"plan", "readiness", "path"}
    assert payload["plan"]["plan_id"] == "glue-etl"
    assert payload["plan"]["status"] == "draft"
    assert payload["readiness"]["ready"] is True
    assert payload["path"] == str(isolated_plans_dir / "glue-etl.md")


# --- plan interview ---


def test_interview_is_prepare_planning(runner, monkeypatch) -> None:
    calls: list[int] = []
    real = PlanApplication.prepare_planning

    def spying(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(PlanApplication, "prepare_planning", spying)

    result = runner.invoke(cli, ["plan", "interview", "--json"])

    assert result.exit_code == 0, result.output
    assert calls == [1]
    payload = json.loads(result.output)
    assert set(payload) == {"questions", "seed"}, "existing_plans is not added here (D-3)"
    assert {"key", "prompt", "why", "required", "multi"} <= set(payload["questions"][0])


# --- plan evaluate ---


def test_evaluate_is_an_assessment_and_reports_a_complete_recording(runner, monkeypatch) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    calls: list[object] = []
    real = PlanApplication.assess

    def spying(self, intent):
        calls.append(intent)
        return real(self, intent)

    monkeypatch.setattr(PlanApplication, "assess", spying)

    result = runner.invoke(
        cli, ["plan", "evaluate", "glue-etl", "--phase", "end", "--record", "--study-id", "s1"]
    )

    assert result.exit_code == 0, result.output
    (intent,) = calls
    assert (intent.plan_id, intent.phase, intent.study_id, intent.record) == (  # type: ignore[attr-defined]
        "glue-etl",
        "end",
        "s1",
        True,
    )
    assert "Checkpoint recorded." in _ANSI.sub("", result.output)
    assert [c.phase for c in store.load_plan("glue-etl").checkpoints] == ["end"]
    assert [row["study_id"] for row in index_module.checkpoint_history("glue-etl")] == ["s1"]


def test_evaluate_record_names_the_sink_that_failed(runner, monkeypatch) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    monkeypatch.setattr(index_module, "record_checkpoint", lambda evaluation, *, study_id="": False)

    result = runner.invoke(cli, ["plan", "evaluate", "glue-etl", "--record"])

    assert result.exit_code == 0, "the evaluation succeeded; a failed sink is reported, not fatal"
    clean = _ANSI.sub("", result.output)
    assert "Plan checkpoint" in clean
    assert "Checkpoint recorded." not in clean
    assert "partially recorded" in clean
    assert "database: failed" in clean
    assert "document: saved" in clean
    assert [c.phase for c in store.load_plan("glue-etl").checkpoints] == ["start"]


def test_evaluate_preview_is_record_false(runner, monkeypatch) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    calls: list[object] = []
    real = PlanApplication.assess

    def spying(self, intent):
        calls.append(intent)
        return real(self, intent)

    monkeypatch.setattr(PlanApplication, "assess", spying)

    result = runner.invoke(cli, ["plan", "evaluate", "glue-etl", "--json"])

    assert result.exit_code == 0, result.output
    assert calls[0].record is False  # type: ignore[attr-defined]
    payload = json.loads(result.output)
    assert payload["phase"] == "start"
    assert store.load_plan("glue-etl").checkpoints == []


# --- plan milestone ---


def test_milestone_is_an_idempotent_set(runner, monkeypatch) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    seen = _spy_apply(monkeypatch)

    first = runner.invoke(cli, ["plan", "milestone", "glue-etl", "0", "--done"])
    again = runner.invoke(cli, ["plan", "milestone", "glue-etl", "0", "--done"])
    toggled = runner.invoke(cli, ["plan", "milestone", "glue-etl", "0"])

    assert first.exit_code == again.exit_code == toggled.exit_code == 0
    assert all(isinstance(intent, SetMilestone) for intent in seen)
    assert [intent.done for intent in seen] == [True, True, False]  # type: ignore[attr-defined]
    assert "1/2" in first.output
    assert "1/2" in again.output, "setting done twice stays done"
    assert "0/2" in toggled.output, "no flag toggles the current state"


def test_milestone_negative_index_is_refused_like_one_past_the_end(runner) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    before = store.load_plan_text("glue-etl")

    # ``--`` ends option parsing so ``-1`` reaches the index argument.
    result = runner.invoke(cli, ["plan", "milestone", "glue-etl", "--done", "--", "-1"])

    assert result.exit_code == 1, result.output
    assert "No milestone at index -1" in result.output
    assert "Traceback" not in result.output
    assert store.load_plan_text("glue-etl") == before


# --- plan record ---


def test_record_is_revise_plan_with_a_learning_record(runner, monkeypatch) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    seen = _spy_apply(monkeypatch)

    first = runner.invoke(
        cli, ["plan", "record", "glue-etl", "--title", "Insight", "--body", "prose", "--json"]
    )
    again = runner.invoke(
        cli, ["plan", "record", "glue-etl", "--title", "Insight", "--body", "prose", "--json"]
    )

    assert first.exit_code == again.exit_code == 0, first.output + again.output
    assert len(seen) == 2 and all(isinstance(intent, RevisePlan) for intent in seen)
    assert seen[0].learning_record is not None  # type: ignore[attr-defined]
    assert seen[0].learning_record.title == "Insight"  # type: ignore[attr-defined]
    assert json.loads(first.output) == {
        "plan_id": "glue-etl",
        "number": 1,
        "title": "Insight",
        "status": "active",
        "created": True,
    }
    assert json.loads(again.output)["created"] is False
    assert json.loads(again.output)["number"] == 1
    assert len(store.load_plan("glue-etl").learning_records) == 1


def test_record_empty_title_is_the_seams_invalid_value(runner) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    result = runner.invoke(cli, ["plan", "record", "glue-etl", "--title", "   "])
    assert result.exit_code == 1
    clean = _ANSI.sub("", result.output)
    assert "Invalid value" in clean
    assert "title" in clean
    assert "Traceback" not in clean


# --- plan reindex ---


def test_reindex_goes_through_the_seam(runner, monkeypatch) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    calls: list[int] = []
    real = PlanApplication.reindex

    def spying(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(PlanApplication, "reindex", spying)
    result = runner.invoke(cli, ["plan", "reindex"])
    assert result.exit_code == 0, result.output
    assert calls == [1]
    assert "Reindexed 1 plan(s)" in result.output


# --- the other CLI readers of plans ---


def test_exercise_from_milestone_reads_the_plan_through_inspect(runner, monkeypatch) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    calls: list[str] = []
    real = PlanApplication.inspect

    def spying(self, plan_id, **options):
        calls.append(plan_id)
        return real(self, plan_id, **options)

    monkeypatch.setattr(PlanApplication, "inspect", spying)

    result = runner.invoke(cli, ["--dev", "exercise", "from-milestone", "glue-etl", "--json"])

    assert result.exit_code == 0, result.output
    assert calls == ["glue-etl"]
    payload = json.loads(result.output)
    assert payload["set"]["plan_id"] == "glue-etl"
    assert "Job anatomy" in payload["set"]["topic"] or payload["set"]["topic"]


def test_brain_selected_plan_ids_browse_through_the_seam(runner, monkeypatch) -> None:
    from studyloop.cli._brain import _selected_plan_ids

    runner.invoke(cli, ["plan", "new", "--title", "Active One", *READY, "--activate"])
    runner.invoke(cli, ["plan", "new", "--title", "Draft One", *READY])
    calls: list[str | None] = []
    real = PlanApplication.browse

    def spying(self, *, status=None):
        calls.append(status)
        return real(self, status=status)

    monkeypatch.setattr(PlanApplication, "browse", spying)

    assert _selected_plan_ids((), publish_all=False, today_only=False) == ["active-one"]
    assert sorted(_selected_plan_ids((), publish_all=True, today_only=False)) == [
        "active-one",
        "draft-one",
    ]
    assert calls == ["active", None]
```

### `tests/test_mcp_plan_record_seam.py`
```python
"""``record_plan_learning`` goes through the seam (T2.2, the one ``tools.py`` edit).

``tests/test_plan_record.py::TestMcpTool`` pins the tool's contract from
before the seam existed — created/number/retry/missing plan. This file pins
what the migration adds: the write is one ``RevisePlan(learning_record=…)``
applied through ``PlanApplication`` (so the resulting-document gate and the
store's single learning-record rule both apply), and every seam refusal is a
``ToolError`` — a not-ready refusal naming its blockers, so an agent can tell
the learner what to fix.
"""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError

from studyloop.planning import (
    Milestone,
    Mission,
    PlanApplication,
    PlanNotReady,
    ReadinessView,
    RevisePlan,
    StudyPlan,
    store,
)


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


def _tool():
    from studyloop.mcp.server import mcp

    return mcp._tool_manager._tools["record_plan_learning"].fn


def _seed(plan_id: str = "decorators") -> StudyPlan:
    plan = StudyPlan(
        plan_id=plan_id,
        title="Python Decorators",
        status="active",
        topics=["python"],
        mission=Mission(why="They keep appearing in code review.", success=["Explain them."]),
        milestones=[Milestone(title="Trace a decorated call", concepts=["wrapper"])],
    )
    store.create_plan(plan)
    return plan


def test_tool_applies_one_revise_plan_with_the_record(monkeypatch) -> None:
    _seed()
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)

    payload = _tool()("decorators", "MCP insight", body="prose", status="active")

    (intent,) = seen
    assert isinstance(intent, RevisePlan)
    assert intent.plan_id == "decorators"
    assert intent.learning_record is not None
    assert (intent.learning_record.title, intent.learning_record.body) == ("MCP insight", "prose")
    assert payload == {
        "plan_id": "decorators",
        "number": 1,
        "title": "MCP insight",
        "status": "active",
        "created": True,
    }
    assert store.load_plan("decorators").learning_records[0].body == "prose"


def test_retry_reports_created_false_through_the_seam(monkeypatch) -> None:
    _seed()
    _tool()("decorators", "Again", body="same")
    seen: list[object] = []
    real_apply = PlanApplication.apply

    def spying_apply(self, intent):
        seen.append(intent)
        return real_apply(self, intent)

    monkeypatch.setattr(PlanApplication, "apply", spying_apply)

    payload = _tool()("decorators", "Again", body="same")

    assert len(seen) == 1, "a retry is still one seam call, not a store call"
    assert payload["created"] is False
    assert payload["number"] == 1
    assert len(store.load_plan("decorators").learning_records) == 1


def test_not_ready_refusal_is_a_tool_error_naming_the_blockers(monkeypatch) -> None:
    readiness = ReadinessView.from_plan(StudyPlan(plan_id="decorators", title="Decorators"))
    _seed()

    def refuse(self, intent):
        raise PlanNotReady(readiness)

    monkeypatch.setattr(PlanApplication, "apply", refuse)

    with pytest.raises(ToolError) as caught:
        _tool()("decorators", "Insight")

    message = str(caught.value)
    assert "not ready" in message
    for blocker in readiness.blockers:
        assert blocker in message


@pytest.mark.parametrize(
    ("title", "body", "fragment"),
    [
        ("   ", "", "title"),
        ("Trap", "fine\n### LR-0999 — fake", "###"),
    ],
    ids=["empty-title", "heading-in-body"],
)
def test_store_rule_refusals_are_tool_errors(title: str, body: str, fragment: str) -> None:
    _seed()
    with pytest.raises(ToolError, match=fragment):
        _tool()("decorators", title, body=body)
    assert store.load_plan("decorators").learning_records == []


def test_missing_plan_and_malformed_id_are_tool_errors() -> None:
    with pytest.raises(ToolError, match="no study plan"):
        _tool()("ghost", "Anything")
    with pytest.raises(ToolError, match="invalid plan id"):
        _tool()("../escape", "Anything")
```

### `tests/test_plan_record.py` — diff vs `a4862301` (fixture only; deviation 12)
```diff
diff --git a/packages/studyloop/tests/test_plan_record.py b/packages/studyloop/tests/test_plan_record.py
index a31e5374..fdfdcb60 100644
--- a/packages/studyloop/tests/test_plan_record.py
+++ b/packages/studyloop/tests/test_plan_record.py
@@ -18,6 +18,7 @@ from click.testing import CliRunner
 from studyloop.cli import cli
 from studyloop.planning import (
     LearningRecord,
+    Milestone,
     Mission,
     StudyPlan,
     create_plan,
@@ -35,12 +36,21 @@ def isolated_plans_dir(tmp_path, monkeypatch):


 def _seed(plan_id: str = "decorators", records: list[LearningRecord] | None = None) -> StudyPlan:
+    # A *ready* active plan. The seam's resulting-document gate (Phase 1,
+    # review-1 F1b) refuses any write that would re-save an active plan with
+    # no success criteria or milestones — so the CLI and MCP paths below,
+    # which now go through RevisePlan, need a document that could legally be
+    # active. The store-level tests are indifferent to the shape.
     plan = StudyPlan(
         plan_id=plan_id,
         title="Python Decorators",
         status="active",
         topics=["python"],
-        mission=Mission(why="They keep appearing in code review."),
+        mission=Mission(
+            why="They keep appearing in code review.",
+            success=["Explain the wrapper relationship unprompted."],
+        ),
+        milestones=[Milestone(title="Trace a decorated call", concepts=["wrapper", "closure"])],
         learning_records=records or [],
     )
     create_plan(plan)
```


## 6. Delta specs (Phase 2 additions only)

### `specs/active-learning-decisions/spec.md` — diff vs `a4862301`
```diff
diff --git a/openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md b/openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md
index b9c0353d..fe7e5e31 100644
--- a/openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md
+++ b/openspec/changes/plan-application-seam/specs/active-learning-decisions/spec.md
@@ -83,3 +83,173 @@ SHALL honour the answer. A successful database write SHALL add no warning.
 #### Scenario: Database write succeeds
 - **WHEN** `record_checkpoint` returns `True`
 - **THEN** no warning mentioning `database` is present
+
+
+### Requirement: Milestone set is idempotent and refuses indices the plan lacks
+`apply(SetMilestone(plan_id, index, done))` SHALL set — not toggle — one
+milestone's `done` state on a loaded candidate, judge the resulting document
+with the same readiness gate every write uses when the plan is active, and
+save once. Applying the same intent twice SHALL leave the same document.
+`index` is a 0-based position: an index past the end **or negative** SHALL
+raise `InvalidMilestone` before any write. A plan that does not exist SHALL
+raise `PlanNotFound` before the index is judged.
+
+#### Scenario: Set is idempotent
+- **WHEN** `SetMilestone(plan_id, 0, done=True)` is applied twice
+- **THEN** each application saves exactly once, the milestone is done after
+  both, `milestone_done` is unchanged by the second, and
+  `SetMilestone(plan_id, 0, done=False)` undoes it
+
+#### Scenario: Negative index
+- **WHEN** `SetMilestone(plan_id, -1, done=True)` is applied
+- **THEN** `InvalidMilestone` is raised and the document is byte-identical
+
+#### Scenario: Ticking a milestone on an unready active document
+- **WHEN** `SetMilestone` is applied to a hand-edited active plan that has no
+  mission
+- **THEN** `PlanNotReady` is raised — the resulting document would be
+  active-but-unready — and nothing is written
+
+### Requirement: Deletion is confirmed and retains the checkpoint log
+`apply(DeletePlan(plan_id, confirmed))` SHALL raise `InvalidField` unless
+`confirmed` is `True` (after `PlanNotFound` for an unknown id), remove the
+canonical document and its derived index row, retain every row of the durable
+checkpoint log for that id, and return a frozen `DeleteResult(plan_id)` whose
+`to_json_dict()` is `{"deleted": true, "plan_id": "<id>"}` — `apply` returns a
+`DeleteResult` for this intent and a `PlanDetail` for every other, because a
+detail cannot describe a plan that no longer exists.
+
+#### Scenario: Unconfirmed delete
+- **WHEN** `DeletePlan(plan_id)` is applied with `confirmed` left `False`
+- **THEN** `InvalidField` is raised and the document is unchanged
+
+#### Scenario: Confirmed delete keeps history
+- **WHEN** a plan with one recorded checkpoint is deleted with `confirmed=True`
+- **THEN** a `DeleteResult` is returned, `inspect(plan_id)` raises
+  `PlanNotFound`, the derived index no longer lists the plan, and
+  `checkpoint_history(plan_id)` still returns the row
+
+### Requirement: Assessment reports each recording sink independently
+`assess(AssessPlan(plan_id, phase, study_id, record, append_to_plan))` SHALL
+return a frozen `AssessmentResult` carrying a `PlanEvaluationView` (whose
+`to_json_dict()` equals `PlanEvaluation.to_dict()` key for key and whose
+`markdown` is the rendered checkpoint block), `db_write` and `document_write`
+each in `not_requested | saved | failed`, and the evaluation's `warnings`.
+`record=False` SHALL call `evaluate_plan` and write to neither sink;
+`record=True` SHALL call the Phase-0 `evaluate_and_record` — the seam adds no
+second checkpoint writer — and read its two recording warnings back into the
+sink fields. A failed sink SHALL be a reported outcome on the result, never an
+exception (no `PartialRecording`), because the evaluation succeeded.
+`recording_complete` is `True` when no requested sink failed — vacuously true
+for a preview. The plan SHALL be found before the phase is judged (`PlanNotFound`
+before `InvalidField`).
+
+#### Scenario: Preview writes neither sink
+- **WHEN** `assess(AssessPlan(id, "mid", record=False))` is called
+- **THEN** both sink fields are `not_requested`, no checkpoint row exists in
+  the log or the document, and `recording_complete` is `True`
+
+#### Scenario: Both sinks saved
+- **WHEN** `assess(AssessPlan(id, "end", study_id="s1"))` is called and both
+  writes succeed
+- **THEN** both sink fields are `saved`, `recording_complete` is `True`, and
+  the row is present in the log (with `study_id == "s1"`) and in the document
+
+#### Scenario: Database failure reported, document still written
+- **WHEN** the log write returns `False` or raises
+- **THEN** `db_write == "failed"`, `document_write == "saved"`,
+  `recording_complete` is `False`, `warnings` contains `checkpoint not saved
+  to the database`, and the evaluation carries a valid verdict
+
+#### Scenario: Document failure reported independently
+- **WHEN** the document save raises
+- **THEN** `document_write == "failed"`, `db_write == "saved"`, the log holds
+  the row, and the document is unchanged
+
+### Requirement: Active-plan guidance is a deterministic read (not yet consumed)
+`get_active_guidance(*, today=None)` SHALL return a frozen `ActiveGuidance`
+holding one `ActivePlanGuidance` per plan whose status is `active`, ordered by
+`plan_id`, with: the `PlanSummary`; `next_milestone` (the first unchecked
+milestone, or `None`); `match_keys`, a `frozenset` of `normalise_match_key`
+over the topics and every milestone's concepts (casefold, punctuation replaced
+by spaces, whitespace collapsed — matching is equality on the key, never a
+substring test); `target_urgency` in `overdue` (days until target `< 0`),
+`soon` (`0..7`), `later` (`> 7`) or `undated`; `energy_floor`; a
+`completion_action` string only when the plan has milestones and every one is
+done; and per-plan `warnings` for defects worked around (no milestones, a
+target date that is not a date). Documents the store could not parse SHALL be
+named in the collection's `warnings`. Non-active plans are skipped. `today`
+pins the urgency computation for frozen-clock callers and defaults to the UTC
+date.
+
+This view exists so that the `now` decision engine (issue #10, Phase 3) has
+one plan-static read to consume. **Nothing consumes it yet**: `studyloop now`
+and the Today card are unchanged by this phase, and `docs/study-plans.md`'s
+"does not do yet" list stays as it is until #10 ships.
+
+#### Scenario: One entry per active plan, ordered, others skipped
+- **WHEN** plans `zeta` (active), `alpha` (active), `mid` (active) and one
+  plan in each of `draft`, `paused`, `complete`, `abandoned` exist
+- **THEN** `get_active_guidance().plans` has three entries in the order
+  `alpha`, `mid`, `zeta`, and repeated calls return equal views
+
+#### Scenario: Match keys and next milestone
+- **WHEN** an active plan has topics `["SQL", "Data-Engineering"]` and
+  milestones with concepts `["Window-Function"]` (done) and `["RANK vs
+  DENSE_RANK", "dense rank"]`, `["window frame"]`
+- **THEN** `match_keys == {"sql", "data engineering", "window function",
+  "rank vs dense rank", "dense rank", "window frame"}` and `next_milestone`
+  is index `1`
+
+#### Scenario: Urgency buckets
+- **WHEN** the target date is 30 or 1 day(s) ago, today, 1, 7, 8 or 90 days
+  ahead, or unset
+- **THEN** `target_urgency` is `overdue`, `overdue`, `soon`, `soon`, `soon`,
+  `later`, `later`, `undated` respectively
+
+#### Scenario: Every milestone done
+- **WHEN** an active plan's milestones are all `done`
+- **THEN** `next_milestone` is `None` and `completion_action` is a non-empty
+  string naming the plan
+
+#### Scenario: Malformed documents become warnings
+- **WHEN** an active plan has no milestones and `target_date: someday`, and an
+  unreadable file sits beside it
+- **THEN** the guidance is returned; the plan's entry has `next_milestone ==
+  None`, `completion_action == None`, `target_urgency == "undated"` and
+  warnings naming the milestones and the date; the collection's `warnings`
+  name the unreadable file
+
+### Requirement: Adapters reach study plans only through the seam
+No module under `studyloop/cli`, `studyloop/web/routes` or `studyloop/mcp`
+SHALL import `studyloop.planning.store`, `.index`, `.authoring` or
+`.evaluation` (directly, relatively, as a whole-package handle, or by name
+through `from studyloop.planning import …` for the names those modules
+contribute). `tests/test_architecture_plan_seam.py` SHALL enforce this by
+parsing every adapter module, SHALL reject a planted bypass in a temp copy of
+an adapter, and SHALL check its explicit name list against what
+`studyloop.planning` actually re-exports from the four modules.
+
+#### Scenario: Planted bypass is rejected
+- **WHEN** `from studyloop.planning.store import save_plan` is appended to a
+  copy of `web/routes/plans.py` and the checker runs on the copy
+- **THEN** the checker reports a violation; on the real tree it reports none
+
+### Requirement: The learning-record rule has one copy
+Learning-record validation (non-empty title; no H1–H3 lines in the body) and
+idempotent numbering SHALL live in one function,
+`studyloop.planning.store.append_learning_record(plan, title, body=, status=)`,
+applied to an in-memory plan. The store's `record_learning` SHALL wrap it
+(load → append → save only when created, so a duplicate leaves the file's
+bytes untouched) and the seam's `RevisePlan(learning_record=…)` SHALL call it
+on the revision candidate, translating its `ValueError` to `InvalidField`.
+`PlanDetail.learning_record_matching(spec)` SHALL answer whether a spec would
+be a duplicate, using the same stripped title-and-body identity, so adapters
+can report `created` without a copy of the rule.
+
+#### Scenario: The seam follows the store's rule
+- **WHEN** `store.append_learning_record` is replaced by a function that
+  raises `ValueError("the store said no")` and `RevisePlan(learning_record=…)`
+  is applied
+- **THEN** `InvalidField` carrying that message is raised and no record is
+  added
```

### `specs/web-ui/spec.md` — diff vs `a4862301`
```diff
diff --git a/openspec/changes/plan-application-seam/specs/web-ui/spec.md b/openspec/changes/plan-application-seam/specs/web-ui/spec.md
index 54e34dec..e41fe115 100644
--- a/openspec/changes/plan-application-seam/specs/web-ui/spec.md
+++ b/openspec/changes/plan-application-seam/specs/web-ui/spec.md
@@ -115,3 +115,76 @@ readiness blocks carry the `authoring.readiness()` key set.
 - **THEN** the response is `400` and `GET /api/plans/{id}` still reports
   `status == "draft"` — the transition is not committed before the field is
   refused
+
+
+### Requirement: The milestone checkbox is an idempotent set
+`POST /api/plans/{id}/milestones/{index}/toggle` SHALL read the milestone's
+current state through the seam and apply one `SetMilestone(plan_id, index,
+done=<opposite>)` intent — never a route-side write and never the full-list
+`RevisePlan` substitute the review-1 corrections used in the interim. The
+seam's `SetMilestone` is a *set*, not a toggle: applying the same intent twice
+leaves the same document, so a retried request cannot flip a box twice. An
+index the plan does not have — past the end **or negative** — SHALL be the
+seam's `InvalidMilestone`, mapped to `404`, with the document byte-identical
+afterwards. The response body SHALL keep its pre-seam keys: `{"updated": true,
+"index": <i>, "done": <bool>, "plan": <summary>}`.
+
+#### Scenario: Toggle flips and flips back
+- **WHEN** the toggle is posted twice for milestone `0` of a two-milestone plan
+- **THEN** the first response has `done == true` and `plan.milestone_done ==
+  1`; the second has `done == false`; each request applied exactly one
+  `SetMilestone` whose `done` was the opposite of the state it read
+
+#### Scenario: Out-of-range and negative indices
+- **WHEN** the toggle is posted for index `42` or `-1`
+- **THEN** the response is `404` and `GET /api/plans/{id}/markdown` is
+  unchanged
+
+### Requirement: Delete is confirmed by the verb and retains checkpoint history
+`DELETE /api/plans/{id}` SHALL apply `DeletePlan(plan_id, confirmed=True)` —
+the HTTP verb is the confirmation this route contract has always had — and
+return `200` with `{"deleted": true, "plan_id": "<id>"}`. The canonical
+document and its derived index row are removed; the durable checkpoint log
+(`study_plan_checkpoints`) is retained. An unknown id SHALL be `404` and a
+malformed id `400`, both before anything is removed.
+
+#### Scenario: Delete removes the document and keeps the log
+- **WHEN** a plan with one recorded checkpoint is deleted
+- **THEN** the response is `200` with `deleted == true`; `GET /api/plans/{id}`
+  is `404`; a second `DELETE` is `404`; the checkpoint log for that id still
+  holds the row; the derived index no longer lists the plan
+
+### Requirement: Checkpoint recording reports each sink
+`POST /api/plans/{id}/evaluate` SHALL call `PlanApplication.assess` with
+`record=True` and return `201` with `recorded`, `db_write`, `document_write`,
+`evaluation` and `markdown`. `db_write` and `document_write` are each
+`"not_requested"`, `"saved"` or `"failed"`; `recorded` SHALL be `true` only
+when no requested sink failed. A failed sink is a reported outcome, not an
+error response: the evaluation succeeded and the client is entitled to it, so
+the status stays `201`. `GET /api/plans/{id}/evaluate` SHALL be
+`assess(record=False)` and write to neither sink. The route SHALL hold no
+phase check of its own: an unknown phase on `POST` is the seam's
+`InvalidField` → `400`, judged after the plan is found (`404` first).
+
+#### Scenario: Both sinks saved
+- **WHEN** `POST /api/plans/{id}/evaluate` is called with `{"phase": "start"}`
+  and both writes succeed
+- **THEN** the body has `recorded == true`, `db_write == "saved"`,
+  `document_write == "saved"`
+
+#### Scenario: Database write fails
+- **WHEN** the checkpoint log write returns `False` or raises during
+  `POST /api/plans/{id}/evaluate`
+- **THEN** the response is still `201`; `recorded == false`, `db_write ==
+  "failed"`, `document_write == "saved"`; `evaluation.warnings` contains
+  `checkpoint not saved to the database`; and the plan document carries the
+  checkpoint row
+
+#### Scenario: Document sink not requested
+- **WHEN** the body has `"append_to_plan": false`
+- **THEN** `document_write == "not_requested"`, `recorded == true`, the
+  document has no new checkpoint and the log has the row
+
+#### Scenario: Preview writes nothing
+- **WHEN** `GET /api/plans/{id}/evaluate?phase=end` is called
+- **THEN** neither the checkpoint log nor the document gains a row
```

### `specs/cli-surface/spec.md` — diff vs `a4862301`
```diff
diff --git a/openspec/changes/plan-application-seam/specs/cli-surface/spec.md b/openspec/changes/plan-application-seam/specs/cli-surface/spec.md
index ba01c8a4..32383496 100644
--- a/openspec/changes/plan-application-seam/specs/cli-surface/spec.md
+++ b/openspec/changes/plan-application-seam/specs/cli-surface/spec.md
@@ -68,3 +68,75 @@ same mapping.
 - **THEN** the exit code is `1` in every case, the output contains the
   mapping's distinguishing text (`already exists`, `Invalid value:`, `Invalid
   plan id`, `No such milestone`, `Cannot activate '<id>'`), and no `Traceback`
+
+
+### Requirement: Every plan command reads and writes through the seam
+`studyloop plan new|interview|evaluate|milestone|record|reindex` SHALL
+delegate to `PlanApplication` like `list|show|status` already do, and
+`cli/_plan.py` SHALL import no storage, index, authoring or evaluation module
+(the architecture guard `tests/test_architecture_plan_seam.py` fails
+otherwise). `plan new` SHALL be one `CreatePlan` whose `status` is `"active"`
+with `--activate` and `"draft"` without; the `--activate` refusal SHALL be the
+seam's `PlanNotReady` reached through `_fail_for` — the command holds no
+readiness decision of its own — and a refused create SHALL write nothing.
+`plan new --json` SHALL keep `{"plan", "readiness", "path"}`. `plan interview`
+SHALL be `prepare_planning` and SHALL keep emitting `{"questions", "seed"}`
+(no `existing_plans` key is added here). `plan reindex` SHALL call
+`PlanApplication.reindex()`. The other CLI readers of plans — `exercise
+from-milestone` and `brain publish`'s plan selection — SHALL read through
+`inspect` / `browse`.
+
+#### Scenario: Create with --activate on a ready plan
+- **WHEN** `studyloop plan new --title "Glue ETL" --why … --success …
+  --milestone … --activate` is run
+- **THEN** exactly one `CreatePlan(status="active")` is applied, the exit
+  code is `0`, and the stored plan's status is `active`
+
+#### Scenario: Create with --activate on an unready plan writes nothing
+- **WHEN** `studyloop plan new --title Empty --activate` is run
+- **THEN** the exit code is `1`, the output contains `Cannot activate 'empty'`
+  and the blockers, and the plans directory holds no document
+
+### Requirement: The CLI milestone command is an idempotent set
+`studyloop plan milestone <id> <index> [--done|--undone]` SHALL apply one
+`SetMilestone`. With a flag the state is set as asked, so running the same
+command twice is safe; without a flag the current state is read through the
+seam and its opposite is set. A negative index SHALL be refused exactly like
+one past the end (`No milestone at index -1 …`, exit `1`, document unchanged).
+
+#### Scenario: Set twice stays set, no flag toggles
+- **WHEN** `plan milestone <id> 0 --done` is run twice and then `plan
+  milestone <id> 0` once
+- **THEN** the outputs report `1/2`, `1/2`, `0/2`, and the three applied
+  intents were `SetMilestone(done=True)`, `SetMilestone(done=True)`,
+  `SetMilestone(done=False)`
+
+### Requirement: Recorded checkpoints report a complete or partial recording
+`studyloop plan evaluate <id> --record` SHALL call `assess(record=True)`,
+print the evaluation Markdown, and then print `Checkpoint recorded.` only when
+every requested sink was saved. When a sink failed the command SHALL exit `0`
+— the evaluation succeeded — and print `Checkpoint partially recorded —
+database: <state>, document: <state>` naming each sink. Without `--record` the
+command is `assess(record=False)` and writes nothing; `--json` keeps emitting
+the evaluation dict unchanged.
+
+#### Scenario: Database sink fails
+- **WHEN** the checkpoint log write returns `False` during `plan evaluate <id>
+  --record`
+- **THEN** the exit code is `0`, the output contains `partially recorded`,
+  `database: failed` and `document: saved`, and the plan document carries
+  the checkpoint
+
+### Requirement: Learning records are one revision through the seam
+`studyloop plan record <id> --title T [--body B]` SHALL apply one
+`RevisePlan(learning_record=LearningRecordSpec(...))`. `created` in the
+`--json` output SHALL be derived by asking `PlanDetail.learning_record_matching`
+before and after the revision — the command carries no copy of the store's
+identity rule — and a retry with the same title and body SHALL report
+`created: false` with the original `number`. An empty title SHALL be the
+seam's `Invalid value: …` refusal, exit `1`.
+
+#### Scenario: Retry reports created false
+- **WHEN** `plan record <id> --title Insight --body prose --json` is run twice
+- **THEN** both exit `0`; the first reports `created: true, number: 1`; the
+  second reports `created: false, number: 1`; the plan holds one record
```

### `specs/mcp-server/spec.md` (new)
```markdown
## ADDED Requirements

### Requirement: record_plan_learning writes through the plan seam
The `record_plan_learning(plan_id, title, body="", status="active")` tool
SHALL apply one `RevisePlan(plan_id, learning_record=LearningRecordSpec(title,
body, status))` through `studyloop.planning.PlanApplication` and SHALL import
no storage module (`studyloop.planning.store` or the store's `record_learning`
/ error family). Its response SHALL keep the pre-seam keys `{"plan_id",
"number", "title", "status", "created"}`; `created` SHALL be derived from
`PlanDetail.learning_record_matching` before and after the revision, so a
retry with the same title and body reports `created: false` with the original
`number`. Every seam refusal SHALL be a `ToolError`: `PlanNotReady` SHALL
render as `plan is not ready to activate: <blocker>; <blocker>…` so the agent
can tell the learner what to repair (design §2, "ToolError containing
blockers"); `PlanNotFound`, `InvalidPlanId` and `InvalidField` (the store's
title/heading rule) SHALL render as their message.

This is the **only** change to `mcp/tools.py` in this phase. The six read/
write plan tools of design §4 (`list_study_plans` … `set_study_plan_status`)
and the three of Phase 4 (`set_study_plan_milestone`, `evaluate_study_plan`,
`delete_study_plan`) are **not yet registered**; the stdio inventory is
unchanged at this phase.

#### Scenario: One revision through the seam
- **WHEN** `record_plan_learning("decorators", "MCP insight", body="prose")`
  is called on a ready active plan
- **THEN** exactly one `RevisePlan` whose `learning_record` carries that title
  and body is applied, the response is `{"plan_id": "decorators", "number": 1,
  "title": "MCP insight", "status": "active", "created": true}`, and the plan
  document holds the record

#### Scenario: Retry is one seam call and reports created false
- **WHEN** the same call is repeated
- **THEN** one `RevisePlan` is applied, the response has `created: false` and
  `number: 1`, and the plan still holds one record

#### Scenario: Not-ready refusal names the blockers
- **WHEN** the seam raises `PlanNotReady` for the revision (the plan is active
  but has no mission, success criteria or milestones)
- **THEN** a `ToolError` is raised whose message contains `not ready` and each
  blocker string from the `ReadinessView`

#### Scenario: Store rule and id refusals are tool errors
- **WHEN** the title is blank, or the body contains a `###` line, or the plan
  id is unknown or malformed
- **THEN** a `ToolError` is raised carrying the seam's message and no record is
  added
```


## 7. Deliverables — numbered H2 sections, in this order

1. **Verdict:** ACCEPT / ACCEPT-WITH-CORRECTIONS / REJECT for Phase 2 as the base of Phase 3, with the single
   sentence that decides it.
2. **Findings**, each with severity 🔴 defect (wrong behaviour or a bug), 🟡 must-fix-before-Phase-3
   (design/contract violation, missing test, unsafe pattern), 🔵 should-fix, 💡 note. For each: file:line or
   function, what is wrong, why it matters, the concrete fix, and the RED test that would pin it. Check
   specifically: (a) does any write path — `SetMilestone`, `DeletePlan`, `RevisePlan(learning_record)`, the
   Web toggle/DELETE/evaluate, the CLI six, the MCP tool — persist anything before its refusal, or bypass the
   gate? (b) is `SetMilestone` genuinely idempotent and is the negative-index rule right? (c) `DeleteResult`
   — is the load-then-unlink race handled truthfully; is retaining the checkpoint log and dropping the index
   row the right pair? (d) `assess()` — do the sink fields ever disagree with the warnings they are derived
   from; is deriving sink status from the two warning strings robust enough or should `evaluate_and_record`
   return structured outcomes; is `recording_complete` vacuously true for a preview acceptable? (e)
   `get_active_guidance` — ordering, the match-key normaliser (`NFKC` + casefold + punctuation→space +
   collapse; is `_` treated right; does it match what decision.py will do), urgency boundaries, the
   completion action, warnings for malformed documents, the unparseable-file detection via `list_plan_ids()
   - parsed`, cost (two directory scans); (f) immutability — `PlanEvaluationView`'s lenient row freeze,
   `ActivePlanGuidance.match_keys` as `frozenset`, any list/dict leaking; (g) the architecture guard — what it
   misses (attribute access on an imported package handle, `importlib` with non-literal strings, tests
   importing store directly are out of scope by design — is that acceptable?), whether the explicit
   forbidden-name list + self-check is the right shape, whether allowing `plans_dir` is a hole; (h) the
   learning-record fold — was making the store authoritative (deviation 4) the right direction given
   tasks.md said "fold into the seam's one copy"; (i) adapters — the two-read `created` derivation in CLI/MCP
   (`inspect` then `apply`), the Web toggle reading state then setting the opposite (race?), the honest
   `recorded` and additive body keys; (j) test quality — public seam only, isolated fixtures, spies on
   `PlanApplication` methods, the RED evidence; (k) each of the 13 deviations: accept or reverse, with
   reason; **deviation 12 in particular** — rule on the legacy active-but-unready document question.
3. **Spec review:** do the four delta specs match the code exactly? Anything claimed that is not shipped
   (the brief says the guidance view is not yet consumed — is that stated clearly enough)? Anything shipped
   that the specs do not say?
4. **Phase 3 hazards** you can see from this base for #10 (`now` consumes `get_active_guidance`), #11 (six MCP
   tools over the seam), #13a (planning purpose): what in these views/intents/guard will trip them.
5. **Process finding:** the agent ran unattended overnight and made judgment calls (deviations 4, 8, 12).
   Name the one call you would most want a human to have made instead, and why.

Be concrete over complete: a file:line and a test name beat a paragraph.
