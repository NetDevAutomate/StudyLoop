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
    LearningRecordSpec,
    ReplaceDocument,
    RevisePlan,
    TransitionLifecycle,
)
from studyloop.planning.models import Milestone, Mission, StudyPlan
from studyloop.planning.views import PlanDetail, PlanSummary, ReadinessView


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    """A fresh checkpoint database per test, so "no history" is a fact about
    this test rather than about what the suite's shared database holds (F6)."""
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))
    return tmp_path / "sessions.db"


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
    assert full.history == ()  # nothing recorded in THIS test's database, but the log was asked for


def test_inspect_history_is_newest_first_and_honours_the_limit(app: PlanApplication) -> None:
    """Seed the isolated checkpoint log directly and read it back through the seam."""
    from studyloop.planning import index
    from studyloop.planning.evaluation import PlanEvaluation

    store.create_plan(_ready_plan("demo"))
    for phase in ("start", "mid", "end"):
        evaluation = PlanEvaluation(
            plan_id="demo", plan_title="Demo", phase=phase, verdict="on-track", headline=phase
        )
        assert index.record_checkpoint(evaluation, study_id=f"sess-{phase}") is True

    full = app.inspect("demo", include_history=True)
    assert full.history is not None
    assert [entry.phase for entry in full.history] == ["end", "mid", "start"]
    assert all(entry.plan_id == "demo" for entry in full.history)
    assert full.history[0].study_id == "sess-end"
    assert full.history[0].summary == "end"
    assert full.history[0].created_at, "the row's timestamp travels with the view"

    limited = app.inspect("demo", include_history=True, history_limit=2)
    assert limited.history is not None
    assert [entry.phase for entry in limited.history] == ["end", "mid"]

    payload = full.to_json_dict()
    assert [row["phase"] for row in payload["history"]] == ["end", "mid", "start"]
    assert set(payload["history"][0]) == {
        "plan_id",
        "study_id",
        "phase",
        "verdict",
        "summary",
        "created_at",
    }
    # Another plan's log is not this plan's.
    assert app.inspect("demo", include_history=True).history == full.history
    store.create_plan(_ready_plan("other"))
    assert app.inspect("other", include_history=True).history == ()


def test_inspect_markdown_translates_store_not_found_after_initial_load(
    app: PlanApplication, monkeypatch
) -> None:
    """F3: the raw-text read happens after the parse succeeded; if the document
    vanishes in between, the store error must still surface as the domain
    ``PlanNotFound`` the adapters map — not escape as a ``LookupError``."""
    store.create_plan(_ready_plan("demo"))

    def vanished(plan_id: str) -> str:
        msg = f"no study plan with id {plan_id!r}"
        raise store.PlanNotFoundError(msg)

    monkeypatch.setattr(store, "load_plan_text", vanished)

    with pytest.raises(PlanNotFound):
        app.inspect("demo", include_markdown=True)
    # Without the raw text nothing else is read from the store a second time.
    assert app.inspect("demo").summary.plan_id == "demo"


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


# --- Council review 1, F5: import identity precedence and the successful active paths ---

_READY_IMPORT_DOC = (
    "---\nid: imported\ntitle: Imported Plan\nstatus: {status}\n"
    "created: 2025-12-24T10:00:00+00:00\nupdated: 2025-12-24T10:00:00+00:00\n---\n\n"
    "# Imported Plan\n\n## Mission\n\n### Why\n\nBecause it matters.\n\n"
    "### Success\n\n- Can do the thing\n\n"
    "## Milestones\n\n- [ ] **Step** `(concepts: x)`\n"
)


def test_import_explicit_id_overrides_frontmatter_without_creating_old_id(
    app: PlanApplication,
) -> None:
    detail = app.apply(
        ImportDocument(markdown=_READY_IMPORT_DOC.format(status="draft"), plan_id="chosen")
    )
    assert detail.summary.plan_id == "chosen"
    assert store.list_plan_ids() == ["chosen"], "the frontmatter id must not become a file"
    on_disk = store.load_plan("chosen")
    assert on_disk.plan_id == "chosen", "the stored frontmatter names the id it was saved under"


