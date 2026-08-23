"""Durable append-only JSONL journal for planning repository transactions."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

JOURNAL_SCHEMA_VERSION = 1
JOURNAL_EVENT_VERSION = 1

JournalEventKind = Literal["intent", "committed", "recovered"]


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
        if payload.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            raise JournalCorruptionError("unsupported planning journal schema version")
        if payload.get("event_version") != JOURNAL_EVENT_VERSION:
            raise JournalCorruptionError("unsupported planning journal event version")
        if payload.get("event") not in {"intent", "committed", "recovered"}:
            raise JournalCorruptionError("unsupported planning journal event kind")
        try:
            return cls(
                event=payload["event"],
                intent_id=str(payload["intent_id"]),
                caller=str(payload["caller"]),
                idempotency_key=str(payload["idempotency_key"]),
                payload_digest=str(payload["payload_digest"]),
                operation=str(payload["operation"]),
                plan_id=str(payload["plan_id"]),
                before_document_digest=_optional_str(payload.get("before_document_digest")),
                after_document_digest=_optional_str(payload.get("after_document_digest")),
                before_structure_digest=_optional_str(payload.get("before_structure_digest")),
                after_structure_digest=_optional_str(payload.get("after_structure_digest")),
                occurred_at=str(payload["occurred_at"]),
                payload=_object_dict(payload.get("payload", {}), "payload"),
                recovery=_object_dict(payload.get("recovery", {}), "recovery"),
                result=_object_dict(payload.get("result", {}), "result"),
                schema_version=int(payload["schema_version"]),
                event_version=int(payload["event_version"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise JournalCorruptionError(f"invalid planning journal event: {error}") from error


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


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


def fsync_directory(directory: Path) -> None:
    """Fsync directory metadata after create, replace, or cleanup."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
