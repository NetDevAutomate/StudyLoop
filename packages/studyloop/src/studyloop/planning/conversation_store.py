"""Private SQLite truth store for durable planning conversations."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from .contracts import PlanningRequest, SourceReference
from .conversation_contracts import (
    AttachContext,
    AttemptRecord,
    BeginModelAttempt,
    CapabilityIntent,
    CaptureLearnerTurn,
    CompleteModelAttempt,
    ContextAttachment,
    ConversationConflictError,
    ConversationRefusedError,
    DecisionIntent,
    DecisionProjection,
    FinalizeAssistantMessage,
    MarkAttemptInterrupted,
    MessageRecord,
    OutboxEvent,
    PrepareCapabilityCall,
    PrepareDecisionIntent,
    ProjectCapabilityResult,
    ProjectDecisionResult,
    StoredCapabilityResult,
    TurnReceipt,
    TurnRecord,
)

_MAX_CONTEXT_CHARS = 100_000
_MAX_TURN_CHARS = 40_000


class _IdGenerator(Protocol):
    def new_id(self, prefix: str) -> str: ...


class _UuidIds:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(domain: str, value: object) -> str:
    payload = _canonical_json({"domain": domain, "version": 1, "payload": value})
    return f"sha256:v1:{sha256(payload.encode('utf-8')).hexdigest()}"


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ConversationRefusedError(f"unsupported durable JSON value {type(value).__name__}")


def _request_payload(request: PlanningRequest) -> dict[str, object]:
    return {
        "mode": request.mode,
        "brain_dump": request.brain_dump,
        "idempotency_key": request.idempotency_key,
        "plan_id": request.plan_id,
        "source_references": [asdict(item) for item in request.source_references],
        "evidence_ids": list(request.evidence_ids),
    }


def _safe_context_label(value: str) -> str:
    label = value.strip()
    if label.startswith(("/", "~", "file://")) or "\\" in label:
        return "selected text context"
    if label.startswith(("http://", "https://")):
        host = urlsplit(label).hostname or ""
        try:
            internal = ip_address(host).is_private or ip_address(host).is_loopback
        except ValueError:
            internal = host.lower() in {"localhost", "localhost.localdomain"}
        if internal:
            return "selected text context"
    return label


def _request_from_payload(payload: Mapping[str, object]) -> PlanningRequest:
    raw_sources = payload.get("source_references", [])
    if not isinstance(raw_sources, list):
        raise ConversationConflictError("stored planning request is invalid")
    return PlanningRequest(
        cast("Any", str(payload["mode"])),
        str(payload["brain_dump"]),
        str(payload["idempotency_key"]),
        str(payload.get("plan_id", "")),
        tuple(SourceReference(**cast("dict[str, Any]", item)) for item in raw_sources),
        tuple(str(item) for item in cast("list[object]", payload.get("evidence_ids", []))),
    )


class ConversationStore:
    """Own SQLite migrations, CAS transitions, and transactional outbox writes."""

    def __init__(self, database_path: Path, *, ids: _IdGenerator | None = None) -> None:
        self.database_path = database_path
        self._ids = ids or _UuidIds()
        self.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.database_path.parent, 0o700)
        self._migrate()
        self.ensure_private_modes()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        self.ensure_private_modes()
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
            self.ensure_private_modes()

    def _migrate(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    context_generation INTEGER NOT NULL DEFAULT 1,
                    context_state TEXT NOT NULL DEFAULT 'open'
                        CHECK(context_state IN ('open','frozen')),
                    next_outbox_seq INTEGER NOT NULL DEFAULT 0,
                    acknowledged_outbox_seq INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS context_attachments (
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                    generation INTEGER NOT NULL,
                    context_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    PRIMARY KEY(conversation_id, generation, context_id),
                    UNIQUE(conversation_id, generation, ordinal)
                );
                CREATE TABLE IF NOT EXISTS turns (
                    turn_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                    turn_ordinal INTEGER NOT NULL,
                    learner_text TEXT NOT NULL,
                    planning_request_json TEXT NOT NULL,
                    context_generation INTEGER NOT NULL,
                    brief_context_digest TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN (
                            'open_for_context','ready','attempt_active','retryable','completed'
                        )),
                    version INTEGER NOT NULL,
                    planning_run_id TEXT NOT NULL DEFAULT '',
                    UNIQUE(conversation_id, turn_ordinal)
                );
                CREATE TABLE IF NOT EXISTS turn_context_snapshots (
                    turn_id TEXT NOT NULL REFERENCES turns(turn_id),
                    ordinal INTEGER NOT NULL,
                    context_id TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    PRIMARY KEY(turn_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                    turn_id TEXT NOT NULL REFERENCES turns(turn_id),
                    attempt_seq INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','completed','interrupted')),
                    retry_of_attempt_id TEXT,
                    private_reason TEXT NOT NULL DEFAULT '',
                    UNIQUE(turn_id, attempt_seq)
                );
                CREATE TABLE IF NOT EXISTS capability_intents (
                    intent_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    lifecycle_idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK(status IN ('prepared','dispatching','projected','refused')),
                    UNIQUE(conversation_id, turn_id, attempt_id, tool_call_id)
                );
                CREATE TABLE IF NOT EXISTS capability_results (
                    intent_id TEXT PRIMARY KEY REFERENCES capability_intents(intent_id),
                    status TEXT NOT NULL CHECK(status IN ('projected','refused')),
                    payload_json TEXT NOT NULL,
                    outbox_seq INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS finalized_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('assistant','learner')),
                    content TEXT NOT NULL,
                    outbox_seq INTEGER NOT NULL,
                    UNIQUE(attempt_id, role)
                );
                CREATE TABLE IF NOT EXISTS decision_intents (
                    intent_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    lifecycle_idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL
                        CHECK(status IN ('prepared','dispatching','projected','refused'))
                );
                CREATE TABLE IF NOT EXISTS decision_projections (
                    intent_id TEXT PRIMARY KEY REFERENCES decision_intents(intent_id),
                    status TEXT NOT NULL CHECK(status IN ('projected','refused')),
                    payload_json TEXT NOT NULL,
                    outbox_seq INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposal_projections (
                    conversation_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL,
                    proposal_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    PRIMARY KEY(conversation_id, proposal_id)
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    conversation_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(conversation_id, sequence)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_open_turn_per_conversation
                ON turns(conversation_id)
                WHERE status IN ('open_for_context', 'ready', 'attempt_active', 'retryable');
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_attempt_per_conversation
                ON attempts(conversation_id) WHERE status = 'active';
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_attempt_per_turn
                ON attempts(turn_id) WHERE status = 'active';
                CREATE UNIQUE INDEX IF NOT EXISTS uq_attempt_sequence_per_turn
                ON attempts(turn_id, attempt_seq);
                """
            )
        finally:
            connection.close()

    def ensure_private_modes(self) -> None:
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)

    @staticmethod
    def _ensure_conversation(connection: sqlite3.Connection, conversation_id: str) -> None:
        if not conversation_id.strip():
            raise ConversationRefusedError("conversation ID is required")
        connection.execute(
            "INSERT OR IGNORE INTO conversations(conversation_id) VALUES (?)",
            (conversation_id,),
        )

    @staticmethod
    def _next_outbox(connection: sqlite3.Connection, conversation_id: str) -> int:
        row = connection.execute(
            "UPDATE conversations SET next_outbox_seq=next_outbox_seq+1 "
            "WHERE conversation_id=? RETURNING next_outbox_seq",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise ConversationConflictError("conversation disappeared during outbox write")
        return int(row[0])

    def attach_context(self, command: AttachContext) -> ContextAttachment:
        if not command.context_id.strip() or not command.label.strip():
            raise ConversationRefusedError("context ID and label are required")
        if len(command.content) > _MAX_CONTEXT_CHARS:
            raise ConversationRefusedError("context exceeds the bounded planning input")
        safe_label = _safe_context_label(command.label)
        digest = _digest("studyloop.planning-context", {"content_exact": command.content})
        with self._transaction() as connection:
            self._ensure_conversation(connection, command.conversation_id)
            conversation = connection.execute(
                "SELECT context_generation, context_state FROM conversations "
                "WHERE conversation_id=?",
                (command.conversation_id,),
            ).fetchone()
            if conversation["context_state"] != "open":
                raise ConversationConflictError(
                    "conversation context is frozen for the active turn"
                )
            generation = int(conversation["context_generation"])
            prior = connection.execute(
                "SELECT * FROM context_attachments WHERE conversation_id=? AND generation=? "
                "AND context_id=?",
                (command.conversation_id, generation, command.context_id),
            ).fetchone()
            if prior is not None:
                if (
                    prior["label"] != safe_label
                    or prior["content"] != command.content
                    or prior["content_digest"] != digest
                ):
                    raise ConversationConflictError("context ID was reused with different content")
                return self._context_from_row(prior)
            ordinal = int(
                connection.execute(
                    "SELECT COALESCE(MAX(ordinal),0)+1 FROM context_attachments "
                    "WHERE conversation_id=? AND generation=?",
                    (command.conversation_id, generation),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO context_attachments VALUES (?,?,?,?,?,?,?)",
                (
                    command.conversation_id,
                    generation,
                    command.context_id,
                    ordinal,
                    safe_label,
                    command.content,
                    digest,
                ),
            )
            row = connection.execute(
                "SELECT * FROM context_attachments WHERE conversation_id=? AND generation=? "
                "AND context_id=?",
                (command.conversation_id, generation, command.context_id),
            ).fetchone()
            return self._context_from_row(row)

    @staticmethod
    def _context_from_row(row: sqlite3.Row) -> ContextAttachment:
        return ContextAttachment(
            str(row["conversation_id"]),
            str(row["context_id"]),
            int(row["ordinal"]),
            str(row["label"]),
            str(row["content"]),
            str(row["content_digest"]),
        )

    def capture_turn_and_freeze_context(self, command: CaptureLearnerTurn) -> TurnReceipt:
        turn = command.turn
        if not turn.turn_id.strip() or not turn.text.strip():
            raise ConversationRefusedError("turn ID and learner text are required")
        if len(turn.text) > _MAX_TURN_CHARS:
            raise ConversationRefusedError("learner turn exceeds the bounded planning input")
        if turn.planning_request.brain_dump != turn.text:
            raise ConversationRefusedError(
                "planning request brain dump must be the exact learner turn text"
            )
        with self._transaction() as connection:
            self._ensure_conversation(connection, command.conversation_id)
            prior = connection.execute(
                "SELECT * FROM turns WHERE turn_id=?", (turn.turn_id,)
            ).fetchone()
            if prior is not None:
                stored_request = _request_from_payload(json.loads(prior["planning_request_json"]))
                if (
                    prior["conversation_id"] != command.conversation_id
                    or prior["learner_text"] != turn.text
                    or stored_request.mode != turn.planning_request.mode
                    or stored_request.idempotency_key != turn.planning_request.idempotency_key
                    or stored_request.plan_id != turn.planning_request.plan_id
                    or stored_request.evidence_ids != turn.planning_request.evidence_ids
                    or stored_request.source_references[
                        : len(turn.planning_request.source_references)
                    ]
                    != turn.planning_request.source_references
                ):
                    raise ConversationConflictError("turn ID was reused with different input")
                return self._receipt(connection, prior)
            conversation = connection.execute(
                "SELECT * FROM conversations WHERE conversation_id=?",
                (command.conversation_id,),
            ).fetchone()
            if conversation["context_state"] != "open":
                raise ConversationConflictError("conversation already has a frozen active turn")
            generation = int(conversation["context_generation"])
            attachments = connection.execute(
                "SELECT * FROM context_attachments WHERE conversation_id=? AND generation=? "
                "ORDER BY ordinal",
                (command.conversation_id, generation),
            ).fetchall()
            frozen_sources = list(turn.planning_request.source_references)
            by_reference = {item.reference_id: item for item in frozen_sources}
            for row in attachments:
                reference = SourceReference(
                    reference_id=str(row["context_id"]),
                    content_digest=str(row["content_digest"]),
                    source_kind="supplied_material",
                    label=str(row["label"]),
                )
                prior_reference = by_reference.get(reference.reference_id)
                if prior_reference is not None and prior_reference != reference:
                    raise ConversationConflictError(
                        "frozen context conflicts with an existing source reference"
                    )
                if prior_reference is None:
                    frozen_sources.append(reference)
                    by_reference[reference.reference_id] = reference
            frozen_request = replace(
                turn.planning_request,
                source_references=tuple(frozen_sources),
            )
            request_json = _canonical_json(_request_payload(frozen_request))
            snapshot = [
                {"context_id": row["context_id"], "content_digest": row["content_digest"]}
                for row in attachments
            ]
            context_digest = _digest(
                "studyloop.planning-turn-context",
                {
                    "conversation_id": command.conversation_id,
                    "turn_id": turn.turn_id,
                    "contexts": snapshot,
                    "source_references": [asdict(item) for item in frozen_sources],
                },
            )
            ordinal = int(
                connection.execute(
                    "SELECT COALESCE(MAX(turn_ordinal),0)+1 FROM turns WHERE conversation_id=?",
                    (command.conversation_id,),
                ).fetchone()[0]
            )
            try:
                connection.execute(
                    "INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        turn.turn_id,
                        command.conversation_id,
                        ordinal,
                        turn.text,
                        request_json,
                        generation,
                        context_digest,
                        "ready",
                        1,
                        "",
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConversationConflictError(
                    "conversation already has a non-terminal learner turn"
                ) from exc
            connection.executemany(
                "INSERT INTO turn_context_snapshots VALUES (?,?,?,?)",
                [
                    (turn.turn_id, row["ordinal"], row["context_id"], row["content_digest"])
                    for row in attachments
                ],
            )
            connection.execute(
                "UPDATE conversations SET context_state='frozen' WHERE conversation_id=?",
                (command.conversation_id,),
            )
            row = connection.execute(
                "SELECT * FROM turns WHERE turn_id=?", (turn.turn_id,)
            ).fetchone()
            return self._receipt(connection, row)

    @staticmethod
    def _receipt(connection: sqlite3.Connection, row: sqlite3.Row) -> TurnReceipt:
        contexts = connection.execute(
            "SELECT context_id,content_digest FROM turn_context_snapshots WHERE turn_id=? "
            "ORDER BY ordinal",
            (row["turn_id"],),
        ).fetchall()
        return TurnReceipt(
            str(row["conversation_id"]),
            str(row["turn_id"]),
            str(row["status"]),
            int(row["version"]),
            str(row["brief_context_digest"]),
            tuple(str(item["context_id"]) for item in contexts),
            tuple(str(item["content_digest"]) for item in contexts),
        )

    def begin_attempt(self, command: BeginModelAttempt) -> AttemptRecord:
        with self._transaction() as connection:
            turn = self._turn_row(connection, command.conversation_id, command.turn_id)
            if int(turn["version"]) != command.expected_turn_version:
                raise ConversationConflictError("stale learner turn version")
            prior = connection.execute(
                "SELECT * FROM attempts WHERE turn_id=? ORDER BY attempt_seq", (command.turn_id,)
            ).fetchall()
            if command.retry_of_attempt_id is None:
                if turn["status"] != "ready" or prior:
                    raise ConversationConflictError("first attempt requires a ready untouched turn")
            else:
                if turn["status"] != "retryable" or not prior:
                    raise ConversationConflictError("retry requires a durably interrupted turn")
                latest = prior[-1]
                if (
                    latest["attempt_id"] != command.retry_of_attempt_id
                    or latest["status"] != "interrupted"
                ):
                    raise ConversationConflictError(
                        "retry ID is not the latest interrupted attempt"
                    )
                unresolved = connection.execute(
                    "SELECT COUNT(*) FROM capability_intents WHERE turn_id=? "
                    "AND status NOT IN ('projected','refused')",
                    (command.turn_id,),
                ).fetchone()[0]
                if unresolved:
                    raise ConversationConflictError(
                        "capability intents must be reconciled before retry"
                    )
            sequence = int(prior[-1]["attempt_seq"] + 1) if prior else 1
            attempt_id = self._ids.new_id("attempt")
            try:
                connection.execute(
                    "INSERT INTO attempts(attempt_id,conversation_id,turn_id,attempt_seq,status,"
                    "retry_of_attempt_id) VALUES (?,?,?,?,?,?)",
                    (
                        attempt_id,
                        command.conversation_id,
                        command.turn_id,
                        sequence,
                        "active",
                        command.retry_of_attempt_id,
                    ),
                )
                changed = connection.execute(
                    "UPDATE turns SET status='attempt_active',version=version+1 "
                    "WHERE turn_id=? AND version=?",
                    (command.turn_id, command.expected_turn_version),
                ).rowcount
                if changed != 1:
                    raise ConversationConflictError(
                        "learner turn changed during attempt allocation"
                    )
            except sqlite3.IntegrityError as exc:
                raise ConversationConflictError(
                    "another model attempt already won the CAS"
                ) from exc
            return AttemptRecord(
                attempt_id,
                command.conversation_id,
                command.turn_id,
                sequence,
                "active",
                command.expected_turn_version + 1,
                command.retry_of_attempt_id,
            )

    def complete_attempt(self, command: CompleteModelAttempt) -> AttemptRecord:
        with self._transaction() as connection:
            row = self._active_attempt(connection, command)
            unresolved = connection.execute(
                "SELECT COUNT(*) FROM capability_intents WHERE turn_id=? "
                "AND status NOT IN ('projected','refused')",
                (command.turn_id,),
            ).fetchone()[0]
            if unresolved:
                raise ConversationConflictError(
                    "capability intents must be reconciled before attempt completion"
                )
            finalized = connection.execute(
                "SELECT 1 FROM finalized_messages WHERE attempt_id=? AND role='assistant'",
                (command.attempt_id,),
            ).fetchone()
            if finalized is None:
                raise ConversationConflictError(
                    "attempt requires a finalized assistant message before completion"
                )
            connection.execute(
                "UPDATE attempts SET status='completed' WHERE attempt_id=?", (command.attempt_id,)
            )
            connection.execute(
                "UPDATE turns SET status='completed',version=version+1 WHERE turn_id=?",
                (command.turn_id,),
            )
            connection.execute(
                "UPDATE conversations SET context_state='open', "
                "context_generation=context_generation+1 WHERE conversation_id=?",
                (command.conversation_id,),
            )
            return self._attempt_from_row(row, "completed", command.expected_turn_version + 1)

    def mark_attempt_interrupted(self, command: MarkAttemptInterrupted) -> AttemptRecord:
        if not command.private_reason.strip():
            raise ConversationRefusedError("interruption requires a private recovery reason")
        with self._transaction() as connection:
            row = self._active_attempt(connection, command)
            connection.execute(
                "UPDATE attempts SET status='interrupted',private_reason=? WHERE attempt_id=?",
                (command.private_reason, command.attempt_id),
            )
            connection.execute(
                "UPDATE turns SET status='retryable',version=version+1 WHERE turn_id=?",
                (command.turn_id,),
            )
            sequence = self._next_outbox(connection, command.conversation_id)
            payload = {
                "turn_id": command.turn_id,
                "attempt_id": command.attempt_id,
                "retryable": True,
            }
            connection.execute(
                "INSERT INTO outbox VALUES (?,?,?,?)",
                (
                    command.conversation_id,
                    sequence,
                    "attempt_interrupted",
                    _canonical_json(payload),
                ),
            )
            return self._attempt_from_row(row, "interrupted", command.expected_turn_version + 1)

    @staticmethod
    def _active_attempt(
        connection: sqlite3.Connection,
        command: CompleteModelAttempt | MarkAttemptInterrupted,
    ) -> sqlite3.Row:
        turn = ConversationStore._turn_row(connection, command.conversation_id, command.turn_id)
        if int(turn["version"]) != command.expected_turn_version:
            raise ConversationConflictError("stale learner turn version")
        row = connection.execute(
            "SELECT * FROM attempts WHERE attempt_id=? AND conversation_id=? AND turn_id=?",
            (command.attempt_id, command.conversation_id, command.turn_id),
        ).fetchone()
        if row is None or row["status"] != "active" or turn["status"] != "attempt_active":
            raise ConversationConflictError("attempt is not the active model attempt")
        return row

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row, status: str, turn_version: int) -> AttemptRecord:
        return AttemptRecord(
            str(row["attempt_id"]),
            str(row["conversation_id"]),
            str(row["turn_id"]),
            int(row["attempt_seq"]),
            cast("Any", status),
            turn_version,
            cast("str | None", row["retry_of_attempt_id"]),
        )

    def prepare_capability_call(self, command: PrepareCapabilityCall) -> CapabilityIntent:
        payload = {
            "conversation_id": command.conversation_id,
            "turn_id": command.turn_id,
            "attempt_id": command.attempt_id,
            "tool_call_id": command.tool_call_id,
            "name": command.name,
            "arguments": _jsonable(command.arguments),
            "run_id": command.run_id,
            "lifecycle_idempotency_key": command.lifecycle_idempotency_key,
        }
        payload_digest = _digest("studyloop.planning-capability-intent", payload)
        arguments_json = _canonical_json(payload["arguments"])
        with self._transaction() as connection:
            attempt = connection.execute(
                "SELECT status FROM attempts WHERE attempt_id=? AND conversation_id=? "
                "AND turn_id=?",
                (command.attempt_id, command.conversation_id, command.turn_id),
            ).fetchone()
            prior = connection.execute(
                "SELECT * FROM capability_intents WHERE conversation_id=? AND turn_id=? "
                "AND attempt_id=? AND tool_call_id=?",
                (
                    command.conversation_id,
                    command.turn_id,
                    command.attempt_id,
                    command.tool_call_id,
                ),
            ).fetchone()
            if prior is not None:
                if prior["payload_digest"] != payload_digest:
                    raise ConversationConflictError(
                        "capability tool-call identity was reused with different input"
                    )
                return self._intent_from_row(prior)
            if attempt is None or attempt["status"] != "active":
                raise ConversationConflictError("new capability intent requires an active attempt")
            intent_id = self._ids.new_id("capability")
            connection.execute(
                "INSERT INTO capability_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    intent_id,
                    command.conversation_id,
                    command.turn_id,
                    command.attempt_id,
                    command.tool_call_id,
                    command.name,
                    arguments_json,
                    command.run_id,
                    payload_digest,
                    command.lifecycle_idempotency_key,
                    "prepared",
                ),
            )
            row = connection.execute(
                "SELECT * FROM capability_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            return self._intent_from_row(row)

    def mark_capability_dispatching(self, intent_id: str) -> CapabilityIntent:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM capability_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if row is None:
                raise ConversationConflictError("capability intent does not exist")
            if row["status"] in {"projected", "refused"}:
                return self._intent_from_row(row)
            connection.execute(
                "UPDATE capability_intents SET status='dispatching' WHERE intent_id=?",
                (intent_id,),
            )
            row = connection.execute(
                "SELECT * FROM capability_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            return self._intent_from_row(row)

    def project_capability_result(self, command: ProjectCapabilityResult) -> StoredCapabilityResult:
        payload_json = _canonical_json(_jsonable(command.payload))
        with self._transaction() as connection:
            intent = connection.execute(
                "SELECT * FROM capability_intents WHERE intent_id=?", (command.intent_id,)
            ).fetchone()
            if intent is None:
                raise ConversationConflictError("capability intent does not exist")
            prior = connection.execute(
                "SELECT * FROM capability_results WHERE intent_id=?", (command.intent_id,)
            ).fetchone()
            if prior is not None:
                if prior["status"] != command.status or prior["payload_json"] != payload_json:
                    raise ConversationConflictError("capability result replay used different input")
                return self._stored_result_from_row(prior)
            sequence = self._next_outbox(connection, str(intent["conversation_id"]))
            connection.execute(
                "INSERT INTO capability_results VALUES (?,?,?,?)",
                (command.intent_id, command.status, payload_json, sequence),
            )
            connection.execute(
                "UPDATE capability_intents SET status=? WHERE intent_id=?",
                (command.status, command.intent_id),
            )
            run_id = command.payload.get("run_id")
            if intent["name"] == "prepare_plan" and isinstance(run_id, str) and run_id:
                connection.execute(
                    "UPDATE turns SET planning_run_id=? WHERE turn_id=?",
                    (run_id, intent["turn_id"]),
                )
            outbox_payload = {
                "intent_id": command.intent_id,
                "tool_call_id": intent["tool_call_id"],
                "name": intent["name"],
                "status": command.status,
                "result": json.loads(payload_json),
            }
            connection.execute(
                "INSERT INTO outbox VALUES (?,?,?,?)",
                (
                    intent["conversation_id"],
                    sequence,
                    "capability_result",
                    _canonical_json(outbox_payload),
                ),
            )
            row = connection.execute(
                "SELECT * FROM capability_results WHERE intent_id=?", (command.intent_id,)
            ).fetchone()
            return self._stored_result_from_row(row)

    @staticmethod
    def _intent_from_row(row: sqlite3.Row) -> CapabilityIntent:
        return CapabilityIntent(
            str(row["intent_id"]),
            str(row["conversation_id"]),
            str(row["turn_id"]),
            str(row["attempt_id"]),
            str(row["tool_call_id"]),
            str(row["name"]),
            cast("dict[str, object]", json.loads(row["arguments_json"])),
            str(row["run_id"]),
            str(row["payload_digest"]),
            str(row["lifecycle_idempotency_key"]),
            cast("Any", str(row["status"])),
        )

    @staticmethod
    def _stored_result_from_row(row: sqlite3.Row) -> StoredCapabilityResult:
        return StoredCapabilityResult(
            str(row["intent_id"]),
            cast("Any", str(row["status"])),
            cast("dict[str, object]", json.loads(row["payload_json"])),
            int(row["outbox_seq"]),
        )

    def finalize_assistant_message(self, command: FinalizeAssistantMessage) -> MessageRecord:
        if not command.content.strip():
            raise ConversationRefusedError("final assistant message cannot be empty")
        with self._transaction() as connection:
            attempt = connection.execute(
                "SELECT status FROM attempts WHERE attempt_id=? AND conversation_id=? "
                "AND turn_id=?",
                (command.attempt_id, command.conversation_id, command.turn_id),
            ).fetchone()
            if attempt is None or attempt["status"] != "active":
                raise ConversationConflictError("assistant message requires an active attempt")
            prior = connection.execute(
                "SELECT * FROM finalized_messages WHERE attempt_id=? AND role='assistant'",
                (command.attempt_id,),
            ).fetchone()
            if prior is not None:
                if prior["content"] != command.content:
                    raise ConversationConflictError(
                        "attempt finalized with different assistant text"
                    )
                return self._message_from_row(prior)
            sequence = self._next_outbox(connection, command.conversation_id)
            message_id = self._ids.new_id("message")
            connection.execute(
                "INSERT INTO finalized_messages VALUES (?,?,?,?,?,?,?)",
                (
                    message_id,
                    command.conversation_id,
                    command.turn_id,
                    command.attempt_id,
                    "assistant",
                    command.content,
                    sequence,
                ),
            )
            payload = {
                "message_id": message_id,
                "turn_id": command.turn_id,
                "content": command.content,
            }
            connection.execute(
                "INSERT INTO outbox VALUES (?,?,?,?)",
                (command.conversation_id, sequence, "assistant_message", _canonical_json(payload)),
            )
            row = connection.execute(
                "SELECT * FROM finalized_messages WHERE message_id=?", (message_id,)
            ).fetchone()
            return self._message_from_row(row)

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            str(row["message_id"]),
            str(row["conversation_id"]),
            str(row["turn_id"]),
            str(row["attempt_id"]),
            cast("Any", str(row["role"])),
            str(row["content"]),
            int(row["outbox_seq"]),
        )

    def prepare_decision_intent(self, command: PrepareDecisionIntent) -> DecisionIntent:
        payload = _jsonable(asdict(command))
        payload_json = _canonical_json(payload)
        digest = _digest("studyloop.planning-decision-intent", payload)
        with self._transaction() as connection:
            self._ensure_conversation(connection, command.conversation_id)
            prior = connection.execute(
                "SELECT * FROM decision_intents WHERE lifecycle_idempotency_key=?",
                (command.lifecycle_idempotency_key,),
            ).fetchone()
            if prior is not None:
                if prior["payload_digest"] != digest:
                    raise ConversationConflictError("decision replay used different input")
                return self._decision_from_row(prior)
            intent_id = self._ids.new_id("decision")
            connection.execute(
                "INSERT INTO decision_intents VALUES (?,?,?,?,?,?,?)",
                (
                    intent_id,
                    command.conversation_id,
                    command.proposal_id,
                    payload_json,
                    digest,
                    command.lifecycle_idempotency_key,
                    "prepared",
                ),
            )
            row = connection.execute(
                "SELECT * FROM decision_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            return self._decision_from_row(row)

    def project_decision_result(self, command: ProjectDecisionResult) -> DecisionProjection:
        payload_json = _canonical_json(_jsonable(command.payload))
        with self._transaction() as connection:
            intent = connection.execute(
                "SELECT * FROM decision_intents WHERE intent_id=?", (command.intent_id,)
            ).fetchone()
            if intent is None:
                raise ConversationConflictError("decision intent does not exist")
            prior = connection.execute(
                "SELECT * FROM decision_projections WHERE intent_id=?", (command.intent_id,)
            ).fetchone()
            if prior is not None:
                if prior["status"] != command.status or prior["payload_json"] != payload_json:
                    raise ConversationConflictError("decision result replay used different input")
                return self._decision_projection_from_row(prior)
            sequence = self._next_outbox(connection, str(intent["conversation_id"]))
            connection.execute(
                "INSERT INTO decision_projections VALUES (?,?,?,?)",
                (command.intent_id, command.status, payload_json, sequence),
            )
            connection.execute(
                "UPDATE decision_intents SET status=? WHERE intent_id=?",
                (command.status, command.intent_id),
            )
            connection.execute(
                "INSERT INTO outbox VALUES (?,?,?,?)",
                (
                    intent["conversation_id"],
                    sequence,
                    "decision_result",
                    payload_json,
                ),
            )
            row = connection.execute(
                "SELECT * FROM decision_projections WHERE intent_id=?", (command.intent_id,)
            ).fetchone()
            return self._decision_projection_from_row(row)

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> DecisionIntent:
        return DecisionIntent(
            str(row["intent_id"]),
            str(row["conversation_id"]),
            str(row["proposal_id"]),
            str(row["payload_digest"]),
            str(row["lifecycle_idempotency_key"]),
            cast("Any", str(row["status"])),
        )

    @staticmethod
    def _decision_projection_from_row(row: sqlite3.Row) -> DecisionProjection:
        return DecisionProjection(
            str(row["intent_id"]),
            cast("Any", str(row["status"])),
            cast("dict[str, object]", json.loads(row["payload_json"])),
            int(row["outbox_seq"]),
        )

    def replay_outbox(self, conversation_id: str, after_seq: int) -> list[OutboxEvent]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM outbox WHERE conversation_id=? AND sequence>? ORDER BY sequence",
                (conversation_id, after_seq),
            ).fetchall()
            return [
                OutboxEvent(
                    conversation_id,
                    int(row["sequence"]),
                    str(row["event_type"]),
                    cast("dict[str, object]", json.loads(row["payload_json"])),
                )
                for row in rows
            ]
        finally:
            connection.close()

    def acknowledge_outbox(self, conversation_id: str, sequence: int) -> None:
        with self._transaction() as connection:
            self._ensure_conversation(connection, conversation_id)
            maximum = int(
                connection.execute(
                    "SELECT next_outbox_seq FROM conversations WHERE conversation_id=?",
                    (conversation_id,),
                ).fetchone()[0]
            )
            if sequence < 0 or sequence > maximum:
                raise ConversationConflictError("outbox acknowledgement is outside durable history")
            connection.execute(
                "UPDATE conversations SET acknowledged_outbox_seq="
                "MAX(acknowledged_outbox_seq,?) WHERE conversation_id=?",
                (sequence, conversation_id),
            )

    def get_turn(self, conversation_id: str, turn_id: str) -> TurnRecord:
        connection = self._connect()
        try:
            return self._turn_from_row(self._turn_row(connection, conversation_id, turn_id))
        finally:
            connection.close()

    def load_request(self, turn_id: str) -> PlanningRequest:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT planning_request_json FROM turns WHERE turn_id=?", (turn_id,)
            ).fetchone()
            if row is None:
                raise ConversationConflictError("learner turn does not exist")
            payload = json.loads(row[0])
            if not isinstance(payload, dict):
                raise ConversationConflictError("stored planning request is invalid")
            return _request_from_payload(payload)
        finally:
            connection.close()

    def load_context(self, turn_id: str) -> tuple[ContextAttachment, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT context_attachments.* FROM turn_context_snapshots "
                "JOIN turns USING(turn_id) JOIN context_attachments ON "
                "context_attachments.conversation_id=turns.conversation_id AND "
                "context_attachments.generation=turns.context_generation AND "
                "context_attachments.context_id=turn_context_snapshots.context_id "
                "WHERE turn_id=? ORDER BY turn_context_snapshots.ordinal",
                (turn_id,),
            ).fetchall()
            return tuple(self._context_from_row(row) for row in rows)
        finally:
            connection.close()

    def list_attempts(self, turn_id: str) -> list[AttemptRecord]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT attempts.*,turns.version AS turn_version FROM attempts "
                "JOIN turns USING(turn_id) "
                "WHERE turn_id=? ORDER BY attempt_seq",
                (turn_id,),
            ).fetchall()
            return [
                self._attempt_from_row(row, str(row["status"]), int(row["turn_version"]))
                for row in rows
            ]
        finally:
            connection.close()

    def private_interruption_reason(self, attempt_id: str) -> str:
        """Return local recovery detail; adapters must not expose it as transcript data."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT private_reason FROM attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise ConversationConflictError("model attempt does not exist")
            return str(row["private_reason"])
        finally:
            connection.close()

    def list_capability_intents(self, turn_id: str) -> list[CapabilityIntent]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM capability_intents WHERE turn_id=? ORDER BY rowid", (turn_id,)
            ).fetchall()
            return [self._intent_from_row(row) for row in rows]
        finally:
            connection.close()

    def list_unreconciled_capability_intents(self, conversation_id: str) -> list[CapabilityIntent]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM capability_intents WHERE conversation_id=? "
                "AND status NOT IN ('projected','refused') ORDER BY rowid",
                (conversation_id,),
            ).fetchall()
            return [self._intent_from_row(row) for row in rows]
        finally:
            connection.close()

    def get_capability_result(self, intent_id: str) -> StoredCapabilityResult | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM capability_results WHERE intent_id=?", (intent_id,)
            ).fetchone()
            return self._stored_result_from_row(row) if row is not None else None
        finally:
            connection.close()

    def list_messages(self, conversation_id: str) -> list[MessageRecord]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM finalized_messages WHERE conversation_id=? ORDER BY outbox_seq",
                (conversation_id,),
            ).fetchall()
            return [self._message_from_row(row) for row in rows]
        finally:
            connection.close()

    def finalized_message_for_attempt(self, attempt_id: str) -> MessageRecord | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM finalized_messages WHERE attempt_id=? AND role='assistant'",
                (attempt_id,),
            ).fetchone()
            return self._message_from_row(row) if row is not None else None
        finally:
            connection.close()

    def list_turns(self, conversation_id: str) -> list[TurnRecord]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM turns WHERE conversation_id=? ORDER BY turn_ordinal",
                (conversation_id,),
            ).fetchall()
            return [self._turn_from_row(row) for row in rows]
        finally:
            connection.close()

    def list_capability_history(
        self, turn_id: str
    ) -> list[tuple[CapabilityIntent, StoredCapabilityResult]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT capability_intents.*,capability_results.status AS result_status,"
                "capability_results.payload_json AS result_payload_json,"
                "capability_results.outbox_seq AS result_outbox_seq "
                "FROM capability_intents JOIN capability_results USING(intent_id) "
                "WHERE capability_intents.turn_id=? ORDER BY capability_intents.rowid",
                (turn_id,),
            ).fetchall()
            return [
                (
                    self._intent_from_row(row),
                    StoredCapabilityResult(
                        str(row["intent_id"]),
                        cast("Any", str(row["result_status"])),
                        cast(
                            "dict[str, object]",
                            json.loads(row["result_payload_json"]),
                        ),
                        int(row["result_outbox_seq"]),
                    ),
                )
                for row in rows
            ]
        finally:
            connection.close()

    def active_attempts(self, conversation_id: str) -> list[AttemptRecord]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT attempts.*,turns.version AS turn_version FROM attempts "
                "JOIN turns USING(turn_id) "
                "WHERE attempts.conversation_id=? AND attempts.status='active'",
                (conversation_id,),
            ).fetchall()
            return [self._attempt_from_row(row, "active", int(row["turn_version"])) for row in rows]
        finally:
            connection.close()

    @staticmethod
    def _turn_row(
        connection: sqlite3.Connection, conversation_id: str, turn_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM turns WHERE conversation_id=? AND turn_id=?",
            (conversation_id, turn_id),
        ).fetchone()
        if row is None:
            raise ConversationConflictError("learner turn does not exist")
        return row

    @staticmethod
    def _turn_from_row(row: sqlite3.Row) -> TurnRecord:
        return TurnRecord(
            str(row["conversation_id"]),
            str(row["turn_id"]),
            str(row["learner_text"]),
            str(row["status"]),
            int(row["version"]),
            str(row["brief_context_digest"]),
            str(row["planning_run_id"]),
        )