def test_import_without_id_allocates_unique_title_slug(app: PlanApplication) -> None:
    no_id = _READY_IMPORT_DOC.format(status="draft").replace("id: imported\n", "")
    assert "id:" not in no_id.split("---")[1]

    first = app.apply(ImportDocument(markdown=no_id))
    second = app.apply(ImportDocument(markdown=no_id))

    assert first.summary.plan_id == "imported-plan"
    assert second.summary.plan_id == "imported-plan-2", "the fallback id is unique, not a clash"
    assert store.list_plan_ids() == ["imported-plan", "imported-plan-2"]


def test_import_preserves_document_created(app: PlanApplication) -> None:
    detail = app.apply(ImportDocument(markdown=_READY_IMPORT_DOC.format(status="draft")))
    assert detail.summary.created == "2025-12-24T10:00:00+00:00"
    assert store.load_plan("imported").created == "2025-12-24T10:00:00+00:00"


def test_ready_active_import_succeeds(app: PlanApplication) -> None:
    detail = app.apply(ImportDocument(markdown=_READY_IMPORT_DOC.format(status="active")))
    assert detail.summary.status == "active"
    assert detail.readiness.ready is True
    assert [p.plan_id for p in app.browse(status="active")] == ["imported"]


def test_ready_active_replacement_succeeds(app: PlanApplication) -> None:
    app.apply(CreatePlan(title="Imported Plan", answers=READY_ANSWERS, plan_id="imported"))
    active_doc = store.load_plan_text("imported").replace("status: draft", "status: active")

    detail = app.apply(ReplaceDocument(plan_id="imported", markdown=active_doc))

    assert detail.summary.status == "active"
    assert detail.readiness.ready is True
    assert store.load_plan("imported").status == "active"


@pytest.mark.parametrize(
    "write",
    [
        ReplaceDocument(
            plan_id="target",
            markdown=_READY_IMPORT_DOC.format(status="draft").replace("id: imported", "id: other"),
        ),
        RevisePlan(plan_id="target", title="Renamed"),
        TransitionLifecycle(plan_id="target", status="paused"),
    ],
    ids=["replace", "revise", "transition"],
)
def test_replace_keeps_requested_storage_identity_when_frontmatter_disagrees(
    app: PlanApplication,
    isolated_plans_dir,
    write: ReplaceDocument | RevisePlan | TransitionLifecycle,
) -> None:
    """The id is the file. A hand-edited document whose frontmatter names some
    other id is still addressed, and re-saved, as the file it lives in — one
    updated target document, never a second file under the frontmatter's id."""
    store.plans_dir()  # creates the directory
    (isolated_plans_dir / "target.md").write_text(
        _READY_IMPORT_DOC.format(status="draft").replace("id: imported", "id: other"),
        encoding="utf-8",
    )

    detail = app.apply(write)

    assert detail.summary.plan_id == "target"
    assert store.list_plan_ids() == ["target"], "no second document under the frontmatter id"
    assert "id: target" in store.load_plan_text("target")


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


# --- Council review 1, F4: identity and conflict are judged before readiness ---

_UNREADY_ACTIVE_DOC = (
    "---\nid: taken\ntitle: Taken\nstatus: active\n---\n\n"
    "# Taken\n\n## Milestones\n\n_No milestones yet._\n"
)


@pytest.mark.parametrize(
    "clash",
    [
        CreatePlan(title="Taken", answers={}, plan_id="taken", status="active"),
        ImportDocument(markdown=_UNREADY_ACTIVE_DOC),
        ImportDocument(
            markdown=_UNREADY_ACTIVE_DOC.replace("id: taken", "id: other"), plan_id="taken"
        ),
    ],
    ids=["create-with-status", "import-frontmatter-id", "import-explicit-id"],
)
def test_duplicate_unready_active_create_reports_conflict(
    app: PlanApplication, clash: CreatePlan | ImportDocument
) -> None:
    """The spec's "Duplicate id without overwrite" promises a conflict
    unconditionally: an id that is already taken is a conflict even when the
    incoming document would also have failed the readiness gate."""
    store.create_plan(_ready_plan("taken"))
    before = store.load_plan_text("taken")

    with pytest.raises(PlanConflict):
        app.apply(clash)

    assert store.load_plan_text("taken") == before
    assert store.list_plan_ids() == ["taken"]


