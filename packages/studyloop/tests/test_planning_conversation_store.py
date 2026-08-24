from __future__ import annotations

import multiprocessing
import stat
from pathlib import Path

import pytest

from studyloop.planning.contracts import PlanningRequest
from studyloop.planning.conversation_contracts import (
    AttachContext,
    BeginModelAttempt,
    CaptureLearnerTurn,
    CompleteModelAttempt,
    ConversationConflictError,
    ConversationRefusedError,
    FinalizeAssistantMessage,
    LearnerTurn,
    MarkAttemptInterrupted,
    PrepareCapabilityCall,
    PrepareDecisionIntent,
    ProjectCapabilityResult,
    ProjectDecisionResult,
)
from studyloop.planning.conversation_store import ConversationStore


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


def _store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "planning-conversations.sqlite3", ids=_Ids())


def _capture(store: ConversationStore, *, turn_id: str = "turn-1"):
    return store.capture_turn_and_freeze_context(
        CaptureLearnerTurn(
            "conversation-1",
            LearnerTurn(
                turn_id,
                "I want to understand protocols",
                PlanningRequest("create", "I want to understand protocols", "request-1"),
            ),
        )
    )


def test_context_is_ordered_frozen_and_post_freeze_attachment_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.attach_context(
        AttachContext("conversation-1", "context-1", "Course", "module one")
    )
    second = store.attach_context(
        AttachContext("conversation-1", "context-2", "Notes", "rough notes")
    )

    receipt = _capture(store)

    assert receipt.context_ids == (first.context_id, second.context_id)
    assert receipt.context_digests == (first.content_digest, second.content_digest)
    assert receipt.brief_context_digest.startswith("sha256:v1:")
    frozen_request = store.load_request("turn-1")
    assert tuple(
        (item.reference_id, item.content_digest, item.source_kind)
        for item in frozen_request.source_references
    ) == (
        (first.context_id, first.content_digest, "supplied_material"),
        (second.context_id, second.content_digest, "supplied_material"),
    )
    with pytest.raises(ConversationConflictError, match="frozen"):
        store.attach_context(AttachContext("conversation-1", "context-3", "Late", "too late"))


def test_turn_refuses_a_planning_request_for_different_learner_text(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ConversationRefusedError, match="brain dump"):
        store.capture_turn_and_freeze_context(
            CaptureLearnerTurn(
                "conversation-1",
                LearnerTurn(
                    "turn-1",
                    "The learner's actual text",
                    PlanningRequest("create", "different text", "request-1"),
                ),
            )
        )


def test_first_attempt_and_interrupted_retry_keep_turn_and_accumulate_history(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    receipt = _capture(store)
    first = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )
    interrupted = store.mark_attempt_interrupted(
        MarkAttemptInterrupted(
            "conversation-1",
            "turn-1",
            first.attempt_id,
            first.turn_version,
            "provider disconnected",
        )
    )
    second = store.begin_attempt(
        BeginModelAttempt(
            "conversation-1",
            "turn-1",
            interrupted.turn_version,
            first.attempt_id,
        )
    )

    assert (first.attempt_seq, second.attempt_seq) == (1, 2)
    assert first.attempt_id != second.attempt_id
    assert first.turn_id == second.turn_id == "turn-1"
    assert [item.status for item in store.list_attempts("turn-1")] == [
        "interrupted",
        "active",
    ]


def test_unresolved_capability_blocks_retry_without_allocating_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = _capture(store)
    first = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )
    store.prepare_capability_call(
        PrepareCapabilityCall(
            "conversation-1",
            "turn-1",
            first.attempt_id,
            "tool-1",
            "prepare_plan",
            {},
            "",
            "capability:key-1",
        )
    )
    interrupted = store.mark_attempt_interrupted(
        MarkAttemptInterrupted(
            "conversation-1", "turn-1", first.attempt_id, first.turn_version, "crash"
        )
    )

    with pytest.raises(ConversationConflictError, match="capability"):
        store.begin_attempt(
            BeginModelAttempt(
                "conversation-1",
                "turn-1",
                interrupted.turn_version,
                first.attempt_id,
            )
        )
    assert len(store.list_attempts("turn-1")) == 1


