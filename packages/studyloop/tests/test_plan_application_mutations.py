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
    CreatePlan,
    DeletePlan,
    LearningRecordSpec,
    RevisePlan,
    SetMilestone,
    TransitionLifecycle,
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

    # Setting the same state again is a no-op: the milestone is still done,
    # nothing else moved, and a retry is always safe (and, per review 2 F1,
    # writes nothing — pinned separately below).
    again = app.apply(SetMilestone(plan_id="demo", index=0, done=True))
    assert again.milestones[0].done is True
    assert again.summary.milestone_done == 1
    assert [m.done for m in again.milestones] == [m.done for m in first.milestones]
    assert store.load_plan("demo").milestones[0].done is True
    assert len(saves) == 1, "the retry did not write"

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


def test_repeated_set_milestone_writes_nothing_and_keeps_bytes_and_updated(
    app: PlanApplication, monkeypatch
) -> None:
    """Council review 2, GPT F1: idempotent means the *document* is the same,
    not merely the milestone flag. A retried set must not re-save — a save
    bumps ``updated``, which reorders ``browse`` and rewrites the file for
    nothing. The clock is advanced past the timestamp's resolution so a save
    could not hide behind same-second equality."""
    _plan("demo")
    saves = _count_saves(monkeypatch)
    app.apply(SetMilestone(plan_id="demo", index=0, done=True))
    assert len(saves) == 1
    before = store.load_plan_text("demo")
    monkeypatch.setattr(store, "utc_now_iso", lambda: "2099-01-01T00:00:00+00:00")

    again = app.apply(SetMilestone(plan_id="demo", index=0, done=True))

    assert len(saves) == 1, "an identical retry writes nothing"
    assert store.load_plan_text("demo") == before
    assert again.milestones[0].done is True
    assert again.summary.updated != "2099-01-01T00:00:00+00:00"


def test_noop_set_on_unready_active_plan_is_still_refused(
    app: PlanApplication, isolated_plans_dir, monkeypatch
) -> None:
    """Policy before the no-op short-circuit: an active husk is refused even
    when the requested state is the one it already has."""
    store.plans_dir()
    (isolated_plans_dir / "husk.md").write_text(
        "---\nid: husk\ntitle: Husk\nstatus: active\n---\n\n"
        "# Husk\n\n## Milestones\n\n- [x] **Step** `(concepts: x)`\n",
        encoding="utf-8",
    )
    saves = _count_saves(monkeypatch)
    with pytest.raises(PlanNotReady):
        app.apply(SetMilestone(plan_id="husk", index=0, done=True))
    assert saves == []


def test_duplicate_learning_record_only_revision_writes_nothing(
    app: PlanApplication, monkeypatch
) -> None:
    """Council review 2, GPT F1: the store's ``record_learning`` left the file's
    bytes untouched on a duplicate; the CLI/MCP paths moved onto ``RevisePlan``
    and must keep that guarantee, or "already recorded (no change)" is a lie
    and a retried wind-down reorders the plan list through ``updated``."""
    _plan("demo")
    spec = LearningRecordSpec(title="Once", body="only")
    saves = _count_saves(monkeypatch)
    app.apply(RevisePlan(plan_id="demo", learning_record=spec))
    assert len(saves) == 1
    before = store.load_plan_text("demo")
    monkeypatch.setattr(store, "utc_now_iso", lambda: "2099-01-01T00:00:00+00:00")

    again = app.apply(RevisePlan(plan_id="demo", learning_record=spec))

    assert len(saves) == 1, "a duplicate record alone is not a write"
    assert store.load_plan_text("demo") == before
    assert len(again.learning_records) == 1


def test_duplicate_record_beside_a_field_change_saves_once(
    app: PlanApplication, monkeypatch
) -> None:
    _plan("demo")
    spec = LearningRecordSpec(title="Once", body="only")
    app.apply(RevisePlan(plan_id="demo", learning_record=spec))
    saves = _count_saves(monkeypatch)

    detail = app.apply(RevisePlan(plan_id="demo", learning_record=spec, title="Renamed"))

    assert len(saves) == 1
    assert detail.summary.title == "Renamed"
    assert len(detail.learning_records) == 1