@pytest.mark.parametrize(
    "malformed",
    [
        CreatePlan(title="Vague", answers={}, plan_id="../escape", status="active"),
        ImportDocument(markdown=_UNREADY_ACTIVE_DOC, plan_id="../escape"),
    ],
    ids=["create", "import"],
)
def test_malformed_explicit_id_is_refused_before_readiness(
    app: PlanApplication, malformed: CreatePlan | ImportDocument
) -> None:
    """Identity validation precedes the gate: a traversal id is an id error,
    not a readiness refusal, and nothing is written either way."""
    with pytest.raises(InvalidPlanId):
        app.apply(malformed)
    assert store.list_plan_ids() == []


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
# Revision — council review 1, F1/F1b: a compound edit is ONE intent, judged on
# the RESULTING document, persisted in ONE write.
# ---------------------------------------------------------------------------


def _count_saves(monkeypatch) -> list[int]:
    """Wrap ``store.save_plan`` so a test can assert how many writes happened."""
    calls: list[int] = []
    real_save = store.save_plan

    def counting_save(plan, **kwargs):
        calls.append(1)
        return real_save(plan, **kwargs)

    monkeypatch.setattr(store, "save_plan", counting_save)
    return calls


def test_revise_compound_status_and_fields_is_one_write(app: PlanApplication, monkeypatch) -> None:
    # An otherwise-ready draft that lacks milestones: activating it alone is
    # refused, but supplying the milestones in the same revision must be
    # judged as one resulting document and land in exactly one save.
    answers = {k: v for k, v in READY_ANSWERS.items() if k != "milestones"}
    app.apply(CreatePlan(title="Nearly", answers=answers, plan_id="nearly"))
    assert app.inspect("nearly").readiness.ready is False
    saves = _count_saves(monkeypatch)

    detail = app.apply(
        RevisePlan(
            plan_id="nearly",
            status="active",
            title="Nearly There",
            milestones=({"title": "First", "concepts": ["a"]},),
        )
    )

    assert len(saves) == 1, "a compound revision is one write, not a transition plus an edit"
    assert detail.summary.status == "active"
    assert detail.summary.title == "Nearly There"
    assert detail.readiness.ready is True
    assert [m.title for m in detail.milestones] == ["First"]
    on_disk = store.load_plan("nearly")
    assert on_disk.status == "active"
    assert on_disk.title == "Nearly There"


def test_revise_preserves_id_and_created_and_bumps_updated(app: PlanApplication) -> None:
    store.create_plan(_ready_plan("stable", updated="2026-01-01T00:00:00+00:00"))

    detail = app.apply(RevisePlan(plan_id="stable", title="Stable, renamed", topics=("sql", "dbt")))

    assert detail.summary.plan_id == "stable"
    assert detail.summary.created == "2026-01-01T00:00:00+00:00"
    assert detail.summary.updated != "2026-01-01T00:00:00+00:00"
    assert detail.summary.title == "Stable, renamed"
    assert detail.summary.topics == ("sql", "dbt")
    assert store.list_plan_ids() == ["stable"], "a revision never creates a second document"
    on_disk = store.load_plan("stable")
    assert on_disk.created == "2026-01-01T00:00:00+00:00"
    assert on_disk.updated == detail.summary.updated


def test_revise_active_plan_that_would_become_unready_raises_plan_not_ready(
    app: PlanApplication,
) -> None:
    store.create_plan(_ready_plan("live", status="active"))
    before = store.load_plan_text("live")

    # A field-only edit — no status in the intent — that strips every
    # milestone from a plan that is already active. The resulting document
    # would be active-but-unready, so it is the same refusal as activation.
    with pytest.raises(PlanNotReady) as caught:
        app.apply(RevisePlan(plan_id="live", milestones=()))

    assert caught.value.readiness.ready is False
    assert caught.value.readiness.plan_id == "live"
    assert any("milestone" in blocker.lower() for blocker in caught.value.readiness.blockers)
    assert store.load_plan_text("live") == before, "refused: nothing written"
    assert app.inspect("live").summary.milestone_total == 1


