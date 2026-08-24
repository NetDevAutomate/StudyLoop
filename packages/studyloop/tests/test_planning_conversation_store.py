from __future__ import annotations

import multiprocessing
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path
from typing import Any, Protocol

import pytest

from studyloop.planning import conversation_store as conversation_store_module
from studyloop.planning.contracts import PlanningRequest, SourceReference
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
from studyloop.planning.repository import PathContainmentError


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


class _Barrier(Protocol):
    def wait(self) -> int: ...


class _Queue(Protocol):
    def put(self, item: object) -> None: ...


class _MigrationProcessCrash:
    def __init__(self, point: str) -> None:
        self.point = point

    def __call__(self, point: str) -> None:
        if point == self.point:
            os._exit(79)


def _migration_crash_worker(database_text: str, point: str) -> None:
    ConversationStore(
        Path(database_text),
        migration_crash_injector=_MigrationProcessCrash(point),
    )


def _attempt_delete_journal_mode(database_text: str, results: Any) -> None:
    try:
        connection = sqlite3.connect(database_text, timeout=0.1)
        try:
            mode = str(connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0])
        finally:
            connection.close()
    except sqlite3.OperationalError as error:
        results.put(("blocked", str(error)))
    else:
        results.put(("changed", mode))


def _journal_delete_result(database: Path) -> tuple[str, str]:
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    worker = context.Process(
        target=_attempt_delete_journal_mode,
        args=(str(database), results),
    )
    worker.start()
    worker.join(10)
    assert worker.exitcode == 0
    value = results.get(timeout=2)
    results.close()
    return value


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


@pytest.mark.parametrize(
    "variant",
    ["empty", "shorter", "longer", "reordered", "changed"],
)
def test_same_turn_replay_requires_the_exact_original_source_references(
    tmp_path: Path,
    variant: str,
) -> None:
    store = _store(tmp_path)
    store.attach_context(
        AttachContext("conversation-1", "attached-1", "Selected notes", "notes body")
    )
    first = SourceReference("source-1", "digest-1", "supplied_material", "Course one")
    second = SourceReference("source-2", "digest-2", "supplied_material", "Course two")
    original = (first, second)
    learner = "I want to understand protocols"
    initial = store.capture_turn_and_freeze_context(
        CaptureLearnerTurn(
            "conversation-1",
            LearnerTurn(
                "turn-1",
                learner,
                PlanningRequest("create", learner, "request-1", source_references=original),
            ),
        )
    )
    reopened = ConversationStore(store.database_path)
    replay = reopened.capture_turn_and_freeze_context(
        CaptureLearnerTurn(
            "conversation-1",
            LearnerTurn(
                "turn-1",
                learner,
                PlanningRequest("create", learner, "request-1", source_references=original),
            ),
        )
    )
    assert replay == initial
    assert [item.reference_id for item in reopened.load_request("turn-1").source_references] == [
        "source-1",
        "source-2",
        "attached-1",
    ]

    changed = {
        "empty": (),
        "shorter": (first,),
        "longer": (
            first,
            second,
            SourceReference("source-3", "digest-3", "supplied_material", "Course three"),
        ),
        "reordered": (second, first),
        "changed": (
            first,
            SourceReference("source-2", "different", "supplied_material", "Course two"),
        ),
    }[variant]
    with pytest.raises(ConversationConflictError, match="different input"):
        reopened.capture_turn_and_freeze_context(
            CaptureLearnerTurn(
                "conversation-1",
                LearnerTurn(
                    "turn-1",
                    learner,
                    PlanningRequest(
                        "create",
                        learner,
                        "request-1",
                        source_references=changed,
                    ),
                ),
            )
        )


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("turns", "inbound_request_json"),
        ("turns", "inbound_request_digest"),
        ("turns", "inbound_source_reference_count"),
        ("attempts", "owner_id"),
        ("attempts", "lease_expires_at"),
    ],
)
def test_hardening_migration_resumes_each_independently_missing_column(
    tmp_path: Path,
    table: str,
    column: str,
) -> None:
    database = tmp_path / f"partial-{column}.sqlite3"
    ConversationStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")

    store = ConversationStore(database, ids=_Ids())
    receipt = _capture(store)
    attempt = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )

    assert attempt.status == "active"


