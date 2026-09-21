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
from _sessions_db_template import seed_sessions_db

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
    seed_sessions_db(tmp_path / "sessions.db", monkeypatch)
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
    """Rule 8: ≥ 1 eligible plan-backed action in primary + alternates when energy permits.

    Below the floor the milestone is deferred, never synthesised; since design §5
    the plan-backed slot rule 8 keeps is then the body-double proposal — sitting
    with the plan asks for no energy the day cannot carry — and the primary and
    first alternate stay the real, higher-ranked candidates.
    """
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

    assert [rec.concept for rec in _all(low)] == ["due 0", "due 1", "Sit with Sql Windows"]
    assert low.alternates[1].source == "body_double"
    assert low.alternates[1].plan_refs == (PlanRef("sql-windows", None),)
    assert not any(rec.source.startswith("study_plan:") for rec in _all(low))
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
# Council review 3 — rule pins the ten tests above did not carry (GPT F3, Grok 🔵)
# ---------------------------------------------------------------------------


def test_guidance_read_once_with_no_checkpoint_history_calls(monkeypatch) -> None:
    """Rule 1: one plan-static read per ``build_now_plan``; zero checkpoint-history
    reads and no session scan on the plans' account."""
    from studyloop.planning import index as plan_index
    from studyloop.planning.application import PlanApplication

    _plan("sql-windows", milestones=[Milestone("Frames", concepts=["window frame"])])
    _plan("later-plan", target_date=LATER)
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))
    reads: list[dict] = []
    real = PlanApplication.get_active_guidance

    def counted(self, **kwargs):
        reads.append(kwargs)
        return real(self, **kwargs)

    monkeypatch.setattr(PlanApplication, "get_active_guidance", counted)

    def forbidden(*args, **kwargs):
        raise AssertionError("the ranker read the checkpoint history")

    monkeypatch.setattr(plan_index, "checkpoint_history", forbidden)

    plan = build_now_plan()

    assert reads == [{"today": TODAY}], "exactly one read, on the engine's own date"
    assert [entry.plan_id for entry in plan.active_plans] == ["later-plan", "sql-windows"]


def test_course_and_punctuated_concept_match_by_normalized_equality(monkeypatch) -> None:
    """Rule 4: the seam's ``normalise_match_key`` on both sides — a course equals a
    topic through punctuation and case; a concept equals a milestone concept the
    same way; nothing else about the strings matters."""
    _plan(
        "de-plan",
        topics=["Data-Engineering"],
        milestones=[Milestone("Windows", concepts=["Window Function"])],
    )
    by_course = _candidate("joins", topic="warehouse", course="data engineering", score=100)
    by_concept = _candidate("window_function", topic="warehouse", score=99)
    near_miss = _candidate("window functions", topic="warehouse", score=98)
    _patch_collectors(monkeypatch, by_course, by_concept, near_miss)

    plan = build_now_plan()

    refs = {rec.concept: rec.plan_refs for rec in _all(plan)}
    assert refs["joins"] == (PlanRef("de-plan", None),)
    assert refs["window_function"] == (PlanRef("de-plan", 0),)
    assert refs["window functions"] == ()


def test_completion_plan_does_not_bias_matching_due_work(monkeypatch) -> None:
    """Rule 9: a fully-checked plan is a completion action only — its topics neither
    bias nor reference a due item that happens to share them."""
    _plan(
        "done-plan",
        topics=["sql"],
        milestones=[Milestone(title="A", done=True, concepts=["alpha"])],
    )
    _patch_collectors(
        monkeypatch,
        _candidate("joins", topic="sql", score=100),
        _candidate("decorators", topic="python", score=101),
    )

    plan = build_now_plan()

    assert plan.primary.concept == "decorators", "no bias reached the completed plan's topic"
    assert all(rec.plan_refs == () for rec in _all(plan))
    assert [action.plan_id for action in plan.completion_actions] == ["done-plan"]


def test_plan_backed_guarantee_respects_time_limit(monkeypatch) -> None:
    """Rule 8 swaps in a plan-backed candidate only when its estimate fits the
    requested time; the primary and the first alternate are never touched."""
    _plan("sql-windows", milestones=[Milestone("Frames", concepts=["window frame"])])
    unrelated = [_candidate(f"due {i}", topic="python", score=140 - 2 * i) for i in range(4)]
    long_repair = _Candidate(
        concept="window frame",
        topic="sql",
        course=None,
        reason="a long plan-related task",
        action_type="hands-on",
        estimated_minutes=60,
        source="test:long",
        evidence_command="x",
        score=50,
    )
    _patch_collectors(monkeypatch, *unrelated, long_repair)

    plan = build_now_plan(time_minutes=25)

    assert [rec.concept for rec in _all(plan)] == ["due 0", "due 1", "due 2"]
    assert plan.primary.plan_refs == ()


def test_weak_due_still_beats_overdue_synthesised_milestone(monkeypatch) -> None:
    """Rule 5 is a bias, not a filter, at a narrow gap too: a modest due item
    (base 55) stays ahead of an overdue plan's synthesised milestone
    (48 + 6 + 12 = 66), so a later scoring tweak cannot silently turn the
    bias into a filter (Grok 🔵)."""
    _plan("overdue-plan", target_date=OVERDUE)
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=55))

    plan = build_now_plan()

    assert plan.primary.concept == "decorators"
    assert plan.alternates[0].source == "study_plan:overdue-plan:0"
    assert plan.alternates[0].score < plan.primary.score


def test_plan_related_continuity_does_not_outrank_unrelated_repair(monkeypatch) -> None:
    """The bias (12) is calibrated to today's bands: it is no larger than the gap
    between continuity (58) and a non-struggling repair (70), so plan-related
    continuity can tie but never pass unrelated repair (GPT F2, pinned as the
    invariant the constant must keep)."""
    _plan("sql-windows", topics=["sql"])
    repair = _candidate("decorators", topic="python", action_type="teachback", score=70)
    continuity = _candidate("joins", topic="sql", action_type="conversation", score=58)
    _patch_collectors(monkeypatch, repair, continuity)

    plan = build_now_plan()

    by_concept = {rec.concept: rec for rec in _all(plan)}
    assert by_concept["joins"].plan_refs == (PlanRef("sql-windows", None),)
    assert by_concept["joins"].score <= by_concept["decorators"].score


def test_synthesised_candidate_without_topics_uses_study_label(monkeypatch) -> None:
    """A ready plan with no topics (a nudge, not a blocker) synthesises under the
    fallback topic ``study`` — pinned so the fallback is a decision, not an
    accident (Grok 🔵; whether readiness should require topics is #12's call)."""
    _plan("no-topics", topics=[], milestones=[Milestone("Frames", concepts=["window frame"])])
    _patch_collectors(monkeypatch)

    plan = build_now_plan()

    assert plan.primary.source == "study_plan:no-topics:0"
    assert plan.primary.topic == "study"
    assert plan.primary.evidence_command == (
        'studyloop progress "window frame" -t "study" -c learning'
    )


def test_guidance_failure_warns_and_logs_without_failing_now(monkeypatch, caplog) -> None:
    """Rule 1's failure mode: an exception from the guidance read degrades to one
    warning and the recommendation still comes — and the exception is logged
    with its traceback, so a programming error cannot hide behind the
    learner-facing warning (GPT F9 🔵, Grok 🔵)."""
    import logging

    from studyloop.planning.application import PlanApplication

    def boom(self, **kwargs):
        raise RuntimeError("plans directory unreadable")

    monkeypatch.setattr(PlanApplication, "get_active_guidance", boom)
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    with caplog.at_level(logging.WARNING, logger="studyloop.learning.decision"):
        plan = build_now_plan()

    assert plan.primary.concept == "decorators"
    assert plan.warnings == ("study plans could not be read; recommending without them",)
    assert plan.active_plans == ()
    records = [r for r in caplog.records if r.name == "studyloop.learning.decision"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].exc_info is not None
    assert "plans directory unreadable" in caplog.text


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