def test_final_message_and_outbox_are_atomic_and_monotonic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = _capture(store)
    attempt = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )

    message = store.finalize_assistant_message(
        FinalizeAssistantMessage(
            "conversation-1", "turn-1", attempt.attempt_id, "What matters most?"
        )
    )
    completed = store.complete_attempt(
        CompleteModelAttempt(
            "conversation-1",
            "turn-1",
            attempt.attempt_id,
            attempt.turn_version,
        )
    )

    assert message.outbox_seq == 1
    assert completed.status == "completed"
    events = store.replay_outbox("conversation-1", 0)
    assert [(event.sequence, event.event_type) for event in events] == [
        (1, "assistant_message"),
    ]
    store.acknowledge_outbox("conversation-1", 1)
    assert store.replay_outbox("conversation-1", 1) == []
    assert store.list_messages("conversation-1")[0].content == "What matters most?"


def test_attempt_cannot_complete_before_a_finalized_message(tmp_path: Path) -> None:
    store = _store(tmp_path)
    receipt = _capture(store)
    attempt = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )

    with pytest.raises(ConversationConflictError, match="finalized assistant message"):
        store.complete_attempt(
            CompleteModelAttempt(
                "conversation-1",
                "turn-1",
                attempt.attempt_id,
                attempt.turn_version,
            )
        )

    assert store.get_turn("conversation-1", "turn-1").status == "attempt_active"
    assert store.list_attempts("turn-1")[0].status == "active"


def test_capability_projection_is_atomic_idempotent_and_changed_replay_conflicts(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    receipt = _capture(store)
    attempt = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )
    command = PrepareCapabilityCall(
        "conversation-1",
        "turn-1",
        attempt.attempt_id,
        "tool-1",
        "prepare_plan",
        {},
        "",
        "capability:key-1",
    )
    intent = store.prepare_capability_call(command)
    assert intent.status == "prepared"
    projected = store.project_capability_result(
        ProjectCapabilityResult(intent.intent_id, "projected", {"run_id": "run-1"})
    )
    replay = store.project_capability_result(
        ProjectCapabilityResult(intent.intent_id, "projected", {"run_id": "run-1"})
    )

    assert replay == projected
    assert len(store.replay_outbox("conversation-1", 0)) == 1
    with pytest.raises(ConversationConflictError, match="different"):
        store.prepare_capability_call(
            PrepareCapabilityCall(
                "conversation-1",
                "turn-1",
                attempt.attempt_id,
                "tool-1",
                "prepare_plan",
                {"authority": "learner"},
                "",
                "capability:key-1",
            )
        )


def test_decision_intent_and_projection_use_exact_idempotent_replay(tmp_path: Path) -> None:
    store = _store(tmp_path)
    command = PrepareDecisionIntent(
        "conversation-1",
        "proposal-1",
        "sha256:v1:" + "a" * 64,
        "sha256:v1:" + "b" * 64,
        "sha256:v1:" + "c" * 64,
        "approve",
        "decision:key-1",
    )
    intent = store.prepare_decision_intent(command)
    projection = store.project_decision_result(
        ProjectDecisionResult(intent.intent_id, "projected", {"status": "applied"})
    )

    replayed_intent = store.prepare_decision_intent(command)
    assert replayed_intent.intent_id == intent.intent_id
    assert replayed_intent.status == "projected"
    assert (
        store.project_decision_result(
            ProjectDecisionResult(intent.intent_id, "projected", {"status": "applied"})
        )
        == projection
    )
    with pytest.raises(ConversationConflictError, match="different"):
        store.prepare_decision_intent(
            PrepareDecisionIntent(
                "conversation-1",
                "proposal-1",
                "sha256:v1:" + "a" * 64,
                "sha256:v1:" + "b" * 64,
                "sha256:v1:" + "c" * 64,
                "reject",
                "decision:key-1",
            )
        )


