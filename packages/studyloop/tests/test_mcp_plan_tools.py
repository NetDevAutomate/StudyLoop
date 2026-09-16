"""The six study-plan MCP tools of design §4 (#11, T3.6/T3.7).

``list_study_plans``, ``get_study_plan``, ``get_planning_interview``,
``create_study_plan``, ``update_study_plan`` and ``set_study_plan_status`` are
thin adapters over :class:`studyloop.planning.PlanApplication`: each call is
one seam call with one intent, each success is the seam view's
``to_json_dict()`` (fresh containers, never a cached dict), and each refusal is
a ``ToolError`` whose message starts with a machine-readable prefix
(``not_found:``, ``invalid_id:``, ``conflict:``, ``invalid:``, ``not_ready:``,
``invalid_milestone:``) followed by the seam's own message — a not-ready
refusal names its blockers so the agent can tell the learner what to repair.

Two contracts the council fixed are pinned here rather than in prose: the
``create_study_plan`` schema exposes no ``overwrite`` (D-4 — an agent must not
be able to replace a learner's plan by picking the same id), and
``get_study_plan`` refuses a ``history_limit`` outside the range the Web
history route accepts *before* any read (review-1 hazard table, "Boundary
validation").

Delegation tests replace the seam's methods and forbid the store, so they
prove the adapter reaches nothing but ``PlanApplication``. The journey tests
at the end run the real seam on an isolated plans directory and database.

Phase 4 (#12, T4.1) appends the three progression tools of design §4 rows 7-9
— ``set_study_plan_milestone`` (an explicit boolean, set not toggle, so a
retry is safe), ``evaluate_study_plan`` (``record=False`` by default: a
preview writes to *neither* sink; ``record=True`` reports each sink as the
seam does, never flattened to a boolean) and ``delete_study_plan`` (refused
by the seam unless ``confirmed=True``; the checkpoint log survives) — and
pins that ``record_plan_learning``'s refusals go through the same
``_plan_tool_error`` mapping as the other eight (review-3 arbitration,
Phase-4 hazards). ``forbid_store`` also forbids the authoring and evaluation
entry points, so an evaluate adapter that reached the checkpoint writer
directly would fail here rather than quietly writing.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError

from studyloop.planning import (
    AssessmentResult,
    AssessPlan,
    CreatePlan,
    DeletePlan,
    DeleteResult,
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    Milestone,
    Mission,
    PlanApplication,
    PlanConflict,
    PlanDetail,
    PlanError,
    PlanEvaluationView,
    PlanningBrief,
    PlanNotFound,
    PlanNotReady,
    PlanSummary,
    ReadinessView,
    RevisePlan,
    SetMilestone,
    StudyPlan,
    TransitionLifecycle,
    store,
)
from studyloop.planning import authoring as plan_authoring
from studyloop.planning import evaluation as plan_evaluation
from studyloop.planning import index as plan_index

SIX_TOOLS = (
    "list_study_plans",
    "get_study_plan",
    "get_planning_interview",
    "create_study_plan",
    "update_study_plan",
    "set_study_plan_status",
)

#: Design §4 rows 7-9, registered by #12 (T4.1).
PHASE_FOUR_TOOLS = (
    "set_study_plan_milestone",
    "evaluate_study_plan",
    "delete_study_plan",
)

NINE_TOOLS: tuple[str, ...] = SIX_TOOLS + PHASE_FOUR_TOOLS

#: 23 original tools at ``0a20a796`` — ``record_plan_learning`` among them —
#: plus the nine design-§4 plan tools = 32 (council review 3, F13: the design's
#: "35" was arithmetic on a stale inventory; review 4, F6: the earlier comment
#: here said "plus nine less one", which is 31).
PRODUCTION_TOOL_COUNT = 32

#: The core names the stdio smoke test also pins; asserted here too so the
#: in-process twin is a real twin (review 4, F4).
CORE_TOOLS = {"list_courses", "get_study_backlog", "end_session"}

DB_WARNING = "checkpoint not saved to the database"
DOCUMENT_WARNING = "checkpoint not appended to the plan document"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    """``store.create_plan`` refreshes the derived index in the sessions
    database; keep that off any developer database (council review 2, F10)."""
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))


@pytest.fixture
def forbid_store(monkeypatch):
    """Make every store/index read or write an assertion failure.

    The delegation tests fake the seam's methods; with the store forbidden
    underneath, a tool that reached round the seam — or called a seam method
    the test did not fake — fails here instead of quietly touching files.
    """

    def _reached(name: str):
        def _fail(*args: Any, **kwargs: Any):
            msg = f"the adapter reached {name} instead of the seam"
            raise AssertionError(msg)

        return _fail

    for name in (
        "list_plans",
        "list_plan_ids",
        "load_plan",
        "load_plan_text",
        "create_plan",
        "save_plan",
        "delete_plan",
    ):
        monkeypatch.setattr(store, name, _reached(f"store.{name}"))
    monkeypatch.setattr(plan_index, "checkpoint_history", _reached("index.checkpoint_history"))
    # T4.1: the authoring and evaluation entry points too, so an evaluate or
    # create adapter that reached the drafting or checkpoint code directly —
    # instead of through ``assess`` / ``apply`` — fails the same way.
    monkeypatch.setattr(plan_index, "record_checkpoint", _reached("index.record_checkpoint"))
    for name in ("evaluate_plan", "evaluate_and_record"):
        monkeypatch.setattr(plan_evaluation, name, _reached(f"evaluation.{name}"))
    for name in ("draft_plan", "interview_spec", "seed_from_history"):
        monkeypatch.setattr(plan_authoring, name, _reached(f"authoring.{name}"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _registry():
    from studyloop.mcp.server import mcp

    return mcp._tool_manager._tools


def _tool(name: str):
    tools = _registry()
    if name not in tools:
        msg = f"Tool {name!r} not registered. Available: {sorted(tools)}"
        raise KeyError(msg)
    return tools[name].fn


def _schema(name: str) -> dict[str, Any]:
    return _registry()[name].parameters


def _ready_plan(plan_id: str = "decorators", status: str = "draft") -> StudyPlan:
    return StudyPlan(
        plan_id=plan_id,
        title="Python Decorators",
        status=status,
        topics=["python"],
        mission=Mission(why="They keep appearing in code review.", success=["Explain them."]),
        milestones=[Milestone(title="Trace a decorated call", concepts=["wrapper"])],
    )


def _unready_plan(plan_id: str = "husk", status: str = "draft") -> StudyPlan:
    """No mission, no success criteria, no milestones — every blocker fires."""
    return StudyPlan(plan_id=plan_id, title="Husk", status=status)


def _brief() -> PlanningBrief:
    return PlanningBrief.build(
        interview=[
            {
                "key": "why",
                "prompt": "What changes once this is learned?",
                "why": "Mission first.",
                "required": True,
                "multi": False,
            }
        ],
        seed={"topics": ["python"], "struggles": [{"topic": "closures", "count": 2}]},
        existing_plans=[PlanSummary.from_plan(_ready_plan())],
    )


class _Spy:
    """Record every call to one faked seam method and hand back a canned view."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append((args, kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _fake(monkeypatch, method: str, result: object) -> _Spy:
    """Replace one ``PlanApplication`` method with a spy (bound like a method)."""
    spy = _Spy(result)

    def bound(_self: PlanApplication, *args: Any, **kwargs: Any) -> object:
        return spy(*args, **kwargs)

    monkeypatch.setattr(PlanApplication, method, bound)
    return spy