def test_cli_recap_rich_panel_shows_engine_plan_context(monkeypatch) -> None:
    """Council review 3, F8 (GPT 🟡): the spec names the daily recap among the renderers
    that show plan relevance; ``--json`` and the spoken form did, the Rich panel did
    not. It prints the engine's ``plan_context`` — escaped, shown, never re-ranked."""
    from click.testing import CliRunner

    from studyloop.cli import cli

    _plan(
        "sql-windows",
        title="SQL [/bold] Windows",
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _patch_collectors(monkeypatch)

    result = CliRunner().invoke(cli, ["recap", "today"])

    assert result.exit_code == 0, result.output or repr(result.exception)
    assert "Plan:" in result.output
    assert "SQL [/bold] Windows" in result.output
    assert "Frames" in result.output


def test_cli_recap_rich_panel_without_plans_prints_no_plan_line(monkeypatch) -> None:
    from click.testing import CliRunner

    from studyloop.cli import cli

    _patch_collectors(monkeypatch)

    result = CliRunner().invoke(cli, ["recap", "today"])

    assert result.exit_code == 0, result.output or repr(result.exception)
    assert "Plan:" not in result.output
    assert "Next:" in result.output


# ---------------------------------------------------------------------------
# Item 4 (D-G) — evidence-based, consensual completion: rule 9's completion
# action carries the end assessment and proposes; it never changes a status.
# ---------------------------------------------------------------------------


def _pre_change_sentence(title: str) -> str:
    """The completion sentence rule 9 emitted before D-G (``planning/views.py``)."""
    return (
        f"Every milestone of {title!r} is checked off — close the plan "
        "or extend it with a follow-on mission."
    )


def _plant_evidence(
    monkeypatch: pytest.MonkeyPatch,
    *,
    due: list[dict] | None = None,
    struggles: list[dict] | None = None,
    mentions: list[dict] | None = None,
) -> None:
    """Point the end assessment's history readers at fixture rows.

    ``planning/evaluation.py`` resolves them on the ``studyloop.history``
    package at call time, so the package attribute is the real seam: the
    evaluation's own relevance filter and ``has_evidence`` logic stay live,
    and nothing here depends on a sessions database.
    """
    from studyloop import history

    monkeypatch.setattr(
        history, "spaced_repetition_due", lambda topic_keywords_map: list(due or [])
    )
    monkeypatch.setattr(
        history.progress, "get_struggling_topics", lambda days=30: list(struggles or [])
    )
    monkeypatch.setattr(history, "topic_frequency", lambda keywords, days=90: list(mentions or []))
    monkeypatch.setattr(history, "last_studied", lambda keywords: None)
    monkeypatch.setattr(history, "struggle_topics", lambda days=14, min_sessions=2: [])


_DONE = [
    Milestone(title="A", done=True, concepts=["alpha"]),
    Milestone(title="B", done=True, concepts=["beta"]),
]


def test_completion_action_carries_the_end_assessment_and_proposes_extend_when_concepts_are_due(
    monkeypatch,
) -> None:
    """D-G: the completion action carries the end assessment — counts of due
    reviews, struggles and unverified milestones on the plan's own concepts —
    and proposes ``extend`` while any count is above zero. One due review on
    a plan concept is outstanding work: the engine proposes extending, the
    evidence names the concept, and the sentence is composed from the
    proposal rather than the old either-way wording."""
    _plan("done-plan", title="Done Plan", topics=["sql"], milestones=_DONE)
    _plant_evidence(
        monkeypatch,
        due=[
            {
                "topic": "sql",
                "concept": "alpha",
                "confidence": "learning",
                "last_studied": "2026-09-07",
                "days_ago": 9,
                "review_type": "overdue",
            }
        ],
        mentions=[{"snippet": "worked through beta with a window frame"}],
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    plan = build_now_plan()

    [action] = plan.completion_actions
    assert action.plan_id == "done-plan"
    assert (action.due_reviews, action.struggles, action.unverified_milestones) == (1, 0, 0)
    assert action.proposal == "extend"
    assert any("alpha" in line for line in action.evidence), action.evidence
    assert "Done Plan" in action.action
    assert "extend" in action.action.lower()
    assert action.action != _pre_change_sentence("Done Plan")

    row = plan.to_json_dict()["completion_actions"][0]
    assert {"due_reviews", "struggles", "unverified_milestones", "proposal", "evidence"} <= set(row)
    assert (row["proposal"], row["due_reviews"]) == ("extend", 1)
    assert plan.primary.concept == "decorators"  # rule 9 still yields no study candidate


def test_completion_action_proposes_close_when_the_assessment_is_clean(monkeypatch) -> None:
    """Nothing due, nothing struggling, every checked milestone backed by
    evidence: the engine proposes ``close`` — and only proposes (see
    :func:`test_completion_never_changes_status`)."""
    _plan("done-plan", title="Done Plan", topics=["sql"], milestones=_DONE)
    _plant_evidence(
        monkeypatch,
        mentions=[{"snippet": "explained alpha and beta in the teach-back"}],
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    plan = build_now_plan()

    [action] = plan.completion_actions
    assert (action.due_reviews, action.struggles, action.unverified_milestones) == (0, 0, 0)
    assert action.proposal == "close"
    assert action.evidence == ()
    assert "Done Plan" in action.action
    assert "close" in action.action.lower()
    assert action.action != _pre_change_sentence("Done Plan")
    assert plan.to_json_dict()["completion_actions"][0]["proposal"] == "close"


def test_completion_review_does_not_count_new_topic_rows_as_due(monkeypatch) -> None:
    """The scheduler's cold-start hint — a ``New topic -- start fresh`` row for
    a plan topic with no progress rows, ``concept: None`` — is not a lapsed
    review. The completion review counts only rows that name a concept, so a
    finished plan whose concepts are backed by session evidence reads
    ``close``, not "extend — 1 due review: start fresh". The evaluator keeps
    the row (``plan evaluate --phase start`` wants it); this is the completion
    review's count, not the evaluator's."""
    _plan("done-plan", title="Done Plan", topics=["sql"], milestones=_DONE)
    _plant_evidence(
        monkeypatch,
        due=[
            {
                "topic": "sql",
                "concept": None,
                "confidence": None,
                "last_studied": None,
                "days_ago": None,
                "review_type": "New topic -- start fresh",
                "evidence": "configured_topic",
            }
        ],
        mentions=[{"snippet": "explained alpha and beta in the teach-back"}],
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    plan = build_now_plan()

    [action] = plan.completion_actions
    assert (action.due_reviews, action.struggles, action.unverified_milestones) == (0, 0, 0)
    assert action.proposal == "close"
    assert action.evidence == ()


def test_completion_never_changes_status(monkeypatch) -> None:
    """#7 / ``NOT_AUTOMATIC``: the assessment is the preview path — exactly one
    ``assess`` per fully-checked plan with ``phase="end"`` and
    ``record=False`` — so the document's bytes and status are unchanged after
    ``build_now_plan``, no checkpoint row is written and the recording writer
    is never called. ``set_study_plan_status`` stays the only door to
    ``complete``."""
    from studyloop.planning import AssessPlan
    from studyloop.planning import evaluation as evaluation_module
    from studyloop.planning import index as plan_index
    from studyloop.planning.application import PlanApplication

    _plan("done-plan", title="Done Plan", milestones=_DONE)
    path = store.plan_path("done-plan")
    before = path.read_bytes()
    _plant_evidence(monkeypatch)
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    intents: list[AssessPlan] = []
    real_assess = PlanApplication.assess

    def counted(self, intent):
        intents.append(intent)
        return real_assess(self, intent)

    def forbidden(*args, **kwargs):
        raise AssertionError("the ranker recorded a checkpoint")

    monkeypatch.setattr(PlanApplication, "assess", counted)
    monkeypatch.setattr(evaluation_module, "evaluate_and_record", forbidden)
    monkeypatch.setattr(plan_index, "record_checkpoint", forbidden)

    plan = build_now_plan()

    assert [action.plan_id for action in plan.completion_actions] == ["done-plan"]
    assert [(i.plan_id, i.phase, i.record) for i in intents] == [("done-plan", "end", False)]
    assert path.read_bytes() == before
    assert store.load_plan("done-plan").status == "active"
    assert plan_index.checkpoint_history("done-plan") == []


def test_completion_assessment_failure_keeps_the_sentence_and_warns(monkeypatch) -> None:
    """A failed assessment is a warning, never a failed ``now``: the completion
    action still appears with the pre-change sentence, and ``warnings`` names
    the plan so the learner knows the counts are missing rather than zero."""
    from studyloop.planning.application import PlanApplication

    _plan("done-plan", title="Done Plan", milestones=_DONE)
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    def boom(self, intent):
        raise RuntimeError("sessions.db is locked")

    monkeypatch.setattr(PlanApplication, "assess", boom)

    plan = build_now_plan()

    [action] = plan.completion_actions
    assert action.action == _pre_change_sentence("Done Plan")
    assert any(
        "done-plan" in warning and "assess" in warning.lower() for warning in plan.warnings
    ), plan.warnings
    assert plan.primary.concept == "decorators"


def test_completion_partial_assessment_never_proposes_a_clean_close(monkeypatch) -> None:
    """Council review 6, F1 (GPT 🔴, Grok 🔵): a reader that fails inside the
    evaluation is a *partial* read — ``evaluate_plan`` swallows it into a
    warning and an empty default — so "nothing due" is not known, only
    unread. The review must carry that: no ``close``, no "clean", the
    proposal ``None`` with the counts it did read, and the data gap named on
    the plan's warnings. A clean slate is a fact about evidence, never about
    its absence."""
    from studyloop import history

    _plan("done-plan", title="Done Plan", topics=["sql"], milestones=_DONE)
    _plant_evidence(
        monkeypatch,
        mentions=[{"snippet": "explained alpha and beta in the teach-back"}],
    )

    def due_reader_down(topic_keywords_map):
        raise RuntimeError("study_progress is locked")

    monkeypatch.setattr(history, "spaced_repetition_due", due_reader_down)
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    plan = build_now_plan()

    [action] = plan.completion_actions
    assert action.proposal is None
    assert action.partial is True
    assert (action.due_reviews, action.struggles, action.unverified_milestones) == (0, 0, 0)
    assert "clean" not in action.action.lower()
    assert "closing the plan" not in action.action.lower()
    assert "partial" in action.action.lower() or "could not" in action.action.lower()
    assert "studyloop plan close done-plan" in action.action
    assert any("done-plan" in w and "unavailable" in w for w in plan.warnings), plan.warnings
    entry = plan.to_json_dict()["completion_actions"][0]
    assert entry["proposal"] is None and entry["partial"] is True


def test_completion_struggle_only_proposes_extend(monkeypatch) -> None:
    """Council review 6, F7: the struggles count alone must carry ``extend`` —
    nothing due, every milestone backed, one live struggle on a plan concept."""
    _plan("done-plan", title="Done Plan", topics=["sql"], milestones=_DONE)
    _plant_evidence(
        monkeypatch,
        struggles=[{"topic": "sql", "concept": "alpha", "sessions": 3}],
        mentions=[{"snippet": "explained alpha and beta in the teach-back"}],
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    [action] = build_now_plan().completion_actions

    assert (action.due_reviews, action.struggles, action.unverified_milestones) == (0, 1, 0)
    assert action.proposal == "extend"
    assert action.evidence == ("Struggle: alpha",)
    assert "1 struggle" in action.action


def test_completion_unverified_milestone_only_proposes_extend(monkeypatch) -> None:
    """Council review 6, F7: a done milestone whose concepts have no evidence at
    all is outstanding work — the unverified count alone carries ``extend``."""
    _plan("done-plan", title="Done Plan", topics=["sql"], milestones=_DONE)
    _plant_evidence(monkeypatch, mentions=[{"snippet": "explained alpha in the teach-back"}])
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    [action] = build_now_plan().completion_actions

    assert (action.due_reviews, action.struggles, action.unverified_milestones) == (0, 0, 1)
    assert action.proposal == "extend"
    assert action.evidence == (
        "Unverified milestone: B — marked done, no evidence on its concepts",
    )


def test_completion_evidence_cap_keeps_the_counts_and_names_the_overflow(monkeypatch) -> None:
    """Council review 6, F7: the evidence lines are capped at
    ``COMPLETION_EVIDENCE_CAP`` with one ``… and N more`` line; the counts are
    never capped by it, so the sentence and the JSON still say how much is
    outstanding."""
    from studyloop.planning.views import COMPLETION_EVIDENCE_CAP

    _plan("done-plan", title="Done Plan", topics=["sql"], milestones=_DONE)
    due = [
        {"topic": "sql", "concept": f"alpha-{i}", "review_type": "overdue"}
        for i in range(COMPLETION_EVIDENCE_CAP + 3)
    ]
    _plant_evidence(
        monkeypatch, due=due, mentions=[{"snippet": "explained alpha and beta in the teach-back"}]
    )
    _patch_collectors(monkeypatch, _candidate("decorators", topic="python", score=100))

    [action] = build_now_plan().completion_actions

    # The evaluator itself keeps ten due rows; the review counts what it was given.
    assert action.due_reviews >= COMPLETION_EVIDENCE_CAP + 1
    assert action.proposal == "extend"
    assert len(action.evidence) == COMPLETION_EVIDENCE_CAP + 1
    assert action.evidence[-1].startswith("… and ")
    assert action.evidence[-1].endswith(" more")
    assert f"{action.due_reviews} due reviews" in action.action


# ---------------------------------------------------------------------------
# T5.2 — item 5 (D-F): per-item energy demand for repair, and the body-doubling
# floor. Design §5 with its three T5.1 amendments. The struggle collector runs
# for real here — demand is derived in the collector, so injecting candidates
# through ``_due_progress_candidates`` would bypass the very thing under test.
# ---------------------------------------------------------------------------


def _struggle(
    concept: str,
    *,
    topic: str = "sql",
    confidence: str = "struggling",
    days_ago: int = 3,
    teachback: int | None = None,
) -> dict:
    """One row as ``history.observations.rows`` projects it.

    ``last_seen`` is relative to the frozen clock.
    """
    from datetime import timedelta

    seen = (FROZEN_NOW - timedelta(days=days_ago)).isoformat()
    return {
        "id": f"{topic}/{concept}",
        "topic": topic,
        "concept": concept,
        "confidence": confidence,
        "first_seen": seen,
        "last_seen": seen,
        "session_count": 1,
        "notes": None,
        "last_teachback_score": teachback,
    }


def _plant_struggles(
    monkeypatch: pytest.MonkeyPatch, *rows: dict, due: tuple[_Candidate, ...] = ()
) -> None:
    """Silence every collector except the struggle collector, which reads ``rows``."""
    from studyloop.history import observations

    real_collector = decision._struggle_candidates
    _patch_collectors(monkeypatch, *due)
    monkeypatch.setattr(decision, "_struggle_candidates", real_collector)
    monkeypatch.setattr(observations, "rows", lambda conn: [dict(row) for row in rows])


def _row3_plan() -> None:
    """Rubric row 3's plan: floor 5, milestone 0 done, milestone 1 ``Frames`` open."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=5,
        milestones=[
            Milestone(title="Window basics", done=True, concepts=["window function"]),
            Milestone(title="Frames", concepts=["window frame"]),
        ],
    )


def _plant_struggles_for_both_collectors(monkeypatch: pytest.MonkeyPatch, *rows: dict) -> None:
    """Like ``_plant_struggles`` but the due-progress collector runs for real too.

    Both collectors read the same ``observations.rows``: a ``struggling`` row is
    *always* due (``_review_type_for`` labels it "Guided repair + tiny practice")
    and ``_action_for_review`` makes that due item ``hands-on`` — the repair,
    collected twice. Silencing the due collector, as ``_plant_struggles`` does,
    hides the second copy.
    """
    from studyloop.history import observations

    real_due = decision._due_progress_candidates
    real_struggle = decision._struggle_candidates
    _patch_collectors(monkeypatch)
    monkeypatch.setattr(decision, "_due_progress_candidates", real_due)
    monkeypatch.setattr(decision, "_struggle_candidates", real_struggle)
    monkeypatch.setattr(observations, "rows", lambda conn: [dict(row) for row in rows])


def test_due_copy_of_a_live_struggle_defers_with_the_repair_at_low_energy(monkeypatch) -> None:
    """Rubric row 3b reading (f), re-read against the real collectors (owner walkthrough
    2026-09-20): the due-progress collector emits every ``struggling`` row as an undeferred
    ``hands-on`` "Guided repair + tiny practice" item — the same observations row the struggle
    collector defers — so against a real sessions.db the row-3 "no" was still the primary at
    low energy, with its own deferral printed beneath it, and the body double never appeared.
    A due row that *is* the repair of a live struggle carries the repair's demand and defers
    with it, named once; due recall is still never deferred; medium energy is untouched."""
    _row3_plan()
    _plant_struggles_for_both_collectors(monkeypatch, _struggle("window function", days_ago=3))

    low = build_now_plan(energy="low")

    assert low.primary.source == "body_double"
    assert not any(rec.concept == "window function" for rec in _all(low))
    assert [(d.concept, d.energy_demand) for d in low.energy_deferred_repairs] == [
        ("window function", "high")
    ]

    medium = build_now_plan(energy="medium")

    assert medium.primary.concept == "window function"
    assert medium.primary.action_type == "hands-on"
    assert medium.primary.source == "study_progress:sql:window function"
    assert medium.energy_deferred_repairs == ()


def test_due_copy_of_a_live_struggle_defers_with_no_plan_too(monkeypatch) -> None:
    """The no-plan floor (reading (d)) against both real collectors: the starter stands in
    and the live struggle is named once in the deferred list — not emitted as an undeferred
    hands-on primary by the due collector."""
    _plant_struggles_for_both_collectors(
        monkeypatch, _struggle("decorators", topic="python", days_ago=3)
    )

    low = build_now_plan(energy="low")

    assert low.primary.source == "starter"
    assert not any(rec.concept == "decorators" for rec in _all(low))
    assert [(d.plan_id, d.concept, d.energy_demand) for d in low.energy_deferred_repairs] == [
        (None, "decorators", "high")
    ]


def test_live_struggle_repair_defers_at_low_energy_like_new_work(monkeypatch) -> None:
    """Rule 3 extended (design §5, amendment 1 + 2): repair carries a demand of its own.

    ``struggling`` seen within 14 days is ``high`` (asks for 6/10); ``struggling``
    older than that, or a row whose only signal is a weak teach-back, is
    ``medium`` (4/10). Below the capability the repair is deferred like new
    milestone work — listed, not ranked — in its own additive key, plan-related
    or not; the milestone deferral beside it is untouched.
    """
    _row3_plan()
    _plant_struggles(
        monkeypatch,
        _struggle("window function", days_ago=3),  # live, plan-related → high
        _struggle("window frame", days_ago=20),  # old, plan-related → medium
        _struggle("decorators", topic="python", days_ago=1),  # live, unrelated → high
        _struggle("closures", topic="python", confidence="confident", days_ago=2, teachback=9),
    )

    low = build_now_plan(energy="low")

    deferred = {item.concept: item for item in low.energy_deferred_repairs}
    assert set(deferred) == {"window function", "window frame", "decorators", "closures"}
    assert not any(rec.concept in deferred for rec in _all(low)), "deferred repair is not ranked"

    live = deferred["window function"]
    assert isinstance(live, decision.DeferredRepair)
    assert (live.plan_id, live.plan_title, live.topic, live.confidence) == (
        "sql-windows",
        "SQL Windows",
        "sql",
        "struggling",
    )
    assert (live.energy_demand, live.required_capability, live.energy_capability) == ("high", 6, 3)
    assert "3/10" in live.reason and "6/10" in live.reason
    assert (
        deferred["window frame"].energy_demand,
        deferred["window frame"].required_capability,
    ) == (
        "medium",
        4,
    )
    assert deferred["closures"].energy_demand == "medium", (
        "a weak teach-back alone is medium demand"
    )
    assert (deferred["decorators"].plan_id, deferred["decorators"].plan_title) == (None, None)
    assert deferred["decorators"].energy_demand == "high"
    # The milestone deferral is what it was (rule 3's original half).
    assert [(d.plan_id, d.milestone_index) for d in low.energy_deferred] == [("sql-windows", 1)]

    payload = low.to_json_dict()
    assert [entry["concept"] for entry in payload["energy_deferred_repairs"]] == [
        item.concept for item in low.energy_deferred_repairs
    ]
    assert payload["energy_deferred_repairs"][0]["energy_demand"] in {"high", "medium"}

    # Medium energy (6/10) carries every demand class: nothing deferred, key absent.
    medium = build_now_plan(energy="medium")

    assert medium.energy_deferred_repairs == ()
    assert "energy_deferred_repairs" not in medium.to_json_dict()
    assert any(rec.concept == "window function" for rec in _all(medium))


def test_recovered_repair_stays_eligible_at_low_energy(monkeypatch) -> None:
    """A ``learning`` row is ``low`` demand — the gentle review "repair is cheaper than
    encoding" was always about — and stays eligible below the plan's floor with its
    plan-related ref. Due recall is unaffected whatever its confidence says."""
    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", confidence="learning", days_ago=2))

    low = build_now_plan(energy="low")

    assert low.primary.concept == "window function"
    assert low.primary.action_type == "teachback"
    assert low.primary.plan_refs == (PlanRef("sql-windows", None),)
    assert low.primary.metadata["energy_demand"] == "low"
    assert low.energy_deferred_repairs == ()
    assert not any(rec.source == "body_double" for rec in _all(low))
    assert [d.milestone_index for d in low.energy_deferred] == [1]

    # A recall-typed due item on a plan concept is never deferred, whatever its
    # metadata says about confidence, and nothing is synthesised beside it.
    # (Through the real collector a `struggling` row is never recall — it is the
    # hands-on "Guided repair" copy, deferred with the repair; see
    # test_due_copy_of_a_live_struggle_defers_with_the_repair_at_low_energy.)
    import dataclasses

    due = dataclasses.replace(
        _candidate("window frame", topic="sql", score=100),
        metadata={"confidence": "struggling", "days_ago": 6},
    )
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3), due=(due,))

    low = build_now_plan(energy="low")

    assert low.primary.concept == "window frame"
    assert low.primary.plan_refs == (PlanRef("sql-windows", None),)
    assert [d.concept for d in low.energy_deferred_repairs] == ["window function"]
    assert not any(rec.source == "body_double" for rec in _all(low))


def test_body_double_candidate_is_synthesised_when_nothing_plan_related_fits(monkeypatch) -> None:
    """Rubric row 3b's world: the plan's milestone is deferred and its only repair is a
    live struggle, so nothing plan-related fits low energy. The engine proposes sitting
    with the plan — a body-double session — naming what it stands in for, through the
    session door (amendment 3), never the least-bad task."""
    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))

    low = build_now_plan(energy="low")

    primary = low.primary
    assert primary.source == "body_double"
    assert primary.action_type == "conversation"
    assert primary.plan_refs == (PlanRef("sql-windows", None),)
    assert primary.evidence_command == 'studyloop study "SQL Windows" --mode co-study'
    assert "Frames" in primary.reason and "window function" in primary.reason
    assert low.starter is False
    assert low.alternates == []
    assert [d.concept for d in low.energy_deferred_repairs] == ["window function"]
    assert [d.milestone_index for d in low.energy_deferred] == [1]
    assert decision.BODY_DOUBLE_BASE_SCORE < decision.MILESTONE_BASE_SCORE

    golden_keys = list(json.loads(GOLDEN.read_text(encoding="utf-8")))
    payload = low.to_json_dict()
    assert list(payload) == [
        *golden_keys,
        "active_plans",
        "energy_deferred",
        "energy_deferred_repairs",
    ]
    assert payload["primary"]["source"] == "body_double"


def test_body_double_reason_leads_with_recorded_progress_and_describes_the_door_truthfully(
    monkeypatch,
) -> None:
    """Rubric-3b council (2026-09-20), applied: the framework's own rule is *never name a
    struggle without an adjacent strength* — the reason opens with the progress the plan
    document records (one milestone done here) before it names what is deferred. And the
    door is described by what the co-study persona guarantees — the learner drives, the
    companion stays quiet unless asked — not by a promise ("no new material, no repair")
    that nothing pins."""
    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))

    reason = build_now_plan(energy="low").primary.reason

    assert reason.startswith("1 of 2 milestones of SQL Windows done."), reason
    assert reason.index("done") < reason.index("window function"), "progress before the struggle"
    assert "you drive; the companion stays quiet unless you ask" in reason
    assert "no new material" not in reason and "no repair" not in reason


def test_body_double_reason_never_fabricates_progress(monkeypatch) -> None:
    """No milestone done → no progress sentence at all (never invent a strength)."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=5,
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _plant_struggles(monkeypatch, _struggle("window frame", days_ago=3))

    reason = build_now_plan(energy="low").primary.reason

    assert "milestones of SQL Windows done" not in reason and "0 of" not in reason
    assert reason.startswith("Nothing plan-related fits low energy today"), reason


def test_co_study_persona_pins_the_promise_the_body_double_reason_makes() -> None:
    """The reason says the companion stays quiet and the learner drives; the persona the
    door launches must say so too, or the reason is a promise about a door it does not
    control."""
    persona = (
        Path(__file__).resolve().parents[3] / "agents" / "shared" / "personas" / "co-study.md"
    ).read_text(encoding="utf-8")

    assert "The student drives" in persona
    assert "Stay quiet by default" in persona


def test_teach_back_protocol_carries_the_low_energy_guided_explanation_fallback() -> None:
    """Rubric row 3b reading (c) — owner verdict "yes, with a fallback" (2026-09-20): the
    micro teach-back is offered at low energy, and if the student cannot produce the one
    sentence the mentor moves to a guided explanation — not the four-round Stuck ladder
    first. The door's protocol must say so, or the yes is shipped without its condition."""
    protocol = (
        Path(__file__).resolve().parents[3] / "agents" / "shared" / "teach-back-protocol.md"
    ).read_text(encoding="utf-8")

    micro = protocol.split("### Micro Teach-Back", 1)[1].split("\n## ", 1)[0]
    assert "Low-energy fallback" in micro
    assert "guided explanation" in micro
    assert "not the four-round Stuck ladder" in micro


def test_body_double_is_a_proposal_not_a_filter(monkeypatch) -> None:
    """An unrelated real candidate still wins; the body-double proposal sits beneath it
    as an alternate, base score below any real candidate's."""
    _row3_plan()
    _plant_struggles(
        monkeypatch,
        _struggle("window function", days_ago=3),
        due=(_candidate("decorators", topic="python", score=100),),
    )

    low = build_now_plan(energy="low")

    assert low.primary.concept == "decorators"
    assert low.primary.plan_refs == ()
    assert [rec.source for rec in low.alternates] == ["body_double"]
    assert low.alternates[0].score < low.primary.score
    assert "Frames" in low.alternates[0].reason


def test_body_double_is_never_synthesised_for_an_unready_plan(monkeypatch) -> None:
    """An active-but-unready plan is matched but never synthesised (spec rule 8), and the
    body double is a synthesis: with only a husk active and nothing plan-related fitting,
    the engine proposes nothing to sit with — the warning already says repair it."""
    husk = StudyPlan(
        plan_id="husk",
        title="Husk",
        status="active",
        created="2026-08-01T00:00:00+00:00",
        updated="2026-09-01T00:00:00+00:00",
        topics=["sql"],
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    store.create_plan(husk)  # no mission, no success criteria: unready
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))

    low = build_now_plan(energy="low")

    assert not any(rec.source == "body_double" for rec in _all(low))
    assert [d.concept for d in low.energy_deferred_repairs] == ["window function"]
    assert low.starter is True
    assert any("husk" in w for w in low.warnings)

    # A ready plan beside the husk: the proposal names the ready one only; rule 7
    # may still attach a `(husk, None)` ref because the topics match.
    _row3_plan()

    low = build_now_plan(energy="low")

    assert low.primary.source == "body_double"
    assert low.primary.concept == "Sit with SQL Windows"
    assert PlanRef("sql-windows", None) in low.primary.plan_refs
    assert low.primary.evidence_command == 'studyloop study "SQL Windows" --mode co-study'
    assert "Husk" not in low.primary.reason


def test_body_double_never_appears_without_an_active_plan(monkeypatch) -> None:
    """No active plan, no plan to sit with: the deferral still happens (plan-independent,
    ``plan_id`` ``None``), the golden world stays untouched, and a non-active plan is
    not an active plan."""
    _plant_struggles(monkeypatch, _struggle("decorators", topic="python", days_ago=1))

    low = build_now_plan(energy="low")

    assert not any(rec.source == "body_double" for rec in _all(low))
    assert [(d.concept, d.plan_id, d.plan_title) for d in low.energy_deferred_repairs] == [
        ("decorators", None, None)
    ]
    # Every real candidate was deferred: the starter stands in, and says why.
    assert low.starter is True
    assert "defer" in low.primary.reason.lower()

    _plan("draft-plan", status="draft")

    low = build_now_plan(energy="low")

    assert not any(rec.source == "body_double" for rec in _all(low))
    assert "active_plans" not in low.to_json_dict()


def test_cli_now_and_recap_render_deferred_repairs_and_the_body_double_door(
    monkeypatch,
) -> None:
    """Amendment 2's "readable off the top" rule: each renderer gains one line per
    deferred repair, and a body-double primary shows its door, not "record evidence"."""
    from click.testing import CliRunner

    from studyloop.cli import cli
    from studyloop.learning import recap

    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))

    rich = CliRunner().invoke(cli, ["now", "--energy", "low"])
    as_json = CliRunner().invoke(cli, ["now", "--energy", "low", "--json"])

    assert rich.exit_code == 0, rich.output
    flat = " ".join(rich.output.split())
    assert "Deferred for energy" in flat and "Frames" in flat  # the milestone line stays
    assert "window function" in flat and "6/10" in flat  # …and the repair has its own line
    assert "Sit with the plan" in flat
    assert "--mode co-study" in flat
    assert "Record evidence" not in flat
    assert as_json.exit_code == 0, as_json.output
    payload = json.loads(as_json.output)
    assert payload["primary"]["source"] == "body_double"
    assert payload["energy_deferred_repairs"][0]["concept"] == "window function"
    assert payload["energy_deferred_repairs"][0]["required_capability"] == 6

    context = recap._plan_context(build_now_plan(energy="low"))

    assert "Frames" in context
    assert "window function" in context and "6 of 10" in context


@pytest.mark.parametrize(
    "title",
    [
        "SQL Windows",
        'SQL "Windows"',
        "SQL $(touch pwned) Windows",
        "SQL `touch pwned` Windows",
        "SQL $HOME Windows",
        "back\\slash Windows",
        "it's Windows",
    ],
)
def test_body_double_command_preserves_title_as_one_literal_shell_argument(
    monkeypatch, tmp_path: Path, title: str
) -> None:
    """Council review 7, F1 (astra 🔴): the command the engine *offers* must reach
    ``studyloop`` as one literal argument when pasted into a POSIX shell — no
    expansion, no substitution, no extra command. Proved with a real ``sh`` and a
    stub ``studyloop`` on PATH that records its argv."""
    import subprocess

    _plan(
        "hostile",
        title=title,
        energy_floor=5,
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _plant_struggles(monkeypatch, _struggle("window frame", days_ago=3))

    low = build_now_plan(energy="low")

    assert low.primary.source == "body_double"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "argv.txt"
    stub = bin_dir / "studyloop"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{argv_file}"\n', encoding="utf-8")
    stub.chmod(0o755)
    subprocess.run(
        ["/bin/sh", "-c", low.primary.evidence_command],
        check=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)},
        cwd=tmp_path,
        timeout=10,
    )

    assert argv_file.read_text(encoding="utf-8").split("\n")[:4] == [
        "study",
        title,
        "--mode",
        "co-study",
    ]
    assert not (tmp_path / "pwned").exists(), "the title's substitution must never run"


# --- Issue #30: the body double proposes one tiny, concrete first move ----------------
#
# Owner note recorded beside rubric row 3b (a) (2026-09-20): "the sit-with session
# must not be a blank page — the body double should propose one tiny, concrete first
# move on the deferred material (e.g. 'open the Frames lesson and read it, nothing
# more'). A goal-less session is the hardest ADHD start." The move is derived from
# facts the engine already holds and is PASSIVE — reading, never an exercise, never
# a Socratic round — because it must be consumable at the capability the day carries.
#
# A body double always has a deferred milestone to draw on: it is synthesised only
# when no plan-related candidate exists, and an eligible next milestone would have
# been synthesised as one (rule 7), so every matchable ready plan behind a body
# double has its next milestone in ``energy_deferred``. The issue's "deferred repair
# only" row is therefore unreachable and is not built (design, issue #30).


def test_body_double_carries_one_passive_first_move_on_the_deferred_milestone(
    monkeypatch,
) -> None:
    """Row 3's world: the move opens the deferred milestone's material and asks for
    reading only. It rides in the payload as ``metadata["first_move"]`` (additive,
    body-double only, so the no-plan golden is untouched) — and ONLY there (rubric
    3c (d), owner 2026-09-21): the reason explains the recommendation, the move is
    an action beside the door, and every renderer reads the field, so the sentence
    appears once on a 3/10 screen instead of closing the reason and then repeating
    as its own line. When the content index was searched and holds no lesson for
    the milestone's concepts (rubric 3c (c), owner 2026-09-21), the sentence names
    the milestone AND says why — the concept no indexed lesson mentions — so it
    carries information instead of vagueness, and the payload has no
    ``first_move_lesson_id``. On the owner's own vault this is exactly ``Frames``
    today."""
    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))
    monkeypatch.setattr(decision, "_resolve_lesson", lambda concepts: None)

    low = build_now_plan(energy="low")

    primary = low.primary
    assert primary.source == "body_double"
    move = primary.metadata["first_move"]
    assert move == (
        "Open your Frames material and read for ten minutes, nothing more — "
        "no indexed lesson mentions “window frame” yet."
    )
    assert primary.reason.endswith("the companion stays quiet unless you ask."), primary.reason
    assert str(move) not in primary.reason and "first move" not in primary.reason.lower(), (
        "rubric 3c (d): the move is an action beside the door, not part of the explanation"
    )
    for forbidden in ("exercise", "practice", "solve", "?"):
        assert forbidden not in move, f"a first move must be passive; found {forbidden!r}"
    assert primary.evidence_command == 'studyloop study "SQL Windows" --mode co-study', (
        "the door is unchanged"
    )
    assert "first_move_lesson_id" not in primary.metadata, "no lesson resolved, no id"
    payload = low.to_json_dict()
    assert payload["primary"]["metadata"]["first_move"] == move
    golden_keys = list(json.loads(GOLDEN.read_text(encoding="utf-8")))
    assert list(payload) == [
        *golden_keys,
        "active_plans",
        "energy_deferred",
        "energy_deferred_repairs",
    ], "the first move adds no top-level key"


