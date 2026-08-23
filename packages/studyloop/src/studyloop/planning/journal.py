"""Durable append-only JSONL journal for planning repository transactions."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from .digests import compute_document_digest, compute_structure_digest
from .markdown import parse_plan

if TYPE_CHECKING:
    from pathlib import Path

JOURNAL_SCHEMA_VERSION = 1
JOURNAL_EVENT_VERSION = 1

JournalEventKind = Literal["intent", "committed", "recovered"]

_TERMINAL_MATCH_FIELDS = (
    "caller",
    "idempotency_key",
    "payload_digest",
    "operation",
    "plan_id",
    "before_document_digest",
    "after_document_digest",
    "before_structure_digest",
    "after_structure_digest",
    "payload",
)


class JournalError(RuntimeError):
    """Base error for a journal that cannot be trusted."""


class JournalCorruptionError(JournalError):
    """Raised when an append-only journal line is malformed or unsupported."""


@dataclass(frozen=True)
class JournalEvent:
    """One versioned transaction event written as a single JSON object."""

    event: JournalEventKind
    intent_id: str
    caller: str
    idempotency_key: str
    payload_digest: str
    operation: str
    plan_id: str
    before_document_digest: str | None
    after_document_digest: str | None
    before_structure_digest: str | None
    after_structure_digest: str | None
    occurred_at: str
    payload: dict[str, object] = field(default_factory=dict)
    recovery: dict[str, object] = field(default_factory=dict)
    result: dict[str, object] = field(default_factory=dict)
    schema_version: int = JOURNAL_SCHEMA_VERSION
    event_version: int = JOURNAL_EVENT_VERSION

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable event mapping."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> JournalEvent:
        """Validate and construct one supported journal event."""
        if not isinstance(payload, dict):
            raise JournalCorruptionError("journal event must be a JSON object")
        if type(payload.get("schema_version")) is not int or (
            payload.get("schema_version") != JOURNAL_SCHEMA_VERSION
        ):
            raise JournalCorruptionError("unsupported planning journal schema version")
        if type(payload.get("event_version")) is not int or (
            payload.get("event_version") != JOURNAL_EVENT_VERSION
        ):
            raise JournalCorruptionError("unsupported planning journal event version")
        event_kind = payload.get("event")
        if event_kind not in {"intent", "committed", "recovered"}:
            raise JournalCorruptionError("unsupported planning journal event kind")
        try:
            return cls(
                event=cast("JournalEventKind", event_kind),
                intent_id=_required_str(payload, "intent_id"),
                caller=_required_str(payload, "caller"),
                idempotency_key=_required_str(payload, "idempotency_key"),
                payload_digest=_required_str(payload, "payload_digest"),
                operation=_required_str(payload, "operation"),
                plan_id=_required_str(payload, "plan_id"),
                before_document_digest=_optional_str(payload.get("before_document_digest")),
                after_document_digest=_optional_str(payload.get("after_document_digest")),
                before_structure_digest=_optional_str(payload.get("before_structure_digest")),
                after_structure_digest=_optional_str(payload.get("after_structure_digest")),
                occurred_at=_required_str(payload, "occurred_at"),
                payload=_object_dict(payload.get("payload", {}), "payload"),
                recovery=_object_dict(payload.get("recovery", {}), "recovery"),
                result=_object_dict(payload.get("result", {}), "result"),
                schema_version=int(payload["schema_version"]),
                event_version=int(payload["event_version"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise JournalCorruptionError(f"invalid planning journal event: {error}") from error


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise JournalCorruptionError("journal digest fields must be strings or null")
    return value


def _required_str(payload: dict[object, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise JournalCorruptionError(f"journal {name} must be a non-empty string")
    return value


def _object_dict(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise JournalCorruptionError(f"journal {name} must be an object")
    return {str(key): item for key, item in value.items()}


def append_event(path: Path, event: JournalEvent) -> None:
    """Append and fsync one JSONL event, creating the journal mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        payload = (
            json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode("utf-8")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:  # pragma: no cover - defensive OS failure
                raise OSError("short write while appending planning journal")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if not existed:
        fsync_directory(path.parent)


def repair_torn_tail(path: Path) -> Literal["truncated", "completed"] | None:
    """Repair only a non-newline-terminated final journal fragment.

    Invalid bytes at EOF are truncated to the last complete newline. A fully
    valid event missing only its newline is completed. Newline-terminated and
    interior corruption remain the responsibility of strict ``read_events``.
    Callers must hold the repository root lock.
    """
    if not path.exists():
        return None
    try:
        data = path.read_bytes()
    except OSError as error:
        raise JournalCorruptionError(f"cannot read planning journal: {error}") from error
    if not data or data.endswith(b"\n"):
        return None

    last_newline = data.rfind(b"\n")
    tail_start = last_newline + 1
    tail = data[tail_start:]
    try:
        decoded = tail.decode("utf-8")
        parsed = json.loads(decoded)
    except (UnicodeError, json.JSONDecodeError):
        _truncate_tail(path, tail_start)
        return "truncated"

    # Valid JSON that is not a valid event is schema corruption, not a torn
    # append. Refuse it rather than silently discarding an intelligible record.
    JournalEvent.from_dict(parsed)
    _complete_final_line(path)
    return "completed"


def _truncate_tail(path: Path, length: int) -> None:
    """Truncate only the invalid EOF bytes without rewriting valid history."""
    descriptor = os.open(path, os.O_WRONLY)
    try:
        os.ftruncate(descriptor, length)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _complete_final_line(path: Path) -> None:
    """Append only the missing newline to an otherwise valid final event."""
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    try:
        written = os.write(descriptor, b"\n")
        if written != 1:  # pragma: no cover - defensive OS failure
            raise OSError("short write while completing planning journal line")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_events(path: Path) -> list[JournalEvent]:
    """Read all durable events, failing closed on any malformed line."""
    if not path.exists():
        return []
    events: list[JournalEvent] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise JournalCorruptionError(f"cannot read planning journal: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise JournalCorruptionError(f"blank planning journal line {line_number}")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise JournalCorruptionError(
                f"malformed planning journal line {line_number}: {error.msg}"
            ) from error
        try:
            events.append(JournalEvent.from_dict(payload))
        except JournalCorruptionError as error:
            raise JournalCorruptionError(f"planning journal line {line_number}: {error}") from error
    return events


def validate_event_sequence(events: list[JournalEvent]) -> None:
    """Fail closed unless events form one internally consistent state machine."""
    active: JournalEvent | None = None
    prior_intents: dict[str, JournalEvent] = {}
    prior_terminals: dict[str, JournalEvent] = {}
    idempotency_payloads: dict[tuple[str, str], str] = {}
    completed_idempotency: set[tuple[str, str]] = set()

    for event in events:
        key = (event.caller, event.idempotency_key)
        prior_payload = idempotency_payloads.setdefault(key, event.payload_digest)
        if prior_payload != event.payload_digest:
            raise JournalCorruptionError("idempotency tuple has conflicting payload digests")

        if event.event == "intent":
            if active is not None:
                raise JournalCorruptionError("duplicate intent while another intent is pending")
            if key in completed_idempotency:
                raise JournalCorruptionError("intent follows a terminal after outcome")
            previous_terminal = prior_terminals.get(event.intent_id)
            if previous_terminal is not None:
                previous_intent = prior_intents[event.intent_id]
                retry_after_before = (
                    previous_terminal.event == "recovered"
                    and previous_terminal.recovery.get("classification") == "before"
                )
                if not retry_after_before or not _matching_transaction(previous_intent, event):
                    raise JournalCorruptionError("duplicate intent_id has conflicting transaction")
            _validate_intent_event(event)
            active = event
            prior_intents[event.intent_id] = event
            continue

        if active is None:
            label = "duplicate" if event.intent_id in prior_terminals else "orphan"
            raise JournalCorruptionError(f"{label} terminal event for {event.intent_id!r}")
        if active.intent_id != event.intent_id:
            raise JournalCorruptionError("terminal event does not match the pending intent_id")
        if not _matching_transaction(active, event):
            raise JournalCorruptionError("terminal does not match prior intent")
        classification = _validate_terminal_event(event, active)
        prior_terminals[event.intent_id] = event
        if classification == "after":
            completed_idempotency.add(key)
        active = None


def _matching_transaction(intent: JournalEvent, other: JournalEvent) -> bool:
    return intent.intent_id == other.intent_id and all(
        getattr(intent, field_name) == getattr(other, field_name)
        for field_name in _TERMINAL_MATCH_FIELDS
    )


def _validate_digest_pair(document: str | None, structure: str | None, label: str) -> None:
    if (document is None) != (structure is None):
        raise JournalCorruptionError(f"{label} document/structure digest pair is incomplete")
    for digest in (document, structure):
        if digest is None:
            continue
        prefix = "sha256:v1:"
        payload = digest.removeprefix(prefix)
        if (
            not digest.startswith(prefix)
            or len(payload) != 64
            or any(character not in "0123456789abcdef" for character in payload)
        ):
            raise JournalCorruptionError(f"{label} digest is not a supported versioned SHA-256")


def _validate_intent_event(event: JournalEvent) -> None:
    if event.operation not in {"create", "update", "upsert", "record", "journal"}:
        raise JournalCorruptionError("journal intent has unsupported operation")
    _validate_digest_pair(
        event.before_document_digest,
        event.before_structure_digest,
        "before",
    )
    _validate_digest_pair(
        event.after_document_digest,
        event.after_structure_digest,
        "after",
    )
    if event.operation == "create" and event.before_document_digest is not None:
        raise JournalCorruptionError("create intent unexpectedly has a before state")
    if event.operation == "update" and event.before_document_digest is None:
        raise JournalCorruptionError("update intent is missing its before state")
    if event.operation in {"create", "update", "upsert"} and (event.after_document_digest is None):
        raise JournalCorruptionError("file mutation intent is missing its after state")
    if event.operation in {"record", "journal"} and (
        event.before_document_digest != event.after_document_digest
        or event.before_structure_digest != event.after_structure_digest
    ):
        raise JournalCorruptionError("journal-only intent changes canonical state")
    _validate_terminal_result(event)
    _validate_result_revisions_against_recovery(event)


def _validate_terminal_event(
    event: JournalEvent, intent: JournalEvent
) -> Literal["before", "after"]:
    classification = event.recovery.get("classification")
    if event.event == "committed":
        if classification != "after":
            raise JournalCorruptionError("committed terminal must classify the after state")
        resolved: Literal["before", "after"] = "after"
    elif classification in {"before", "after"}:
        resolved = cast("Literal['before', 'after']", classification)
    else:
        raise JournalCorruptionError("recovered terminal has invalid classification")

    if resolved == "before":
        if event.result:
            raise JournalCorruptionError("before recovery terminal must not contain a result")
        return resolved
    _validate_terminal_result(event)
    if any(
        event.result.get(field_name) != intent.result.get(field_name)
        for field_name in ("document_revision", "structure_revision")
    ):
        raise JournalCorruptionError("terminal result revisions disagree with prior intent")
    if event.result != intent.result:
        raise JournalCorruptionError("terminal result disagrees with prior intent")
    return resolved


def _validate_terminal_result(event: JournalEvent) -> None:
    expected = {
        "status": "committed",
        "intent_id": event.intent_id,
        "plan_id": event.plan_id,
        "document_digest": event.after_document_digest,
        "structure_digest": event.after_structure_digest,
    }
    for field_name, expected_value in expected.items():
        if event.result.get(field_name) != expected_value:
            raise JournalCorruptionError(f"terminal result {field_name} disagrees with event")
    document_revision = event.result.get("document_revision")
    structure_revision = event.result.get("structure_revision")
    if event.after_document_digest is None:
        if document_revision is not None or structure_revision is not None:
            raise JournalCorruptionError("journal-only absent result unexpectedly has revisions")
        return
    if (
        type(document_revision) is not int
        or document_revision < 1
        or type(structure_revision) is not int
        or structure_revision < 1
    ):
        raise JournalCorruptionError("terminal result revisions must be positive integers")


def _validate_result_revisions_against_recovery(event: JournalEvent) -> None:
    """Bind redundant result revisions to the exact intended after bytes."""
    if event.recovery.get("recovery_version") != 1:
        raise JournalCorruptionError("intent has unsupported recovery payload version")
    encoded = event.recovery.get("after_bytes_b64")
    if encoded is None:
        if event.after_document_digest is not None:
            raise JournalCorruptionError("intent after state is missing recovery bytes")
        return
    if not isinstance(encoded, str):
        raise JournalCorruptionError("intent recovery bytes must be base64 text or null")
    try:
        after_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
        after_text = after_bytes.decode("utf-8")
        plan = parse_plan(after_text, plan_id=event.plan_id)
    except Exception as error:
        raise JournalCorruptionError("intent has invalid after recovery bytes") from error

    if event.after_document_digest is None:
        raise JournalCorruptionError("intent has recovery bytes without an after state")
    if plan.plan_id != event.plan_id:
        raise JournalCorruptionError("intent recovery plan_id disagrees with event")
    document_digest = compute_document_digest(after_bytes)
    structure_digest = compute_structure_digest(plan)
    if (
        document_digest != event.after_document_digest
        or structure_digest != event.after_structure_digest
    ):
        raise JournalCorruptionError("intent recovery bytes disagree with after digests")
    if plan.schema_version >= 2 and (
        plan.document_digest != document_digest or plan.structure_digest != structure_digest
    ):
        raise JournalCorruptionError("intent recovery plan stores inconsistent digests")
    if (
        event.result.get("document_revision") != plan.document_revision
        or event.result.get("structure_revision") != plan.structure_revision
    ):
        raise JournalCorruptionError("terminal result revisions disagree with recovery state")


def fsync_directory(directory: Path) -> None:
    """Fsync directory metadata after create, replace, or cleanup."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
