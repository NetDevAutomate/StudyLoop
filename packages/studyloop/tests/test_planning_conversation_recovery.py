from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from studyloop.planning.capabilities import PlanningCapabilityScope
from studyloop.planning.contracts import PlanningRequest
from studyloop.planning.conversation_contracts import (
    BeginModelAttempt,
    CaptureLearnerTurn,
    ConversationConflictError,
    LearnerTurn,
    MarkAttemptInterrupted,
    PrepareCapabilityCall,
)
from studyloop.planning.conversation_runtime import PlanningConversationRuntime
from studyloop.planning.conversation_store import ConversationStore
from studyloop.planning.lifecycle import PlanningLifecycle
from studyloop.planning.model_port import (
    MODEL_WIRE_VERSION,
    ModelTextDelta,
    ModelToolCall,
    ModelTurnCompleted,
)
from studyloop.planning.repository import PlanningPaths, PlanningRepository
from studyloop.planning.scripted_model import ScriptedPlanningModel, ScriptedResponse


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


class _Crash(BaseException):
    pass


class _CrashOnce:
    def __init__(self, point: str) -> None:
        self.point = point
        self.hit = False

    def __call__(self, point: str) -> None:
        if point == self.point and not self.hit:
            self.hit = True
            raise _Crash(point)


class _ProcessCrash:
    def __init__(self, point: str) -> None:
        self.point = point

    def __call__(self, point: str) -> None:
        if point == self.point:
            os._exit(79)


class _SignalPoint:
    def __init__(self, point: str, event) -> None:
        self.point = point
        self.event = event

    def __call__(self, point: str) -> None:
        if point == self.point:
            self.event.set()


class _ProviderErrorModel:
    async def stream(self, request):
        raise RuntimeError("provider connection ended")
        yield request  # pragma: no cover


class _FinalTextModel:
    async def stream(self, request):
        yield ModelTextDelta(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            1,
            "A finalized response",
        )
        yield ModelTurnCompleted(MODEL_WIRE_VERSION, request.turn_id, request.attempt_id, 2, "stop")


class _LiveProcessModel:
    def __init__(self, started, release) -> None:
        self.started = started
        self.release = release

    async def stream(self, request):
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.005)
        yield ModelTextDelta(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            1,
            "Live provider completed",
        )
        yield ModelTurnCompleted(
            MODEL_WIRE_VERSION,
            request.turn_id,
            request.attempt_id,
            2,
            "stop",
        )


def _root_lock_holder(root_text: str, held, release) -> None:
    repository = PlanningRepository(
        PlanningPaths.in_root(Path(root_text)),
        index_refresher=None,
    )
    with repository._root_lock():
        held.set()
        release.wait(10)


def _root_lock_blocked_attempt_worker(root_text: str, dispatch_started) -> None:
    root = Path(root_text)
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelToolCall(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        1,
                        "tool-1",
                        "prepare_plan",
                        {},
                    ),
                    ModelTurnCompleted(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        2,
                        "tool_calls",
                    ),
                ),
            ),
            ScriptedResponse(
                "turn-1",
                (
                    ModelTextDelta(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        1,
                        "Root-lock wait completed",
                    ),
                    ModelTurnCompleted(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        2,
                        "stop",
                    ),
                ),
            ),
        )
    )
    runtime = PlanningConversationRuntime(
        ConversationStore(
            root / "conversations.sqlite3",
            ids=_Ids(),
            attempt_lease_seconds=0.08,
        ),
        model,
        PlanningLifecycle(PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)),
        lease_heartbeat_seconds=0.01,
        crash_injector=_SignalPoint("before_lifecycle_dispatch", dispatch_started),
    )
    asyncio.run(
        runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    )


