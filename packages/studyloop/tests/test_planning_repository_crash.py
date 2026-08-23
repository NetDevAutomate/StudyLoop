"""Crash-injection and deterministic journal recovery contracts."""

from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from planning_lifecycle_support import MODEL, FixedClock, PrefixIds

import studyloop.planning.repository as repository_module
from studyloop.planning import (
    GoalProposal,
    IdempotencyConflictError,
    MilestoneProposal,
    PlanningCommand,
    PlanningLifecycle,
    PlanningRequest,
    PlanningRunRef,
    PlanProposalDraft,
    ProposalRef,
    SubmitProposalDraft,
)
from studyloop.planning.journal import JournalCorruptionError
from studyloop.planning.models import Goal, Milestone, Mission, StudyPlan
from studyloop.planning.repository import (
    MutationIntent,
    PlanningPaths,
    PlanningRef,
    PlanningRepository,
    PrivateRunArtifact,
    RecoveryError,
)

CRASH_POINTS = (
    "after_journal_intent",
    "after_temp_fsync",
    "after_replace",
    "after_directory_fsync",
    "after_commit_event",
)


class InjectedCrashError(RuntimeError):
    """Test-only abrupt stop after one durable commit step."""


def _paths(root: Path) -> PlanningPaths:
    return PlanningPaths.in_root(root)


def _intent() -> MutationIntent:
    plan = StudyPlan(
        plan_id="crash-plan",
        title="Crash plan",
        status="draft",
        created="2026-08-23T12:00:00+00:00",
        updated="2026-08-23T12:00:00+00:00",
        mission=Mission(why="Prove recovery.", success=["Classify every state"]),
        goals=[Goal("goal-crash", "Recover", "Needed", "Aligned")],
        milestones=[
            Milestone(
                "Inject crashes",
                milestone_id="milestone-crash",
                goal_id="goal-crash",
            )
        ],
    )
    return MutationIntent(
        intent_id="intent-crash",
        caller="pytest-crash",
        idempotency_key="key-crash",
        operation="create",
        plan=plan,
    )


def _private_intent() -> MutationIntent:
    return MutationIntent(
        intent_id="intent-private-crash",
        caller="pytest-private-crash",
        idempotency_key="key-private-crash",
        idempotency_digest="sha256:v1:" + "d" * 64,
        operation="journal",
        ref=PlanningRef("private-crash-run"),
        private_artifacts=(
            PrivateRunArtifact(
                "private-crash-run",
                "brain-dump.txt",
                "sensitive orphan candidate",
            ),
        ),
    )


def _semantic_plan_intent() -> MutationIntent:
    return replace(
        _intent(),
        idempotency_digest="sha256:v1:" + "e" * 64,
    )


def _lifecycle(
    root: Path,
    *,
    clock: str,
    crash_point: str | None = None,
) -> PlanningLifecycle:
    return PlanningLifecycle(
        PlanningRepository(
            _paths(root),
            crash_injector=_inject_at(crash_point) if crash_point else None,
            index_refresher=None,
        ),
        clock=FixedClock(clock),
        ids=PrefixIds(),
    )


def _proposal_draft() -> PlanProposalDraft:
    return PlanProposalDraft(
        title="Recover proposal submission",
        mission=Mission(why="Keep retry state durable", success=["Submit one proposal"]),
        goals=(GoalProposal("retry-goal", "Retry safely", "Needed", "Supports mission"),),
        milestones=(MilestoneProposal("retry-step", "retry-goal", "Exercise proposal recovery"),),
        next_action="Exercise proposal recovery",
    )


def _journal_dicts(paths: PlanningPaths) -> list[dict[str, object]]:
    return [json.loads(line) for line in paths.journal.read_text().splitlines()]