def test_database_and_live_sidecars_are_private(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _capture(store)
    store.database_path.chmod(0o666)
    store.ensure_private_modes()

    assert stat.S_IMODE(store.database_path.stat().st_mode) == 0o600
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{store.database_path}{suffix}")
        if sidecar.exists():
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def _begin_worker(
    path: str, barrier: multiprocessing.Barrier, queue: multiprocessing.Queue
) -> None:
    store = ConversationStore(Path(path))
    receipt = store.get_turn("conversation-1", "turn-1")
    barrier.wait()
    try:
        result = store.begin_attempt(
            BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
        )
        queue.put(("ok", result.attempt_id))
    except ConversationConflictError:
        queue.put(("conflict", ""))


def _retry_worker(
    path: str,
    turn_version: int,
    retry_of_attempt_id: str,
    barrier: multiprocessing.Barrier,
    queue: multiprocessing.Queue,
) -> None:
    store = ConversationStore(Path(path))
    barrier.wait()
    try:
        result = store.begin_attempt(
            BeginModelAttempt(
                "conversation-1",
                "turn-1",
                turn_version,
                retry_of_attempt_id,
            )
        )
        queue.put(("ok", result.attempt_seq))
    except ConversationConflictError:
        queue.put(("conflict", 0))


def _attach_race_worker(
    path: str, barrier: multiprocessing.Barrier, queue: multiprocessing.Queue
) -> None:
    store = ConversationStore(Path(path))
    barrier.wait()
    try:
        attachment = store.attach_context(
            AttachContext("conversation-1", "context-race", "Course", "race content")
        )
        queue.put(("attached", attachment.content_digest))
    except ConversationConflictError:
        queue.put(("frozen", ""))


def _capture_race_worker(
    path: str, barrier: multiprocessing.Barrier, queue: multiprocessing.Queue
) -> None:
    store = ConversationStore(Path(path))
    barrier.wait()
    receipt = _capture(store)
    queue.put(("captured", receipt.context_ids))


def test_two_process_initial_begin_has_one_cas_winner(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "planning-conversations.sqlite3")
    _capture(store)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(target=_begin_worker, args=(str(store.database_path), barrier, queue))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0
    outcomes = sorted(queue.get(timeout=2)[0] for _ in workers)

    assert outcomes == ["conflict", "ok"]
    attempts = store.list_attempts("turn-1")
    assert len(attempts) == 1 and attempts[0].attempt_seq == 1


def test_two_process_retry_has_one_cas_winner_and_monotonic_sequence(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "planning-conversations.sqlite3", ids=_Ids())
    receipt = _capture(store)
    first = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )
    interrupted = store.mark_attempt_interrupted(
        MarkAttemptInterrupted(
            "conversation-1", "turn-1", first.attempt_id, first.turn_version, "crash"
        )
    )
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(
            target=_retry_worker,
            args=(
                str(store.database_path),
                interrupted.turn_version,
                first.attempt_id,
                barrier,
                queue,
            ),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0

    assert sorted(queue.get(timeout=2)[0] for _ in workers) == ["conflict", "ok"]
    attempts = store.list_attempts("turn-1")
    assert [(item.attempt_seq, item.status) for item in attempts] == [
        (1, "interrupted"),
        (2, "active"),
    ]


def test_attach_and_capture_race_has_one_serialized_context_snapshot(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "planning-conversations.sqlite3")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(
            target=_attach_race_worker,
            args=(str(store.database_path), barrier, queue),
        ),
        context.Process(
            target=_capture_race_worker,
            args=(str(store.database_path), barrier, queue),
        ),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(15)
        assert worker.exitcode == 0
    outcomes = [queue.get(timeout=2), queue.get(timeout=2)]
    captured = next(payload for name, payload in outcomes if name == "captured")
    attach_state = next(name for name, _payload in outcomes if name != "captured")

    if attach_state == "attached":
        assert captured == ("context-race",)
    else:
        assert attach_state == "frozen" and captured == ()
    receipt = store.get_turn("conversation-1", "turn-1")
    assert receipt.brief_context_digest.startswith("sha256:v1:")


def test_production_conversation_store_uses_the_planning_root(tmp_path: Path) -> None:
    from studyloop.planning.runtime import planning_conversation_store

    store = planning_conversation_store(tmp_path / "documents")

    assert store.database_path == tmp_path / "planning-conversations.sqlite3"