def _evaluation_view(
    plan_id: str = "decorators", phase: str = "mid", warnings: tuple[str, ...] = ()
) -> PlanEvaluationView:
    """A canned evaluation for the delegation tests (no history read behind it)."""
    return PlanEvaluationView(
        plan_id=plan_id,
        plan_title="Python Decorators",
        phase=phase,
        verdict="on-track",
        headline="On track.",
        at="2026-09-16T10:00:00+00:00",
        study_id="",
        progress_pct=0,
        milestone_total=1,
        milestone_done=0,
        next_milestone="Trace a decorated call",
        next_concepts=("wrapper",),
        days_since_activity=None,
        days_until_target=None,
        due_reviews=(),
        struggles=(),
        concept_evidence=(),
        unverified_milestones=(),
        drift_topics=(),
        recommendations=(),
        warnings=warnings,
        markdown="## Checkpoint\n\nOn track.\n",
    )


def _assessment(
    db_write: str = "not_requested",
    document_write: str = "not_requested",
    warnings: tuple[str, ...] = (),
) -> AssessmentResult:
    return AssessmentResult(
        evaluation=_evaluation_view(warnings=warnings),
        db_write=db_write,  # type: ignore[arg-type]
        document_write=document_write,  # type: ignore[arg-type]
        warnings=warnings,
    )


def _legacy_active_husk(plan_id: str = "husk") -> StudyPlan:
    """An active document with a milestone but no mission — written straight
    through the store, as a hand-edited or pre-gate plan would be. The seam
    refuses every write to it until it is paused or repaired (deviation 12)."""
    plan = StudyPlan(
        plan_id=plan_id, title="Husk", status="active", milestones=[Milestone(title="Only one")]
    )
    store.create_plan(plan)
    return plan


def _ready_plan_on_disk(plan_id: str = "decorators") -> str:
    """Create a ready draft through the tools themselves and return its id."""
    _tool("create_study_plan")(
        "Python Decorators",
        {"why": "They keep appearing in code review.", "success": ["Explain them."]},
        plan_id=plan_id,
    )
    _tool("update_study_plan")(
        plan_id,
        topics=["python"],
        milestones=[
            {"title": "Trace a decorated call", "concepts": ["wrapper"]},
            {"title": "Write one", "concepts": ["closure"]},
        ],
    )
    return plan_id


def _database_checkpoints(plan_id: str) -> list[str]:
    return [str(row["phase"]) for row in plan_index.checkpoint_history(plan_id)]


# ---------------------------------------------------------------------------
# Registration and schemas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SIX_TOOLS)
def test_plan_tool_is_registered_with_a_schema(name: str) -> None:
    schema = _schema(name)
    assert schema["type"] == "object"
    assert "properties" in schema


def test_schemas_carry_the_design_signatures() -> None:
    """Design §4: the argument names, the required ones, and the defaults."""
    assert _schema("list_study_plans")["properties"].keys() == {"status"}
    assert "status" not in _schema("list_study_plans").get("required", [])

    get_props = _schema("get_study_plan")["properties"]
    assert get_props.keys() == {"plan_id", "include_markdown", "include_history", "history_limit"}
    assert _schema("get_study_plan")["required"] == ["plan_id"]
    assert get_props["include_markdown"]["default"] is False
    assert get_props["include_history"]["default"] is False
    assert get_props["history_limit"]["default"] == 20

    assert _schema("get_planning_interview")["properties"] == {}

    create = _schema("create_study_plan")
    assert set(create["properties"]) == {"title", "answers", "plan_id", "status"}
    assert set(create["required"]) == {"title", "answers"}
    assert create["properties"]["status"]["default"] == "draft"

    update = _schema("update_study_plan")
    assert set(update["properties"]) == {
        "plan_id",
        "title",
        "topics",
        "target_date",
        "energy_floor",
        "review_cadence_days",
        "notes",
        "milestones",
        "status",
    }
    assert update["required"] == ["plan_id"]

    status = _schema("set_study_plan_status")
    assert set(status["properties"]) == {"plan_id", "status"}
    assert set(status["required"]) == {"plan_id", "status"}


def test_create_study_plan_schema_exposes_no_overwrite() -> None:
    """D-4: ``overwrite`` stays on the intent for Web/CLI and never reaches an agent."""
    schema = _schema("create_study_plan")
    assert "overwrite" not in schema["properties"]
    assert "overwrite" not in (_registry()["create_study_plan"].description or "")


def test_no_learning_record_on_update_study_plan() -> None:
    """``record_plan_learning`` is the one record writer (D-9); the revision tool
    does not grow a second door to the same rule."""
    assert "learning_record" not in _schema("update_study_plan")["properties"]


# ---------------------------------------------------------------------------
# Delegation: one seam call, the view's JSON, nothing else
# ---------------------------------------------------------------------------


def test_list_study_plans_delegates_to_browse(monkeypatch, forbid_store) -> None:
    summaries = (PlanSummary.from_plan(_ready_plan()), PlanSummary.from_plan(_ready_plan("b")))
    browse = _fake(monkeypatch, "browse", summaries)

    payload = _tool("list_study_plans")()

    assert browse.calls == [((), {"status": None})]
    assert payload["plans"] == [summary.to_json_dict() for summary in summaries]
    assert payload["count"] == 2


def test_list_study_plans_passes_the_status_filter_through(monkeypatch, forbid_store) -> None:
    browse = _fake(monkeypatch, "browse", ())

    payload = _tool("list_study_plans")(status="active")

    assert browse.calls == [((), {"status": "active"})]
    assert payload == {"plans": [], "count": 0}


def test_get_study_plan_delegates_to_inspect_with_its_options(monkeypatch, forbid_store) -> None:
    detail = PlanDetail.from_plan(_ready_plan(), markdown="# doc", history=())
    inspect = _fake(monkeypatch, "inspect", detail)

    payload = _tool("get_study_plan")(
        "decorators", include_markdown=True, include_history=True, history_limit=5
    )

    assert inspect.calls == [
        (("decorators",), {"include_markdown": True, "include_history": True, "history_limit": 5})
    ]
    assert payload == detail.to_json_dict()
    assert payload["markdown"] == "# doc"
    assert payload["history"] == []


def test_get_study_plan_defaults_match_the_seam(monkeypatch, forbid_store) -> None:
    detail = PlanDetail.from_plan(_ready_plan())
    inspect = _fake(monkeypatch, "inspect", detail)

    payload = _tool("get_study_plan")("decorators")

    defaults = {"include_markdown": False, "include_history": False, "history_limit": 20}
    assert inspect.calls == [(("decorators",), defaults)]
    assert "markdown" not in payload
    assert "history" not in payload
    assert payload["plan"]["plan_id"] == "decorators"


@pytest.mark.parametrize("limit", [0, -1, 201, 10_000], ids=["zero", "negative", "201", "huge"])
def test_get_study_plan_bounds_history_limit_before_any_read(
    monkeypatch, forbid_store, limit: int
) -> None:
    """Review-1 hazard, "Boundary validation": the Web history route accepts
    1..200; the tool refuses the rest itself, with no seam call and so no
    database query behind it."""
    inspect = _fake(monkeypatch, "inspect", PlanDetail.from_plan(_ready_plan()))

    with pytest.raises(ToolError, match=r"^invalid: history_limit") as caught:
        _tool("get_study_plan")("decorators", include_history=True, history_limit=limit)

    assert str(limit) in str(caught.value)
    assert inspect.calls == []