@pytest.mark.parametrize(
    ("table", "column", "crash_point"),
    [
        ("turns", "inbound_request_json", "after_add_turns_inbound_request_json"),
        ("turns", "inbound_request_digest", "after_add_turns_inbound_request_digest"),
        (
            "turns",
            "inbound_source_reference_count",
            "after_add_turns_inbound_source_reference_count",
        ),
        ("turns", "inbound_replay_state", "after_add_turns_inbound_replay_state"),
        ("attempts", "owner_id", "after_add_attempts_owner_id"),
        ("attempts", "lease_expires_at", "after_add_attempts_lease_expires_at"),
    ],
)
def test_hardening_schema_migration_rolls_back_and_restarts_after_process_death(
    tmp_path: Path,
    table: str,
    column: str,
    crash_point: str,
) -> None:
    database = tmp_path / f"crash-{column}.sqlite3"
    ConversationStore(database)
    with sqlite3.connect(database) as connection:
        columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
        if column in columns:
            connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_migration_crash_worker,
        args=(str(database), crash_point),
    )
    worker.start()
    worker.join(15)

    assert worker.exitcode == 79
    store = ConversationStore(database, ids=_Ids())
    receipt = _capture(store)
    assert (
        store.begin_attempt(
            BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
        ).status
        == "active"
    )


def test_legacy_attachment_id_collision_is_readable_but_exact_replay_is_unavailable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-collision.sqlite3"
    store = ConversationStore(database, ids=_Ids())
    attachment = store.attach_context(
        AttachContext("conversation-1", "shared-id", "Selected notes", "notes body")
    )
    learner = "I want to understand protocols"
    original_reference = SourceReference(
        attachment.context_id,
        attachment.content_digest,
        "supplied_material",
        attachment.label,
    )
    original_turn = LearnerTurn(
        "turn-1",
        learner,
        PlanningRequest(
            "create",
            learner,
            "request-1",
            source_references=(original_reference,),
        ),
    )
    store.capture_turn_and_freeze_context(CaptureLearnerTurn("conversation-1", original_turn))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE turns SET inbound_request_json='',inbound_request_digest='',"
            "inbound_source_reference_count=0"
        )

    migrated = ConversationStore(database)

    assert [item.reference_id for item in migrated.load_request("turn-1").source_references] == [
        "shared-id"
    ]
    with pytest.raises(ConversationConflictError, match=r"exact replay unavailable.*legacy"):
        migrated.capture_turn_and_freeze_context(
            CaptureLearnerTurn("conversation-1", original_turn)
        )
    with sqlite3.connect(database) as connection:
        inbound_json, replay_state = connection.execute(
            "SELECT inbound_request_json,inbound_replay_state FROM turns WHERE turn_id='turn-1'"
        ).fetchone()
    assert inbound_json == ""
    assert replay_state == "unavailable"


def test_legacy_replay_classification_rolls_back_and_restarts_after_process_death(
    tmp_path: Path,
) -> None:
    database = tmp_path / "classification-crash.sqlite3"
    store = ConversationStore(database)
    _capture(store)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE turns SET inbound_request_digest=''")
    context = multiprocessing.get_context("spawn")
    worker = context.Process(
        target=_migration_crash_worker,
        args=(str(database), "after_legacy_replay_classification"),
    )
    worker.start()
    worker.join(15)

    assert worker.exitcode == 79
    migrated = ConversationStore(database)
    with pytest.raises(ConversationConflictError, match=r"exact replay unavailable.*legacy"):
        _capture(migrated)


def test_complete_hardening_schema_reopens_without_a_write_migration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "complete-schema.sqlite3"
    store = ConversationStore(database)
    _capture(store)

    def unexpected_migration_write(point: str) -> None:
        raise AssertionError(f"steady-state reopen reached migration write point {point}")

    reopened = ConversationStore(
        database,
        migration_crash_injector=unexpected_migration_write,
    )

    assert reopened.get_turn("conversation-1", "turn-1").status == "ready"


@pytest.mark.parametrize(
    "label",
    [
        "Course from /secret (selected)",
        "Selected ~/secret for planning",
        "Course from /Users/alice/private/course.md (selected)",
        r"Imported from C:\\Users\\alice\\course.txt today",
        "Loaded (file:///srv/studyloop/course.txt), selected",
        "Fetched via http://127.0.0.1:4000/internal/source.",
        "Fetched via https://192.168.1.9:8443/course, selected",
        "Gateway localhost:4000 (local)",
        "Gateway 10.1.2.3:8080; local",
        "Gateway [::1]:4000; local",
        "Gateway [fd00::1234]:8080 (private)",
    ],
)
def test_context_metadata_redacts_embedded_server_locations_before_persistence(
    tmp_path: Path,
    label: str,
) -> None:
    store = _store(tmp_path)

    attached = store.attach_context(
        AttachContext("conversation-1", "context-1", label, "learner-selected body")
    )

    assert attached.label == "selected text context"
    _capture(store)
    assert store.load_context("turn-1")[0].label == "selected text context"


