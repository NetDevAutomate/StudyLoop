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


def test_evaluate_record_with_both_sinks_failed_is_not_called_partial(runner, monkeypatch) -> None:
    """Council review 2, GPT Astra F9: when neither sink saved, "partially
    recorded" is a lie of the same shape Bug B was. The evaluation still
    succeeded (exit 0) and both sinks are named, but the headline is "not
    recorded"."""
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    monkeypatch.setattr(index_module, "record_checkpoint", lambda evaluation, *, study_id="": False)

    def refuse_write(plan, **kwargs):
        msg = "read-only file system"
        raise OSError(msg)

    monkeypatch.setattr(store, "save_plan", refuse_write)

    result = runner.invoke(cli, ["plan", "evaluate", "glue-etl", "--record"])

    assert result.exit_code == 0, result.output
    clean = _ANSI.sub("", result.output)
    assert "Plan checkpoint" in clean
    assert "Checkpoint not recorded" in clean
    assert "partially recorded" not in clean
    assert "Checkpoint recorded." not in clean
    assert "database: failed" in clean
    assert "document: failed" in clean
    assert store.load_plan("glue-etl").checkpoints == []


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


def test_evaluate_record_on_unready_active_plan_is_refused_with_a_repair_hint(
    runner, isolated_plans_dir
) -> None:
    """Council review 2, GPT F2 + the legacy-document ruling: the refusal keeps
    the frozen "Cannot activate" line but tells a learner whose plan is
    *already* active what to do — pause it or repair the blockers."""
    store.plans_dir()
    (isolated_plans_dir / "husk.md").write_text(
        "---\nid: husk\ntitle: Husk\nstatus: active\ntopics: [sql]\n---\n\n"
        "# Husk\n\n## Milestones\n\n- [ ] **Step** `(concepts: x)`\n",
        encoding="utf-8",
    )
    before = store.load_plan_text("husk")

    result = runner.invoke(cli, ["plan", "evaluate", "husk", "--record"])

    assert result.exit_code == 1, result.output
    clean = _ANSI.sub("", result.output)
    assert "Cannot activate 'husk'" in clean
    assert "already active" in clean
    assert "studyloop plan status husk paused" in clean
    assert "Traceback" not in clean
    assert store.load_plan_text("husk") == before
    assert index_module.checkpoint_history("husk") == []


def test_activation_refusal_carries_no_already_active_hint(runner) -> None:
    runner.invoke(cli, ["plan", "new", "--title", "Vague"])
    result = runner.invoke(cli, ["plan", "status", "vague", "active"])
    assert result.exit_code == 1
    assert "already active" not in _ANSI.sub("", result.output)


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


