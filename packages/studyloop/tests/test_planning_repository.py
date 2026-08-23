"""Public repository contract for locked file-first plan mutations."""

from __future__ import annotations

import json
import multiprocessing
import stat
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from studyloop.planning.journal import JournalCorruptionError
from studyloop.planning.markdown import render_plan
from studyloop.planning.models import Goal, Milestone, Mission, StudyPlan
from studyloop.planning.repository import (
    IdempotencyConflictError,
    MutationIntent,
    PathContainmentError,
    PlanCapacityError,
    PlanConflictError,
    PlanningPaths,
    PlanningRef,
    PlanningRepository,
    PlanScanError,
    PrivateRunArtifact,
)


def _paths(root: Path) -> PlanningPaths:
    return PlanningPaths(
        root=root,
        plans=root / "plans",
        journal=root / "planning-journal.jsonl",
        private_runs=root / "private-runs",
        lock_file=root / ".planning.lock",
    )


def _plan(plan_id: str, *, status: str = "draft", title: str | None = None) -> StudyPlan:
    return StudyPlan(
        plan_id=plan_id,
        title=title or plan_id.replace("-", " ").title(),
        status=status,
        created="2026-08-23T10:00:00+00:00",
        updated="2026-08-23T10:00:00+00:00",
        mission=Mission(why="Learn it.", success=["Demonstrate it."]),
        goals=[Goal(f"goal-{plan_id}", "One goal", "Needed", "Aligned")],
        milestones=[
            Milestone(
                "One step",
                milestone_id=f"milestone-{plan_id}",
                goal_id=f"goal-{plan_id}",
            )
        ],
    )


def _intent(
    plan: StudyPlan,
    *,
    key: str | None = None,
    operation: str = "create",
) -> MutationIntent:
    return MutationIntent(
        intent_id=f"intent-{plan.plan_id}",
        caller="pytest",
        idempotency_key=key or f"key-{plan.plan_id}",
        operation=operation,
        plan=plan,
    )


def _race_commit(root: str, plan_id: str, actor: str, barrier, results) -> None:
    repository = PlanningRepository(_paths(Path(root)), index_refresher=None)
    intent = MutationIntent(
        intent_id=f"intent-{actor}",
        caller=actor,
        idempotency_key=f"key-{actor}",
        operation="create",
        plan=_plan(plan_id),
    )
    barrier.wait()
    try:
        result = repository.commit(intent)
    except Exception as error:  # result is intentionally sent across a process boundary
        results.put(("error", type(error).__name__, str(error)))
    else:
        results.put(("ok", result.status, result.plan_id))


def _cas_update(
    view,
    plan: StudyPlan,
    *,
    intent_id: str,
    operation: str = "update",
) -> MutationIntent:
    return MutationIntent(
        intent_id=intent_id,
        caller="pytest-cas",
        idempotency_key=f"key-{intent_id}",
        operation=operation,
        plan=plan,
        expected_document_digest=view.document_digest,
        expected_structure_digest=view.structure_digest,
        expected_document_revision=view.plan.document_revision,
        expected_structure_revision=view.plan.structure_revision,
    )


def test_create_commits_a_digested_plan_and_a_durable_decision_record(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)

    result = repository.commit(_intent(_plan("first")))
    view = repository.inspect(PlanningRef("first"))
    events = [json.loads(line) for line in paths.journal.read_text().splitlines()]

    assert result.status == "committed"
    assert view.plan.document_revision == 1
    assert view.plan.structure_revision == 1
    assert view.plan.document_digest.startswith("sha256:v1:")
    assert view.plan.structure_digest.startswith("sha256:v1:")
    assert [event["event"] for event in events] == ["intent", "committed"]
    assert events[0]["after_document_digest"] == view.plan.document_digest
    assert events[0]["after_structure_digest"] == view.plan.structure_digest
    assert stat.S_IMODE(paths.journal.stat().st_mode) == 0o600
    assert stat.S_IMODE(paths.lock_file.stat().st_mode) == 0o600
    temporary_name = events[0]["recovery"]["temporary_name"]
    assert Path(temporary_name).name == temporary_name
    assert temporary_name.startswith(".first.")


