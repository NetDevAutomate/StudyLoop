"""Crash-injection and deterministic journal recovery contracts."""

from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
from pathlib import Path

import pytest

import studyloop.planning.repository as repository_module
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