def test_body_double_first_move_names_the_lesson_the_content_index_resolves(
    monkeypatch,
) -> None:
    """Rubric 3c (b) — owner: a deliberate lesson should always be the case; it stops
    decision fatigue. The move names the indexed lesson, and its id and title ride
    beside the sentence so a renderer can open it in StudyLoop's own frame. Rubric
    3c (c) bounds the search: the resolver is asked ONCE, with the deferred
    milestone's own concepts and nothing else — never the milestone's title, never
    the plan's topics. Rubric 3c (d2), owner 2026-09-21 — *"I would likely still
    open it in case there was some link being enforced"*: a named lesson carries
    implied authority, so the sentence states its EVIDENCE — the course the lesson
    belongs to and the concept the match rests on — and the link can be judged from
    the sentence instead of by opening the lesson."""
    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))
    seen: list[tuple[str, ...]] = []

    def resolve(concepts):
        seen.append(tuple(concepts))
        return (
            "ztm/advanced-sql/window-frames",
            "Window Frames and Ranges",
            "Advanced Sql",
            "window frame",
        )

    monkeypatch.setattr(decision, "_resolve_lesson", resolve)

    primary = build_now_plan(energy="low").primary

    assert primary.metadata["first_move"] == (
        "Open “Window Frames and Ranges” from Advanced Sql — the match is the phrase "
        "“window frame” — and read for ten minutes, nothing more."
    )
    assert primary.metadata["first_move_lesson_id"] == "ztm/advanced-sql/window-frames"
    assert primary.metadata["first_move_lesson_title"] == "Window Frames and Ranges"
    assert seen == [("window frame",)], "the milestone's own concepts, nothing else"


