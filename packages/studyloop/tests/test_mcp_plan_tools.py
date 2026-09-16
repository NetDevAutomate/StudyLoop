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
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError

from studyloop.planning import (
    CreatePlan,
    InvalidField,
    InvalidMilestone,
    InvalidPlanId,
    Milestone,
    Mission,
    PlanApplication,
    PlanConflict,
    PlanDetail,
    PlanError,
    PlanningBrief,
    PlanNotFound,
    PlanNotReady,
    PlanSummary,
    ReadinessView,
    RevisePlan,
    StudyPlan,
    TransitionLifecycle,
    store,
)
from studyloop.planning import index as plan_index

SIX_TOOLS = (
    "list_study_plans",
    "get_study_plan",
    "get_planning_interview",
    "create_study_plan",
    "update_study_plan",
    "set_study_plan_status",
)


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

    def __call__(self, _self: PlanApplication, *args: Any, **kwargs: Any) -> object:
        self.calls.append((args, kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _fake(monkeypatch, method: str, result: object) -> _Spy:
    spy = _Spy(result)
    monkeypatch.setattr(PlanApplication, method, spy)
    return spy


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