def test_record_created_is_the_mutations_outcome_not_a_prior_read(runner, monkeypatch) -> None:
    """Council review 2, GPT Astra F4: ``created`` was inferred from an
    ``inspect`` taken *before* the revision. Another writer landing the same
    record in that window made the no-op report ``created: true``. Model the
    writer at the seam boundary — the record is filed just before the
    mutation runs — and the command must say false, from the mutation's own
    outcome, with no preliminary read of its own."""
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY])
    real_apply = PlanApplication.apply
    inspections: list[str] = []
    real_inspect = PlanApplication.inspect

    def racing_apply(self, intent):
        store.record_learning("glue-etl", "Insight", body="prose")  # the other writer
        return real_apply(self, intent)

    def spying_inspect(self, plan_id, **kwargs):
        inspections.append(plan_id)
        return real_inspect(self, plan_id, **kwargs)

    monkeypatch.setattr(PlanApplication, "apply", racing_apply)
    monkeypatch.setattr(PlanApplication, "inspect", spying_inspect)

    result = runner.invoke(
        cli, ["plan", "record", "glue-etl", "--title", "Insight", "--body", "prose", "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["created"] is False, "the record existed when the mutation ran"
    assert payload["number"] == 1
    assert inspections == [], "one seam mutation decides persistence and `created`"
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


# ---------------------------------------------------------------------------
# Item 3 (D-C, deviation 12 kept): husk discovery and ``plan repair <id>``
# ---------------------------------------------------------------------------

_HUSK_BLOCKERS = (
    "Mission 'why' is empty — interview the learner first.",
    "No observable success criteria.",
)


def _write_husk(plans_dir, plan_id: str, title: str, *, created: str = "") -> None:
    """An active document with no mission: the shape the gate refuses to write
    to. The seam never produces one, so the fixture is a raw file."""
    created_line = f"created: {created}\n" if created else ""
    (plans_dir / f"{plan_id}.md").write_text(
        f"---\nid: {plan_id}\ntitle: {title}\nstatus: active\ntopics: [sql]\n{created_line}---\n\n"
        f"# {title}\n\n## Milestones\n\n- [ ] **Step** `(concepts: x)`\n",
        encoding="utf-8",
    )


def _documents(plans_dir) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in plans_dir.glob("*.md")}


def _repair_section(brief: str) -> list[str]:
    """The ``- `` lines directly under the brief's first section."""
    lines = brief.splitlines()
    assert lines[0] == "### Repair: what this plan is missing", brief
    items: list[str] = []
    for line in lines[1:]:
        if line.startswith("### ") or line.startswith("## "):
            break
        if line.startswith("- "):
            items.append(line[2:])
    return items


def test_plan_list_marks_husks(runner, isolated_plans_dir) -> None:
    """Discovery on the everyday surface: the Rich table carries a ``!`` after
    the status of an active-but-unready plan and nothing after any other
    status; ``--husks`` filters to them; every ``--json`` row carries
    ``ready`` (the 18th summary key) so an agent needs no second call."""
    store.plans_dir()
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY, "--activate"])
    runner.invoke(cli, ["plan", "new", "--title", "Vague"])
    _write_husk(isolated_plans_dir, "husk", "Husk")

    table = _ANSI.sub("", runner.invoke(cli, ["plan", "list"]).output)
    # Rich body rows: `│ id │ title │ status │ progress │ next │` — read the Status cell by id.
    status_by_id = {
        cells[0]: cells[2]
        for cells in (
            [cell.strip() for cell in line.strip().strip("│").split("│")]
            for line in table.splitlines()
            if line.startswith("│")
        )
    }
    assert set(status_by_id) == {"husk", "glue-etl", "vague"}, table
    assert re.fullmatch(r"active\s*!", status_by_id["husk"]), status_by_id
    assert status_by_id["glue-etl"] == "active", status_by_id
    assert status_by_id["vague"] == "draft", status_by_id

    payload = json.loads(runner.invoke(cli, ["plan", "list", "--json"]).output)
    ready_by_id = {row["plan_id"]: row["ready"] for row in payload}
    assert ready_by_id == {"husk": False, "glue-etl": True, "vague": False}
    assert all(len(row) == 18 for row in payload), sorted(payload[0])

    only_husks = runner.invoke(cli, ["plan", "list", "--husks"])
    assert only_husks.exit_code == 0, only_husks.output
    clean = _ANSI.sub("", only_husks.output)
    assert "husk" in clean
    assert "glue-etl" not in clean
    assert "vague" not in clean

    husks_json = json.loads(runner.invoke(cli, ["plan", "list", "--husks", "--json"]).output)
    assert [row["plan_id"] for row in husks_json] == ["husk"]
    assert husks_json[0]["ready"] is False


