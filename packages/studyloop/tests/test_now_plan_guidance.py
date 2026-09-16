"""Plan-aware ``now`` — issue #10 (design §3; decisions D-5, D-16).

The one non-negotiable in this module is the golden: with **no active plan**
the JSON ``studyloop now --json`` / ``GET /api/now`` emit must be byte for
byte what it was before any plan-awareness existed
(``tests/golden/now_plan_no_active.json``, captured on the pre-#10 tree). The
additive ``NowPlan`` keys and ``plan_refs`` are therefore emitted only when
non-empty (D-5).

Everything the engine reads is isolated here — an empty sessions database, an
empty plans directory, empty content roots, a config with no topics and no
focus — and the engine's clock is frozen, so the emit is a function of the
fixtures alone and the golden holds on any machine.

The ranking tests prove *ranking compliance* with the nine ordered rules of
design §3 — not learner benefit, which is a separate, later measurement
(D-16). Candidates are injected through the same collector monkeypatches
``test_learning_decision.py`` uses; plans are real documents written through
the store into the isolated plans directory and read back through
``PlanApplication().get_active_guidance()``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from studyloop.learning import decision
from studyloop.learning.decision import PlanRef, _Candidate, build_now_plan
from studyloop.planning import store
from studyloop.planning.models import Milestone, Mission, StudyPlan

if TYPE_CHECKING:
    from studyloop.learning.decision import NowPlan

GOLDEN = Path(__file__).parent / "golden" / "now_plan_no_active.json"

#: One frozen instant for ``generated_at`` and for every date derived from it.
FROZEN_NOW = datetime(2026, 9, 16, 9, 30, tzinfo=UTC)
TODAY = FROZEN_NOW.date()

OVERDUE = "2026-09-10"  # six days before TODAY
SOON = "2026-09-18"  # two days after TODAY
LATER = "2026-10-30"  # well past the seven-day "soon" window


class _FrozenDatetime(datetime):
    """``datetime`` whose ``now()`` always answers :data:`FROZEN_NOW`."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return FROZEN_NOW if tz is None else FROZEN_NOW.astimezone(tz)