@pytest.mark.parametrize("target_kind", ["database", "wal", "shm"])
def test_conversation_store_rejects_symlinked_sqlite_targets_before_open(
    tmp_path: Path,
    target_kind: str,
) -> None:
    root = tmp_path / "planning"
    root.mkdir()
    database = root / "planning-conversations.sqlite3"
    suffix = {"database": "", "wal": "-wal", "shm": "-shm"}[target_kind]
    outside = tmp_path / f"outside-{target_kind}.sqlite3"
    Path(f"{database}{suffix}").symlink_to(outside)

    with pytest.raises(PathContainmentError, match="symlink"):
        ConversationStore(database)

    assert not outside.exists()


def test_conversation_store_rejects_a_symlinked_planning_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_root = tmp_path / "linked-planning"
    linked_root.symlink_to(outside, target_is_directory=True)
    database = linked_root / "planning-conversations.sqlite3"

    with pytest.raises(PathContainmentError, match="planning root"):
        ConversationStore(database)

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("swap_target", ["database", "parent"])
def test_conversation_store_detects_identity_swap_during_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap_target: str,
) -> None:
    root = tmp_path / "planning"
    root.mkdir()
    database = root / "planning-conversations.sqlite3"
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    outside_database = outside_root / database.name
    with sqlite3.connect(outside_database) as connection:
        connection.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel VALUES ('unchanged')")
    outside_before = outside_database.read_bytes()
    real_connect = sqlite3.connect
    swapped = False

    def racing_connect(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and database.name in os.fspath(path):
            swapped = True
            if swap_target == "database":
                database.unlink(missing_ok=True)
                database.symlink_to(outside_database)
            else:
                displaced = tmp_path / "displaced-planning"
                root.rename(displaced)
                root.symlink_to(outside_root, target_is_directory=True)
            return real_connect(path, *args, **kwargs)
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(conversation_store_module.sqlite3, "connect", racing_connect)

    with pytest.raises(PathContainmentError, match=r"changed|identity|symlink"):
        ConversationStore(database)

    assert swapped
    assert outside_database.read_bytes() == outside_before


@pytest.mark.parametrize("swap_target", ["database", "parent"])
def test_conversation_store_identity_swap_cannot_create_an_absent_outside_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap_target: str,
) -> None:
    root = tmp_path / "planning"
    root.mkdir()
    database = root / "planning-conversations.sqlite3"
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    outside_database = outside_root / database.name
    real_connect = sqlite3.connect
    swapped = False

    def racing_connect(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and database.name in os.fspath(path):
            swapped = True
            if swap_target == "database":
                database.unlink(missing_ok=True)
                database.symlink_to(outside_database)
            else:
                displaced = tmp_path / "displaced-planning"
                root.rename(displaced)
                root.symlink_to(outside_root, target_is_directory=True)
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(conversation_store_module.sqlite3, "connect", racing_connect)

    with pytest.raises(PathContainmentError, match=r"changed|identity|symlink"):
        ConversationStore(database)

    assert swapped
    assert not outside_database.exists()


@pytest.mark.parametrize("second_operation", ["list", "modes"])
def test_cross_store_operation_cannot_release_a_live_wal_reader_lock(
    tmp_path: Path,
    second_operation: str,
) -> None:
    database = tmp_path / "planning-conversations.sqlite3"
    first = ConversationStore(database)
    second = ConversationStore(database)
    _capture(first)
    reader = first._connect()
    worker_errors: list[BaseException] = []
    started = threading.Event()

    def use_second_store() -> None:
        started.set()
        try:
            if second_operation == "list":
                second.list_turns("conversation-1")
            else:
                second.ensure_private_modes()
        except BaseException as error:
            worker_errors.append(error)

    worker = threading.Thread(target=use_second_store)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM turns").fetchone()
        assert _journal_delete_result(database)[0] == "blocked"

        worker.start()
        assert started.wait(2)
        time.sleep(0.05)

        assert worker.is_alive()
        assert _journal_delete_result(database)[0] == "blocked"
    finally:
        reader.close()
        worker.join(5)

    assert not worker.is_alive()
    assert worker_errors == []
    assert _journal_delete_result(database)[0] == "changed"


@pytest.mark.parametrize("nested_operation", ["connect", "modes"])
def test_same_thread_nested_store_use_preserves_a_live_wal_reader_lock(
    tmp_path: Path,
    nested_operation: str,
) -> None:
    database = tmp_path / "planning-conversations.sqlite3"
    first = ConversationStore(database)
    second = ConversationStore(database)
    _capture(first)
    reader = first._connect()
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM turns").fetchone()
        assert _journal_delete_result(database)[0] == "blocked"

        if nested_operation == "connect":
            nested = second._connect()
            nested.close()
        else:
            second.ensure_private_modes()

        assert _journal_delete_result(database)[0] == "blocked"
    finally:
        reader.close()

    assert _journal_delete_result(database)[0] == "changed"


@pytest.mark.parametrize("target_kind", ["database", "wal", "shm"])
def test_private_mode_enforcement_does_not_follow_check_chmod_target_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    database = tmp_path / "planning-conversations.sqlite3"
    store = ConversationStore(database)
    suffix = {"database": "", "wal": "-wal", "shm": "-shm"}[target_kind]
    target = Path(f"{database}{suffix}")
    target.touch(exist_ok=True)
    outside = tmp_path / f"outside-{target_kind}"
    outside.write_text("outside", encoding="utf-8")
    outside.chmod(0o644)
    real_open = os.open
    swapped = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and dir_fd is not None and os.fspath(path) == target.name:
            swapped = True
            target.unlink()
            target.symlink_to(outside)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(conversation_store_module.os, "open", racing_open)

    with pytest.raises(PathContainmentError, match=r"symlink|changed|regular"):
        store.ensure_private_modes()

    assert swapped
    assert stat.S_IMODE(outside.stat().st_mode) == 0o644


def test_private_mode_enforcement_tolerates_a_disappearing_sqlite_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "planning-conversations.sqlite3"
    store = ConversationStore(database)
    wal = Path(f"{database}-wal")
    wal.touch()
    real_stat = os.stat
    wal_stat_calls = 0

    def racing_stat(path, *args, **kwargs):
        nonlocal wal_stat_calls
        if kwargs.get("dir_fd") is not None and os.fspath(path) == wal.name:
            wal_stat_calls += 1
            if wal_stat_calls == 2:
                wal.unlink()
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(conversation_store_module.os, "stat", racing_stat)

    store.ensure_private_modes()

    assert wal_stat_calls == 2
    assert not wal.exists()


def test_planning_parent_mode_enforcement_uses_stable_directory_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "planning"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o755)
    database = root / "planning-conversations.sqlite3"
    real_open = os.open
    swapped = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and dir_fd is None and Path(path) == root:
            swapped = True
            displaced = tmp_path / "displaced-root"
            root.rename(displaced)
            root.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(conversation_store_module.os, "open", racing_open)

    with pytest.raises(PathContainmentError, match=r"planning root|symlink|changed"):
        ConversationStore(database)

    assert swapped
    assert stat.S_IMODE(outside.stat().st_mode) == 0o755


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
            first.owner_id,
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
            first.owner_id,
        )
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
            "conversation-1",
            "turn-1",
            attempt.attempt_id,
            "What matters most?",
            attempt.owner_id,
        )
    )
    completed = store.complete_attempt(
        CompleteModelAttempt(
            "conversation-1",
            "turn-1",
            attempt.attempt_id,
            attempt.turn_version,
            attempt.owner_id,
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
                attempt.owner_id,
            )
        )

    assert store.get_turn("conversation-1", "turn-1").status == "attempt_active"
    assert store.list_attempts("turn-1")[0].status == "active"