def test_body_double_first_move_shows_the_course_so_a_lexical_match_is_judgeable(
    monkeypatch,
) -> None:
    """Measured on the owner's vault 2026-09-21: a Python plan's milestone concept
    ``decorators`` FTS-resolves to *Decorators 29M* in *The Ultimate TypeScript* —
    the match is lexical, not topic-scoped. The owner's own answer to the (c)
    self-check (*"I would likely still open it in case there was some link that is
    being enforced"*) means that lesson would be OPENED, not just doubted. So the
    sentence names the course from the hit's own ``course_id`` — humanised exactly
    as the explorer's course list shows it — and says the match is the word: the
    "link" is a word match and nothing more, judgeable at a glance. Replays the
    vault at the explorer's own search function, through the real seam."""
    from studyloop.web.routes import explorer

    _plan(
        "python-patterns",
        title="Python Patterns",
        energy_floor=5,
        milestones=[
            Milestone(title="Closures", done=True, concepts=["closure"]),
            Milestone(title="Decorators", concepts=["decorators"]),
        ],
    )
    _plant_struggles(monkeypatch, _struggle("closure", days_ago=3))

    def vault(db_path, base, q, limit):
        if q == "decorators":
            return [
                {
                    "lesson_id": "udemy/the-ultimate-typescript/decorators-29m",
                    "course_id": "udemy/the-ultimate-typescript",
                    "provider": "udemy",
                    "title": "Decorators 29M",
                }
            ]
        return []

    monkeypatch.setattr(explorer, "_run_fts_search", vault)

    primary = build_now_plan(energy="low").primary

    assert primary.source == "body_double"
    assert primary.metadata["first_move"] == (
        "Open “Decorators 29M” from The Ultimate Typescript — the match is the word "
        "“decorators” — and read for ten minutes, nothing more."
    )
    lesson_id = "udemy/the-ultimate-typescript/decorators-29m"
    assert primary.metadata["first_move_lesson_id"] == lesson_id
    assert primary.metadata["first_move_lesson_title"] == "Decorators 29M"