def isolate_now_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every input of ``build_now_plan`` at an empty world and freeze its clock.

    A plain function (not a fixture) so the golden capture script could call
    it the same way the tests do; the fixture below is its pytest face.
    """
    content = tmp_path / "content"
    study = tmp_path / "study"
    content.mkdir()
    study.mkdir()
    config = tmp_path / "config.yaml"
    config.write_text(
        "content:\n"
        f"  base_path: {content}\n"
        f"  study_paths: [{study}]\n"
        "review:\n"
        f"  directories: [{content}]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("STUDYLOOP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    monkeypatch.setattr(decision, "datetime", _FrozenDatetime)
    return tmp_path


@pytest.fixture(autouse=True)
def now_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_now_world(tmp_path, monkeypatch)


def serialise(plan: NowPlan) -> bytes:
    """The exact bytes the golden file holds for a plan."""
    return (json.dumps(plan.to_json_dict(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _candidate(
    concept: str,
    *,
    topic: str = "python",
    course: str | None = None,
    action_type: str = "recall",
    score: float = 50,
) -> _Candidate:
    return _Candidate(
        concept=concept,
        topic=topic,
        course=course,
        reason=f"reason for {concept}",
        action_type=action_type,  # type: ignore[arg-type]
        estimated_minutes=10,
        source=f"test:{concept}",
        evidence_command=f'studyloop progress "{concept}" -t "{topic}" -c learning',
        score=score,
    )


def _patch_collectors(monkeypatch: pytest.MonkeyPatch, *candidates: _Candidate) -> None:
    """Silence every collector; inject ``candidates`` as due-progress items."""
    for name in (
        "_due_card_candidates",
        "_due_progress_candidates",
        "_struggle_candidates",
        "_continuity_candidates",
        "_practice_candidates",
        "_transfer_candidates",
    ):
        monkeypatch.setattr(decision, name, lambda time_minutes: [])
    if candidates:
        monkeypatch.setattr(
            decision, "_due_progress_candidates", lambda time_minutes: list(candidates)
        )


def _plan(
    plan_id: str,
    *,
    title: str | None = None,
    topics: list[str] | None = None,
    milestones: list[Milestone] | None = None,
    target_date: str = "",
    energy_floor: int = 3,
    updated: str = "2026-09-01T00:00:00+00:00",
    status: str = "active",
) -> StudyPlan:
    """Write a ready plan document into the isolated plans directory."""
    plan = StudyPlan(
        plan_id=plan_id,
        title=title or plan_id.replace("-", " ").title(),
        status=status,
        created="2026-08-01T00:00:00+00:00",
        updated=updated,
        topics=topics if topics is not None else ["sql"],
        energy_floor=energy_floor,
        target_date=target_date,
        mission=Mission(why="Because", success=["Do a thing"]),
        milestones=(
            milestones
            if milestones is not None
            else [Milestone(title="Window basics", concepts=["window function"])]
        ),
    )
    store.create_plan(plan)
    return plan


def _all(plan: NowPlan):
    return [plan.primary, *plan.alternates]


# ---------------------------------------------------------------------------
# T3.1 — the golden: no active plans → the pre-#10 emit, byte for byte
# ---------------------------------------------------------------------------


def test_no_active_plans_json_byte_identical_to_golden() -> None:
    plan = build_now_plan()

    assert plan.starter is True, "an empty world must still yield the starter recommendation"
    assert serialise(plan) == GOLDEN.read_bytes()


# ---------------------------------------------------------------------------
# T3.2 — the nine ordered rules of design §3
# ---------------------------------------------------------------------------


def test_matching_due_concept_outranks_unrelated_same_urgency(monkeypatch) -> None:
    """Rule 5: within one urgency class, plan-related beats unrelated."""
    _plan("sql-windows")
    unrelated = _candidate("decorators", topic="python", score=102)
    matching = _candidate("window function", topic="sql", score=100)
    _patch_collectors(monkeypatch, unrelated, matching)

    plan = build_now_plan()

    assert plan.primary.concept == "window function"
    assert plan.primary.plan_refs == (PlanRef("sql-windows", 0),)
    assert plan.alternates[0].concept == "decorators"
    assert plan.alternates[0].plan_refs == ()


def test_unrelated_more_urgent_due_outranks_new_milestone(monkeypatch) -> None:
    """Rule 5 is a bias, not a filter: a globally more-urgent unrelated due item wins."""
    _plan("sql-windows")
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    plan = build_now_plan()

    assert plan.primary.concept == "decorators"
    assert plan.primary.plan_refs == ()
    synthesised = [r for r in plan.alternates if r.source == "study_plan:sql-windows:0"]
    assert len(synthesised) == 1
    assert synthesised[0].concept == "window function"
    assert synthesised[0].plan_refs == (PlanRef("sql-windows", 0),)
    assert synthesised[0].score < plan.primary.score


def test_one_action_keeps_every_matching_plan_ref_ordered(monkeypatch) -> None:
    """Rule 7: every matching ref is kept, ordered urgency → latest update → plan id."""
    _plan("later-plan", target_date=LATER, updated="2026-09-14T00:00:00+00:00")
    _plan("undated-c", updated="2026-09-10T00:00:00+00:00")
    _plan("undated-a", updated="2026-09-12T00:00:00+00:00")
    _plan("undated-b", updated="2026-09-10T00:00:00+00:00")
    _plan("soon-plan", target_date=SOON, updated="2026-08-01T00:00:00+00:00")
    _plan("overdue-plan", target_date=OVERDUE, updated="2026-07-01T00:00:00+00:00")
    _patch_collectors(monkeypatch, _candidate("window function", topic="sql", score=100))

    plan = build_now_plan()

    expected = ["overdue-plan", "soon-plan", "later-plan", "undated-a", "undated-b", "undated-c"]
    assert plan.primary.plan_refs == tuple(PlanRef(plan_id, 0) for plan_id in expected)
    assert [entry.plan_id for entry in plan.active_plans] == expected


def test_milestone_without_concepts_does_not_substring_match(monkeypatch) -> None:
    """Rule 4: equality on the normalised key — never a substring test."""
    _plan(
        "sql-windows",
        topics=["sql"],
        milestones=[Milestone(title="Window functions deep dive")],
    )
    superstring = _candidate("window functions deep dive tutorial", topic="python", score=100)
    substring = _candidate("window", topic="python", score=99)
    topic_match = _candidate("joins", topic="SQL", score=98)
    _patch_collectors(monkeypatch, superstring, substring, topic_match)

    plan = build_now_plan()

    by_concept = {rec.concept: rec for rec in _all(plan)}
    assert by_concept["window functions deep dive tutorial"].plan_refs == ()
    assert by_concept["window"].plan_refs == ()
    # A topic match is plan-related but names no milestone.
    assert by_concept["joins"].plan_refs == (PlanRef("sql-windows", None),)
    assert plan.primary.concept == "joins"


def test_energy_below_floor_defers_new_milestone_keeps_repair(monkeypatch) -> None:
    """Rule 3: below the floor new-milestone work is deferred; plan-related repair stays."""
    _plan(
        "sql-windows",
        energy_floor=5,
        milestones=[
            Milestone(title="Window basics", done=True, concepts=["window function"]),
            Milestone(title="Frames", concepts=["window frame"]),
        ],
    )
    repair = _candidate("window function", topic="sql", action_type="hands-on", score=82)
    _patch_collectors(monkeypatch, repair)

    low = build_now_plan(energy="low")

    assert low.primary.concept == "window function"
    assert low.primary.plan_refs == (PlanRef("sql-windows", None),)
    assert [
        (d.plan_id, d.milestone_index, d.energy_floor, d.energy_capability)
        for d in low.energy_deferred
    ] == [("sql-windows", 1, 5, 3)]
    assert not any(rec.source.startswith("study_plan:") for rec in _all(low))

    medium = build_now_plan(energy="medium")

    assert medium.energy_deferred == ()
    assert any(rec.source == "study_plan:sql-windows:1" for rec in medium.alternates)


def test_fully_checked_active_plan_emits_completion_not_candidate(monkeypatch) -> None:
    """Rule 9: a fully-checked plan yields a completion action, never a study candidate."""
    _plan(
        "done-plan",
        title="Done Plan",
        milestones=[
            Milestone(title="A", done=True, concepts=["alpha"]),
            Milestone(title="B", done=True, concepts=["beta"]),
        ],
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    plan = build_now_plan()

    assert [action.plan_id for action in plan.completion_actions] == ["done-plan"]
    assert "Done Plan" in plan.completion_actions[0].action
    assert not any(rec.source.startswith("study_plan:") for rec in _all(plan))
    assert plan.active_plans[0].plan_id == "done-plan"
    assert plan.active_plans[0].next_milestone_index is None


def test_synthesizes_milestone_when_no_candidate_represents_it(monkeypatch) -> None:
    """Rule 6: an unrepresented eligible next milestone becomes a candidate."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        milestones=[Milestone(title="Frames", concepts=["window frame", "rows between"])],
    )
    _patch_collectors(monkeypatch)

    plan = build_now_plan()

    assert plan.starter is False
    assert plan.primary.concept == "window frame"
    assert plan.primary.topic == "sql"
    assert plan.primary.action_type == "conversation"
    assert plan.primary.source == "study_plan:sql-windows:0"
    assert plan.primary.plan_refs == (PlanRef("sql-windows", 0),)
    assert "SQL Windows" in plan.primary.reason
    assert "Frames" in plan.primary.reason
    assert plan.primary.evidence_command == (
        'studyloop progress "window frame" -t "sql" -c learning'
    )