def _append_forged_retry(
    paths: PlanningPaths,
    source: dict[str, object],
    *,
    intent_id: str,
    payload_digest: str,
    idempotency_digest: str | None = None,
    operation: str | None = None,
) -> None:
    forged = deepcopy(source)
    forged["event"] = "intent"
    forged["intent_id"] = intent_id
    forged["payload_digest"] = payload_digest
    if idempotency_digest is not None:
        forged["idempotency_digest"] = idempotency_digest
    if operation is not None:
        forged["operation"] = operation
    result = forged["result"]
    assert isinstance(result, dict)
    result["intent_id"] = intent_id
    with paths.journal.open("a", encoding="utf-8") as journal:
        journal.write(json.dumps(forged, sort_keys=True) + "\n")


def _inject_at(selected: str):
    def inject(point: str) -> None:
        if point == selected:
            raise InjectedCrashError(point)

    return inject


def _abrupt_crash_worker(root: str, selected: str) -> None:
    def terminate(point: str) -> None:
        if point == selected:
            os._exit(97)

    repository = PlanningRepository(
        _paths(Path(root)),
        crash_injector=terminate,
        index_refresher=None,
    )
    repository.commit(_intent())
    os._exit(0)


def _assert_lock_released(path: Path) -> None:
    descriptor = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_restart_classifies_each_crash_point_and_retry_is_idempotent(
    tmp_path: Path, crash_point: str
) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at(crash_point),
        index_refresher=None,
    )

    with pytest.raises(InjectedCrashError, match=crash_point):
        crashing.commit(_intent())

    restarted = PlanningRepository(paths, index_refresher=None)
    report = restarted.recover()
    before_points = {"after_journal_intent", "after_temp_fsync"}
    after_points = {"after_replace", "after_directory_fsync"}
    if crash_point in before_points:
        assert [item.classification for item in report.recovered] == ["before"]
        assert not (paths.plans / "crash-plan.md").exists()
        assert restarted.commit(_intent()).status == "committed"
    elif crash_point in after_points:
        assert [item.classification for item in report.recovered] == ["after"]
        assert restarted.inspect(PlanningRef("crash-plan")).plan.title == "Crash plan"
        assert restarted.commit(_intent()).status == "replayed"
    else:
        assert report.recovered == ()
        assert restarted.inspect(PlanningRef("crash-plan")).plan.title == "Crash plan"
        assert restarted.commit(_intent()).status == "replayed"

    assert list(paths.plans.glob("*.tmp")) == []