def _launch_patches(tmp_path, captured: dict, calls: list):
    """The launch-capture pattern of ``test_cli_plan.py::test_architect_delegates_…``:
    the real ``study`` command runs up to the one launch chain, whose entry
    ``start_session`` is replaced so the test reads what would have been
    launched instead of launching it."""
    from unittest.mock import MagicMock, patch

    def _fake_start_session(topic, agent, mode, timer, energy, web, **kwargs):
        calls.append(topic)
        captured.update(topic=topic, mode=mode, agent=agent, **kwargs)

    def _tmux(args, **kwargs):
        if "-V" in args:
            return MagicMock(returncode=0, stdout="tmux 3.4\n", stderr="")
        if "has-session" in args:
            return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="%0\n", stderr="")

    return (
        patch("studyloop.tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("studyloop.tmux.subprocess.run", side_effect=_tmux),
        patch("studyloop.agent_launcher.shutil.which", return_value="/usr/bin/claude"),
        patch("studyloop.session_state.read_session_state", return_value={}),
        patch("studyloop.session_state.STATE_FILE", tmp_path / "state.json"),
        patch("studyloop.session_state.SESSION_DIR", tmp_path),
        patch("studyloop.session_state.TOPICS_FILE", tmp_path / "topics.md"),
        patch("studyloop.session_state.PARKING_FILE", tmp_path / "parking.md"),
        patch("studyloop.history.start_study_session", return_value="abc12345"),
        patch("studyloop.session.start.start_session", side_effect=_fake_start_session),
    )


def test_plan_repair_launches_the_architect_with_the_blockers_in_the_brief_and_creates_nothing(
    runner, isolated_plans_dir, tmp_path, monkeypatch
) -> None:
    """D-C guided repair: ``plan repair <id>`` on a husk is the architect
    launch — the same ``study --mode plan-architect`` chain as ``plan
    architect``, never a second path — with a brief whose first section
    lists exactly ``readiness.blockers`` and then the plan as it stands, and
    an honest provenance line. The command itself writes nothing: the
    document, the plans directory and the checkpoint log are untouched."""
    from contextlib import ExitStack

    store.plans_dir()
    _write_husk(isolated_plans_dir, "husk", "Husk", created="2026-09-01T00:00:00+00:00")
    before = _documents(isolated_plans_dir)
    blockers = ReadinessView.from_plan(store.load_plan("husk")).blockers
    assert blockers == _HUSK_BLOCKERS  # the fixture is what this test thinks it is

    captured: dict = {}
    calls: list = []
    with ExitStack() as stack:
        for p in _launch_patches(tmp_path, captured, calls):
            stack.enter_context(p)
        monkeypatch.setenv("TMUX", "/tmp/tmux")
        result = runner.invoke(cli, ["plan", "repair", "husk"])

    assert result.exit_code == 0, result.output
    assert calls == ["Husk"], calls  # one launch, topic = the plan's title
    assert captured["mode"] == "plan-architect"

    brief = captured["brief"]
    assert _repair_section(brief) == list(blockers)
    assert "Husk" in brief
    assert "active" in brief
    assert "sql" in brief
    assert "0/1" in brief  # milestones done/total, as the plan stands
    assert "predates the readiness gate" in brief

    intro = captured["brief_intro"]
    assert "PLAN REPAIR" in intro
    assert "build a study plan" not in intro
    assert "ask the learner only for what is missing" in intro

    assert _documents(isolated_plans_dir) == before
    assert index_module.checkpoint_history("husk") == []


def test_plan_repair_brief_is_honest_when_provenance_is_unknown(
    runner, isolated_plans_dir, tmp_path, monkeypatch
) -> None:
    """A husk created after the gate's date could be a hand edit or an import;
    the seam cannot tell, so the brief says so instead of guessing."""
    from contextlib import ExitStack

    store.plans_dir()
    _write_husk(isolated_plans_dir, "husk", "Husk")  # created: now

    captured: dict = {}
    with ExitStack() as stack:
        for p in _launch_patches(tmp_path, captured, []):
            stack.enter_context(p)
        monkeypatch.setenv("TMUX", "/tmp/tmux")
        result = runner.invoke(cli, ["plan", "repair", "husk"])

    assert result.exit_code == 0, result.output
    brief = captured["brief"]
    assert "cannot tell how it got that way" in brief
    assert "predates the readiness gate" not in brief
    assert "hand edit" not in brief


def test_plan_repair_on_a_ready_plan_says_nothing_to_repair(runner, tmp_path, monkeypatch) -> None:
    from contextlib import ExitStack

    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY, "--activate"])

    calls: list = []
    with ExitStack() as stack:
        for p in _launch_patches(tmp_path, {}, calls):
            stack.enter_context(p)
        monkeypatch.setenv("TMUX", "/tmp/tmux")
        result = runner.invoke(cli, ["plan", "repair", "glue-etl"])

    assert result.exit_code == 0, result.output
    assert "Nothing to repair on 'glue-etl'" in _ANSI.sub("", result.output)
    assert calls == []  # no launch