@pytest.mark.parametrize("limit", [1, 200])
def test_get_study_plan_accepts_the_history_limit_bounds(
    monkeypatch, forbid_store, limit: int
) -> None:
    inspect = _fake(monkeypatch, "inspect", PlanDetail.from_plan(_ready_plan(), history=()))

    _tool("get_study_plan")("decorators", include_history=True, history_limit=limit)

    assert inspect.calls[0][1]["history_limit"] == limit


def test_get_planning_interview_delegates_to_prepare_planning(monkeypatch, forbid_store) -> None:
    brief = _brief()
    prepare = _fake(monkeypatch, "prepare_planning", brief)

    payload = _tool("get_planning_interview")()

    assert prepare.calls == [((), {})]
    assert payload == brief.to_json_dict()
    assert set(payload) == {"questions", "seed", "existing_plans"}
    assert payload["questions"][0]["key"] == "why"
    assert payload["existing_plans"][0]["plan_id"] == "decorators"


def test_create_study_plan_applies_one_create_plan_without_overwrite(
    monkeypatch, forbid_store
) -> None:
    detail = PlanDetail.from_plan(_ready_plan())
    apply = _fake(monkeypatch, "apply", detail)
    answers = {"why": "Code review.", "success": ["Explain them."], "topics": ["python"]}

    payload = _tool("create_study_plan")(
        "Python Decorators", answers, plan_id="decorators", status="draft"
    )

    ((intent,), _kwargs) = apply.calls[0]
    assert len(apply.calls) == 1
    assert isinstance(intent, CreatePlan)
    assert intent.title == "Python Decorators"
    assert intent.answers == answers
    assert intent.plan_id == "decorators"
    assert intent.status == "draft"
    assert intent.overwrite is False, "D-4: the MCP door can never overwrite"
    assert payload == detail.to_json_dict()


def test_create_study_plan_defaults_leave_id_and_status_to_the_seam(
    monkeypatch, forbid_store
) -> None:
    apply = _fake(monkeypatch, "apply", PlanDetail.from_plan(_ready_plan()))

    _tool("create_study_plan")("Python Decorators", {"why": "Code review."})

    ((intent,), _kwargs) = apply.calls[0]
    assert isinstance(intent, CreatePlan)
    assert intent.plan_id is None, "the seam allocates the unique slug"
    assert intent.status == "draft"
    assert intent.overwrite is False


def test_update_study_plan_applies_one_revise_plan_with_explicit_fields(
    monkeypatch, forbid_store
) -> None:
    detail = PlanDetail.from_plan(_ready_plan())
    apply = _fake(monkeypatch, "apply", detail)
    milestones = [{"title": "Write one", "concepts": ["closure"], "done": False}]

    payload = _tool("update_study_plan")(
        "decorators",
        title="Decorators, properly",
        topics=["python", "closures"],
        target_date="2026-10-01",
        energy_floor=4,
        review_cadence_days=5,
        notes="Weekly.",
        milestones=milestones,
        status="active",
    )

    ((intent,), _kwargs) = apply.calls[0]
    assert len(apply.calls) == 1
    assert isinstance(intent, RevisePlan)
    assert intent.plan_id == "decorators"
    assert intent.title == "Decorators, properly"
    assert intent.topics == ["python", "closures"]
    assert intent.target_date == "2026-10-01"
    assert intent.energy_floor == 4
    assert intent.review_cadence_days == 5
    assert intent.notes == "Weekly."
    assert intent.milestones == milestones
    assert intent.status == "active"
    assert intent.learning_record is None
    assert payload == detail.to_json_dict()


def test_update_study_plan_omitted_fields_are_none_not_blank(monkeypatch, forbid_store) -> None:
    """``None`` is "leave as is" for the seam; a field the agent did not send
    must arrive as ``None``, never as ``""`` or ``[]`` that would wipe it."""
    apply = _fake(monkeypatch, "apply", PlanDetail.from_plan(_ready_plan()))

    _tool("update_study_plan")("decorators", notes="Only this.")

    ((intent,), _kwargs) = apply.calls[0]
    assert isinstance(intent, RevisePlan)
    assert intent.notes == "Only this."
    for field in (
        "title",
        "topics",
        "target_date",
        "energy_floor",
        "review_cadence_days",
        "milestones",
        "status",
        "learning_record",
    ):
        assert getattr(intent, field) is None, field


def test_set_study_plan_status_applies_one_transition(monkeypatch, forbid_store) -> None:
    detail = PlanDetail.from_plan(_ready_plan(status="active"))
    apply = _fake(monkeypatch, "apply", detail)

    payload = _tool("set_study_plan_status")("decorators", "active")

    assert apply.calls == [((TransitionLifecycle(plan_id="decorators", status="active"),), {})]
    assert payload == detail.to_json_dict()
    assert payload["plan"]["status"] == "active"


def test_set_study_plan_status_retry_is_idempotent(monkeypatch, forbid_store) -> None:
    """A retried transition is the same intent again, returns the same view,
    and raises nothing — the adapter holds no state a replay could trip on."""
    detail = PlanDetail.from_plan(_ready_plan(status="paused"))
    apply = _fake(monkeypatch, "apply", detail)

    first = _tool("set_study_plan_status")("decorators", "paused")
    second = _tool("set_study_plan_status")("decorators", "paused")

    assert first == second == detail.to_json_dict()
    assert first is not second, "fresh containers on every call"
    assert apply.calls == [
        ((TransitionLifecycle(plan_id="decorators", status="paused"),), {}),
        ((TransitionLifecycle(plan_id="decorators", status="paused"),), {}),
    ]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("list_study_plans", ()),
        ("get_study_plan", ("decorators",)),
        ("get_planning_interview", ()),
        ("create_study_plan", ("Python Decorators", {"why": "Code review."})),
        ("update_study_plan", ("decorators",)),
        ("set_study_plan_status", ("decorators", "paused")),
    ],
)
def test_responses_are_fresh_containers(monkeypatch, forbid_store, name: str, args) -> None:
    """Mutating one response must not change the next: the adapter returns the
    view's ``to_json_dict()`` each time, never a shared or cached dict."""
    detail = PlanDetail.from_plan(_ready_plan())
    _fake(monkeypatch, "browse", (PlanSummary.from_plan(_ready_plan()),))
    _fake(monkeypatch, "inspect", detail)
    _fake(monkeypatch, "prepare_planning", _brief())
    _fake(monkeypatch, "apply", detail)

    first = _tool(name)(*args)
    pristine = _tool(name)(*args)
    first.clear()
    first["tampered"] = True

    second = _tool(name)(*args)
    assert second == pristine
    assert second is not first


# ---------------------------------------------------------------------------
# Error mapping: every seam refusal is one prefixed ToolError
# ---------------------------------------------------------------------------