def test_body_double_first_move_never_names_a_lesson_from_the_title_or_the_topic(
    monkeypatch,
) -> None:
    """Rubric 3c (c), measured on the owner's real vault 2026-09-21: a chain that fell
    back to the milestone's title and the plan's topic always named a lesson — the
    WRONG one. ``Frames`` FTS-hit a PySpark data-frames lab; ``sql`` hit an SQL
    bootcamp introduction; only the sibling milestone's concept found the lesson
    where window frames are taught, and only because this plan's two milestones
    share one lesson. A deliberate-but-wrong lesson spends a 3/10 day's one action
    on the wrong material and looks certain doing it — worse than vagueness. So the
    explorer's search is asked the deferred milestone's concepts only, and when they
    match nothing the move names the milestone and says so. Replays that vault at
    the explorer's own search function, through the real seam."""
    from studyloop.web.routes import explorer

    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))
    asked: list[str] = []

    def real_vault(db_path, base, q, limit):
        asked.append(q)
        return {
            "Frames": [{"lesson_id": "pyspark/405-lab", "title": "405 Lab Execute PySpark"}],
            "sql": [{"lesson_id": "sql/ztm-intro", "title": "ZTM Complete SQL Bootcamp"}],
            "window function": [{"lesson_id": "sql/advanced-sql-4h", "title": "Advanced Sql 4H"}],
        }.get(q, [])

    monkeypatch.setattr(explorer, "_run_fts_search", real_vault)

    low = build_now_plan(energy="low")
    primary = low.primary

    assert asked == ["window frame"], "the deferred milestone's concepts only"
    assert primary.metadata["first_move"] == (
        "Open your Frames material and read for ten minutes, nothing more — "
        "no indexed lesson mentions “window frame” yet."
    )
    assert "first_move_lesson_id" not in primary.metadata
    serialised = json.dumps(low.to_json_dict()["primary"], ensure_ascii=False)
    assert "PySpark" not in serialised and "Bootcamp" not in serialised, (
        "neither wrong lesson appears anywhere in the recommendation"
    )


def test_body_double_first_move_says_when_the_milestone_names_no_concept(
    monkeypatch,
) -> None:
    """A milestone with no ``concepts`` gives the index nothing to look up: the
    resolver is not asked (asking it with the title is the rejected chain), and the
    sentence says what would fix it — a concept name on the milestone, not a better
    search."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=5,
        milestones=[
            Milestone(title="Window basics", done=True, concepts=["window function"]),
            Milestone(title="Frames"),
        ],
    )
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))

    def must_not_be_asked(concepts):
        raise AssertionError(f"resolver asked with {concepts!r}")

    monkeypatch.setattr(decision, "_resolve_lesson", must_not_be_asked)

    primary = build_now_plan(energy="low").primary

    assert primary.source == "body_double"
    assert primary.metadata["first_move"] == (
        "Open your Frames material and read for ten minutes, nothing more — "
        "this milestone names no concept to look up yet."
    )
    assert "first_move_lesson_id" not in primary.metadata


def test_body_double_first_move_names_every_unmatched_concept(monkeypatch) -> None:
    """Two named concepts, none matched: both are named in the why-clause, so the
    learner sees exactly which words the index lacks."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=5,
        milestones=[
            Milestone(title="Window basics", done=True, concepts=["window function"]),
            Milestone(title="Frames", concepts=["window frame", "frame clause"]),
        ],
    )
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))
    monkeypatch.setattr(decision, "_resolve_lesson", lambda concepts: None)

    move = str(build_now_plan(energy="low").primary.metadata["first_move"])

    assert move.endswith("— no indexed lesson mentions “window frame” or “frame clause” yet.")


