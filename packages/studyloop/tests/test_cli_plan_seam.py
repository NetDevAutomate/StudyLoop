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
