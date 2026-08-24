"""Private SQLite truth store for durable planning conversations."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
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
from .repository import PathContainmentError

_MAX_CONTEXT_CHARS = 100_000
_MAX_TURN_CHARS = 40_000
_POSIX_PATH = re.compile(r"(?<![/\w:])(?:~)?/(?!/)[^/\s,;!?()]+(?:/[^/\s,;!?()]+)*")
_WINDOWS_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\s,;!?()]+")
_FILE_URI = re.compile(r"(?i)\bfile:(?://)?[^\s,;!?()]+")
_URL = re.compile(r"(?i)\bhttps?://[^\s,;!?()]+")
_HOST_PORT = re.compile(
    r"(?i)(?<![\w.-])(?P<host>\[[0-9a-f:]+\]|localhost(?:\.localdomain)?|"
    r"\d{1,3}(?:\.\d{1,3}){3}|[a-z0-9.-]+\.(?:local|internal)):(?P<port>\d{1,5})\b"
)
MigrationCrashInjector = Callable[[str], None]


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


def _is_internal_host(host: str) -> bool:
    normalized = host.strip("[]").lower()
    if normalized in {"localhost", "localhost.localdomain"}:
        return True
    if normalized.endswith((".local", ".internal")):
        return True
    try:
        address = ip_address(normalized)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def _safe_context_label(value: str) -> str:
    label = value.strip()
    if _POSIX_PATH.search(label) or _WINDOWS_PATH.search(label) or _FILE_URI.search(label):
        return "selected text context"
    for match in _URL.finditer(label):
        if _is_internal_host(urlsplit(match.group(0)).hostname or ""):
            return "selected text context"
    if any(_is_internal_host(match.group("host")) for match in _HOST_PORT.finditer(label)):
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

    def __init__(
        self,
        database_path: Path,
        *,
        ids: _IdGenerator | None = None,
        attempt_lease_seconds: float = 30.0,
        clock: Callable[[], float] = time.time,
        migration_crash_injector: MigrationCrashInjector | None = None,
    ) -> None:
        if not 0.01 <= attempt_lease_seconds <= 600:
            raise ValueError("attempt lease must be between 0.01 and 600 seconds")
        self.database_path = database_path.expanduser().absolute()
        self._ids = ids or _UuidIds()
        self.attempt_lease_seconds = attempt_lease_seconds
        self._clock = clock
        self._migration_crash_injector = migration_crash_injector
        self._validate_database_location()
        self.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._stable_root_descriptor() as root_descriptor:
            os.fchmod(root_descriptor, 0o700)
        self._migrate()
        self.ensure_private_modes()

    def _validate_database_location(self) -> None:
        parent = self.database_path.parent
        resolved_parent = parent.resolve(strict=False)
        if parent.is_symlink() or resolved_parent != parent:
            raise PathContainmentError("conversation planning root cannot be a symlink")
        if parent.exists() and not parent.is_dir():
            raise PathContainmentError("conversation planning root is not a directory")
        for path in self._database_files():
            if path.is_symlink():
                raise PathContainmentError("conversation SQLite target cannot be a symlink")
            if path.resolve(strict=False).parent != resolved_parent:
                raise PathContainmentError("conversation SQLite target escapes planning root")

    def _database_files(self) -> tuple[Path, Path, Path]:
        return (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        )

    @staticmethod
    def _identity(value: os.stat_result) -> tuple[int, int]:
        return (value.st_dev, value.st_ino)

    @contextmanager
    def _stable_root_descriptor(self) -> Iterator[int]:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.database_path.parent, flags)
        except OSError:
            raise PathContainmentError(
                "conversation planning root changed or became a symlink"
            ) from None
        try:
            self._assert_root_descriptor_identity(descriptor)
            yield descriptor
            self._assert_root_descriptor_identity(descriptor)
        finally:
            os.close(descriptor)

    def _assert_root_descriptor_identity(self, descriptor: int) -> None:
        descriptor_stat = os.fstat(descriptor)
        try:
            path_stat = os.stat(self.database_path.parent, follow_symlinks=False)
        except OSError:
            raise PathContainmentError("conversation planning root changed during access") from None
        if (
            not stat.S_ISDIR(descriptor_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or self._identity(descriptor_stat) != self._identity(path_stat)
        ):
            raise PathContainmentError("conversation planning root identity changed during access")

    def _open_private_target(
        self,
        root_descriptor: int,
        path: Path,
        *,
        create: bool,
        require_stable_identity: bool = True,
    ) -> int | None:
        try:
            path_stat = os.stat(path.name, dir_fd=root_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            path_stat = None
        except OSError:
            raise PathContainmentError("conversation SQLite target changed during access") from None
        if path_stat is not None and not stat.S_ISREG(path_stat.st_mode):
            raise PathContainmentError(
                "conversation SQLite target is a symlink or non-regular file"
            )
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if create:
            flags |= os.O_CREAT
        elif path_stat is None:
            return None
        try:
            descriptor = os.open(path.name, flags, 0o600, dir_fd=root_descriptor)
        except FileNotFoundError:
            return None
        except OSError:
            raise PathContainmentError(
                "conversation SQLite target changed or became a symlink"
            ) from None
        descriptor_stat = os.fstat(descriptor)
        try:
            final_stat = os.stat(path.name, dir_fd=root_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            if not require_stable_identity:
                return descriptor
            os.close(descriptor)
            raise PathContainmentError("conversation SQLite target changed during access") from None
        except OSError:
            os.close(descriptor)
            raise PathContainmentError("conversation SQLite target changed during access") from None
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or not stat.S_ISREG(final_stat.st_mode)
            or (
                require_stable_identity
                and self._identity(descriptor_stat) != self._identity(final_stat)
            )
        ):
            os.close(descriptor)
            raise PathContainmentError("conversation SQLite target identity changed during access")
        return descriptor

    def _assert_private_target_identity(
        self,
        root_descriptor: int,
        path: Path,
        expected_identity: tuple[int, int],
    ) -> None:
        try:
            path_stat = os.stat(path.name, dir_fd=root_descriptor, follow_symlinks=False)
        except OSError:
            raise PathContainmentError("conversation SQLite target changed during open") from None
        if not stat.S_ISREG(path_stat.st_mode) or self._identity(path_stat) != expected_identity:
            raise PathContainmentError("conversation SQLite target identity changed during open")

    def _connect(self) -> sqlite3.Connection:
        self._validate_database_location()
        connection: sqlite3.Connection | None = None
        with self._stable_root_descriptor() as root_descriptor:
            database_descriptor = self._open_private_target(
                root_descriptor,
                self.database_path,
                create=True,
            )
            if database_descriptor is None:  # pragma: no cover - create=True is exhaustive
                raise PathContainmentError("conversation SQLite database could not be anchored")
            try:
                os.fchmod(database_descriptor, 0o600)
                database_identity = self._identity(os.fstat(database_descriptor))
            finally:
                os.close(database_descriptor)
            try:
                connection = sqlite3.connect(
                    self.database_path,
                    timeout=15,
                    isolation_level=None,
                )
                self._assert_root_descriptor_identity(root_descriptor)
                self._assert_private_target_identity(
                    root_descriptor,
                    self.database_path,
                    database_identity,
                )
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=15000")
                connection.execute("PRAGMA synchronous=FULL")
                self._assert_root_descriptor_identity(root_descriptor)
                self._assert_private_target_identity(
                    root_descriptor,
                    self.database_path,
                    database_identity,
                )
            except BaseException:
                if connection is not None:
                    connection.close()
                raise
        if connection is None:  # pragma: no cover - guarded by the successful path above
            raise PathContainmentError("conversation SQLite database could not be opened")
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

    def _migrate(self) -> None:
        connection = self._connect()
        try:
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if journal_mode != "wal":
                configured_mode = str(
                    connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                ).lower()
                if configured_mode != "wal":
                    raise ConversationConflictError(
                        "conversation database could not enable WAL mode"
                    )
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
                    inbound_request_json TEXT NOT NULL,
                    inbound_request_digest TEXT NOT NULL,
                    inbound_source_reference_count INTEGER NOT NULL,
                    inbound_replay_state TEXT NOT NULL DEFAULT 'exact'
                        CHECK(inbound_replay_state IN ('exact','unavailable')),
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
                    owner_id TEXT NOT NULL,
                    lease_expires_at REAL NOT NULL,
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
            self._migrate_hardening_columns(connection)
        finally:
            connection.close()

    @staticmethod
    def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}

    def _migrate_hardening_columns(self, connection: sqlite3.Connection) -> None:
        required_turn_columns = {
            "inbound_request_json",
            "inbound_request_digest",
            "inbound_source_reference_count",
            "inbound_replay_state",
        }
        required_attempt_columns = {"owner_id", "lease_expires_at"}
        existing_turn_columns = self._column_names(connection, "turns")
        existing_attempt_columns = self._column_names(connection, "attempts")
        invalid_replay = False
        if required_turn_columns <= existing_turn_columns:
            invalid_replay = (
                connection.execute(
                    "SELECT 1 FROM turns WHERE inbound_request_json='' "
                    "OR inbound_request_digest='' "
                    "OR inbound_replay_state NOT IN ('exact','unavailable') LIMIT 1"
                ).fetchone()
                is not None
            )
        if (
            required_turn_columns <= existing_turn_columns
            and required_attempt_columns <= existing_attempt_columns
            and not invalid_replay
        ):
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            turn_columns = self._column_names(connection, "turns")
            inbound_schema_was_incomplete = False
            turn_additions = (
                (
                    "inbound_request_json",
                    "TEXT NOT NULL DEFAULT ''",
                ),
                (
                    "inbound_request_digest",
                    "TEXT NOT NULL DEFAULT ''",
                ),
                (
                    "inbound_source_reference_count",
                    "INTEGER NOT NULL DEFAULT 0",
                ),
                (
                    "inbound_replay_state",
                    "TEXT NOT NULL DEFAULT 'unavailable'",
                ),
            )
            for column, declaration in turn_additions:
                if column in turn_columns:
                    continue
                inbound_schema_was_incomplete = True
                connection.execute(f"ALTER TABLE turns ADD COLUMN {column} {declaration}")
                self._inject_migration(f"after_add_turns_{column}")

            attempt_columns = self._column_names(connection, "attempts")
            attempt_additions = (
                ("owner_id", "TEXT NOT NULL DEFAULT 'legacy-orphan'"),
                ("lease_expires_at", "REAL NOT NULL DEFAULT 0"),
            )
            for column, declaration in attempt_additions:
                if column in attempt_columns:
                    continue
                connection.execute(f"ALTER TABLE attempts ADD COLUMN {column} {declaration}")
                self._inject_migration(f"after_add_attempts_{column}")

            if inbound_schema_was_incomplete:
                connection.execute("UPDATE turns SET inbound_replay_state='unavailable'")
            connection.execute(
                "UPDATE turns SET inbound_replay_state='unavailable' "
                "WHERE inbound_request_json='' OR inbound_request_digest='' "
                "OR inbound_replay_state NOT IN ('exact','unavailable')"
            )
            self._inject_migration("after_legacy_replay_classification")
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _inject_migration(self, point: str) -> None:
        if self._migration_crash_injector is not None:
            self._migration_crash_injector(point)

    def ensure_private_modes(self) -> None:
        with self._stable_root_descriptor() as root_descriptor:
            self._ensure_private_modes(root_descriptor)

    def _ensure_private_modes(self, root_descriptor: int) -> None:
        os.fchmod(root_descriptor, 0o700)
        for path in self._database_files():
            is_main_database = path == self.database_path
            descriptor = self._open_private_target(
                root_descriptor,
                path,
                create=False,
                require_stable_identity=is_main_database,
            )
            if descriptor is None:
                continue
            try:
                os.fchmod(descriptor, 0o600)
                if is_main_database:
                    self._assert_private_target_identity(
                        root_descriptor,
                        path,
                        self._identity(os.fstat(descriptor)),
                    )
            finally:
                os.close(descriptor)

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
        inbound_request_json = _canonical_json(_request_payload(turn.planning_request))
        inbound_request_digest = _digest(
            "studyloop.planning-inbound-request",
            json.loads(inbound_request_json),
        )
        with self._transaction() as connection:
            self._ensure_conversation(connection, command.conversation_id)
            prior = connection.execute(
                "SELECT * FROM turns WHERE turn_id=?", (turn.turn_id,)
            ).fetchone()
            if prior is not None:
                if (
                    prior["conversation_id"] != command.conversation_id
                    or prior["learner_text"] != turn.text
                ):
                    raise ConversationConflictError("turn ID was reused with different input")
                if prior["inbound_replay_state"] != "exact":
                    raise ConversationConflictError(
                        "exact replay unavailable for legacy learner turn"
                    )
                if (
                    prior["inbound_request_digest"] != inbound_request_digest
                    or prior["inbound_request_json"] != inbound_request_json
                    or int(prior["inbound_source_reference_count"])
                    != len(turn.planning_request.source_references)
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
                    "INSERT INTO turns("
                    "turn_id,conversation_id,turn_ordinal,learner_text,"
                    "inbound_request_json,inbound_request_digest,"
                    "inbound_source_reference_count,inbound_replay_state,planning_request_json,"
                    "context_generation,brief_context_digest,status,version,planning_run_id"
                    ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        turn.turn_id,
                        command.conversation_id,
                        ordinal,
                        turn.text,
                        inbound_request_json,
                        inbound_request_digest,
                        len(turn.planning_request.source_references),
                        "exact",
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
            owner_id = command.owner_id.strip() or self._ids.new_id("owner")
            lease_expires_at = self._clock() + self.attempt_lease_seconds
            try:
                connection.execute(
                    "INSERT INTO attempts(attempt_id,conversation_id,turn_id,attempt_seq,status,"
                    "retry_of_attempt_id,private_reason,owner_id,lease_expires_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        attempt_id,
                        command.conversation_id,
                        command.turn_id,
                        sequence,
                        "active",
                        command.retry_of_attempt_id,
                        "",
                        owner_id,
                        lease_expires_at,
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
                owner_id,
                lease_expires_at,
            )

    def renew_attempt_lease(self, attempt: AttemptRecord, owner_id: str) -> AttemptRecord:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT attempts.*,turns.version AS turn_version FROM attempts "
                "JOIN turns USING(turn_id) WHERE attempt_id=?",
                (attempt.attempt_id,),
            ).fetchone()
            if (
                row is None
                or row["status"] != "active"
                or row["owner_id"] != owner_id
                or int(row["turn_version"]) != attempt.turn_version
            ):
                raise ConversationConflictError("model attempt lease ownership was lost")
            deadline = self._clock() + self.attempt_lease_seconds
            connection.execute(
                "UPDATE attempts SET lease_expires_at=? WHERE attempt_id=? AND owner_id=?",
                (deadline, attempt.attempt_id, owner_id),
            )
            return self._attempt_from_row(row, "active", attempt.turn_version, deadline)

    def claim_expired_attempt(
        self,
        attempt: AttemptRecord,
        recovery_owner_id: str,
    ) -> AttemptRecord | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT attempts.*,turns.version AS turn_version FROM attempts "
                "JOIN turns USING(turn_id) WHERE attempt_id=?",
                (attempt.attempt_id,),
            ).fetchone()
            now = self._clock()
            if (
                row is None
                or row["status"] != "active"
                or int(row["turn_version"]) != attempt.turn_version
                or str(row["owner_id"]) != attempt.owner_id
                or float(row["lease_expires_at"]) != attempt.lease_expires_at
                or float(row["lease_expires_at"]) > now
            ):
                return None
            deadline = now + self.attempt_lease_seconds
            connection.execute(
                "UPDATE attempts SET owner_id=?,lease_expires_at=? WHERE attempt_id=?",
                (recovery_owner_id, deadline, attempt.attempt_id),
            )
            return self._attempt_from_row(
                row,
                "active",
                attempt.turn_version,
                deadline,
                owner_id=recovery_owner_id,
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

    def _active_attempt(
        self,
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
        if not command.expected_owner_id or row["owner_id"] != command.expected_owner_id:
            raise ConversationConflictError("model attempt lease ownership was lost")
        if (
            isinstance(command, MarkAttemptInterrupted)
            and command.require_expired_lease
            and float(row["lease_expires_at"]) > self._clock()
        ):
            raise ConversationConflictError("live model attempt lease has not expired")
        return row

    @staticmethod
    def _attempt_from_row(
        row: sqlite3.Row,
        status: str,
        turn_version: int,
        lease_expires_at: float | None = None,
        *,
        owner_id: str | None = None,
    ) -> AttemptRecord:
        return AttemptRecord(
            str(row["attempt_id"]),
            str(row["conversation_id"]),
            str(row["turn_id"]),
            int(row["attempt_seq"]),
            cast("Any", status),
            turn_version,
            cast("str | None", row["retry_of_attempt_id"]),
            owner_id if owner_id is not None else str(row["owner_id"]),
            lease_expires_at if lease_expires_at is not None else float(row["lease_expires_at"]),
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
                "SELECT status,owner_id FROM attempts WHERE attempt_id=? AND conversation_id=? "
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
            if not command.expected_owner_id or attempt["owner_id"] != command.expected_owner_id:
                raise ConversationConflictError("model attempt lease ownership was lost")
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

    def mark_capability_dispatching(
        self,
        intent_id: str,
        expected_owner_id: str,
    ) -> CapabilityIntent:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM capability_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            if row is None:
                raise ConversationConflictError("capability intent does not exist")
            if row["status"] in {"projected", "refused"}:
                return self._intent_from_row(row)
            attempt = connection.execute(
                "SELECT status,owner_id FROM attempts WHERE attempt_id=?",
                (row["attempt_id"],),
            ).fetchone()
            if attempt is None or attempt["status"] == "completed":
                raise ConversationConflictError("capability attempt is no longer recoverable")
            if attempt["status"] == "active" and (
                not expected_owner_id or attempt["owner_id"] != expected_owner_id
            ):
                raise ConversationConflictError("model attempt lease ownership was lost")
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
            attempt = connection.execute(
                "SELECT status,owner_id FROM attempts WHERE attempt_id=?",
                (intent["attempt_id"],),
            ).fetchone()
            if attempt is None or attempt["status"] == "completed":
                raise ConversationConflictError("capability attempt is no longer recoverable")
            if attempt["status"] == "active" and (
                not command.expected_owner_id or attempt["owner_id"] != command.expected_owner_id
            ):
                raise ConversationConflictError("model attempt lease ownership was lost")
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
                "SELECT status,owner_id FROM attempts WHERE attempt_id=? AND conversation_id=? "
                "AND turn_id=?",
                (command.attempt_id, command.conversation_id, command.turn_id),
            ).fetchone()
            if attempt is None or attempt["status"] != "active":
                raise ConversationConflictError("assistant message requires an active attempt")
            if not command.expected_owner_id or attempt["owner_id"] != command.expected_owner_id:
                raise ConversationConflictError("model attempt lease ownership was lost")
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

    def recoverable_attempts(self, conversation_id: str) -> list[AttemptRecord]:
        """Return expired candidates; callers must still claim each candidate by CAS."""
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT attempts.*,turns.version AS turn_version FROM attempts "
                "JOIN turns USING(turn_id) WHERE attempts.conversation_id=? "
                "AND attempts.status='active' AND attempts.lease_expires_at<=?",
                (conversation_id, self._clock()),
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