def _root_lock_blocked_recovery_worker(root_text: str) -> None:
    root = Path(root_text)
    runtime = PlanningConversationRuntime(
        ConversationStore(
            root / "conversations.sqlite3",
            attempt_lease_seconds=0.08,
        ),
        ScriptedPlanningModel(()),
        PlanningLifecycle(PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)),
        owner_id="recovery-owner",
        lease_heartbeat_seconds=0.01,
    )
    asyncio.run(runtime.recover("conversation-1"))


def _live_attempt_worker(root_text: str, started, release) -> None:
    root = Path(root_text)
    runtime = PlanningConversationRuntime(
        ConversationStore(
            root / "conversations.sqlite3",
            ids=_Ids(),
            attempt_lease_seconds=0.08,
        ),
        _LiveProcessModel(started, release),  # type: ignore[arg-type]
        PlanningLifecycle(PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)),
        lease_heartbeat_seconds=0.01,
    )
    asyncio.run(
        runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    )


def _crash_worker(root_text: str, point: str) -> None:
    root = Path(root_text)
    store = ConversationStore(
        root / "conversations.sqlite3",
        ids=_Ids(),
        attempt_lease_seconds=0.01,
    )
    lifecycle = PlanningLifecycle(
        PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
    )
    if point == "before_durable_interruption":
        model = _ProviderErrorModel()
    elif point in {
        "before_finalized_message_commit",
        "after_finalized_message_commit",
        "before_attempt_complete",
        "after_attempt_complete",
    }:
        model = _FinalTextModel()
    else:
        model = ScriptedPlanningModel(
            (
                ScriptedResponse(
                    "turn-1",
                    (
                        ModelToolCall(
                            MODEL_WIRE_VERSION,
                            "turn-1",
                            "attempt-1",
                            1,
                            "tool-1",
                            "prepare_plan",
                            {},
                        ),
                        ModelTurnCompleted(
                            MODEL_WIRE_VERSION,
                            "turn-1",
                            "attempt-1",
                            2,
                            "tool_calls",
                        ),
                    ),
                ),
            )
        )
    runtime = PlanningConversationRuntime(
        store,
        model,  # type: ignore[arg-type]
        lifecycle,
        crash_injector=_ProcessCrash(point),
    )
    asyncio.run(
        runtime.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    )


def _retry_crash_worker(root_text: str, point: str, expected_version: int) -> None:
    root = Path(root_text)
    runtime = PlanningConversationRuntime(
        ConversationStore(root / "conversations.sqlite3", attempt_lease_seconds=0.01),
        ScriptedPlanningModel(()),
        PlanningLifecycle(PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)),
        crash_injector=_ProcessCrash(point),
    )
    asyncio.run(
        runtime.retry_turn(
            "conversation-1",
            "turn-1",
            expected_turn_version=expected_version,
        )
    )


@pytest.mark.asyncio
async def test_recovery_projects_journalled_capability_once_before_retry(tmp_path: Path) -> None:
    root = tmp_path / "planning"
    lifecycle = PlanningLifecycle(
        PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
    )
    store = ConversationStore(
        root / "conversations.sqlite3",
        ids=_Ids(),
        attempt_lease_seconds=0.01,
    )
    model = ScriptedPlanningModel(
        (
            ScriptedResponse(
                "turn-1",
                (
                    ModelToolCall(
                        MODEL_WIRE_VERSION,
                        "turn-1",
                        "attempt-1",
                        1,
                        "tool-1",
                        "prepare_plan",
                        {},
                    ),
                    ModelTurnCompleted(MODEL_WIRE_VERSION, "turn-1", "attempt-1", 2, "tool_calls"),
                ),
            ),
        )
    )
    crashed = PlanningConversationRuntime(
        store,
        model,
        lifecycle,
        crash_injector=_CrashOnce("after_lifecycle_dispatch"),
    )
    with pytest.raises(_Crash):
        await crashed.accept_turn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    await asyncio.sleep(0.02)

    recovered = await PlanningConversationRuntime(
        ConversationStore(root / "conversations.sqlite3"),
        ScriptedPlanningModel(()),
        PlanningLifecycle(PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)),
    ).recover("conversation-1")

    assert recovered.interrupted_attempt_ids == ("attempt-1",)
    projected_intent = store.list_capability_intents("turn-1")[0]
    assert recovered.projected_capability_ids == (projected_intent.intent_id,)
    assert len(store.replay_outbox("conversation-1", 0)) == 2
    assert store.list_capability_intents("turn-1")[0].status == "projected"