def _not_ready(already_active: bool = False) -> PlanNotReady:
    return PlanNotReady(ReadinessView.from_plan(_unready_plan()), already_active=already_active)


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("create_study_plan", ("Husk", {}, "husk", "active")),
        ("update_study_plan", ("husk",)),
        ("set_study_plan_status", ("husk", "active")),
    ],
)
def test_not_ready_refusal_is_a_tool_error_naming_the_blockers(
    monkeypatch, forbid_store, name: str, args
) -> None:
    error = _not_ready()
    assert error.readiness.blockers, "the fixture must have something to name"
    _fake(monkeypatch, "apply", error)

    with pytest.raises(ToolError) as caught:
        _tool(name)(*args)

    message = str(caught.value)
    assert message.startswith("not_ready: plan is not ready to activate")
    for blocker in error.readiness.blockers:
        assert blocker in message


def test_not_ready_on_an_already_active_plan_says_pause_or_repair(
    monkeypatch, forbid_store
) -> None:
    _fake(monkeypatch, "apply", _not_ready(already_active=True))

    with pytest.raises(ToolError, match=r"^not_ready: .*already active.*pause") as caught:
        _tool("update_study_plan")("husk", notes="x")

    assert "activate" in str(caught.value)


def test_duplicate_create_is_a_conflict_tool_error(monkeypatch, forbid_store) -> None:
    _fake(monkeypatch, "apply", PlanConflict("study plan 'decorators' already exists"))

    with pytest.raises(ToolError, match=r"^conflict: study plan 'decorators' already exists$"):
        _tool("create_study_plan")("Python Decorators", {}, plan_id="decorators")


@pytest.mark.parametrize(
    ("error", "prefix"),
    [
        (PlanNotFound("no study plan with id 'ghost'"), "not_found"),
        (InvalidPlanId("invalid plan id '../x'"), "invalid_id"),
        (PlanConflict("study plan 'x' already exists"), "conflict"),
        (InvalidField("status must be one of (...)"), "invalid"),
        (InvalidMilestone("No milestone at index 9 (plan has 1)"), "invalid_milestone"),
        (PlanError("something the mapping has not met"), "plan_error"),
    ],
    ids=["not_found", "invalid_id", "conflict", "invalid", "invalid_milestone", "fallback"],
)
@pytest.mark.parametrize("method", ["inspect", "apply"])
def test_every_seam_refusal_maps_to_one_prefixed_tool_error(
    monkeypatch, forbid_store, error: PlanError, prefix: str, method: str
) -> None:
    _fake(monkeypatch, method, error)
    call = (
        (lambda: _tool("get_study_plan")("ghost"))
        if method == "inspect"
        else (lambda: _tool("set_study_plan_status")("ghost", "paused"))
    )

    with pytest.raises(ToolError) as caught:
        call()

    assert str(caught.value) == f"{prefix}: {error}"
    assert caught.value.__cause__ is error


def test_browse_and_prepare_refusals_are_mapped_too(monkeypatch, forbid_store) -> None:
    _fake(monkeypatch, "browse", InvalidField("status must be one of (...)"))
    with pytest.raises(ToolError, match=r"^invalid: status must be one of"):
        _tool("list_study_plans")(status="bogus")

    _fake(monkeypatch, "prepare_planning", PlanError("seed unavailable"))
    with pytest.raises(ToolError, match=r"^plan_error: seed unavailable$"):
        _tool("get_planning_interview")()


# ---------------------------------------------------------------------------
# The real seam, on an isolated directory: the spec's journey and its refusals
# ---------------------------------------------------------------------------


def test_discover_inspect_create_revise_activate_journey() -> None:
    """mcp-server delta, "Study-plan discovery and authoring tools", scenario 1."""
    interview = _tool("get_planning_interview")()
    assert {q["key"] for q in interview["questions"]} >= {"why", "success", "milestones"}
    assert interview["existing_plans"] == []
    assert _tool("list_study_plans")() == {"plans": [], "count": 0}

    created = _tool("create_study_plan")(
        "Python Decorators",
        {
            "why": "They keep appearing in code review.",
            "success": ["Explain the wrapper relationship."],
            "topics": ["python"],
        },
    )
    plan_id = created["plan"]["plan_id"]
    assert plan_id == "python-decorators"
    assert created["plan"]["status"] == "draft"
    assert created["readiness"]["ready"] is False, "no milestones yet"

    listed = _tool("list_study_plans")()
    assert [plan["plan_id"] for plan in listed["plans"]] == [plan_id]
    assert listed["count"] == 1

    revised = _tool("update_study_plan")(
        plan_id,
        topics=["python", "closures"],
        milestones=[{"title": "Trace a decorated call", "concepts": ["wrapper", "closure"]}],
    )
    assert revised["plan"]["topics"] == ["python", "closures"]
    assert revised["milestones"][0]["concepts"] == ["wrapper", "closure"]
    assert revised["readiness"]["ready"] is True

    activated = _tool("set_study_plan_status")(plan_id, "active")
    assert activated["plan"]["status"] == "active"

    shown = _tool("get_study_plan")(plan_id, include_markdown=True)
    assert shown["plan"]["status"] == "active"
    assert shown["markdown"].startswith("---")
    assert store.load_plan(plan_id).status == "active", "the document is the source of truth"
    assert _tool("list_study_plans")(status="active")["count"] == 1
    assert _tool("list_study_plans")(status="draft")["count"] == 0


def test_refused_activation_of_a_real_document_carries_blockers_and_writes_nothing() -> None:
    """Scenario 2: the refusal names the blockers; the document is byte-identical after."""
    created = _tool("create_study_plan")("Husk", {}, plan_id="husk")
    assert created["readiness"]["ready"] is False
    before = store.load_plan_text("husk")

    with pytest.raises(ToolError) as caught:
        _tool("set_study_plan_status")("husk", "active")

    message = str(caught.value)
    assert message.startswith("not_ready: plan is not ready to activate: ")
    for blocker in created["readiness"]["blockers"]:
        assert blocker in message
    assert store.load_plan_text("husk") == before
    assert store.load_plan("husk").status == "draft"


def test_create_with_active_status_is_gated_the_same_way() -> None:
    with pytest.raises(ToolError, match=r"^not_ready: "):
        _tool("create_study_plan")("Husk", {}, plan_id="husk", status="active")
    assert not store.plan_path("husk").exists(), "a refusal writes nothing"


def test_duplicate_create_through_the_real_seam_preserves_the_existing_plan() -> None:
    """Scenario 3: no overwrite — a second create on the same id is a conflict
    and the learner's document is untouched."""
    _tool("create_study_plan")("Python Decorators", {"why": "Original."}, plan_id="decorators")
    before = store.load_plan_text("decorators")

    with pytest.raises(ToolError, match=r"^conflict: "):
        _tool("create_study_plan")("Replacement", {"why": "Clobber."}, plan_id="decorators")

    assert store.load_plan_text("decorators") == before
    assert store.load_plan("decorators").mission.why == "Original."


def test_set_study_plan_status_retry_on_the_real_seam_is_not_refused() -> None:
    _tool("create_study_plan")("Python Decorators", {"why": "Code review."}, plan_id="decorators")

    first = _tool("set_study_plan_status")("decorators", "paused")
    second = _tool("set_study_plan_status")("decorators", "paused")

    assert first["plan"]["status"] == second["plan"]["status"] == "paused"
    assert store.load_plan("decorators").status == "paused"


def test_missing_plan_and_malformed_id_are_prefixed_tool_errors() -> None:
    with pytest.raises(ToolError, match=r"^not_found: "):
        _tool("get_study_plan")("ghost")
    with pytest.raises(ToolError, match=r"^invalid_id: "):
        _tool("get_study_plan")("../escape")
    with pytest.raises(ToolError, match=r"^not_found: "):
        _tool("set_study_plan_status")("ghost", "paused")