def test_resolve_lesson_asks_one_query_per_concept_in_order_and_returns_the_first_hit(
    monkeypatch,
) -> None:
    """The seam itself: one FTS query per concept, in the order given, stopping at
    the first hit; the hit is ``(lesson_id, title, course, concept)`` — the concept that
    matched, not the first asked — with the course the
    hit's own ``course_id`` humanised as the explorer's course list shows it; a
    searched miss is ``None``. A hit without a course or a title is skipped, never
    named — the sentence states its evidence or names nothing (rubric 3c (d2)).
    An index that cannot be read is NOT a searched miss — the seam lets that raise
    so the caller can decline to claim "no indexed lesson mentions X" about an
    index it never read. Faked at the explorer's own search function so no
    content index is needed."""
    from studyloop.web.routes import explorer

    asked: list[str] = []

    def fake_search(db_path, base, q, limit):
        asked.append(q)
        if q == "frame clause":
            return [
                {
                    "lesson_id": "ztm/advanced-sql-4h/frames",
                    "course_id": "ztm/advanced-sql-4h",
                    "provider": "ztm",
                    "title": "Advanced Sql 4H",
                }
            ]
        if q == "orphan":
            return [{"lesson_id": "x/y/z", "course_id": "", "provider": "x", "title": "Orphan"}]
        return []

    monkeypatch.setattr(explorer, "_run_fts_search", fake_search)

    hit = decision._resolve_lesson(("window frame", "frame clause", "range"))

    assert hit == (
        "ztm/advanced-sql-4h/frames",
        "Advanced Sql 4H",
        "Advanced Sql 4H",
        "frame clause",
    ), "the concept that hit, not the first one asked"
    assert asked == ["window frame", "frame clause"], "stops at the first hit"
    assert decision._resolve_lesson(("nothing", "matches")) is None
    assert asked[-2:] == ["nothing", "matches"]
    assert decision._resolve_lesson(("orphan",)) is None, "no course, no lesson named"

    def unreadable(db_path, base, q, limit):
        raise RuntimeError("fts index unreadable")

    monkeypatch.setattr(explorer, "_run_fts_search", unreadable)
    with pytest.raises(RuntimeError):
        decision._resolve_lesson(("window frame",))


def test_body_double_first_move_survives_a_broken_content_index(monkeypatch) -> None:
    """The content index is a refinement, never a dependency: when the lookup raises,
    the move still names the milestone and ``now`` still answers. It makes NO claim
    about an index it could not read — "no indexed lesson mentions … yet" is a
    verified statement or it is not said."""
    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))

    def explode(concepts):
        raise RuntimeError("fts index unreadable")

    monkeypatch.setattr(decision, "_resolve_lesson", explode)

    low = build_now_plan(energy="low")

    assert low.primary.source == "body_double"
    assert low.primary.metadata["first_move"] == (
        "Open your Frames material and read for ten minutes, nothing more."
    )
    assert "first_move_lesson_id" not in low.primary.metadata
    assert not any("fts" in w for w in low.warnings), "a failed refinement is not a warning"


def test_cli_now_prints_the_first_move_beneath_the_sit_with_door(monkeypatch) -> None:
    """The CLI shows the move as its own line under the door, after the door, so the
    learner reads where to sit before what to open — the why-clause included — and
    that line is the ONLY place the sentence appears on the panel (rubric 3c (d)):
    the ``Why:`` paragraph explains the recommendation and does not repeat it."""
    from click.testing import CliRunner

    from studyloop.cli import cli

    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))
    monkeypatch.setattr(decision, "_resolve_lesson", lambda concepts: None)

    rich = CliRunner().invoke(cli, ["now", "--energy", "low"])

    assert rich.exit_code == 0, rich.output
    assert "Sit with the plan:" in rich.output
    assert "First move:" in rich.output
    assert rich.output.index("Sit with the plan:") < rich.output.index("First move:")
    # The panel wraps at the terminal width; read it as one line, borders stripped.
    flat = " ".join(rich.output.replace("│", " ").split())
    assert (
        "First move: Open your Frames material and read for ten minutes, nothing more — "
        "no indexed lesson mentions “window frame” yet." in flat
    ), flat
    assert flat.count("Open your Frames material") == 1, (
        "the sentence appears once — beside the door, not also closing the Why: paragraph"
    )


def test_cli_milestone_deferral_does_not_promise_live_repair(monkeypatch) -> None:
    """Council review 7, F5 (astra 🟡): in row 3b's own fixture the milestone line used to end
    "Plan-related review and repair stay available" one line above the line saying the
    repair is deferred. Both the engine's reason and the CLI's sentence now promise only
    what rule 3 still guarantees — due recall and gentle review — asserted as whole
    sentences, not by the presence of a word."""
    from click.testing import CliRunner

    from studyloop.cli import cli

    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3))

    low = build_now_plan(energy="low")
    rich = CliRunner().invoke(cli, ["now", "--energy", "low"])

    assert rich.exit_code == 0, rich.output
    flat = " ".join(rich.output.split())
    assert (
        "Deferred for energy: SQL Windows — milestone 2 “Frames” needs energy 5/10; "
        "low energy carries 3/10. Due recall and gentle review stay available."
    ) in flat
    assert (
        "Deferred for energy: SQL Windows — repairing “window function” (struggling) asks for "
        "6/10; low energy carries 3/10. Due recall and gentle review stay available."
    ) in flat
    assert "repair stay available" not in flat
    assert "repair stay available" not in low.energy_deferred[0].reason
    assert low.energy_deferred[0].reason.endswith("due recall and gentle review stay available")


# --- Council review 7 — pins the seats asked for -----------------------------------


def _unrelated_trio() -> tuple[_Candidate, ...]:
    """A due recall, a conversation and a hands-on task, none plan-related."""
    return (
        _candidate("due", topic="python", action_type="recall", score=100),
        _candidate("talk", topic="python", action_type="conversation", score=58),
        _candidate("exercise", topic="python", action_type="hands-on", score=48),
    )


@pytest.mark.parametrize("modality", ["recall", "conversation"])
def test_body_double_ordering_after_adjustments_follows_the_energy_rule(
    monkeypatch, modality
) -> None:
    """Review 7, F2 (astra 🔴 / qwen 🔴 / grok 💡 — arbitrated): the proposal's *base* is
    below every real candidate's, and the day's adjustments then apply to it as to any
    candidate. So a due recall and a conversation outrank it at every modality, while a
    hands-on task the low-energy rule penalises (48 - 14 = 34) sits beneath it (30 + 12 =
    42): the energy rule, not a filter — nothing is removed from the ranking, and the
    primary is never the proposal while any due or conversation candidate exists."""
    _row3_plan()
    _plant_struggles(monkeypatch, _struggle("window function", days_ago=3), due=_unrelated_trio())

    low = build_now_plan(energy="low", modality=modality)  # type: ignore[arg-type]

    assert [rec.concept for rec in _all(low)] == ["due", "talk", "Sit with SQL Windows"]
    assert low.alternates[1].source == "body_double"
    assert low.primary.score > low.alternates[0].score > low.alternates[1].score
    real_bases = (decision.MILESTONE_BASE_SCORE, 48, 52, 58, 70, 82, 96, 100)
    assert all(base > decision.BODY_DOUBLE_BASE_SCORE for base in real_bases)


@pytest.mark.parametrize(
    ("confidence", "energy"),
    [("learning", "low"), ("struggling", "medium")],
)
def test_no_plan_eligible_repair_exposes_demand_without_deferral(
    monkeypatch, confidence, energy
) -> None:
    """Review 7, F3 (astra 🟡): the plan-independent changes are exactly two — every
    struggle-collector candidate carries ``metadata.energy_demand`` at every energy, and
    repair above its demand is deferred. An eligible repair with no plan is ranked as
    before, carries the demand, defers nothing and proposes nothing."""
    _plant_struggles(monkeypatch, _struggle("decorators", topic="python", confidence=confidence))

    plan = build_now_plan(energy=energy)  # type: ignore[arg-type]

    assert plan.primary.concept == "decorators"
    assert plan.primary.metadata["energy_demand"] == ("low" if confidence == "learning" else "high")
    assert plan.energy_deferred_repairs == ()
    payload = plan.to_json_dict()
    assert "energy_deferred_repairs" not in payload and "active_plans" not in payload
    assert not any(rec.source == "body_double" for rec in _all(plan))


def test_energy_demand_recency_boundaries_and_unknown_dates(monkeypatch) -> None:
    """Review 7, F4 / grok 🔵: exactly 14 days is still live (high); 15 is medium; a null
    or unparseable ``last_seen`` on a struggling row is read as live. (A row with no
    ``last_seen`` key at all cannot reach the derivation: the collector's own sort reads
    the key first, and the projection always supplies it.)"""
    from studyloop.history import observations

    rows = [
        _struggle("on the day", days_ago=14),
        _struggle("day after", days_ago=15),
        {**_struggle("garbled"), "last_seen": "not-a-date"},
        {**_struggle("missing"), "last_seen": None},
    ]
    _plant_struggles(monkeypatch)
    monkeypatch.setattr(observations, "rows", lambda conn: [dict(r) for r in rows])

    low = build_now_plan(energy="low")

    demand = {d.concept: d.energy_demand for d in low.energy_deferred_repairs}
    assert demand == {
        "on the day": "high",
        "day after": "medium",
        "garbled": "high",
        "missing": "high",
    }