def test_recovery_refuses_an_unclassifiable_third_state(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_journal_intent"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError):
        crashing.commit(_intent())
    (paths.plans / "crash-plan.md").write_text("# Unjournalled third state\n", encoding="utf-8")

    restarted = PlanningRepository(paths, index_refresher=None)
    with pytest.raises(RecoveryError, match="neither its before nor after state"):
        restarted.recover()

    events = [json.loads(line) for line in paths.journal.read_text().splitlines()]
    assert [event["event"] for event in events] == ["intent"]


def test_recovery_removes_uncommitted_transactional_private_artifact(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_private_artifacts"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError, match="after_private_artifacts"):
        crashing.commit(_private_intent())
    artifact = paths.private_runs / "private-crash-run" / "brain-dump.txt"
    assert artifact.is_file()

    restarted = PlanningRepository(paths, index_refresher=None)
    report = restarted.recover()

    assert [item.classification for item in report.recovered] == ["before"]
    assert not artifact.exists()
    assert not artifact.parent.exists()
    assert restarted.commit(_private_intent()).status == "committed"
    assert artifact.read_text() == "sensitive orphan candidate"


@pytest.mark.parametrize("crash_point", ["after_journal_intent", "after_private_artifacts"])
def test_prepare_retries_a_recovered_before_semantic_lineage_with_new_generated_state(
    tmp_path: Path,
    crash_point: str,
) -> None:
    paths = _paths(tmp_path)
    request = PlanningRequest("create", "Exact sensitive dump", "recover-prepare")
    crashing = _lifecycle(
        tmp_path,
        clock="2026-08-23T12:00:00+00:00",
        crash_point=crash_point,
    )

    with pytest.raises(InjectedCrashError, match=crash_point):
        crashing.prepare(request, MODEL)
    failed_intent = _journal_dicts(paths)[-1]
    failed_run_id = failed_intent["plan_id"]
    assert isinstance(failed_run_id, str)

    report = PlanningRepository(paths, index_refresher=None).recover()
    assert [item.classification for item in report.recovered] == ["before"]
    assert not (paths.private_runs / failed_run_id).exists()

    retrying = _lifecycle(tmp_path, clock="2026-08-23T13:00:00+00:00")
    winner = retrying.prepare(request, MODEL)

    assert winner.run_id != failed_run_id
    assert winner.created_at == "2026-08-23T13:00:00+00:00"
    assert _lifecycle(tmp_path, clock="2026-08-23T14:00:00+00:00").prepare(request, MODEL) == winner
    assert (
        _lifecycle(tmp_path, clock="2026-08-23T15:00:00+00:00").inspect(
            PlanningRunRef(winner.run_id)
        )
        == winner
    )
    assert sorted(path.name for path in paths.private_runs.iterdir()) == [winner.run_id]
    assert [path.name for path in (paths.private_runs / winner.run_id).iterdir()] == [
        "brain-dump.txt"
    ]
    assert (paths.private_runs / winner.run_id / "brain-dump.txt").read_text() == request.brain_dump
    history = _journal_dicts(paths)
    assert [event["event"] for event in history] == [
        "intent",
        "recovered",
        "intent",
        "committed",
    ]
    assert history[2]["plan_id"] == winner.run_id

    with pytest.raises(IdempotencyConflictError, match="different planning request"):
        _lifecycle(tmp_path, clock="2026-08-23T16:00:00+00:00").prepare(
            replace(request, brain_dump="Changed semantic input"),
            MODEL,
        )


@pytest.mark.parametrize("crash_point", ["after_journal_intent", "after_private_artifacts"])
def test_proposal_retries_a_recovered_before_semantic_lineage_with_only_winner_artifact(
    tmp_path: Path,
    crash_point: str,
) -> None:
    paths = _paths(tmp_path)
    seed = _lifecycle(tmp_path, clock="2026-08-23T10:00:00+00:00")
    brief = seed.prepare(
        PlanningRequest("create", "Need a safe proposal", "proposal-run"),
        MODEL,
    )
    command = SubmitProposalDraft(
        brief.run_id,
        "recover-proposal",
        brief.brief_context_digest,
        _proposal_draft(),
    )
    crashing = _lifecycle(
        tmp_path,
        clock="2026-08-23T12:00:00+00:00",
        crash_point=crash_point,
    )

    with pytest.raises(InjectedCrashError, match=crash_point):
        crashing.handle(PlanningCommand(MODEL, command))
    failed_intent = _journal_dicts(paths)[-1]
    lifecycle_payload = failed_intent["payload"]
    assert isinstance(lifecycle_payload, dict)
    lifecycle_event = lifecycle_payload["lifecycle"]
    assert isinstance(lifecycle_event, dict)
    failed_proposal_id = lifecycle_event["proposal_id"]
    assert isinstance(failed_proposal_id, str)

    report = PlanningRepository(paths, index_refresher=None).recover()
    assert [item.classification for item in report.recovered] == ["before"]
    assert not (paths.private_runs / brief.run_id / f"{failed_proposal_id}.json").exists()

    retrying = _lifecycle(tmp_path, clock="2026-08-23T13:00:00+00:00")
    winner = retrying.handle(PlanningCommand(MODEL, command))

    assert winner.proposal_id != failed_proposal_id
    assert winner.created_at == "2026-08-23T13:00:00+00:00"
    assert (
        _lifecycle(tmp_path, clock="2026-08-23T14:00:00+00:00").handle(
            PlanningCommand(MODEL, command)
        )
        == winner
    )
    assert (
        _lifecycle(tmp_path, clock="2026-08-23T15:00:00+00:00").inspect(
            ProposalRef(winner.proposal_id)
        )
        == winner
    )
    proposal_artifacts = sorted((paths.private_runs / brief.run_id).glob("*.json"))
    assert [path.name for path in proposal_artifacts] == [f"{winner.proposal_id}.json"]
    history = [
        event
        for event in _journal_dicts(paths)
        if event["idempotency_key"] == "proposal:recover-proposal"
    ]
    assert [event["event"] for event in history] == [
        "intent",
        "recovered",
        "intent",
        "committed",
    ]
    winning_payload = history[2]["payload"]
    assert isinstance(winning_payload, dict)
    winning_lifecycle = winning_payload["lifecycle"]
    assert isinstance(winning_lifecycle, dict)
    assert winning_lifecycle["proposal_id"] == winner.proposal_id

    changed = replace(command, draft=replace(command.draft, title="Changed proposal"))
    with pytest.raises(IdempotencyConflictError, match="different proposal draft"):
        _lifecycle(tmp_path, clock="2026-08-23T16:00:00+00:00").handle(
            PlanningCommand(MODEL, changed)
        )


def test_semantic_payload_change_is_rejected_after_committed_outcome(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    repository.commit(_private_intent())
    source = _journal_dicts(paths)[0]
    _append_forged_retry(
        paths,
        source,
        intent_id="forged-after-committed",
        payload_digest="sha256:v1:" + "1" * 64,
    )

    with pytest.raises(JournalCorruptionError, match="intent follows a terminal after outcome"):
        PlanningRepository(paths, index_refresher=None).recover()


def test_semantic_payload_change_is_rejected_after_recovered_after_outcome(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_replace"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError, match="after_replace"):
        crashing.commit(_semantic_plan_intent())
    restarted = PlanningRepository(paths, index_refresher=None)
    assert [item.classification for item in restarted.recover().recovered] == ["after"]
    source = _journal_dicts(paths)[0]
    _append_forged_retry(
        paths,
        source,
        intent_id="forged-after-recovered-after",
        payload_digest="sha256:v1:" + "2" * 64,
    )

    with pytest.raises(JournalCorruptionError, match="intent follows a terminal after outcome"):
        PlanningRepository(paths, index_refresher=None).recover()


def test_recovered_before_retry_rejects_a_different_semantic_digest(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_journal_intent"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError, match="after_journal_intent"):
        crashing.commit(_private_intent())
    restarted = PlanningRepository(paths, index_refresher=None)
    assert [item.classification for item in restarted.recover().recovered] == ["before"]
    source = _journal_dicts(paths)[0]
    _append_forged_retry(
        paths,
        source,
        intent_id="forged-different-semantics",
        payload_digest="sha256:v1:" + "3" * 64,
        idempotency_digest="sha256:v1:" + "f" * 64,
    )

    with pytest.raises(JournalCorruptionError, match="conflicting semantic digests"):
        PlanningRepository(paths, index_refresher=None).recover()


def test_recovered_before_retry_rejects_a_different_operation(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_journal_intent"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError, match="after_journal_intent"):
        crashing.commit(_private_intent())
    restarted = PlanningRepository(paths, index_refresher=None)
    assert [item.classification for item in restarted.recover().recovered] == ["before"]
    source = _journal_dicts(paths)[0]
    _append_forged_retry(
        paths,
        source,
        intent_id="forged-different-operation",
        payload_digest="sha256:v1:" + "5" * 64,
        operation="record",
    )

    with pytest.raises(
        JournalCorruptionError, match="semantic retry changes transaction operation"
    ):
        PlanningRepository(paths, index_refresher=None).recover()


def test_semantic_payload_change_is_rejected_for_parallel_intents(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_journal_intent"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError, match="after_journal_intent"):
        crashing.commit(_private_intent())
    source = _journal_dicts(paths)[0]
    _append_forged_retry(
        paths,
        source,
        intent_id="forged-parallel",
        payload_digest="sha256:v1:" + "4" * 64,
    )

    with pytest.raises(
        JournalCorruptionError, match="duplicate intent while another intent is pending"
    ):
        PlanningRepository(paths, index_refresher=None).recover()


def test_after_replace_recovery_fsyncs_plan_directory_before_terminal_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_replace"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError):
        crashing.commit(_intent())

    actions: list[tuple[str, object]] = []
    real_fsync = repository_module.fsync_directory
    real_append = repository_module.append_event

    def observe_fsync(path: Path) -> None:
        actions.append(("fsync", path))
        real_fsync(path)

    def observe_append(path: Path, event) -> None:
        actions.append(("event", event.event))
        real_append(path, event)

    monkeypatch.setattr(repository_module, "fsync_directory", observe_fsync)
    monkeypatch.setattr(repository_module, "append_event", observe_append)

    report = PlanningRepository(paths, index_refresher=None).recover()

    assert [item.classification for item in report.recovered] == ["after"]
    assert actions.index(("fsync", paths.plans)) < actions.index(("event", "recovered"))


def test_journal_rejects_forged_recovered_result_revisions(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_replace"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError):
        crashing.commit(_intent())

    restarted = PlanningRepository(paths, index_refresher=None)
    assert [item.classification for item in restarted.recover().recovered] == ["after"]
    events = [json.loads(line) for line in paths.journal.read_text().splitlines()]
    events[1]["result"]["document_revision"] = 99
    events[1]["result"]["structure_revision"] = 88
    paths.journal.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(JournalCorruptionError, match="result revisions"):
        restarted.commit(_intent())


def test_recovery_truncates_only_a_torn_intent_at_eof(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    paths.journal.write_bytes(b'{"schema_version":1,"event":"intent"')

    report = repository.recover()

    assert report.recovered == ()
    assert paths.journal.read_bytes() == b""


def test_recovery_repairs_torn_committed_tail_then_classifies_intent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    crashing = PlanningRepository(
        paths,
        crash_injector=_inject_at("after_directory_fsync"),
        index_refresher=None,
    )
    with pytest.raises(InjectedCrashError):
        crashing.commit(_intent())
    with paths.journal.open("ab") as journal:
        journal.write(b'{"schema_version":1,"event":"committed"')

    report = PlanningRepository(paths, index_refresher=None).recover()

    assert [item.classification for item in report.recovered] == ["after"]
    assert paths.journal.read_bytes().endswith(b"\n")
    events = [json.loads(line) for line in paths.journal.read_text().splitlines()]
    assert [event["event"] for event in events] == ["intent", "recovered"]


def test_recovery_completes_a_valid_final_event_missing_only_newline(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    repository.commit(_intent())
    paths.journal.write_bytes(paths.journal.read_bytes().removesuffix(b"\n"))

    assert repository.recover().recovered == ()
    assert paths.journal.read_bytes().endswith(b"\n")


def test_recovery_keeps_newline_terminated_or_interior_corruption_fail_closed(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    repository = PlanningRepository(paths, index_refresher=None)
    repository.commit(_intent())
    valid = paths.journal.read_bytes()
    for suffix in (b"{not-json}\n", b"{not-json}\n{}"):
        paths.journal.write_bytes(valid + suffix)
        with pytest.raises(JournalCorruptionError):
            repository.recover()


@pytest.mark.parametrize("crash_point", CRASH_POINTS)
def test_real_process_death_releases_lock_and_recovers_exact_state(
    tmp_path: Path, crash_point: str
) -> None:
    paths = _paths(tmp_path)
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_abrupt_crash_worker,
        args=(str(tmp_path), crash_point),
    )
    worker.start()
    worker.join(timeout=15)

    assert not worker.is_alive()
    assert worker.exitcode == 97
    _assert_lock_released(paths.lock_file)

    restarted = PlanningRepository(paths, index_refresher=None)
    report = restarted.recover()
    before_points = {"after_journal_intent", "after_temp_fsync"}
    after_points = {"after_replace", "after_directory_fsync"}
    if crash_point in before_points:
        assert [item.classification for item in report.recovered] == ["before"]
        assert not (paths.plans / "crash-plan.md").exists()
        assert restarted.commit(_intent()).status == "committed"
    elif crash_point in after_points:
        assert [item.classification for item in report.recovered] == ["after"]
        assert restarted.commit(_intent()).status == "replayed"
    else:
        assert report.recovered == ()
        assert restarted.commit(_intent()).status == "replayed"
    assert list(paths.plans.glob("*.tmp")) == []
