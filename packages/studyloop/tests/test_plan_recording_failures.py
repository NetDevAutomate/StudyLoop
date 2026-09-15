"""Checkpoint recording: the database write and the document write are independent.

Bug B (issue #7, decision D-1): ``evaluate_and_record`` must report a failed
database write as a warning — whether ``record_checkpoint`` *returned*
``False`` or *raised* — and must still attempt the Markdown append, because
the two sinks are independent by design. And the reverse: a failed document
write must not discard a checkpoint the database already holds.

Every test here runs against its own checkpoint database (``STUDYLOOP_DB``
pointed at ``tmp_path``) and its own plans directory, so "one row" and "no
rows" are facts about *this* test, not about whatever the suite's shared
database happens to contain. Council review 1, finding F6.
"""

from __future__ import annotations

import pytest

from studyloop.planning import evaluation as evaluation_module
from studyloop.planning import index as index_module
from studyloop.planning import store
from studyloop.planning.evaluation import evaluate_and_record
from studyloop.planning.models import Milestone, Mission, StudyPlan

DB_WARNING = "checkpoint not saved to the database"
DOCUMENT_WARNING = "checkpoint not appended to the plan document"


@pytest.fixture(autouse=True)
def isolated_plans_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.PLANS_DIR_ENV, str(tmp_path / "study-plans"))


@pytest.fixture(autouse=True)
def isolated_checkpoint_db(tmp_path, monkeypatch):
    """A fresh sessions database per test; the schema is created on first connect."""
    monkeypatch.setenv("STUDYLOOP_DB", str(tmp_path / "sessions.db"))
    return tmp_path / "sessions.db"


@pytest.fixture
def plan() -> StudyPlan:
    plan = StudyPlan(
        plan_id="demo",
        title="Demo Plan",
        status="active",
        topics=["sql"],
        mission=Mission(why="Because", success=["Do a thing"]),
        milestones=[Milestone(title="One", concepts=["a"])],
    )
    store.create_plan(plan)
    return plan


def _document_checkpoints(plan_id: str) -> list[str]:
    return [checkpoint.phase for checkpoint in store.load_plan(plan_id).checkpoints]


def _database_checkpoints(plan_id: str) -> list[str]:
    return [str(row["phase"]) for row in index_module.checkpoint_history(plan_id)]


def test_record_false_warns_and_still_attempts_markdown_append(
    plan: StudyPlan, monkeypatch
) -> None:
    monkeypatch.setattr(index_module, "record_checkpoint", lambda evaluation, *, study_id="": False)

    result = evaluate_and_record(plan, "start")

    assert DB_WARNING in result.warnings
    assert DOCUMENT_WARNING not in result.warnings
    assert result.phase == "start"
    assert _document_checkpoints("demo") == ["start"], "the document sink was still written"
    assert _database_checkpoints("demo") == [], "and the refused row really is absent"


def test_record_exception_warns_and_still_attempts_markdown_append(
    plan: StudyPlan, monkeypatch
) -> None:
    def explode(evaluation, *, study_id=""):
        msg = "database is locked"
        raise RuntimeError(msg)

    monkeypatch.setattr(index_module, "record_checkpoint", explode)

    result = evaluate_and_record(plan, "mid")

    assert DB_WARNING in result.warnings
    assert DOCUMENT_WARNING not in result.warnings
    assert _document_checkpoints("demo") == ["mid"]
    assert _database_checkpoints("demo") == []


def test_record_success_adds_no_database_warning(plan: StudyPlan) -> None:
    result = evaluate_and_record(plan, "end", study_id="sess-1")

    assert DB_WARNING not in result.warnings
    assert DOCUMENT_WARNING not in result.warnings
    assert _database_checkpoints("demo") == ["end"], "exactly the row this test recorded"
    history = index_module.checkpoint_history("demo")
    assert history[0]["study_id"] == "sess-1"
    assert _document_checkpoints("demo") == ["end"]


def test_markdown_failure_does_not_discard_successful_database_recording(
    plan: StudyPlan, monkeypatch
) -> None:
    def refuse_write(plan, **kwargs):
        msg = "read-only file system"
        raise OSError(msg)

    monkeypatch.setattr(store, "save_plan", refuse_write)

    result = evaluate_and_record(plan, "start")

    assert DOCUMENT_WARNING in result.warnings
    assert DB_WARNING not in result.warnings, "the database sink succeeded independently"
    assert _database_checkpoints("demo") == ["start"]
    assert _document_checkpoints("demo") == [], "the on-disk document is unchanged"
    assert result.verdict in {"on-track", "at-risk", "stalled", "complete"}


def test_append_to_plan_false_skips_the_document_sink_without_a_warning(plan: StudyPlan) -> None:
    result = evaluate_and_record(plan, "start", append_to_plan=False)

    assert DOCUMENT_WARNING not in result.warnings
    assert DB_WARNING not in result.warnings
    assert _database_checkpoints("demo") == ["start"]
    assert _document_checkpoints("demo") == []


def test_evaluation_is_returned_even_when_both_sinks_fail(plan: StudyPlan, monkeypatch) -> None:
    """D-1/D-3: no ``PartialRecording`` exception — the evaluation always comes back."""
    monkeypatch.setattr(index_module, "record_checkpoint", lambda evaluation, *, study_id="": False)

    def refuse_write(plan, **kwargs):
        raise OSError

    monkeypatch.setattr(store, "save_plan", refuse_write)

    result = evaluate_and_record(plan, "end")

    assert DB_WARNING in result.warnings
    assert DOCUMENT_WARNING in result.warnings
    assert isinstance(result, evaluation_module.PlanEvaluation)
    assert _database_checkpoints("demo") == []
    assert _document_checkpoints("demo") == []