def test_plan_repair_unknown_id_is_the_seams_not_found(runner) -> None:
    result = runner.invoke(cli, ["plan", "repair", "nope"])

    assert result.exit_code == 1, result.output
    clean = _ANSI.sub("", result.output)
    assert "nope" in clean
    assert "Traceback" not in clean


def test_husk_refusal_names_both_pause_and_repair(runner, isolated_plans_dir) -> None:
    """The refusal a husk write meets (council review 2) now has a second exit:
    it names ``plan repair <id>`` beside ``plan status <id> paused``."""
    store.plans_dir()
    _write_husk(isolated_plans_dir, "husk", "Husk")

    result = runner.invoke(cli, ["plan", "evaluate", "husk", "--record"])

    assert result.exit_code == 1, result.output
    clean = _ANSI.sub("", result.output)
    assert "studyloop plan status husk paused" in clean
    assert "studyloop plan repair husk" in clean


# ---------------------------------------------------------------------------
# Item 4 (D-G) — `plan close <id>`: the closing review is a launch, not a write
# ---------------------------------------------------------------------------


def _closing_section(brief: str) -> list[str]:
    """The ``- `` lines directly under the brief's first section."""
    lines = brief.splitlines()
    assert lines[0] == "### Closing review", brief
    items: list[str] = []
    for line in lines[1:]:
        if line.startswith("### ") or line.startswith("## "):
            break
        if line.startswith("- "):
            items.append(line[2:])
    return items


def _plant_end_evidence(monkeypatch, *, due: list[dict], mentions: list[dict]) -> None:
    """Fixture rows for the end assessment's history readers (the same seam
    ``test_now_plan_guidance.py`` uses): no sessions database is involved."""
    from studyloop import history

    monkeypatch.setattr(history, "spaced_repetition_due", lambda topic_keywords_map: list(due))
    monkeypatch.setattr(history.progress, "get_struggling_topics", lambda days=30: [])
    monkeypatch.setattr(history, "topic_frequency", lambda keywords, days=90: list(mentions))
    monkeypatch.setattr(history, "last_studied", lambda keywords: None)
    monkeypatch.setattr(history, "struggle_topics", lambda days=14, min_sessions=2: [])


def test_plan_close_launches_the_architect_with_the_assessment_in_the_brief(
    runner, isolated_plans_dir, tmp_path, monkeypatch
) -> None:
    """D-G: ``plan close <id>`` on a fully-checked plan is the architect launch —
    the one ``study --mode plan-architect`` chain, sibling of ``plan repair`` —
    with a brief whose first section is the closing review: the three counts,
    the proposal and the evidence lines, readable off the top. The assessment
    is the preview: the command writes nothing — document, status and
    checkpoint log are untouched — because the learner, not the engine,
    decides whether the plan is complete. The due fixture carries a
    scheduler "new topic" row (``concept: None``) beside the real due row:
    the brief's count is the completion review's — one, not two."""
    from contextlib import ExitStack

    store.plans_dir()
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY, "--activate"])
    runner.invoke(cli, ["plan", "milestone", "glue-etl", "0", "--done"])
    runner.invoke(cli, ["plan", "milestone", "glue-etl", "1", "--done"])
    assert store.load_plan("glue-etl").milestone_done == 2  # the fixture is fully checked
    before = _documents(isolated_plans_dir)
    _plant_end_evidence(
        monkeypatch,
        due=[
            {
                "topic": "data-engineering",
                "concept": "glue job",
                "confidence": "learning",
                "last_studied": "2026-09-07",
                "days_ago": 9,
                "review_type": "overdue",
            },
            {
                "topic": "data-engineering",
                "concept": None,
                "confidence": None,
                "last_studied": None,
                "days_ago": None,
                "review_type": "New topic -- start fresh",
                "evidence": "configured_topic",
            },
        ],
        mentions=[{"snippet": "walked through a dynamicframe transform"}],
    )

    captured: dict = {}
    calls: list = []
    with ExitStack() as stack:
        for p in _launch_patches(tmp_path, captured, calls):
            stack.enter_context(p)
        monkeypatch.setenv("TMUX", "/tmp/tmux")
        result = runner.invoke(cli, ["plan", "close", "glue-etl"])

    assert result.exit_code == 0, result.output
    assert calls == ["Glue ETL"], calls  # one launch, topic = the plan's title
    assert captured["mode"] == "plan-architect"

    items = _closing_section(captured["brief"])
    assert items[:4] == [
        "Due reviews on plan concepts: 1",
        "Struggles on plan concepts: 0",
        "Unverified milestones: 0",
        "Proposal: extend",
    ], items
    assert any("glue job" in item for item in items[4:]), items  # the evidence names the concept
    assert "2/2" in captured["brief"]  # milestones done/total, as the plan stands

    intro = captured["brief_intro"]
    assert "CLOSING REVIEW" in intro
    assert "build a study plan" not in intro
    assert "only when the learner agrees" in intro

    assert _documents(isolated_plans_dir) == before
    assert store.load_plan("glue-etl").status == "active"
    assert index_module.checkpoint_history("glue-etl") == []