def test_same_idempotency_tuple_and_payload_replays_but_changed_payload_conflicts(
    tmp_path: Path,
) -> None:
    repository = PlanningRepository(_paths(tmp_path), index_refresher=None)
    intent = _intent(_plan("stable-key"), key="same-key")

    first = repository.commit(intent)
    replay = repository.commit(intent)

    assert first.status == "committed"
    assert replay == replace(first, status="replayed")
    changed = _intent(_plan("stable-key", title="Changed payload"), key="same-key")
    with pytest.raises(IdempotencyConflictError, match="different payload"):
        repository.commit(changed)


def test_default_operation_is_create_and_same_slug_never_clobbers(tmp_path: Path) -> None:
    repository = PlanningRepository(_paths(tmp_path), index_refresher=None)
    first = MutationIntent(
        intent_id="intent-default-first",
        caller="pytest-default",
        idempotency_key="key-default-first",
        plan=_plan("default-slug", title="First title"),
    )
    second = replace(
        first,
        intent_id="intent-default-second",
        idempotency_key="key-default-second",
        plan=_plan("default-slug", title="Must not win"),
    )

    repository.commit(first)
    with pytest.raises(PlanConflictError, match="already exists"):
        repository.commit(second)

    assert repository.inspect(PlanningRef("default-slug")).plan.title == "First title"


@pytest.mark.parametrize("operation", ["update", "upsert"])
def test_existing_plan_update_requires_complete_compare_and_swap(
    tmp_path: Path, operation: str
) -> None:
    repository = PlanningRepository(_paths(tmp_path), index_refresher=None)
    repository.commit(_intent(_plan("cas-required")))
    changed = _plan("cas-required", title="Must not overwrite")

    with pytest.raises(PlanConflictError, match="complete expected state"):
        repository.commit(
            MutationIntent(
                intent_id=f"intent-missing-cas-{operation}",
                caller="pytest-cas",
                idempotency_key=f"key-missing-cas-{operation}",
                operation=operation,
                plan=changed,
            )
        )

    assert repository.inspect(PlanningRef("cas-required")).plan.title == "Cas Required"


def test_stale_old_view_cannot_overwrite_a_newer_signed_plan(tmp_path: Path) -> None:
    repository = PlanningRepository(_paths(tmp_path), index_refresher=None)
    repository.commit(_intent(_plan("stale-view", title="Original")))
    stale = repository.inspect(PlanningRef("stale-view"))

    current_plan = deepcopy(stale.plan)
    current_plan.title = "Newer accepted title"
    repository.commit(_cas_update(stale, current_plan, intent_id="intent-newer-accepted"))

    stale_plan = deepcopy(stale.plan)
    stale_plan.title = "Stale overwrite"
    with pytest.raises(PlanConflictError, match="stale document digest"):
        repository.commit(_cas_update(stale, stale_plan, intent_id="intent-stale"))

    current = repository.inspect(PlanningRef("stale-view"))
    assert current.plan.title == "Newer accepted title"
    assert current.plan.document_revision == 2