def test_unknown_status_is_the_seams_refusal_not_the_adapters() -> None:
    """The adapter carries no status list of its own (no policy in the adapter):
    the seam's ``InvalidField`` message, prefixed, is what the agent reads."""
    _tool("create_study_plan")("Python Decorators", {"why": "Code review."}, plan_id="decorators")

    with pytest.raises(ToolError, match=r"^invalid: status must be one of"):
        _tool("set_study_plan_status")("decorators", "archived")
    with pytest.raises(ToolError, match=r"^invalid: status must be one of"):
        _tool("list_study_plans")(status="archived")
    with pytest.raises(ToolError, match=r"^invalid: status must be one of"):
        _tool("create_study_plan")("Other", {}, plan_id="other", status="archived")
    assert not store.plan_path("other").exists()


def test_get_study_plan_history_reads_the_isolated_log() -> None:
    _tool("create_study_plan")("Python Decorators", {"why": "Code review."}, plan_id="decorators")

    payload = _tool("get_study_plan")("decorators", include_history=True, history_limit=3)

    assert payload["history"] == []
    assert "markdown" not in payload


# ===========================================================================
# Phase 4 (#12, T4.1): the three progression tools of design §4 rows 7-9
# ===========================================================================

# ---------------------------------------------------------------------------
# Registration, schemas and the production inventory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PHASE_FOUR_TOOLS)
def test_phase_four_tool_is_registered_with_a_schema(name: str) -> None:
    schema = _schema(name)
    assert schema["type"] == "object"
    assert "properties" in schema


def test_phase_four_schemas_carry_the_design_signatures() -> None:
    """Design §4 rows 7-9: names, required arguments and defaults.

    ``done`` is an explicit boolean with no default (set, not toggle);
    ``record`` defaults to ``False`` (a preview); ``confirmed`` defaults to
    ``False`` and stays an ordinary boolean — the seam refuses an unconfirmed
    delete, the schema does not require the parameter or constrain it to a
    literal ``true`` (review-3 arbitration, Phase-4 hazards).
    """
    milestone = _schema("set_study_plan_milestone")
    assert set(milestone["properties"]) == {"plan_id", "index", "done"}
    assert set(milestone["required"]) == {"plan_id", "index", "done"}
    assert milestone["properties"]["done"]["type"] == "boolean"
    assert "default" not in milestone["properties"]["done"]
    assert milestone["properties"]["index"]["type"] == "integer"

    evaluate = _schema("evaluate_study_plan")
    assert set(evaluate["properties"]) == {"plan_id", "phase", "study_id", "record"}
    assert set(evaluate["required"]) == {"plan_id", "phase"}
    assert evaluate["properties"]["study_id"]["default"] == ""
    assert evaluate["properties"]["record"]["default"] is False
    assert evaluate["properties"]["record"]["type"] == "boolean"
    assert "append_to_plan" not in evaluate["properties"], "design §4 exposes four arguments"

    delete = _schema("delete_study_plan")
    assert set(delete["properties"]) == {"plan_id", "confirmed"}
    assert delete["required"] == ["plan_id"]
    confirmed = delete["properties"]["confirmed"]
    assert confirmed["default"] is False
    assert confirmed["type"] == "boolean"
    assert "const" not in confirmed and "enum" not in confirmed


def test_production_inventory_is_thirty_two_with_the_nine_plan_tools() -> None:
    """The in-process twin of the stdio pin (T4.1): exactly 32 names, each
    tool registered under its own name (a duplicate registration would
    overwrite its key silently, so the dict's size alone cannot show one),
    all nine design-§4 plan tools, ``record_plan_learning`` and the core
    names (review 4, F4)."""
    registry = _registry()
    names = set(registry)
    assert len(registry) == PRODUCTION_TOOL_COUNT, sorted(names)
    assert sorted(tool.name for tool in registry.values()) == sorted(names), (
        "a tool is registered under a key that is not its own name"
    )
    assert names >= set(NINE_TOOLS), set(NINE_TOOLS) - names
    assert "record_plan_learning" in names
    assert names >= CORE_TOOLS, CORE_TOOLS - names


# ---------------------------------------------------------------------------
# Delegation: milestone → apply(SetMilestone); evaluate → assess; delete → apply(DeletePlan)
# ---------------------------------------------------------------------------


def test_set_study_plan_milestone_applies_one_set_milestone(monkeypatch, forbid_store) -> None:
    detail = PlanDetail.from_plan(_ready_plan())
    apply = _fake(monkeypatch, "apply", detail)

    payload = _tool("set_study_plan_milestone")("decorators", 0, True)

    assert apply.calls == [((SetMilestone(plan_id="decorators", index=0, done=True),), {})]
    assert payload == detail.to_json_dict()


def test_set_study_plan_milestone_forwards_done_false_as_a_set_not_a_toggle(
    monkeypatch, forbid_store
) -> None:
    """``done`` is the state asked for, forwarded as given: the adapter reads
    nothing first and computes no opposite (the CLI's toggle is the CLI's)."""
    inspect = _fake(monkeypatch, "inspect", PlanDetail.from_plan(_ready_plan()))
    apply = _fake(monkeypatch, "apply", PlanDetail.from_plan(_ready_plan()))

    _tool("set_study_plan_milestone")("decorators", 0, False)

    assert apply.calls == [((SetMilestone(plan_id="decorators", index=0, done=False),), {})]
    assert inspect.calls == []


def test_set_study_plan_milestone_retry_is_idempotent(monkeypatch, forbid_store) -> None:
    """A retried set is the same intent again, the same view back, no error
    — the second identical call is indistinguishable from the first."""
    detail = PlanDetail.from_plan(_ready_plan())
    apply = _fake(monkeypatch, "apply", detail)

    first = _tool("set_study_plan_milestone")("decorators", 0, True)
    second = _tool("set_study_plan_milestone")("decorators", 0, True)

    assert first == second == detail.to_json_dict()
    assert first is not second, "fresh containers on every call"
    assert apply.calls == [
        ((SetMilestone(plan_id="decorators", index=0, done=True),), {}),
        ((SetMilestone(plan_id="decorators", index=0, done=True),), {}),
    ]


def test_evaluate_study_plan_calls_assess_never_apply(monkeypatch, forbid_store) -> None:
    """``AssessPlan`` is not a ``PlanIntent``: the adapter goes to ``assess``
    and the response is the ``AssessmentResult`` view — sinks as the seam
    reports them, not flattened to booleans (review-3 arbitration)."""
    result = _assessment()
    assess = _fake(monkeypatch, "assess", result)
    apply = _fake(monkeypatch, "apply", PlanDetail.from_plan(_ready_plan()))

    payload = _tool("evaluate_study_plan")("decorators", "mid")

    assert assess.calls == [
        ((AssessPlan(plan_id="decorators", phase="mid", study_id="", record=False),), {})
    ]
    assert apply.calls == []
    assert payload == result.to_json_dict()
    assert set(payload) == {
        "evaluation",
        "markdown",
        "db_write",
        "document_write",
        "recording_complete",
        "warnings",
    }
    assert payload["db_write"] == payload["document_write"] == "not_requested"
    assert payload["recording_complete"] is True
    assert payload["evaluation"]["phase"] == "mid"
    assert payload["markdown"].startswith("## Checkpoint")