def test_plan_close_on_an_unfinished_plan_refuses(
    runner, isolated_plans_dir, tmp_path, monkeypatch
) -> None:
    """A plan with open milestones has nothing to close: exit 1, the count of
    open milestones in the message, no launch, nothing written."""
    from contextlib import ExitStack

    store.plans_dir()
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY, "--activate"])
    before = _documents(isolated_plans_dir)

    calls: list = []
    with ExitStack() as stack:
        for p in _launch_patches(tmp_path, {}, calls):
            stack.enter_context(p)
        monkeypatch.setenv("TMUX", "/tmp/tmux")
        result = runner.invoke(cli, ["plan", "close", "glue-etl"])

    assert result.exit_code == 1, result.output
    clean = _ANSI.sub("", result.output)
    assert "'glue-etl' still has 2 open milestone(s)" in clean
    assert "Traceback" not in clean
    assert calls == []  # no launch
    assert _documents(isolated_plans_dir) == before


def test_plan_close_with_a_partial_assessment_does_not_present_a_clean_proposal(
    runner, isolated_plans_dir, tmp_path, monkeypatch
) -> None:
    """Council review 6, F1: one of the end assessment's readers is down, the
    rest is clean. ``evaluate_plan`` swallows the failure into a warning and
    an empty default, so the counts it did read are zero — but "zero due" is
    unread, not known. The brief must say so in its fixed lines
    (``Proposal: unassessed — the review is partial``), name the gap in the
    same first section, and still launch: the architect is the right place to
    decide what a partial review means. The status line must not say the
    review "proposes: close"."""
    from contextlib import ExitStack

    from studyloop import history

    store.plans_dir()
    runner.invoke(cli, ["plan", "new", "--title", "Glue ETL", *READY, "--activate"])
    runner.invoke(cli, ["plan", "milestone", "glue-etl", "0", "--done"])
    runner.invoke(cli, ["plan", "milestone", "glue-etl", "1", "--done"])
    before = _documents(isolated_plans_dir)
    _plant_end_evidence(
        monkeypatch,
        due=[],
        mentions=[{"snippet": "walked through the glue job anatomy and a dynamicframe transform"}],
    )

    def due_reader_down(topic_keywords_map):
        raise RuntimeError("study_progress is locked")

    monkeypatch.setattr(history, "spaced_repetition_due", due_reader_down)

    captured: dict = {}
    calls: list = []
    with ExitStack() as stack:
        for p in _launch_patches(tmp_path, captured, calls):
            stack.enter_context(p)
        monkeypatch.setenv("TMUX", "/tmp/tmux")
        result = runner.invoke(cli, ["plan", "close", "glue-etl"])

    assert result.exit_code == 0, result.output
    assert calls == ["Glue ETL"], calls  # the launch still happens: the architect decides
    clean = _ANSI.sub("", result.output)
    assert "proposes: close" not in clean
    assert "partial" in clean.lower()

    items = _closing_section(captured["brief"])
    assert items[:4] == [
        "Due reviews on plan concepts: 0",
        "Struggles on plan concepts: 0",
        "Unverified milestones: 0",
        "Proposal: unassessed — the review is partial",
    ], items
    assert any("unavailable" in item for item in items[4:]), items  # the gap, in the same section
    assert _documents(isolated_plans_dir) == before