def test_preserves_one_plan_backed_action_when_energy_allows(monkeypatch) -> None:
    """Rule 8: ≥ 1 eligible plan-backed action in primary + alternates when energy permits."""
    _plan(
        "sql-windows", energy_floor=5, milestones=[Milestone("Frames", concepts=["window frame"])]
    )
    unrelated = [_candidate(f"due {i}", topic="python", score=140 - 2 * i) for i in range(4)]
    _patch_collectors(monkeypatch, *unrelated)

    medium = build_now_plan(energy="medium")

    assert medium.primary.concept == "due 0"
    assert [rec.concept for rec in medium.alternates] == ["due 1", "window frame"]
    assert medium.alternates[1].plan_refs == (PlanRef("sql-windows", 0),)

    low = build_now_plan(energy="low")

    assert [rec.concept for rec in _all(low)] == ["due 0", "due 1", "due 2"]
    assert [d.milestone_index for d in low.energy_deferred] == [0]


def test_unready_active_plan_is_matched_never_synthesised_and_names_no_milestone(
    monkeypatch,
) -> None:
    """Review-2 G1 / deviation 12 (council review 3, F1): an active-but-unready plan is
    listed and matched — bias and a plan-related ref — but the ranker never names its
    next milestone, because the seam would refuse to tick it (``PlanNotReady``)."""
    husk = StudyPlan(
        plan_id="husk",
        title="Husk",
        status="active",
        created="2026-08-01T00:00:00+00:00",
        updated="2026-09-01T00:00:00+00:00",
        topics=["sql"],
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    store.create_plan(husk)  # no mission, no success criteria: every blocker fires
    _patch_collectors(
        monkeypatch,
        _candidate("decorators", topic="python", score=100),
        _candidate("window frame", topic="sql", score=100),
    )

    plan = build_now_plan()

    assert plan.primary.concept == "window frame", "matched: the bias still applies"
    assert plan.primary.plan_refs == (PlanRef("husk", None),), "never the unwritable milestone"
    assert not any(rec.source.startswith("study_plan:") for rec in _all(plan))
    entry = plan.active_plans[0]
    assert (entry.plan_id, entry.ready, entry.eligible) == ("husk", False, False)
    assert len(plan.warnings) == 1
    assert "husk" in plan.warnings[0]
    assert "pause or repair" in plan.warnings[0]
    for blocker in ("Mission", "success"):
        assert blocker in plan.warnings[0]


def test_energy_deferred_plan_ref_carries_no_milestone_index(monkeypatch) -> None:
    """Council review 3, F1: one payload must not say both "this action advances milestone
    1" and "milestone 1 is deferred for energy". Below the floor a match on the next
    milestone's concept is plan-related repair (``None``); at eligible energy it names it."""
    _plan(
        "sql-windows", energy_floor=5, milestones=[Milestone("Frames", concepts=["window frame"])]
    )
    _patch_collectors(monkeypatch, _candidate("window frame", topic="sql", score=100))

    low = build_now_plan(energy="low")

    assert low.primary.concept == "window frame"
    assert low.primary.plan_refs == (PlanRef("sql-windows", None),)
    assert [d.milestone_index for d in low.energy_deferred] == [0]
    assert not any(rec.source.startswith("study_plan:") for rec in _all(low))

    medium = build_now_plan(energy="medium")

    assert medium.primary.plan_refs == (PlanRef("sql-windows", 0),)
    assert medium.energy_deferred == ()


def test_additive_keys_present_only_when_active_plans_exist(monkeypatch) -> None:
    """D-5: additive keys and ``plan_refs`` appear only when non-empty."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    _plan("draft-plan", status="draft")
    _patch_collectors(monkeypatch)

    # A non-active plan changes nothing — byte for byte.
    assert serialise(build_now_plan()) == GOLDEN.read_bytes()

    _plan("sql-windows", milestones=[Milestone("Frames", concepts=["window frame"])])
    with_plan = build_now_plan().to_json_dict()

    assert list(with_plan) == [*golden, "active_plans"]
    assert list(with_plan["primary"]) == [*golden["primary"], "plan_refs"]
    assert with_plan["primary"]["plan_refs"] == [{"plan_id": "sql-windows", "milestone_index": 0}]
    assert with_plan["active_plans"][0]["plan_id"] == "sql-windows"
    for absent in ("energy_deferred", "completion_actions", "warnings"):
        assert absent not in with_plan


# ---------------------------------------------------------------------------
# Renderers show plan relevance and energy deferral — and never re-rank
# ---------------------------------------------------------------------------


def _deferral_world(monkeypatch) -> None:
    """One active plan whose next milestone is beyond low energy, plus plan-related repair."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=5,
        milestones=[
            Milestone(title="Window basics", done=True, concepts=["window function"]),
            Milestone(title="Frames", concepts=["window frame"]),
        ],
    )
    _patch_collectors(
        monkeypatch,
        _candidate("window function", topic="sql", action_type="hands-on", score=82),
    )