def test_journal_only_transaction_persists_typed_audit_payload(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    intent = MutationIntent(
        intent_id="intent-rejection",
        caller="learner-web",
        idempotency_key="decision-1",
        operation="record",
        ref=PlanningRef("rejected-create"),
        metadata={
            "record_kind": "proposal_decision",
            "proposal_id": "proposal-1",
            "outcome": "reject",
        },
    )

    result = repository.commit(intent)
    events = [json.loads(line) for line in paths.journal.read_text().splitlines()]

    assert result.status == "committed"
    assert result.document_digest is None
    assert events[0]["payload"] == intent.metadata
    assert [event["event"] for event in events] == ["intent", "committed"]
    assert not list(paths.plans.glob("*.md"))


def test_corrupt_journal_blocks_mutation_without_touching_plans(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    paths.journal.write_text("{}\n", encoding="utf-8")

    with pytest.raises(JournalCorruptionError, match="schema version"):
        repository.commit(_intent(_plan("must-not-write")))

    assert not (paths.plans / "must-not-write.md").exists()


def test_unsigned_schema_v2_plan_blocks_every_mutation_scan(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    unsigned = _plan("unsigned-v2")
    assert unsigned.schema_version == 2
    assert unsigned.document_digest == unsigned.structure_digest == ""
    (paths.plans / "unsigned-v2.md").write_text(render_plan(unsigned), encoding="utf-8")

    with pytest.raises(PlanScanError, match="schema v2 plan requires versioned digests"):
        repository.scan_for_mutation()
    with pytest.raises(PlanScanError, match="schema v2 plan requires versioned digests"):
        repository.commit(_intent(_plan("must-not-write")))

    assert not (paths.plans / "must-not-write.md").exists()


def test_journal_rejects_terminal_result_that_disagrees_with_event(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    intent = _intent(_plan("journal-result"))
    repository.commit(intent)
    events = [json.loads(line) for line in paths.journal.read_text().splitlines()]
    events[1]["result"]["plan_id"] = "wrong-plan"
    paths.journal.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(JournalCorruptionError, match="terminal result plan_id"):
        repository.commit(intent)


def test_journal_rejects_terminal_that_disagrees_with_prior_intent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    intent = _intent(_plan("journal-identity"))
    repository.commit(intent)
    events = [json.loads(line) for line in paths.journal.read_text().splitlines()]
    events[0]["after_document_digest"] = "sha256:v1:" + ("0" * 64)
    paths.journal.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(
        JournalCorruptionError,
        match=r"result document_digest|terminal does not match prior intent",
    ):
        repository.commit(intent)


def test_journal_rejects_orphan_and_duplicate_terminal_events(tmp_path: Path) -> None:
    for corruption in ("orphan", "duplicate"):
        root = tmp_path / corruption
        paths = _paths(root)
        repository = PlanningRepository(paths, index_refresher=None)
        intent = _intent(_plan(f"journal-{corruption}"))
        repository.commit(intent)
        lines = paths.journal.read_text().splitlines(keepends=True)
        if corruption == "orphan":
            paths.journal.write_text(lines[1], encoding="utf-8")
        else:
            paths.journal.write_text("".join([*lines, lines[1]]), encoding="utf-8")

        with pytest.raises(JournalCorruptionError, match=f"{corruption} terminal"):
            repository.recover()


def test_fourth_current_plan_is_refused_under_the_root_snapshot(tmp_path: Path) -> None:
    repository = PlanningRepository(_paths(tmp_path), index_refresher=None)
    for plan_id in ("one", "two", "three"):
        repository.commit(_intent(_plan(plan_id)))

    with pytest.raises(PlanCapacityError, match="maximum is 3"):
        repository.commit(_intent(_plan("four")))

    assert repository.scan_for_mutation().current_plan_ids == ("one", "three", "two")


@pytest.mark.parametrize(
    "document",
    [
        "---\nschema_version: [broken\n---\n# Broken\n",
        "---\nschema_version: 999\nid: unsupported\ntitle: Unsupported\n---\n# Unsupported\n",
        "---\nschema_version: 2\nid: unsupported\ntitle: Unsupported\n# Missing delimiter\n",
        "---\nschema_version: 2\nid: unsupported\ntitle: Unsupported\nstatus: invalid\n---\n",
    ],
    ids=["malformed", "unsupported", "unterminated", "invalid-status"],
)
def test_malformed_or_unsupported_candidate_blocks_mutation(tmp_path: Path, document: str) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    (paths.plans / "unsupported.md").write_text(document, encoding="utf-8")

    with pytest.raises(PlanScanError):
        repository.commit(_intent(_plan("safe")))

    assert not (paths.plans / "safe.md").exists()


def test_external_edit_without_revision_bump_blocks_the_next_mutation(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    repository.commit(_intent(_plan("edited")))
    path = paths.plans / "edited.md"
    path.write_text(path.read_text().replace("One step", "Edited outside"), encoding="utf-8")

    with pytest.raises(PlanScanError, match="document digest mismatch"):
        repository.commit(_intent(_plan("another")))


def test_document_only_update_keeps_structure_identity_and_structural_update_bumps_it(
    tmp_path: Path,
) -> None:
    repository = PlanningRepository(_paths(tmp_path), index_refresher=None)
    repository.commit(_intent(_plan("revisions")))
    before = repository.inspect(PlanningRef("revisions"))
    document_only = before.plan
    document_only.notes = "Non-structural working note"

    document_result = repository.commit(
        _cas_update(before, document_only, intent_id="intent-document-update")
    )
    after_document = repository.inspect(PlanningRef("revisions"))

    assert document_result.document_revision == 2
    assert document_result.structure_revision == 1
    assert after_document.structure_digest == before.structure_digest

    structural = after_document.plan
    structural.goals[0].title = "Changed learning path"
    structure_result = repository.commit(
        _cas_update(after_document, structural, intent_id="intent-structure-update")
    )

    assert structure_result.document_revision == 3
    assert structure_result.structure_revision == 2
    assert structure_result.structure_digest != before.structure_digest


def test_plan_symlink_that_escapes_the_root_blocks_mutation(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    outside = tmp_path.parent / f"outside-{tmp_path.name}.md"
    outside.write_text("# Outside", encoding="utf-8")
    (paths.plans / "escape.md").symlink_to(outside)

    try:
        with pytest.raises(PathContainmentError, match="escapes planning root"):
            repository.scan_for_mutation()
    finally:
        outside.unlink()


def test_configured_path_outside_root_is_rejected(tmp_path: Path) -> None:
    paths = replace(_paths(tmp_path / "root"), journal=tmp_path / "outside.jsonl")

    with pytest.raises(PathContainmentError, match="configured journal"):
        PlanningRepository(paths, index_refresher=None)


def test_private_run_artifacts_are_mode_0600(tmp_path: Path) -> None:
    repository = PlanningRepository(_paths(tmp_path), index_refresher=None)

    path = repository.write_private_artifact(
        PrivateRunArtifact("run-1", "brain-dump.txt", "private learner input")
    )

    assert path.read_text() == "private learner input"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_outside_temporary_path_is_rejected_before_open(tmp_path: Path) -> None:
    repository = PlanningRepository(_paths(tmp_path / "root"), index_refresher=None)
    outside = tmp_path / "outside.tmp"

    with pytest.raises(PathContainmentError, match="temporary path escapes"):
        repository._write_temporary(outside, b"must not be written")

    assert not outside.exists()


def test_symlinked_private_run_directory_cannot_escape(tmp_path: Path) -> None:
    paths = _paths(tmp_path / "root")
    repository = PlanningRepository(paths, index_refresher=None)
    outside = tmp_path / "outside-private"
    outside.mkdir()
    (paths.private_runs / "run-escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathContainmentError, match="private run directory escapes"):
        repository.write_private_artifact(
            PrivateRunArtifact("run-escape", "brain-dump.txt", "must stay inside")
        )

    assert list(outside.iterdir()) == []


def test_two_process_capacity_race_allows_exactly_one_third_plan(tmp_path: Path) -> None:
    repository = PlanningRepository(_paths(tmp_path), index_refresher=None)
    repository.commit(_intent(_plan("existing-one")))
    repository.commit(_intent(_plan("existing-two")))

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    workers = [
        context.Process(
            target=_race_commit,
            args=(str(tmp_path), plan_id, actor, barrier, results),
        )
        for plan_id, actor in (("candidate-a", "worker-a"), ("candidate-b", "worker-b"))
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)

    assert all(not worker.is_alive() for worker in workers)
    assert [worker.exitcode for worker in workers] == [0, 0]
    outcomes = [results.get(timeout=2), results.get(timeout=2)]
    assert [outcome[0] for outcome in outcomes].count("ok") == 1
    assert sorted(outcome[1] for outcome in outcomes) == ["PlanCapacityError", "committed"]
    snapshot = repository.scan_for_mutation()
    assert snapshot.current_count == 3
    assert len(set(snapshot.current_plan_ids) & {"candidate-a", "candidate-b"}) == 1


def test_two_process_same_slug_race_never_clobbers_the_winner(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    workers = [
        context.Process(
            target=_race_commit,
            args=(str(tmp_path), "same-slug", actor, barrier, results),
        )
        for actor in ("slug-worker-a", "slug-worker-b")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)

    assert all(not worker.is_alive() for worker in workers)
    outcomes = [results.get(timeout=2), results.get(timeout=2)]
    assert [outcome[0] for outcome in outcomes].count("ok") == 1
    assert sorted(outcome[1] for outcome in outcomes) == ["PlanConflictError", "committed"]
    assert (
        PlanningRepository(_paths(tmp_path), index_refresher=None)
        .inspect(PlanningRef("same-slug"))
        .plan.title
        == "Same Slug"
    )