def test_second_process_recovery_and_retry_cannot_interrupt_a_live_provider(
    tmp_path: Path,
) -> None:
    root = tmp_path / "live-race"
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    release = context.Event()
    worker = context.Process(
        target=_live_attempt_worker,
        args=(str(root), started, release),
    )
    worker.start()
    assert started.wait(10)
    time.sleep(0.2)

    store = ConversationStore(
        root / "conversations.sqlite3",
        attempt_lease_seconds=0.08,
    )
    before = store.get_turn("conversation-1", "turn-1")
    assert before.status == "attempt_active"
    second = PlanningConversationRuntime(
        store,
        ScriptedPlanningModel(()),
        PlanningLifecycle(PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)),
    )
    try:
        recovered = asyncio.run(second.recover("conversation-1"))
        try:
            asyncio.run(
                second.retry_turn(
                    "conversation-1",
                    "turn-1",
                    expected_turn_version=before.turn_version,
                )
            )
        except ConversationConflictError as exc:
            retry_conflict = str(exc)
        else:
            retry_conflict = ""
        after = store.get_turn("conversation-1", "turn-1")
        attempt_statuses = [item.status for item in store.list_attempts("turn-1")]
    finally:
        release.set()
        worker.join(15)

    assert "retry" in retry_conflict
    assert recovered.interrupted_attempt_ids == ()
    assert (after.status, after.turn_version) == ("attempt_active", before.turn_version)
    assert attempt_statuses == ["active"]
    assert worker.exitcode == 0
    assert store.get_turn("conversation-1", "turn-1").status == "completed"
    assert [item.content for item in store.list_messages("conversation-1")] == [
        "Live provider completed"
    ]


