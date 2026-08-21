"""``studyloop plan`` CLI contract.

Agents drive these commands, so the exit codes and the ``--json`` shapes are
part of the contract, not incidental.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from studyloop.cli import cli
from studyloop.planning import store


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))
    return tmp_path / "study-plans"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make(runner: CliRunner, title: str = "Glue ETL Basics", extra: list[str] | None = None):
    args = [
        "plan",
        "new",
        "--title",
        title,
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
    result = runner.invoke(cli, args + (extra or []))
    assert result.exit_code == 0, result.output
    return result


def test_new_then_list_then_show(runner: CliRunner) -> None:
    _make(runner)

    listed = runner.invoke(cli, ["plan", "list"])
    assert listed.exit_code == 0
    assert "glue-etl-basics" in listed.output

    shown = runner.invoke(cli, ["plan", "show", "glue-etl-basics"])
    assert shown.exit_code == 0
    assert "Own the nightly pipeline" in shown.output
    assert "Job anatomy" in shown.output


def test_show_markdown_emits_the_document(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "show", "glue-etl-basics", "--markdown"])
    assert result.exit_code == 0
    for heading in ("## Mission", "## Milestones", "## Checkpoints", "### Why"):
        assert heading in result.output, f"missing {heading}"
    assert "(concepts: glue job)" in result.output


def test_list_json_is_machine_readable(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["plan_id"] == "glue-etl-basics"
    assert payload[0]["milestone_total"] == 2


def test_show_json_includes_readiness(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "show", "glue-etl-basics", "--json"])
    payload = json.loads(result.output)
    assert payload["readiness"]["ready"] is True
    assert payload["mission"]["why"] == "Own the nightly pipeline"


@pytest.mark.parametrize("phase", ["start", "mid", "end"])
def test_evaluate_every_phase(runner: CliRunner, phase: str) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "evaluate", "glue-etl-basics", "--phase", phase])
    assert result.exit_code == 0, result.output
    assert "Plan checkpoint" in result.output
    assert phase in result.output


def test_evaluate_json_shape(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "evaluate", "glue-etl-basics", "--json"])
    payload = json.loads(result.output)
    assert payload["phase"] == "start"
    assert payload["verdict"] in {"on-track", "at-risk", "stalled", "complete"}
    assert isinstance(payload["recommendations"], list)


def test_evaluate_record_appends_a_checkpoint(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(
        cli, ["plan", "evaluate", "glue-etl-basics", "--phase", "end", "--record"]
    )
    assert result.exit_code == 0
    assert "Checkpoint recorded" in result.output

    doc = runner.invoke(cli, ["plan", "show", "glue-etl-basics", "--markdown"]).output
    assert "| end |" in doc.replace(" |", " |")


def test_milestone_toggle_moves_progress(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "milestone", "glue-etl-basics", "0", "--done"])
    assert result.exit_code == 0
    assert "1/2" in result.output

    toggled_back = runner.invoke(cli, ["plan", "milestone", "glue-etl-basics", "0", "--undone"])
    assert "0/2" in toggled_back.output


def test_milestone_out_of_range_fails_cleanly(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "milestone", "glue-etl-basics", "99", "--done"])
    assert result.exit_code == 1
    assert "No milestone at index 99" in result.output
    assert "Traceback" not in result.output


def test_status_active_is_refused_for_an_incomplete_plan(runner: CliRunner) -> None:
    created = runner.invoke(cli, ["plan", "new", "--title", "Vague Plan"])
    assert created.exit_code == 0

    result = runner.invoke(cli, ["plan", "status", "vague-plan", "active"])
    assert result.exit_code == 1
    assert "Cannot activate" in result.output
    assert "Mission" in result.output
    assert "Traceback" not in result.output

    still_draft = json.loads(runner.invoke(cli, ["plan", "show", "vague-plan", "--json"]).output)
    assert still_draft["plan"]["status"] == "draft"


def test_new_with_activate_is_refused_when_incomplete(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["plan", "new", "--title", "Empty", "--activate"])
    assert result.exit_code == 1
    assert "Cannot activate" in result.output


def test_status_active_succeeds_for_a_complete_plan(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "status", "glue-etl-basics", "active"])
    assert result.exit_code == 0
    payload = json.loads(runner.invoke(cli, ["plan", "show", "glue-etl-basics", "--json"]).output)
    assert payload["plan"]["status"] == "active"


def test_unknown_plan_id_exits_non_zero_without_a_traceback(runner: CliRunner) -> None:
    for args in (["show", "nope"], ["evaluate", "nope"], ["milestone", "nope", "0"]):
        result = runner.invoke(cli, ["plan", *args])
        assert result.exit_code == 1, args
        assert "No study plan with id" in result.output
        assert "Traceback" not in result.output


def test_traversal_id_is_refused(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["plan", "show", "../../etc/passwd"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_interview_lists_the_questions(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["plan", "interview"])
    assert result.exit_code == 0
    assert "Plan interview" in result.output
    assert "What changes in your work" in result.output


def test_interview_json_carries_questions_and_seed(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["plan", "interview", "--json"])
    payload = json.loads(result.output)
    assert len(payload["questions"]) >= 6
    assert {"key", "prompt", "why", "required", "multi"} <= set(payload["questions"][0])
    assert "struggling_topics" in payload["seed"]


def test_duplicate_titles_get_distinct_ids(runner: CliRunner) -> None:
    _make(runner)
    _make(runner)
    ids = [p["plan_id"] for p in json.loads(runner.invoke(cli, ["plan", "list", "--json"]).output)]
    assert "glue-etl-basics" in ids
    assert "glue-etl-basics-2" in ids


def test_path_prints_the_plans_directory(runner: CliRunner, isolated_plans_dir) -> None:
    result = runner.invoke(cli, ["plan", "path"])
    assert result.exit_code == 0
    assert str(isolated_plans_dir) in result.output


def test_reindex_reports_a_count(runner: CliRunner) -> None:
    _make(runner)
    result = runner.invoke(cli, ["plan", "reindex"])
    assert result.exit_code == 0
    assert "Reindexed" in result.output