def test_revise_compound_activation_that_strips_milestones_is_refused(
    app: PlanApplication, monkeypatch
) -> None:
    store.create_plan(_ready_plan("ready"))
    before = store.load_plan_text("ready")
    saves = _count_saves(monkeypatch)

    with pytest.raises(PlanNotReady):
        app.apply(RevisePlan(plan_id="ready", status="active", milestones=()))

    assert saves == [], "the refused revision must not have committed the status first"
    assert store.load_plan_text("ready") == before
    assert app.inspect("ready").summary.status == "draft"


@pytest.mark.parametrize(
    "intent",
    [
        RevisePlan(plan_id="demo", title="   "),
        RevisePlan(plan_id="demo", status="banana"),
        RevisePlan(plan_id="demo", energy_floor="high"),  # type: ignore[arg-type]  # boundary
        RevisePlan(plan_id="demo", review_cadence_days="soon"),  # type: ignore[arg-type]
        RevisePlan(plan_id="demo", milestones="nope"),  # type: ignore[arg-type]  # boundary
        RevisePlan(plan_id="demo", topics="sql"),  # type: ignore[arg-type]  # a str is not a list
        RevisePlan(plan_id="demo", status="active", title=""),  # bad field beside a transition
    ],
    ids=[
        "empty-title",
        "unknown-status",
        "energy-floor-not-int",
        "cadence-not-int",
        "milestones-not-list",
        "topics-not-list",
        "empty-title-with-status",
    ],
)
def test_revise_invalid_field_raises_before_any_write(
    app: PlanApplication, monkeypatch, intent: RevisePlan
) -> None:
    store.create_plan(_ready_plan("demo"))
    before = store.load_plan_text("demo")
    saves = _count_saves(monkeypatch)

    with pytest.raises(InvalidField):
        app.apply(intent)

    assert saves == []
    assert store.load_plan_text("demo") == before
    assert app.inspect("demo").summary.status == "draft"


def test_revise_unknown_plan_raises_not_found_before_field_validation(
    app: PlanApplication,
) -> None:
    # 404 before 400: the spec's "Unknown plan on a write" scenario.
    with pytest.raises(PlanNotFound):
        app.apply(RevisePlan(plan_id="missing", title="   ", status="banana"))


def test_revise_clamps_numeric_fields_like_the_legacy_route(app: PlanApplication) -> None:
    store.create_plan(_ready_plan("demo"))
    detail = app.apply(RevisePlan(plan_id="demo", energy_floor=99, review_cadence_days=0))
    assert detail.summary.energy_floor == 10
    assert detail.summary.review_cadence_days == 1


def test_revise_with_no_fields_is_a_touch(app: PlanApplication) -> None:
    """An empty PATCH body has always been a save that bumps ``updated``; keep it."""
    store.create_plan(_ready_plan("demo", updated="2026-01-01T00:00:00+00:00"))
    detail = app.apply(RevisePlan(plan_id="demo"))
    assert detail.summary.updated != "2026-01-01T00:00:00+00:00"
    assert detail.summary.title == "Demo"


def test_revise_learning_record_appends_once_and_is_idempotent(
    app: PlanApplication, monkeypatch
) -> None:
    store.create_plan(_ready_plan("demo"))
    saves = _count_saves(monkeypatch)
    record = LearningRecordSpec(title="Window frames default to RANGE", body="Not ROWS.")

    first = app.apply(RevisePlan(plan_id="demo", learning_record=record))
    assert [(r.number, r.title, r.body) for r in first.learning_records] == [
        (1, "Window frames default to RANGE", "Not ROWS.")
    ]
    assert len(saves) == 1

    # Same title and body again: no second record, but the revision is still
    # the one save every revision is (it touches ``updated``).
    again = app.apply(RevisePlan(plan_id="demo", learning_record=record))
    assert len(again.learning_records) == 1
    assert len(saves) == 2

    with pytest.raises(InvalidField):
        app.apply(RevisePlan(plan_id="demo", learning_record=LearningRecordSpec(title="  ")))
    with pytest.raises(InvalidField):
        app.apply(
            RevisePlan(
                plan_id="demo",
                learning_record=LearningRecordSpec(title="Bad", body="## a heading"),
            )
        )
    assert len(saves) == 2, "refused records write nothing"


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