def test_terminal_attempt_transitions_require_the_durable_owner(tmp_path: Path) -> None:
    interrupted_store = ConversationStore(
        tmp_path / "interrupted" / "conversations.sqlite3",
        ids=_Ids(),
    )
    receipt = _capture(interrupted_store)
    attempt = interrupted_store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )
    with pytest.raises(ConversationConflictError, match="ownership"):
        interrupted_store.mark_attempt_interrupted(
            MarkAttemptInterrupted(
                "conversation-1",
                "turn-1",
                attempt.attempt_id,
                attempt.turn_version,
                "unowned interruption",
            )
        )
    assert interrupted_store.list_attempts("turn-1")[0].status == "active"

    completed_store = ConversationStore(
        tmp_path / "completed" / "conversations.sqlite3",
        ids=_Ids(),
    )
    receipt = _capture(completed_store)
    attempt = completed_store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )
    completed_store.finalize_assistant_message(
        FinalizeAssistantMessage(
            "conversation-1",
            "turn-1",
            attempt.attempt_id,
            "Final response",
            attempt.owner_id,
        )
    )
    with pytest.raises(ConversationConflictError, match="ownership"):
        completed_store.complete_attempt(
            CompleteModelAttempt(
                "conversation-1",
                "turn-1",
                attempt.attempt_id,
                attempt.turn_version,
            )
        )
    assert completed_store.list_attempts("turn-1")[0].status == "active"


