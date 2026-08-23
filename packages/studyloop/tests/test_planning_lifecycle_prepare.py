"""Preparation and durable-run contracts for PlanningLifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from planning_lifecycle_support import (
    LEARNER,
    MODEL,
    canonical_plan,
    evidence_ref,
    lifecycle,
    store_plan,
)

from studyloop.planning import (
    IdempotencyConflictError,
    PlanCapacityError,
    PlanningCommand,
    PlanningRequest,
    PlanningRunRef,
    SourceReference,
    TransitionPlanStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_no_notes_create_preserves_exact_raw_dump_and_context_provenance(tmp_path: Path) -> None:
    note = evidence_ref("note-1", source_kind="notes", tier=4)
    service = lifecycle(tmp_path, evidence=(note,))
    raw = "  I can say ABC, but protocols still feel fuzzy.\nPlease help.  "
    source = SourceReference("course-outline", "sha256:v1:" + "c" * 64)

    brief = service.prepare(
        PlanningRequest(
            mode="create",
            brain_dump=raw,
            idempotency_key="first-plan",
            source_references=(source,),
        ),
        MODEL,
    )

    assert brief.raw_brain_dump == raw
    assert brief.evidence == (note,)
    assert brief.source_references == (source,)
    assert brief.current_count == 0
    assert brief.target_plan is None
    assert brief.invariants
    assert "Tier-four context never proves progress or completion" in brief.invariants
    assert brief.brief_context_digest.startswith("sha256:v1:")
    artifact = tmp_path / "private-runs" / brief.run_id / "brain-dump.txt"
    assert artifact.read_text() == raw
    assert artifact.stat().st_mode & 0o777 == 0o600
    assert raw not in (tmp_path / "planning-journal.jsonl").read_text()
    assert not list((tmp_path / "plans").glob("*.md"))


def test_prepare_replays_after_restart_but_changed_input_conflicts(tmp_path: Path) -> None:
    request = PlanningRequest(
        mode="create",
        brain_dump="Learn data contracts",
        idempotency_key="durable-run",
    )
    first = lifecycle(tmp_path).prepare(request, MODEL)
    replay = lifecycle(tmp_path).prepare(request, MODEL)

    assert replay == first
    assert lifecycle(tmp_path).inspect(PlanningRunRef(first.run_id)) == first

    with pytest.raises(IdempotencyConflictError, match="different planning request"):
        lifecycle(tmp_path).prepare(
            PlanningRequest(
                mode="create",
                brain_dump="Learn a different subject",
                idempotency_key="durable-run",
            ),
            MODEL,
        )


def test_prepare_idempotency_normalises_unordered_context_references(tmp_path: Path) -> None:
    first_evidence = evidence_ref("context-a", source_kind="notes", tier=4)
    second_evidence = evidence_ref("context-b", source_kind="course_structure", tier=4)
    first_source = SourceReference("source-a", "sha256:v1:" + "a" * 64)
    second_source = SourceReference("source-b", "sha256:v1:" + "b" * 64)
    service = lifecycle(tmp_path, evidence=(first_evidence, second_evidence))

    first = service.prepare(
        PlanningRequest(
            "create",
            "Exact dump",
            "normalised-run",
            source_references=(first_source, second_source),
            evidence_ids=(first_evidence.evidence_id, second_evidence.evidence_id),
        ),
        MODEL,
    )
    replay = service.prepare(
        PlanningRequest(
            "create",
            "Exact dump",
            "normalised-run",
            source_references=(second_source, first_source),
            evidence_ids=(second_evidence.evidence_id, first_evidence.evidence_id),
        ),
        MODEL,
    )

    assert replay == first


@pytest.mark.parametrize("terminal_status", ["complete", "abandoned"])
def test_prepare_refuses_fourth_current_plan_but_history_releases_capacity(
    tmp_path: Path,
    terminal_status: str,
) -> None:
    for plan_id in ("one", "two", "three"):
        store_plan(tmp_path, canonical_plan(plan_id))

    with pytest.raises(PlanCapacityError, match="maximum of 3 current plans"):
        lifecycle(tmp_path).prepare(
            PlanningRequest("create", "A fourth direction", "fourth"), MODEL
        )

    repository_lifecycle = lifecycle(tmp_path)
    repository_lifecycle.handle(
        PlanningCommand(
            LEARNER,
            TransitionPlanStatus("three", terminal_status, f"release-slot-{terminal_status}"),
        )
    )

    brief = lifecycle(tmp_path).prepare(
        PlanningRequest("create", "Now there is room", "released"), MODEL
    )
    assert brief.current_count == 2


def test_revise_digest_includes_target_and_all_current_plan_state(tmp_path: Path) -> None:
    store_plan(tmp_path, canonical_plan("target"))
    store_plan(tmp_path, canonical_plan("other"))
    service = lifecycle(tmp_path)
    before = service.prepare(
        PlanningRequest("revise", "Narrow the scope", "revision-1", plan_id="target"), MODEL
    )

    service.handle(
        PlanningCommand(LEARNER, TransitionPlanStatus("other", "complete", "complete-other"))
    )
    after = lifecycle(tmp_path).prepare(
        PlanningRequest("revise", "Narrow the scope", "revision-2", plan_id="target"), MODEL
    )

    assert before.target_document_digest
    assert before.target_structure_digest
    assert before.target_plan is not None
    assert before.target_plan.plan_id == "target"
    assert before.brief_context_digest != after.brief_context_digest