def test_cli_now_renders_plan_relevance_and_energy_deferral(monkeypatch) -> None:
    from click.testing import CliRunner

    from studyloop.cli import cli

    _deferral_world(monkeypatch)

    rich = CliRunner().invoke(cli, ["now", "--energy", "low"])
    as_json = CliRunner().invoke(cli, ["now", "--energy", "low", "--json"])

    assert rich.exit_code == 0, rich.output
    assert "window function" in rich.output  # the primary is unchanged
    assert "SQL Windows" in rich.output  # …and its plan relevance is shown
    assert "Deferred" in rich.output
    assert "Frames" in rich.output
    assert as_json.exit_code == 0, as_json.output
    payload = json.loads(as_json.output)
    assert payload["primary"]["concept"] == "window function"
    assert payload["primary"]["plan_refs"] == [{"plan_id": "sql-windows", "milestone_index": None}]
    assert payload["energy_deferred"][0]["milestone_index"] == 1
    assert payload["active_plans"][0]["title"] == "SQL Windows"


def _hostile_world(monkeypatch) -> bytes:
    """One active plan whose title, topic and milestone text carry Rich markup, brackets,
    shell punctuation and HTML — the hostile-content fixture review 2 required. Returns
    the document's bytes so a caller can prove the read paths performed no write."""
    _plan(
        "hostile",
        title="Plan [/bold]",
        topics=["<script>alert(1)</script>"],
        # No parentheses in the concept: the concepts regex stopping at the first ``)``
        # is the tracked parser bug (review-2 deviation 13), not this fixture's subject.
        milestones=[Milestone(title="Frames [/red]", concepts=['window "frame"; rm -rf ~'])],
    )
    _patch_collectors(monkeypatch)
    return store.plan_path("hostile").read_bytes()