def test_active_attempt_messages_and_capability_intents_require_the_durable_owner(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    receipt = _capture(store)
    attempt = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )

    with pytest.raises(ConversationConflictError, match="ownership"):
        store.finalize_assistant_message(
            FinalizeAssistantMessage(
                "conversation-1",
                "turn-1",
                attempt.attempt_id,
                "Unowned final response",
            )
        )
    with pytest.raises(ConversationConflictError, match="ownership"):
        store.prepare_capability_call(
            PrepareCapabilityCall(
                "conversation-1",
                "turn-1",
                attempt.attempt_id,
                "tool-1",
                "prepare_plan",
                {},
                "",
                "capability:key-1",
            )
        )

    assert store.list_messages("conversation-1") == []
    assert store.list_capability_intents("turn-1") == []


def test_expired_owner_cannot_write_after_recovery_claims_the_attempt(tmp_path: Path) -> None:
    current_time = [100.0]
    store = ConversationStore(
        tmp_path / "conversations.sqlite3",
        ids=_Ids(),
        attempt_lease_seconds=1,
        clock=lambda: current_time[0],
    )
    receipt = _capture(store)
    attempt = store.begin_attempt(
        BeginModelAttempt("conversation-1", "turn-1", receipt.turn_version, None)
    )
    current_time[0] = 102.0
    claimed = store.claim_expired_attempt(attempt, "recovery-owner")
    assert claimed is not None

    with pytest.raises(ConversationConflictError, match="ownership"):
        store.finalize_assistant_message(
            FinalizeAssistantMessage(
                "conversation-1",
                "turn-1",
                attempt.attempt_id,
                "Stale owner response",
                attempt.owner_id,
            )
        )
    with pytest.raises(ConversationConflictError, match="ownership"):
        store.prepare_capability_call(
            PrepareCapabilityCall(
                "conversation-1",
                "turn-1",
                attempt.attempt_id,
                "tool-1",
                "prepare_plan",
                {},
                "",
                "capability:key-1",
                attempt.owner_id,
            )
        )

    assert store.list_messages("conversation-1") == []
    assert store.list_capability_intents("turn-1") == []


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
        attempt.owner_id,
    )
    intent = store.prepare_capability_call(command)
    assert intent.status == "prepared"
    projected = store.project_capability_result(
        ProjectCapabilityResult(
            intent.intent_id,
            "projected",
            {"run_id": "run-1"},
            attempt.owner_id,
        )
    )
    replay = store.project_capability_result(
        ProjectCapabilityResult(
            intent.intent_id,
            "projected",
            {"run_id": "run-1"},
            attempt.owner_id,
        )
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
                attempt.owner_id,
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


def _begin_worker(path: str, barrier: _Barrier, queue: _Queue) -> None:
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
    barrier: _Barrier,
    queue: _Queue,
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


def _attach_race_worker(path: str, barrier: _Barrier, queue: _Queue) -> None:
    store = ConversationStore(Path(path))
    barrier.wait()
    try:
        attachment = store.attach_context(
            AttachContext("conversation-1", "context-race", "Course", "race content")
        )
        queue.put(("attached", attachment.content_digest))
    except ConversationConflictError:
        queue.put(("frozen", ""))


def _capture_race_worker(path: str, barrier: _Barrier, queue: _Queue) -> None:
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
            "conversation-1",
            "turn-1",
            first.attempt_id,
            first.turn_version,
            "crash",
            first.owner_id,
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