# --- Council review 1, F2: immutability is a property of the view, not of one factory ---


def test_planning_brief_direct_constructor_defensively_freezes_seed() -> None:
    from types import MappingProxyType

    from studyloop.planning.views import PlanningBrief

    seed: dict[str, object] = {"notes": ["before"], "configured_topics": ["sql"]}
    brief = PlanningBrief(interview=(), evidence_seed=seed, existing_plans=())

    # The caller's mapping is copied, not aliased: later edits do not reach in.
    seed["notes"] = ["replaced"]
    seed["configured_topics"].append("python")  # type: ignore[attr-defined]  # caller's own list
    assert brief.evidence_seed["notes"] == ("before",)
    assert brief.evidence_seed["configured_topics"] == ("sql",)
    assert isinstance(brief.evidence_seed, MappingProxyType)
    with pytest.raises(TypeError):
        brief.evidence_seed["notes"] = ()  # type: ignore[index]  # read-only mapping


def test_planning_brief_nested_seed_mutation_cannot_change_view() -> None:
    from studyloop.planning.views import PlanningBrief

    inner_row = {"topic": "joins", "tags": ["a"]}
    seed: dict[str, object] = {"struggling_topics": [inner_row], "by_key": {"x": {"y": [1]}}}
    brief = PlanningBrief(interview=(), evidence_seed=seed, existing_plans=())
    snapshot = brief.to_json_dict()["seed"]

    inner_row["topic"] = "mutated"
    inner_row["tags"].append("b")  # type: ignore[attr-defined]
    seed["by_key"]["x"]["y"].append(2)  # type: ignore[index]

    assert brief.to_json_dict()["seed"] == snapshot
    nested = brief.evidence_seed["by_key"]["x"]  # type: ignore[index]
    assert nested["y"] == (1,)
    with pytest.raises(TypeError):
        nested["y"] = (2,)
    with pytest.raises(AttributeError):
        brief.evidence_seed["struggling_topics"][0]["tags"].append("c")  # type: ignore[index]


def test_planning_brief_json_calls_do_not_share_nested_containers() -> None:
    from studyloop.planning.views import PlanningBrief

    brief = PlanningBrief(
        interview=(),
        evidence_seed={"struggling_topics": [{"topic": "joins", "tags": ["a"]}]},
        existing_plans=(),
    )
    first = brief.to_json_dict()
    second = brief.to_json_dict()
    assert first == second
    assert first["seed"] is not second["seed"]
    assert first["seed"]["struggling_topics"] is not second["seed"]["struggling_topics"]
    assert first["seed"]["struggling_topics"][0] is not second["seed"]["struggling_topics"][0]

    first["seed"]["struggling_topics"][0]["tags"].append("leaked")
    assert brief.to_json_dict() == second


@pytest.mark.parametrize(
    "leaf",
    [object(), bytearray(b"x"), StudyPlan(plan_id="p", title="P")],
    ids=["object", "bytearray", "model"],
)
def test_planning_brief_rejects_unsupported_mutable_seed_leaf(leaf: object) -> None:
    from studyloop.planning.views import PlanningBrief

    with pytest.raises(TypeError, match="evidence seed"):
        PlanningBrief(interview=(), evidence_seed={"rows": [leaf]}, existing_plans=())
    with pytest.raises(TypeError, match="evidence seed"):
        PlanningBrief(interview=(), evidence_seed=["not", "a", "mapping"], existing_plans=())  # type: ignore[arg-type]


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