def test_evaluate_study_plan_default_is_a_preview(monkeypatch, forbid_store) -> None:
    assess = _fake(monkeypatch, "assess", _assessment())

    _tool("evaluate_study_plan")("decorators", "start")

    ((intent,), _kwargs) = assess.calls[0]
    assert isinstance(intent, AssessPlan)
    assert intent.record is False, "design §4: evaluate defaults to record=False"
    assert intent.study_id == ""
    assert intent.append_to_plan is True, "the seam's default; the tool does not expose it"


def test_evaluate_study_plan_record_true_and_study_id_are_forwarded(
    monkeypatch, forbid_store
) -> None:
    result = _assessment(db_write="saved", document_write="saved")
    assess = _fake(monkeypatch, "assess", result)

    payload = _tool("evaluate_study_plan")("decorators", "end", study_id="sess-9", record=True)

    assert assess.calls == [
        ((AssessPlan(plan_id="decorators", phase="end", study_id="sess-9", record=True),), {})
    ]
    assert payload["db_write"] == "saved"
    assert payload["document_write"] == "saved"
    assert payload["recording_complete"] is True


def test_evaluate_study_plan_partial_failure_is_reported_not_raised(
    monkeypatch, forbid_store
) -> None:
    """A failed sink is an outcome on the result, never an exception, and the
    warnings carry the seam's own strings — so the agent reads
    ``recording_complete: false`` and the reason, not a success."""
    result = _assessment(db_write="failed", document_write="saved", warnings=(DB_WARNING,))
    _fake(monkeypatch, "assess", result)

    payload = _tool("evaluate_study_plan")("decorators", "start", record=True)

    assert payload["db_write"] == "failed"
    assert payload["document_write"] == "saved"
    assert payload["recording_complete"] is False
    assert DB_WARNING in payload["warnings"]


def test_delete_study_plan_applies_one_delete_plan_with_confirmed_forwarded(
    monkeypatch, forbid_store
) -> None:
    result = DeleteResult(plan_id="decorators")
    apply = _fake(monkeypatch, "apply", result)

    payload = _tool("delete_study_plan")("decorators", confirmed=True)

    assert apply.calls == [((DeletePlan(plan_id="decorators", confirmed=True),), {})]
    assert payload == result.to_json_dict() == {"deleted": True, "plan_id": "decorators"}


def test_delete_study_plan_default_is_unconfirmed_and_left_to_the_seam(
    monkeypatch, forbid_store
) -> None:
    """The adapter carries no confirmation policy of its own: ``confirmed``
    defaults to ``False`` and reaches the seam as ``False``; the seam's
    ``InvalidField`` is what the agent reads, prefixed ``invalid:``."""
    refusal = InvalidField("deleting 'decorators' requires confirmed=True")
    apply = _fake(monkeypatch, "apply", refusal)

    with pytest.raises(
        ToolError, match=r"^invalid: deleting 'decorators' requires confirmed=True$"
    ):
        _tool("delete_study_plan")("decorators")

    assert apply.calls == [((DeletePlan(plan_id="decorators", confirmed=False),), {})]


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("set_study_plan_milestone", ("decorators", 0, True)),
        ("evaluate_study_plan", ("decorators", "mid")),
        ("delete_study_plan", ("decorators", True)),
    ],
)
def test_phase_four_responses_are_fresh_containers(
    monkeypatch, forbid_store, name: str, args
) -> None:
    _fake(monkeypatch, "assess", _assessment())
    _fake(
        monkeypatch,
        "apply",
        PlanDetail.from_plan(_ready_plan()) if name != "delete_study_plan" else DeleteResult("x"),
    )

    first = _tool(name)(*args)
    pristine = _tool(name)(*args)
    first.clear()
    first["tampered"] = True

    second = _tool(name)(*args)
    assert second == pristine
    assert second is not first


# ---------------------------------------------------------------------------
# Error mapping for the three: the same ``_plan_tool_error``, unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "prefix"),
    [
        (PlanNotFound("no study plan with id 'ghost'"), "not_found"),
        (InvalidPlanId("invalid plan id '../x'"), "invalid_id"),
        (PlanConflict("study plan 'x' already exists"), "conflict"),
        (InvalidField("phase must be one of ('start', 'mid', 'end')"), "invalid"),
        (InvalidMilestone("No milestone at index 9 (plan has 1)"), "invalid_milestone"),
        (PlanError("something the mapping has not met"), "plan_error"),
    ],
    ids=["not_found", "invalid_id", "conflict", "invalid", "invalid_milestone", "fallback"],
)
@pytest.mark.parametrize(
    ("name", "method", "args"),
    [
        ("set_study_plan_milestone", "apply", ("ghost", 0, True)),
        ("evaluate_study_plan", "assess", ("ghost", "start")),
        ("delete_study_plan", "apply", ("ghost", True)),
    ],
)
def test_every_phase_four_refusal_maps_to_one_prefixed_tool_error(
    monkeypatch, forbid_store, error: PlanError, prefix: str, name: str, method: str, args
) -> None:
    _fake(monkeypatch, method, error)

    with pytest.raises(ToolError) as caught:
        _tool(name)(*args)

    assert str(caught.value) == f"{prefix}: {error}"
    assert caught.value.__cause__ is error


@pytest.mark.parametrize(
    ("name", "method", "args"),
    [
        ("set_study_plan_milestone", "apply", ("husk", 0, True)),
        ("evaluate_study_plan", "assess", ("husk", "start", "", True)),
    ],
)
def test_phase_four_not_ready_on_an_active_plan_says_pause_or_repair(
    monkeypatch, forbid_store, name: str, method: str, args
) -> None:
    """The twin of F1's engine test: a milestone set — or a recorded checkpoint
    — on an active-but-unready document is refused naming the blockers and
    telling the agent to pause or repair, not to "activate"."""
    error = _not_ready(already_active=True)
    _fake(monkeypatch, method, error)

    with pytest.raises(ToolError, match=r"^not_ready: plan is not ready to activate: ") as caught:
        _tool(name)(*args)

    message = str(caught.value)
    for blocker in error.readiness.blockers:
        assert blocker in message
    assert "already active" in message
    assert "pause it or repair" in message
    assert caught.value.__cause__ is error


# ---------------------------------------------------------------------------
# ``record_plan_learning`` goes through the shared mapping (the T4.1 fold)
# ---------------------------------------------------------------------------


def test_record_plan_learning_not_ready_refusal_is_prefixed_with_blockers_and_cause(
    monkeypatch, forbid_store
) -> None:
    """Pinned before the fold: the same ``not_ready:`` prefix, the blockers,
    and the domain error chained — what the other eight tools already do."""
    error = _not_ready()
    _fake(monkeypatch, "apply", error)

    with pytest.raises(ToolError) as caught:
        _tool("record_plan_learning")("husk", "Insight")

    message = str(caught.value)
    assert message.startswith("not_ready: plan is not ready to activate: ")
    for blocker in error.readiness.blockers:
        assert blocker in message
    assert "already active" not in message
    assert caught.value.__cause__ is error


def test_record_plan_learning_on_an_active_husk_says_pause_or_repair(
    monkeypatch, forbid_store
) -> None:
    error = _not_ready(already_active=True)
    _fake(monkeypatch, "apply", error)

    with pytest.raises(ToolError, match=r"^not_ready: .*already active.*pause it or repair"):
        _tool("record_plan_learning")("husk", "Insight")