def test_empty_revision_is_still_a_touch(app: PlanApplication, monkeypatch) -> None:
    """The Phase-1 contract stands: an empty PATCH body has always been a save
    that bumps ``updated``. Only a duplicate-record-only revision is exempt."""
    _plan("demo")
    saves = _count_saves(monkeypatch)
    app.apply(RevisePlan(plan_id="demo"))
    assert len(saves) == 1


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


def _husk(isolated_plans_dir, plan_id: str = "husk") -> None:
    """An active document with milestones and topics but no mission: readable,
    active, unready — the shape a hand edit or a pre-gate import can leave."""
    store.plans_dir()
    (isolated_plans_dir / f"{plan_id}.md").write_text(
        f"---\nid: {plan_id}\ntitle: Husk\nstatus: active\ntopics: [sql]\n---\n\n"
        "# Husk\n\n## Milestones\n\n- [ ] **Step** `(concepts: x)`\n",
        encoding="utf-8",
    )


def test_recording_to_unready_active_document_refuses_before_either_sink(
    app: PlanApplication, isolated_plans_dir, monkeypatch
) -> None:
    """Council review 2, GPT F2: ``evaluate_and_record`` re-saves the active
    document with a checkpoint row. On an active husk that is the same
    active-but-unready re-save ``SetMilestone`` and ``RevisePlan`` refuse, so
    ``assess(record=True, append_to_plan=True)`` must refuse it too — before
    the database sink, not after."""
    _husk(isolated_plans_dir)
    before = store.load_plan_text("husk")

    def must_not_be_called(evaluation, *, study_id=""):
        raise AssertionError("refused before the database sink")

    monkeypatch.setattr(index_module, "record_checkpoint", must_not_be_called)

    with pytest.raises(PlanNotReady) as caught:
        app.assess(AssessPlan(plan_id="husk", phase="start"))

    assert caught.value.readiness.ready is False
    assert caught.value.already_active is True
    assert store.load_plan_text("husk") == before
    assert _database_checkpoints("husk") == []


def test_preview_of_unready_active_plan_is_allowed(
    app: PlanApplication, isolated_plans_dir
) -> None:
    _husk(isolated_plans_dir)
    result = app.assess(AssessPlan(plan_id="husk", phase="mid", record=False))
    assert result.evaluation.plan_id == "husk"
    assert result.db_write == result.document_write == "not_requested"


def test_database_only_assessment_of_unready_active_plan_is_allowed(
    app: PlanApplication, isolated_plans_dir
) -> None:
    """No resulting plan document is persisted, so the gate has nothing to judge."""
    _husk(isolated_plans_dir)
    before = store.load_plan_text("husk")
    result = app.assess(AssessPlan(plan_id="husk", phase="end", append_to_plan=False))
    assert result.db_write == "saved"
    assert result.document_write == "not_requested"
    assert _database_checkpoints("husk") == ["end"]
    assert store.load_plan_text("husk") == before


def test_revise_learning_record_on_unready_active_is_refused(
    app: PlanApplication, isolated_plans_dir, monkeypatch
) -> None:
    """Council review 2 (Grok 🔵): the product decision in deviation 12 pinned
    for the learning-record path, on a real document rather than a mocked
    exception — byte-identical document, ``PlanNotReady``, zero saves."""
    _husk(isolated_plans_dir)
    before = store.load_plan_text("husk")
    saves = _count_saves(monkeypatch)

    with pytest.raises(PlanNotReady) as caught:
        app.apply(RevisePlan(plan_id="husk", learning_record=LearningRecordSpec(title="Insight")))

    assert caught.value.already_active is True
    assert saves == []
    assert store.load_plan_text("husk") == before


def test_not_ready_on_activation_is_not_flagged_already_active(app: PlanApplication) -> None:
    app.apply(CreatePlan(title="Vague", answers={}))
    with pytest.raises(PlanNotReady) as via_transition:
        app.apply(TransitionLifecycle(plan_id="vague", status="active"))
    assert via_transition.value.already_active is False
    with pytest.raises(PlanNotReady) as via_create:
        app.apply(CreatePlan(title="Vague two", answers={}, status="active"))
    assert via_create.value.already_active is False


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