def test_root_lock_wait_longer_than_lease_keeps_live_dispatch_owned_once(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root-lock-race"
    context = multiprocessing.get_context("spawn")
    lock_held = context.Event()
    release_lock = context.Event()
    holder = context.Process(
        target=_root_lock_holder,
        args=(str(root), lock_held, release_lock),
    )
    holder.start()
    assert lock_held.wait(10)

    dispatch_started = context.Event()
    worker = context.Process(
        target=_root_lock_blocked_attempt_worker,
        args=(str(root), dispatch_started),
    )
    worker.start()
    assert dispatch_started.wait(10)
    store = ConversationStore(
        root / "conversations.sqlite3",
        attempt_lease_seconds=0.08,
    )
    assert [item.status for item in store.list_capability_intents("turn-1")] == ["dispatching"]

    time.sleep(0.2)
    recovered = asyncio.run(
        PlanningConversationRuntime(
            store,
            ScriptedPlanningModel(()),
            PlanningLifecycle(
                PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
            ),
        ).recover("conversation-1")
    )
    during_wait = store.get_turn("conversation-1", "turn-1")
    release_lock.set()
    holder.join(10)
    worker.join(15)

    assert recovered.interrupted_attempt_ids == ()
    assert during_wait.status == "attempt_active"
    assert holder.exitcode == 0
    assert worker.exitcode == 0
    assert [item.status for item in store.list_attempts("turn-1")] == ["completed"]
    assert [item.status for item in store.list_capability_intents("turn-1")] == ["projected"]
    event_types = [event.event_type for event in store.replay_outbox("conversation-1", 0)]
    assert event_types.count("capability_result") == 1
    assert event_types.count("assistant_message") == 1


def test_recovery_renews_claim_while_real_root_lock_blocks_lifecycle(
    tmp_path: Path,
) -> None:
    root = tmp_path / "recovery-root-lock-race"
    store = ConversationStore(
        root / "conversations.sqlite3",
        ids=_Ids(),
        attempt_lease_seconds=0.08,
    )
    receipt = store.capture_turn_and_freeze_context(
        CaptureLearnerTurn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    )
    attempt = store.begin_attempt(
        BeginModelAttempt(
            "conversation-1",
            "turn-1",
            receipt.turn_version,
            None,
            "dead-owner",
        )
    )
    scope_key = PlanningCapabilityScope(
        "conversation-1", "turn-1", attempt.attempt_id
    ).lifecycle_idempotency_key(
        run_id="",
        tool_call_id="tool-1",
    )
    store.prepare_capability_call(
        PrepareCapabilityCall(
            "conversation-1",
            "turn-1",
            attempt.attempt_id,
            "tool-1",
            "prepare_plan",
            {},
            "",
            scope_key,
            attempt.owner_id,
        )
    )
    time.sleep(0.1)
    context = multiprocessing.get_context("spawn")
    lock_held = context.Event()
    release_lock = context.Event()
    holder = context.Process(
        target=_root_lock_holder,
        args=(str(root), lock_held, release_lock),
    )
    holder.start()
    assert lock_held.wait(10)
    recovery = context.Process(
        target=_root_lock_blocked_recovery_worker,
        args=(str(root),),
    )
    recovery.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = store.active_attempts("conversation-1")
        intents = store.list_capability_intents("turn-1")
        if (
            current
            and current[0].owner_id == "recovery-owner"
            and intents
            and intents[0].status == "dispatching"
        ):
            break
        time.sleep(0.01)
    else:
        release_lock.set()
        holder.join(10)
        recovery.join(10)
        pytest.fail("recovery did not claim and reach lifecycle dispatch")

    time.sleep(0.2)
    competing = asyncio.run(
        PlanningConversationRuntime(
            ConversationStore(root / "conversations.sqlite3"),
            ScriptedPlanningModel(()),
            PlanningLifecycle(
                PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
            ),
        ).recover("conversation-1")
    )
    release_lock.set()
    holder.join(10)
    recovery.join(15)

    assert competing.interrupted_attempt_ids == ()
    assert holder.exitcode == 0
    assert recovery.exitcode == 0
    assert [item.status for item in store.list_attempts("turn-1")] == ["interrupted"]
    assert [item.status for item in store.list_capability_intents("turn-1")] == ["projected"]
    event_types = [event.event_type for event in store.replay_outbox("conversation-1", 0)]
    assert event_types.count("capability_result") == 1
    assert event_types.count("attempt_interrupted") == 1


@pytest.mark.parametrize(
    ("crash_point", "expect_projection"),
    [
        ("before_capability_intent_commit", False),
        ("after_capability_intent_commit", True),
        ("before_lifecycle_dispatch", True),
        ("after_lifecycle_dispatch", True),
        ("before_result_projection", True),
        ("after_result_projection", False),
        ("before_durable_interruption", False),
    ],
)
def test_real_subprocess_crash_boundaries_reconcile_once(
    tmp_path: Path,
    crash_point: str,
    expect_projection: bool,
) -> None:
    root = tmp_path / crash_point
    context = multiprocessing.get_context("spawn")
    worker = context.Process(target=_crash_worker, args=(str(root), crash_point))
    worker.start()
    worker.join(20)
    assert worker.exitcode == 79
    time.sleep(0.03)

    store = ConversationStore(root / "conversations.sqlite3")
    lifecycle = PlanningLifecycle(
        PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
    )
    result = asyncio.run(
        PlanningConversationRuntime(
            store,
            ScriptedPlanningModel(()),
            lifecycle,
        ).recover("conversation-1")
    )

    assert len(result.interrupted_attempt_ids) == 1
    intents = store.list_capability_intents("turn-1")
    if crash_point in {"before_capability_intent_commit", "before_durable_interruption"}:
        assert intents == []
    else:
        assert len(intents) == 1 and intents[0].status == "projected"
    assert bool(result.projected_capability_ids) is expect_projection
    assert [item.status for item in store.list_attempts("turn-1")] == ["interrupted"]
    event_types = [item.event_type for item in store.replay_outbox("conversation-1", 0)]
    assert event_types.count("attempt_interrupted") == 1
    assert event_types.count("capability_result") == (1 if intents else 0)


@pytest.mark.parametrize(
    ("crash_point", "expected_attempt_count"),
    [("before_retry_cas", 1), ("after_retry_cas", 2)],
)
def test_real_subprocess_crash_around_retry_cas_preserves_attempt_history(
    tmp_path: Path,
    crash_point: str,
    expected_attempt_count: int,
) -> None:
    root = tmp_path / crash_point
    store = ConversationStore(
        root / "conversations.sqlite3",
        ids=_Ids(),
        attempt_lease_seconds=0.01,
    )
    receipt = store.capture_turn_and_freeze_context(
        CaptureLearnerTurn(
            "conversation-1",
            LearnerTurn("turn-1", "A dump", PlanningRequest("create", "A dump", "request-1")),
        )
    )
    first = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )
    interrupted = store.mark_attempt_interrupted(
        MarkAttemptInterrupted(
            "conversation-1",
            "turn-1",
            first.attempt_id,
            first.turn_version,
            "crash",
            first.owner_id,
        )
    )
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_retry_crash_worker,
        args=(str(root), crash_point, interrupted.turn_version),
    )
    worker.start()
    worker.join(20)
    assert worker.exitcode == 79
    time.sleep(0.03)

    result = asyncio.run(
        PlanningConversationRuntime(
            ConversationStore(root / "conversations.sqlite3"),
            ScriptedPlanningModel(()),
            PlanningLifecycle(
                PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
            ),
        ).recover("conversation-1")
    )
    attempts = store.list_attempts("turn-1")
    assert len(attempts) == expected_attempt_count
    assert [item.attempt_seq for item in attempts] == list(range(1, expected_attempt_count + 1))
    assert all(item.status == "interrupted" for item in attempts)
    assert len(result.interrupted_attempt_ids) == expected_attempt_count - 1