def test_energy_demand_confidence_and_teachback_precedence(monkeypatch) -> None:
    """Review 7, F4: ``learning`` is low demand even with a weak teach-back (eligible at
    low energy); an old ``struggling`` row with a weak teach-back stays medium."""
    _plant_struggles(
        monkeypatch,
        _struggle("gentle", confidence="learning", days_ago=2, teachback=9),
        _struggle("stale", days_ago=20, teachback=9),
    )

    low = build_now_plan(energy="low")

    assert low.primary.concept == "gentle"
    assert low.primary.metadata["energy_demand"] == "low"
    assert [(d.concept, d.energy_demand) for d in low.energy_deferred_repairs] == [
        ("stale", "medium")
    ]


def test_low_demand_teachback_door_is_the_micro_teach_back(monkeypatch) -> None:
    """Rubric row 3b reading (c), defect 1 (owner walkthrough 2026-09-20): demand ``low``
    (0/10) was justified by the protocol's *micro* teach-back — "in one sentence, explain
    [concept]", two dimensions scored — yet the door named ``--type structured``, the
    15-minute five-dimension review. The door must be the form the demand class stands
    on: ``micro`` for ``low``; a weak-teach-back row (``medium``) keeps ``structured``."""
    _plant_struggles(
        monkeypatch,
        _struggle("window function", confidence="learning", days_ago=2),
        _struggle("weak", topic="python", confidence="confident", days_ago=20, teachback=9),
    )

    high = build_now_plan(energy="high")

    doors = {rec.concept: rec for rec in _all(high)}
    gentle, weak = doors["window function"], doors["weak"]
    assert gentle.action_type == weak.action_type == "teachback"
    assert gentle.metadata["energy_demand"] == "low"
    assert weak.metadata["energy_demand"] == "medium"
    assert gentle.evidence_command == (
        'studyloop teachback "window function" -t "sql" --score "3,3,3,3,3" --type micro'
    )
    assert weak.evidence_command == (
        'studyloop teachback "weak" -t "python" --score "3,3,3,3,3" --type structured'
    )


def test_learning_row_reason_is_a_gentle_review_not_a_repair(monkeypatch) -> None:
    """Rubric row 3b reading (c), defect 2 (owner walkthrough 2026-09-20): design §5 calls a
    ``learning`` row the *gentle review* that stays eligible at low energy, but its reason
    read "repair now while the signal is fresh" — on a low-energy screen that word
    contradicts the deferred-repair line printed beside it. The learning row's reason
    names the gentle review and its one-sentence door; a live struggle's reason is
    untouched."""
    _plant_struggles(
        monkeypatch,
        _struggle("window function", confidence="learning", days_ago=2, teachback=11),
        _struggle("decorators", topic="python", days_ago=1),
    )

    low = build_now_plan(energy="low")

    assert low.primary.concept == "window function"
    assert low.primary.reason == (
        "Recorded as learning; a gentle review keeps it fresh — one sentence, in your own "
        "words; last teach-back score 11/20"
    )
    assert "repair" not in low.primary.reason
    [deferred] = low.energy_deferred_repairs
    assert deferred.concept == "decorators"
    assert "repairing 'decorators'" in deferred.reason

    high = build_now_plan(energy="high")

    live = next(rec for rec in _all(high) if rec.concept == "decorators")
    assert live.reason == "Recorded as struggling; repair now while the signal is fresh"


@pytest.mark.parametrize(
    ("energy", "deferred"),
    [("low", {"live", "stale"}), ("medium", set()), ("high", set())],
)
def test_repair_demand_capability_matrix(monkeypatch, energy, deferred) -> None:
    """Review 7, F4: low (3) rejects medium and high demand and carries low; medium (6)
    and high (10) carry every class."""
    _plant_struggles(
        monkeypatch,
        _struggle("live", days_ago=1),
        _struggle("stale", days_ago=30),
        _struggle("gentle", confidence="learning"),
    )

    plan = build_now_plan(energy=energy)  # type: ignore[arg-type]

    assert {d.concept for d in plan.energy_deferred_repairs} == deferred
    ranked = {rec.concept for rec in _all(plan)}
    assert "gentle" in ranked
    assert ranked.isdisjoint(deferred)


def test_deferred_repair_allows_only_eligible_milestone_conversation(monkeypatch) -> None:
    """Review 7, F4 / grok 🔵 (design §5 decision 5): when the deferred live struggle was the
    only representative of an *eligible* next milestone (floor 3 at low energy), rule 6
    synthesises that milestone's conversation — not another hands-on repair, and not a
    body double, since the plan is now represented."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=3,
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _plant_struggles(monkeypatch, _struggle("window frame", days_ago=2))

    low = build_now_plan(energy="low")

    assert low.primary.source == "study_plan:sql-windows:0"
    assert low.primary.action_type == "conversation"
    assert low.primary.plan_refs == (PlanRef("sql-windows", 0),)
    assert [d.concept for d in low.energy_deferred_repairs] == ["window frame"]
    assert not any(rec.source == "body_double" for rec in _all(low))
    assert not any(rec.action_type == "hands-on" for rec in _all(low))
    assert low.energy_deferred == ()


def test_body_double_two_ready_plans_has_deterministic_context(monkeypatch) -> None:
    """Review 7, F4 / grok 🔵: two ready plans, both below the floor, both with live
    struggles → one proposal, refs in plan order (rule 6: most recent ``updated`` first),
    both deferred milestones and both repairs named, the door on the first plan."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        topics=["sql"],
        energy_floor=5,
        updated="2026-09-02T00:00:00+00:00",
        milestones=[Milestone(title="Frames", concepts=["window frame"])],
    )
    _plan(
        "py-decorators",
        title="Python Decorators",
        topics=["python"],
        energy_floor=5,
        updated="2026-09-01T00:00:00+00:00",
        milestones=[Milestone(title="Closures", concepts=["closure"])],
    )
    _plant_struggles(
        monkeypatch,
        _struggle("window function", topic="sql", days_ago=3),
        _struggle("decorators", topic="python", days_ago=2),
    )

    low = build_now_plan(energy="low")

    assert [rec.source for rec in _all(low)] == ["body_double"]
    proposal = low.primary
    assert proposal.concept == "Sit with your plans"
    assert proposal.plan_refs == (PlanRef("sql-windows", None), PlanRef("py-decorators", None))
    assert proposal.evidence_command == 'studyloop study "SQL Windows" --mode co-study'
    for named in (
        "Frames",
        "Closures",
        "window function",
        "decorators",
        "SQL Windows and Python Decorators",
    ):
        assert named in proposal.reason
    assert {d.plan_id for d in low.energy_deferred} == {"sql-windows", "py-decorators"}
    assert {d.plan_id for d in low.energy_deferred_repairs} == {"sql-windows", "py-decorators"}


# ---------------------------------------------------------------------------
# Rubric 3c (e), owner 2026-09-21: "no, offer the move at medium energy too" —
# built as (e1) the WARM-UP INTO THE PRIMARY, on the primary's own material
# (the owner took that steer over the passive alternative beside the primary).
# The low-energy move is the sit-with's whole action and ends "nothing more";
# the warm-up lowers the first step of a task the day CAN carry and ends
# "then start …", so the card never tells the learner two contradictory
# things. It attaches only to a plan-related ACTIVE primary (hands-on,
# conversation, teachback): never to recall — reading the lesson before a
# retrieval test defeats the test (row 3b (b): familiar recall leads as it
# is) — never to the body double (it has its own move), never in the no-plan
# world (the golden stays byte-identical).
# ---------------------------------------------------------------------------


def test_a_plan_related_repair_at_medium_energy_carries_a_warm_up_on_its_own_material(
    monkeypatch,
) -> None:
    """Row 3's world at medium (6/10), both collectors live: the primary is the
    ``window function`` repair. It now carries one first move on ITS OWN material —
    the resolver is asked the repair's concept and nothing else — worded as a ramp
    into the repair, with the evidence sentence of (d2) and the lesson id/title beside
    it so the Today card's Open-the-lesson control follows. The reason is untouched
    (the move lives in ``metadata.first_move`` only, (d1)); no body double appears."""
    _row3_plan()
    _plant_struggles_for_both_collectors(monkeypatch, _struggle("window function", days_ago=3))
    seen: list[tuple[str, ...]] = []

    def resolve(concepts):
        seen.append(tuple(concepts))
        return (
            "ztm/complete-sql-bootcamp/advanced-sql-4h",
            "Advanced Sql 4H",
            "Complete Sql Databases Bootcamp",
            "window function",
        )

    monkeypatch.setattr(decision, "_resolve_lesson", resolve)

    medium = build_now_plan(energy="medium")

    primary = medium.primary
    assert primary.concept == "window function" and primary.action_type == "hands-on"
    assert primary.metadata["first_move"] == (
        "Open “Advanced Sql 4H” from Complete Sql Databases Bootcamp — the match is the "
        "phrase “window function” — and read for ten minutes, then start the repair."
    )
    assert primary.metadata["first_move_lesson_id"] == ("ztm/complete-sql-bootcamp/advanced-sql-4h")
    assert primary.metadata["first_move_lesson_title"] == "Advanced Sql 4H"
    assert seen == [("window function",)], "the primary's own concept, nothing else"
    assert primary.reason.startswith("Guided repair + tiny practice"), primary.reason
    assert "first move" not in primary.reason.lower()
    assert "Open “Advanced Sql 4H”" not in primary.reason, "(d1): the move is not in the reason"
    assert not any(rec.source == "body_double" for rec in _all(medium))
    payload = medium.to_json_dict()
    golden_keys = list(json.loads(GOLDEN.read_text(encoding="utf-8")))
    # Nothing is deferred at medium, so the two energy_deferred* keys are absent
    # (omitted when empty); the plans key is the only addition to the golden's shape.
    assert list(payload) == [*golden_keys, "active_plans"], "the warm-up adds no top-level key"