def test_hostile_plan_text_does_not_break_now_emit(monkeypatch) -> None:
    """Review-2 rule for #10: plan text is data. The engine must rank it, serialise it and
    write nothing back (council review 3, F4 / Grok 🟡)."""
    before = _hostile_world(monkeypatch)

    plan = build_now_plan()

    assert plan.primary.source == "study_plan:hostile:0"
    assert plan.primary.concept == 'window "frame"; rm -rf ~'
    assert plan.primary.topic == "<script>alert(1)</script>"
    round_trip = json.loads(json.dumps(plan.to_json_dict(), ensure_ascii=False))
    assert round_trip["primary"]["plan_refs"] == [{"plan_id": "hostile", "milestone_index": 0}]
    assert round_trip["active_plans"][0]["title"] == "Plan [/bold]"
    assert store.plan_path("hostile").read_bytes() == before, "ranking performs no write"


def test_cli_now_renders_hostile_plan_text_literally(monkeypatch) -> None:
    """Council review 3, F4 (GPT 🟡 / Grok 🟡, reproduced as a crash): a plan title holding
    ``[/bold]`` reached Rich as markup and ``studyloop now`` died with ``MarkupError``.
    Plan-derived text is escaped, so it renders literally and the command exits 0."""
    from click.testing import CliRunner

    from studyloop.cli import cli

    before = _hostile_world(monkeypatch)

    result = CliRunner().invoke(cli, ["now"])

    assert result.exit_code == 0, result.output or repr(result.exception)
    assert "Plan [/bold]" in result.output
    assert "Frames [/red]" in result.output
    assert "<script>alert(1)</script>" in result.output
    assert store.plan_path("hostile").read_bytes() == before, "rendering performs no write"


def test_cli_now_without_plans_prints_no_plan_lines(monkeypatch) -> None:
    from click.testing import CliRunner

    from studyloop.cli import cli

    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    rich = CliRunner().invoke(cli, ["now"])

    assert rich.exit_code == 0, rich.output
    assert "decorators" in rich.output
    for absent in ("Plan", "Deferred", "milestone"):
        assert absent not in rich.output


def test_api_now_carries_plan_guidance_end_to_end(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

    from studyloop.web.app import create_app

    _deferral_world(monkeypatch)
    client = TestClient(create_app(study_dirs=[]))

    resp = client.get("/api/now?energy=low")

    assert resp.status_code == 200
    data = resp.json()
    assert data["primary"]["concept"] == "window function"
    assert data["primary"]["plan_refs"] == [{"plan_id": "sql-windows", "milestone_index": None}]
    assert [item["plan_id"] for item in data["active_plans"]] == ["sql-windows"]
    assert data["energy_deferred"][0]["title"] == "Frames"
    assert "completion_actions" not in data
    assert "warnings" not in data


def test_api_now_without_plans_matches_golden_shape(monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

    from studyloop.web.app import create_app

    client = TestClient(create_app(study_dirs=[]))

    resp = client.get("/api/now")

    assert resp.status_code == 200
    assert resp.json() == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_recap_shows_plan_context_without_reranking(monkeypatch) -> None:
    from studyloop.learning import recap

    _plan(
        "sql-windows",
        title="SQL Windows",
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _patch_collectors(monkeypatch)

    result = recap.build_daily_recap()

    # The next action is still the engine's primary — the synthesised milestone.
    assert result.next_action == 'studyloop progress "window frame" -t "sql" -c learning'
    assert "SQL Windows" in result.plan_context
    assert "Frames" in result.plan_context
    assert result.to_json_dict()["plan_context"] == result.plan_context
    assert "Plan:" in result.speakable_text()


def test_recap_without_plans_has_no_plan_context(monkeypatch) -> None:
    from studyloop.learning import recap

    _patch_collectors(monkeypatch)

    result = recap.build_daily_recap()

    assert result.plan_context == ""
    assert "plan_context" not in result.to_json_dict()
    assert "Plan:" not in result.speakable_text()
    assert result.speakable_text().endswith(f"Next action: {result.next_action}.")


def test_recap_names_energy_deferral(monkeypatch) -> None:
    from studyloop.learning import recap

    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=8,  # beyond the recap's default medium energy (6/10)
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    result = recap.build_daily_recap()

    assert result.next_action == 'studyloop progress "decorators" -t "python" -c learning'
    assert "Frames" in result.plan_context
    assert "energy" in result.plan_context