@pytest.mark.parametrize(
    ("error", "prefix"),
    [
        (PlanNotFound("no study plan with id 'ghost'"), "not_found"),
        (InvalidPlanId("invalid plan id '../x'"), "invalid_id"),
        (InvalidField("learning record title is required"), "invalid"),
        (PlanConflict("study plan 'x' already exists"), "conflict"),
        (InvalidMilestone("No milestone at index 9 (plan has 1)"), "invalid_milestone"),
        (PlanError("something the mapping has not met"), "plan_error"),
    ],
    ids=["not_found", "invalid_id", "invalid", "conflict", "invalid_milestone", "fallback"],
)
def test_record_plan_learning_refusals_go_through_the_shared_mapping(
    monkeypatch, forbid_store, error: PlanError, prefix: str
) -> None:
    _fake(monkeypatch, "apply", error)

    with pytest.raises(ToolError) as caught:
        _tool("record_plan_learning")("ghost", "Insight")

    assert str(caught.value) == f"{prefix}: {error}"
    assert caught.value.__cause__ is error


def test_record_plan_learning_success_shape_is_unchanged_by_the_fold() -> None:
    """The response keys and ``created`` semantics ``test_plan_record.py`` and
    ``test_mcp_plan_record_seam.py`` pin still hold on the real seam."""
    plan_id = _ready_plan_on_disk()
    _tool("set_study_plan_status")(plan_id, "active")

    first = _tool("record_plan_learning")(plan_id, "MCP insight", body="prose")
    second = _tool("record_plan_learning")(plan_id, "MCP insight", body="prose")

    assert first == {
        "plan_id": plan_id,
        "number": 1,
        "title": "MCP insight",
        "status": "active",
        "created": True,
    }
    assert second == {**first, "created": False}
    assert len(store.load_plan(plan_id).learning_records) == 1


def test_record_plan_learning_on_a_real_active_husk_is_refused_and_writes_nothing() -> None:
    _legacy_active_husk()
    before = store.load_plan_text("husk")

    with pytest.raises(ToolError, match=r"^not_ready: .*already active.*pause it or repair"):
        _tool("record_plan_learning")("husk", "Insight")

    assert store.load_plan_text("husk") == before
    assert store.load_plan("husk").learning_records == []


# ---------------------------------------------------------------------------
# The real seam: milestone set, evaluate preview/record, confirmed delete
# ---------------------------------------------------------------------------


def test_set_milestone_journey_second_identical_call_is_a_no_op() -> None:
    """mcp-server delta, "Study-plan progression and deletion tools", scenario 1:
    set, not toggle — the retry returns the same view and rewrites nothing."""
    plan_id = _ready_plan_on_disk()

    first = _tool("set_study_plan_milestone")(plan_id, 0, True)
    assert first["milestones"][0]["done"] is True
    assert first["milestones"][1]["done"] is False
    assert first["plan"]["milestone_done"] == 1
    assert first["plan"]["milestone_total"] == 2
    assert store.load_plan(plan_id).milestones[0].done is True
    after_first = store.load_plan_text(plan_id)

    second = _tool("set_study_plan_milestone")(plan_id, 0, True)

    assert second == first, "the same intent twice returns the same plan"
    assert store.load_plan_text(plan_id) == after_first, "a retry writes nothing"

    reverted = _tool("set_study_plan_milestone")(plan_id, 0, False)
    assert reverted["milestones"][0]["done"] is False
    assert reverted["plan"]["milestone_done"] == 0
    assert store.load_plan(plan_id).milestones[0].done is False


@pytest.mark.parametrize("index", [2, 9, -1], ids=["past-the-end", "far", "negative"])
def test_set_milestone_outside_the_plan_is_invalid_milestone_and_writes_nothing(
    index: int,
) -> None:
    plan_id = _ready_plan_on_disk()
    before = store.load_plan_text(plan_id)

    with pytest.raises(ToolError, match=r"^invalid_milestone: No milestone at index ") as caught:
        _tool("set_study_plan_milestone")(plan_id, index, True)

    assert str(index) in str(caught.value)
    assert store.load_plan_text(plan_id) == before


def test_set_milestone_on_a_real_active_husk_is_refused_and_writes_nothing() -> None:
    """Scenario 2: the seam's gate, not the adapter's — an active document
    that is unready is refused with the blockers and "pause it or repair",
    and its bytes are untouched."""
    _legacy_active_husk()
    before = store.load_plan_text("husk")

    with pytest.raises(ToolError) as caught:
        _tool("set_study_plan_milestone")("husk", 0, True)

    message = str(caught.value)
    assert message.startswith("not_ready: plan is not ready to activate: ")
    assert "already active" in message
    assert "pause it or repair" in message
    assert store.load_plan_text("husk") == before
    assert store.load_plan("husk").milestones[0].done is False


def test_evaluate_preview_writes_neither_sink() -> None:
    """Scenario 3: ``record=False`` (the default) computes the evaluation and
    touches nothing — the document is byte-identical and the checkpoint log
    is empty; the response says so with ``not_requested`` on both sinks."""
    plan_id = _ready_plan_on_disk()
    _tool("set_study_plan_status")(plan_id, "active")
    before = store.load_plan_text(plan_id)

    payload = _tool("evaluate_study_plan")(plan_id, "mid")

    assert payload["db_write"] == "not_requested"
    assert payload["document_write"] == "not_requested"
    assert payload["recording_complete"] is True
    assert payload["evaluation"]["plan_id"] == plan_id
    assert payload["evaluation"]["phase"] == "mid"
    assert payload["evaluation"]["verdict"] in {"on-track", "at-risk", "stalled", "complete"}
    assert payload["markdown"], "the block an agent pastes into the conversation"
    assert DB_WARNING not in payload["warnings"]
    assert DOCUMENT_WARNING not in payload["warnings"]
    assert store.load_plan_text(plan_id) == before
    assert _database_checkpoints(plan_id) == []
    assert _tool("get_study_plan")(plan_id, include_history=True)["history"] == []
    assert _tool("get_study_plan")(plan_id)["checkpoints"] == []


def test_evaluate_record_true_reports_both_sinks_and_the_log_grows() -> None:
    """Scenario 4: ``record=True`` writes the durable log and the document's
    Checkpoints table, and reports each as ``saved``."""
    plan_id = _ready_plan_on_disk()
    _tool("set_study_plan_status")(plan_id, "active")

    payload = _tool("evaluate_study_plan")(plan_id, "end", study_id="sess-9", record=True)

    assert payload["db_write"] == "saved"
    assert payload["document_write"] == "saved"
    assert payload["recording_complete"] is True
    assert payload["evaluation"]["study_id"] == "sess-9"
    assert _database_checkpoints(plan_id) == ["end"]
    history = _tool("get_study_plan")(plan_id, include_history=True)["history"]
    assert [row["phase"] for row in history] == ["end"]
    assert history[0]["study_id"] == "sess-9"
    assert [c["phase"] for c in _tool("get_study_plan")(plan_id)["checkpoints"]] == ["end"]