@pytest.mark.parametrize(
    ("crash_point", "expected_status", "recovery_completes"),
    [
        ("before_finalized_message_commit", "interrupted", False),
        ("after_finalized_message_commit", "completed", True),
        ("before_attempt_complete", "completed", True),
        ("after_attempt_complete", "completed", False),
    ],
)
def test_real_subprocess_final_message_boundaries_are_classified_without_regeneration(
    tmp_path: Path,
    crash_point: str,
    expected_status: str,
    recovery_completes: bool,
) -> None:
    root = tmp_path / crash_point
    context = multiprocessing.get_context("spawn")
    worker = context.Process(target=_crash_worker, args=(str(root), crash_point))
    worker.start()
    worker.join(20)
    assert worker.exitcode == 79
    time.sleep(0.03)

    store = ConversationStore(root / "conversations.sqlite3")
    result = asyncio.run(
        PlanningConversationRuntime(
            store,
            ScriptedPlanningModel(()),
            PlanningLifecycle(
                PlanningRepository(PlanningPaths.in_root(root), index_refresher=None)
            ),
        ).recover("conversation-1")
    )

    attempts = store.list_attempts("turn-1")
    assert [item.status for item in attempts] == [expected_status]
    assert bool(result.completed_attempt_ids) is recovery_completes
    messages = store.list_messages("conversation-1")
    assert len(messages) == (0 if expected_status == "interrupted" else 1)
    event_types = [event.event_type for event in store.replay_outbox("conversation-1", 0)]
    if expected_status == "interrupted":
        assert event_types == ["attempt_interrupted"]
    else:
        assert event_types == ["assistant_message"]