def test_a_plan_milestone_primary_carries_a_warm_up_on_the_milestone_s_concepts(
    monkeypatch,
) -> None:
    """When the primary is the plan's next milestone (rule 6's synthesised candidate,
    eligible at medium), the resolver is asked that milestone's own concepts — all of
    them, in order — and the ramp ends "then start the milestone"."""
    _plan(
        "sql-windows",
        title="SQL Windows",
        energy_floor=5,
        milestones=[
            Milestone(title="Window basics", done=True, concepts=["window function"]),
            Milestone(title="Frames", concepts=["window frame", "frame clause"]),
        ],
    )
    _patch_collectors(monkeypatch)
    seen: list[tuple[str, ...]] = []

    def resolve(concepts):
        seen.append(tuple(concepts))
        return ("ztm/advanced-sql/window-frames", "Window Frames", "Advanced Sql", "frame clause")

    monkeypatch.setattr(decision, "_resolve_lesson", resolve)

    primary = build_now_plan(energy="medium").primary

    assert primary.source == "study_plan:sql-windows:1"
    assert primary.metadata["first_move"] == (
        "Open “Window Frames” from Advanced Sql — the match is the phrase “frame clause” — "
        "and read for ten minutes, then start the milestone."
    )
    assert primary.metadata["first_move_lesson_id"] == "ztm/advanced-sql/window-frames"
    assert seen == [("window frame", "frame clause")]


def test_the_warm_up_names_the_material_and_says_why_when_nothing_is_indexed(
    monkeypatch,
) -> None:
    """(c)'s honesty carries over: with no indexed lesson the ramp names the material
    (the repair's concept) and says which concept the index lacks; no lesson id, so no
    Open-the-lesson control. A resolver that cannot read the index gets the plain
    ramp with no claim about an index never consulted."""
    _row3_plan()
    _plant_struggles_for_both_collectors(monkeypatch, _struggle("window function", days_ago=3))
    monkeypatch.setattr(decision, "_resolve_lesson", lambda concepts: None)

    primary = build_now_plan(energy="medium").primary

    assert primary.metadata["first_move"] == (
        "Open your “window function” material and read for ten minutes, then start the "
        "repair — no indexed lesson mentions “window function” yet."
    )
    assert "first_move_lesson_id" not in primary.metadata

    def explode(concepts):
        raise RuntimeError("index unreadable")

    monkeypatch.setattr(decision, "_resolve_lesson", explode)

    primary = build_now_plan(energy="medium").primary

    assert primary.metadata["first_move"] == (
        "Open your “window function” material and read for ten minutes, then start the repair."
    )
    assert not any("index" in w for w in build_now_plan(energy="medium").warnings)


def test_no_warm_up_on_recall_or_without_a_plan_or_off_the_plan(monkeypatch) -> None:
    """The warm-up is a property of a plan-related ACTIVE recommendation and nothing
    else: a plan-related recall carries none and the resolver is not asked (reading
    the lesson before a retrieval test defeats the test); an active primary unrelated
    to any plan carries none; the no-plan world is byte-identical to the golden."""

    def must_not_be_asked(concepts):
        raise AssertionError(f"resolver asked with {concepts!r}")

    monkeypatch.setattr(decision, "_resolve_lesson", must_not_be_asked)

    # No plan at all: the golden world.
    _patch_collectors(monkeypatch)
    plan = build_now_plan(energy="medium")
    assert "first_move" not in plan.primary.metadata
    assert serialise(plan) == GOLDEN.read_bytes(), "the no-plan golden is untouched"

    # A plan-related recall as primary.
    _row3_plan()
    _patch_collectors(
        monkeypatch, _candidate("window function", topic="sql", action_type="recall", score=200)
    )
    recall = build_now_plan(energy="medium").primary
    assert recall.action_type == "recall" and recall.plan_refs, "precondition: plan-related recall"
    assert "first_move" not in recall.metadata

    # An active primary that matches no plan.
    _patch_collectors(
        monkeypatch, _candidate("decorators", topic="python", action_type="hands-on", score=200)
    )
    unrelated = build_now_plan(energy="medium").primary
    assert unrelated.concept == "decorators" and not unrelated.plan_refs
    assert "first_move" not in unrelated.metadata


def test_a_plan_related_active_item_that_is_neither_repair_nor_milestone_ramps_by_concept(
    monkeypatch,
) -> None:
    """The third tail: a plan-related teach-back (or practice) is active but neither a
    repair (no ``energy_demand``) nor the plan's next milestone, so the ramp names what
    the card names — "then start on “<concept>”" — and asks the resolver its concept."""
    _row3_plan()
    _patch_collectors(
        monkeypatch,
        _candidate("window function", topic="sql", action_type="teachback", score=200),
    )
    seen: list[tuple[str, ...]] = []

    def resolve(concepts):
        seen.append(tuple(concepts))
        return None

    monkeypatch.setattr(decision, "_resolve_lesson", resolve)

    primary = build_now_plan(energy="medium").primary

    assert primary.action_type == "teachback" and primary.plan_refs
    assert primary.metadata["first_move"] == (
        "Open your “window function” material and read for ten minutes, then start on "
        "“window function” — no indexed lesson mentions “window function” yet."
    )
    assert seen == [("window function",)]


def test_cli_now_prints_the_warm_up_beneath_the_evidence_door_at_medium_energy(
    monkeypatch,
) -> None:
    """At medium the door is ``Record evidence:``; the ``First move:`` line sits beneath
    it, once, exactly as it sits beneath ``Sit with the plan:`` at low — the CLI keys
    on ``metadata.first_move``, not on the body double."""
    from click.testing import CliRunner

    from studyloop.cli import cli

    _row3_plan()
    _plant_struggles_for_both_collectors(monkeypatch, _struggle("window function", days_ago=3))
    monkeypatch.setattr(decision, "_resolve_lesson", lambda concepts: None)

    rich = CliRunner().invoke(cli, ["now", "--energy", "medium"])

    assert rich.exit_code == 0, rich.output
    assert "Record evidence:" in rich.output
    assert "First move:" in rich.output
    assert rich.output.index("Record evidence:") < rich.output.index("First move:")
    flat = " ".join(rich.output.replace("│", " ").split())
    assert (
        "First move: Open your “window function” material and read for ten minutes, then "
        "start the repair — no indexed lesson mentions “window function” yet." in flat
    ), flat
    assert flat.count("Open your “window function” material") == 1


# ---------------------------------------------------------------------------
# Council review 8 (2026-09-21), accepted findings on the engine.
# ---------------------------------------------------------------------------


def test_a_concept_too_short_to_search_is_not_reported_as_a_searched_miss(monkeypatch) -> None:
    """Review 8, astra F3 (🟡) — the explorer's search refuses queries under two
    characters, and the seam skipped them silently, so a milestone whose concept is
    ``C`` or ``R`` was told "no indexed lesson mentions “C” yet" about a search that
    never ran. ``None`` must stay a SEARCHED miss: unsearchable concepts are named
    as too short, and only searched concepts are named in a miss."""
    _plan(
        "systems-c",
        title="Systems C",
        topics=["c"],
        energy_floor=5,
        milestones=[Milestone(title="Pointers", concepts=["C"])],
    )
    _plant_struggles(monkeypatch)
    asked: list[tuple[str, ...]] = []

    def resolve(concepts):
        asked.append(tuple(concepts))
        return None

    monkeypatch.setattr(decision, "_resolve_lesson", resolve)

    primary = build_now_plan(energy="low").primary

    assert primary.source == "body_double"
    assert primary.metadata["first_move"] == (
        "Open your Pointers material and read for ten minutes, nothing more — "
        "“C” is too short for the index to look up."
    )
    assert asked == [], "an unsearchable concept is not sent to the resolver"


def test_a_miss_names_only_the_concepts_that_were_searched(monkeypatch) -> None:
    """Mixed concepts: the searchable one is searched and named in the miss; the
    too-short one is never claimed as searched (review 8, astra F3)."""
    _plan(
        "systems-c-mixed",
        title="Systems C",
        topics=["c"],
        energy_floor=5,
        milestones=[Milestone(title="Pointers", concepts=["C", "pointer arithmetic"])],
    )
    _plant_struggles(monkeypatch)
    asked: list[tuple[str, ...]] = []

    def resolve(concepts):
        asked.append(tuple(concepts))
        return None

    monkeypatch.setattr(decision, "_resolve_lesson", resolve)

    primary = build_now_plan(energy="low").primary

    assert primary.metadata["first_move"] == (
        "Open your Pointers material and read for ten minutes, nothing more — "
        "no indexed lesson mentions “pointer arithmetic” yet."
    )
    assert asked == [("pointer arithmetic",)]


def test_resolve_lesson_skips_a_malformed_top_row_and_names_the_well_formed_hit_beneath_it(
    monkeypatch,
) -> None:
    """Review 8, grok 🔵 / astra refutation 3 — the seam fetched ONE row per concept
    and skipped the concept when that row lacked its course or title, so a malformed
    top row hid a well-formed lesson ranked beneath it. "A hit lacking its course or
    its title SHALL be skipped" means skip the ROW; the first well-formed hit wins."""
    from studyloop.web.routes import explorer

    limits: list[int] = []

    def fake_search(db_path, base, q, limit):
        limits.append(limit)
        return [
            {"lesson_id": "x/y/z", "course_id": "", "provider": "x", "title": "Orphan"},
            {
                "lesson_id": "ztm/advanced-sql-4h/frames",
                "course_id": "ztm/advanced-sql-4h",
                "provider": "ztm",
                "title": "Advanced Sql 4H",
            },
        ]

    monkeypatch.setattr(explorer, "_run_fts_search", fake_search)

    hit = decision._resolve_lesson(("window frame",))

    assert hit == (
        "ztm/advanced-sql-4h/frames",
        "Advanced Sql 4H",
        "Advanced Sql 4H",
        "window frame",
    )
    assert limits and limits[0] >= 2, "more than one row must be fetched for a row to be skipped"