def test_evaluate_partial_failure_surfaces_as_warnings_on_the_real_seam(monkeypatch) -> None:
    """Scenario 5: the database sink fails, the document sink lands; the tool
    returns (no error) with ``db_write: failed``, ``recording_complete: false``
    and the seam's warning — never a bare success."""
    plan_id = _ready_plan_on_disk()
    monkeypatch.setattr(plan_index, "record_checkpoint", lambda evaluation, *, study_id="": False)

    payload = _tool("evaluate_study_plan")(plan_id, "start", record=True)

    assert payload["db_write"] == "failed"
    assert payload["document_write"] == "saved"
    assert payload["recording_complete"] is False
    assert DB_WARNING in payload["warnings"]
    assert DB_WARNING in payload["evaluation"]["warnings"]
    assert _database_checkpoints(plan_id) == []
    assert [c["phase"] for c in _tool("get_study_plan")(plan_id)["checkpoints"]] == ["start"]


def test_evaluate_record_on_a_real_active_husk_is_refused_before_either_sink() -> None:
    """Review-2 F2: appending the checkpoint re-saves the document, so an
    active-but-unready plan is refused before the log or the file is touched.
    The preview of the same plan is not gated — it persists nothing."""
    _legacy_active_husk()
    before = store.load_plan_text("husk")

    with pytest.raises(ToolError, match=r"^not_ready: .*already active.*pause it or repair"):
        _tool("evaluate_study_plan")("husk", "start", record=True)

    assert store.load_plan_text("husk") == before
    assert _database_checkpoints("husk") == []

    preview = _tool("evaluate_study_plan")("husk", "start")
    assert preview["db_write"] == preview["document_write"] == "not_requested"
    assert store.load_plan_text("husk") == before


def test_evaluate_unknown_phase_is_the_seams_invalid_refusal() -> None:
    plan_id = _ready_plan_on_disk()

    with pytest.raises(ToolError, match=r"^invalid: phase must be one of"):
        _tool("evaluate_study_plan")(plan_id, "halfway", record=True)

    assert _database_checkpoints(plan_id) == []
    # 404 before 400: the plan is judged before the phase.
    with pytest.raises(ToolError, match=r"^not_found: "):
        _tool("evaluate_study_plan")("ghost", "halfway")


def test_delete_without_confirmation_is_refused_and_the_plan_still_exists() -> None:
    """Scenario 6: ``confirmed`` defaults to ``False``; the seam refuses with
    ``invalid:`` naming the flag, and the document is untouched."""
    plan_id = _ready_plan_on_disk()
    before = store.load_plan_text(plan_id)

    with pytest.raises(ToolError, match=r"^invalid: .*requires confirmed=True") as caught:
        _tool("delete_study_plan")(plan_id)
    with pytest.raises(ToolError, match=r"^invalid: .*requires confirmed=True"):
        _tool("delete_study_plan")(plan_id, confirmed=False)

    assert plan_id in str(caught.value)
    assert store.plan_path(plan_id).exists()
    assert store.load_plan_text(plan_id) == before
    assert _tool("list_study_plans")()["count"] == 1


def test_delete_confirmed_returns_delete_result_and_keeps_the_checkpoint_history() -> None:
    """Scenario 7: a confirmed delete removes the document and its index row;
    the durable checkpoint log is evidence about the learner and survives."""
    plan_id = _ready_plan_on_disk()
    _tool("set_study_plan_status")(plan_id, "active")
    _tool("evaluate_study_plan")(plan_id, "start", study_id="sess-1", record=True)
    assert _database_checkpoints(plan_id) == ["start"]

    payload = _tool("delete_study_plan")(plan_id, confirmed=True)

    assert payload == {"deleted": True, "plan_id": plan_id}
    assert not store.plan_path(plan_id).exists()
    assert _tool("list_study_plans")() == {"plans": [], "count": 0}
    with pytest.raises(ToolError, match=r"^not_found: "):
        _tool("get_study_plan")(plan_id)
    history = plan_index.checkpoint_history(plan_id)
    assert [row["phase"] for row in history] == ["start"], "the durable log survives deletion"
    assert history[0]["study_id"] == "sess-1"


def test_delete_missing_plan_is_not_found_before_confirmation_is_judged() -> None:
    with pytest.raises(ToolError, match=r"^not_found: "):
        _tool("delete_study_plan")("ghost")
    with pytest.raises(ToolError, match=r"^not_found: "):
        _tool("delete_study_plan")("ghost", confirmed=True)
    with pytest.raises(ToolError, match=r"^invalid_id: "):
        _tool("delete_study_plan")("../escape", confirmed=True)


# ---------------------------------------------------------------------------
# Council review 4, F4 (GPT 🔵): writer tripwires beside the byte-equality proofs
# ---------------------------------------------------------------------------
#
# Byte-identical document contents prove the *state* did not change; they do
# not prove the writer was never invoked (a rewrite of identical bytes would
# pass). An empty checkpoint log after a preview is weaker than existing rows
# surviving one. These pins close both gaps on the real seam, and add the
# document-sink failure the earlier partial-failure test did not exercise.


def test_milestone_retry_does_not_call_save_plan(monkeypatch) -> None:
    """Scenario 1's "rewrites nothing", proven at the writer: after the first
    set, ``store.save_plan`` is replaced by a tripwire, and the identical retry
    returns the same view without ever reaching it."""
    plan_id = _ready_plan_on_disk()
    first = _tool("set_study_plan_milestone")(plan_id, 0, True)

    def _tripwire(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a retried identical set reached store.save_plan")

    monkeypatch.setattr(store, "save_plan", _tripwire)

    second = _tool("set_study_plan_milestone")(plan_id, 0, True)

    assert second == first


def test_evaluate_preview_preserves_existing_checkpoint_rows() -> None:
    """Scenario 3, strengthened: a preview after a recorded checkpoint leaves
    the recorded row — and the document's Checkpoints table — exactly as
    they were, not merely "still empty"."""
    plan_id = _ready_plan_on_disk()
    _tool("set_study_plan_status")(plan_id, "active")
    _tool("evaluate_study_plan")(plan_id, "start", study_id="sess-1", record=True)
    rows_before = [dict(row) for row in plan_index.checkpoint_history(plan_id)]
    document_before = store.load_plan_text(plan_id)
    assert [row["phase"] for row in rows_before] == ["start"]

    payload = _tool("evaluate_study_plan")(plan_id, "mid")

    assert payload["db_write"] == payload["document_write"] == "not_requested"
    assert [dict(row) for row in plan_index.checkpoint_history(plan_id)] == rows_before
    assert store.load_plan_text(plan_id) == document_before


def test_evaluate_document_failure_reports_saved_database_and_failed_document(
    monkeypatch,
) -> None:
    """The mirror of scenario 5: the log takes the checkpoint, the document
    write raises; the tool returns ``db_write: saved``, ``document_write:
    failed``, ``recording_complete: false`` and the seam's document warning
    — the checkpoint row exists, the document is byte-identical."""
    plan_id = _ready_plan_on_disk()
    _tool("set_study_plan_status")(plan_id, "active")
    document_before = store.load_plan_text(plan_id)

    def _disk_full(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "save_plan", _disk_full)

    payload = _tool("evaluate_study_plan")(plan_id, "start", record=True)

    assert payload["db_write"] == "saved"
    assert payload["document_write"] == "failed"
    assert payload["recording_complete"] is False
    assert DOCUMENT_WARNING in payload["warnings"]
    assert _database_checkpoints(plan_id) == ["start"]
    assert store.load_plan_text(plan_id) == document_before
