"""Tests for the shared learning decision engine and CLI surface."""

from __future__ import annotations

from click.testing import CliRunner

from studyloop.cli import cli
from studyloop.learning import decision
from studyloop.learning.decision import _Candidate, build_now_plan


def _candidate(
    concept: str,
    *,
    topic: str = "python",
    action_type: str = "recall",
    score: float = 50,
) -> _Candidate:
    return _Candidate(
        concept=concept,
        topic=topic,
        reason=f"reason for {concept}",
        action_type=action_type,  # type: ignore[arg-type]
        estimated_minutes=10,
        source=f"test:{concept}",
        evidence_command=f'studyloop progress "{concept}" -t "{topic}" -c learning',
        score=score,
    )


def _patch_collectors(monkeypatch, *candidates: _Candidate) -> None:
    monkeypatch.setattr(decision, "_due_card_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_due_progress_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_struggle_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_continuity_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_practice_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_transfer_candidates", lambda time_minutes: [])
    if candidates:
        monkeypatch.setattr(
            decision,
            "_due_progress_candidates",
            lambda time_minutes: list(candidates),
        )


def test_no_data_returns_starter_recommendation(monkeypatch) -> None:
    _patch_collectors(monkeypatch)
    monkeypatch.setattr(
        decision,
        "_starter_candidate",
        lambda time_minutes: _candidate("starter", score=10),
    )

    plan = build_now_plan()

    assert plan.starter is True
    assert plan.primary.concept == "starter"
    assert plan.primary.evidence_command.startswith("studyloop progress")


def test_due_concept_outranks_new_topic(monkeypatch) -> None:
    due = _candidate("due decorators", score=100)
    new = _candidate("new topic", score=10)
    monkeypatch.setattr(decision, "_due_card_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_due_progress_candidates", lambda time_minutes: [due])
    monkeypatch.setattr(decision, "_struggle_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_continuity_candidates", lambda time_minutes: [new])
    monkeypatch.setattr(decision, "_practice_candidates", lambda time_minutes: [])

    plan = build_now_plan()

    assert plan.primary.concept == "due decorators"


def test_struggling_concept_outranks_confident_concept(monkeypatch) -> None:
    struggling = _candidate("joins repair", action_type="hands-on", score=82)
    confident = _candidate("confident review", score=55)
    _patch_collectors(monkeypatch, confident, struggling)

    plan = build_now_plan(modality="hands-on")

    assert plan.primary.concept == "joins repair"


def test_low_energy_suppresses_transfer_context_switch(monkeypatch) -> None:
    current = _candidate("current repair", topic="python", action_type="conversation", score=60)
    transfer = _candidate("far transfer", topic="sql", action_type="visual", score=80)
    monkeypatch.setattr(decision, "_due_card_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_due_progress_candidates", lambda time_minutes: [transfer])
    monkeypatch.setattr(decision, "_struggle_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_continuity_candidates", lambda time_minutes: [current])
    monkeypatch.setattr(decision, "_practice_candidates", lambda time_minutes: [])
    monkeypatch.setattr(decision, "_transfer_candidates", lambda time_minutes: [transfer])

    plan = build_now_plan(energy="low", interleave="adaptive")

    assert plan.primary.concept == "current repair"


def test_json_output_contains_same_primary_as_rich_output(monkeypatch) -> None:
    _patch_collectors(monkeypatch, _candidate("decorators", score=100))

    json_result = CliRunner().invoke(cli, ["now", "--json"])
    rich_result = CliRunner().invoke(cli, ["now"])

    assert json_result.exit_code == 0
    assert rich_result.exit_code == 0
    assert '"concept": "decorators"' in json_result.output
    assert "decorators" in rich_result.output
