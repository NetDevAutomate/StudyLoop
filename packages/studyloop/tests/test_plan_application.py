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
