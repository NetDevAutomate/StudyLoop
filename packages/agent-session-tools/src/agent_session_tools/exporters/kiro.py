"""Kiro CLI session exporter.

Kiro stores conversations in a SQLite database with two table generations:
- ``conversations`` (v1): columns (key TEXT, value TEXT)
- ``conversations_v2`` (v2): columns (key TEXT, conversation_id TEXT,
  value TEXT, created_at INTEGER, updated_at INTEGER)

Both tables store the same JSON blob in ``value``.  History entries use a
nested structure — each item has ``user``, ``assistant``, and
``request_metadata`` keys (NOT a flat ``role``/``content`` layout).

User text lives at   ``msg["user"]["content"]["Prompt"]["prompt"]``.
Assistant prose uses ``ToolUse.content`` or ``Response.content``.
Both dict-shaped history entries and older turn-pair lists are supported.
"""

import hashlib
import json
import sqlite3
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from ..context.capture import capture_run
from .base import ExportStats, commit_batch
from .native import NativeCollector, kiro_entry

# Kiro CLI database location
KIRO_DB = Path.home() / "Library/Application Support/kiro-cli/data.sqlite3"


def _extract_turn(turn: dict) -> tuple[str, str] | None:
    """Extract one (role, text) from a single kiro turn dict, or None.

    Handles the on-disk list-entry turn shapes:
    - user turn:      ``{"content": {"Prompt": {"prompt": "..."}}}``
    - assistant turn: ``{"ToolUse": {"content": "..."}}`` or
                      ``{"Response": {"content": "..."}}``
    Tool-result / cancelled turns carry no prose and yield None.
    """
    content = turn.get("content")
    if isinstance(content, dict):
        prompt = content.get("Prompt")
        if (
            isinstance(prompt, dict)
            and isinstance(prompt.get("prompt"), str)
            and prompt["prompt"]
        ):
            return ("user", prompt["prompt"])
    for key in ("ToolUse", "Response"):
        block = turn.get(key)
        if (
            isinstance(block, dict)
            and isinstance(block.get("content"), str)
            and block["content"]
        ):
            return ("assistant", block["content"])
    return None


def _extract_text(msg: object) -> list[tuple[str, str, str | None]]:
    """Extract (role, text, timestamp_iso) tuples from a Kiro history entry.

    Kiro entries come in two shapes: the real on-disk format is a *list* of
    turn dicts (``[user_turn, assistant_turn, ...]``); an older/normalised
    dict form uses top-level ``user``/``assistant`` keys. Both are handled;
    anything else yields no text.
    """
    results: list[tuple[str, str, str | None]] = []

    if isinstance(msg, list):
        # Real on-disk format: a sequence of turn dicts.
        for turn in msg:
            if isinstance(turn, dict):
                extracted = _extract_turn(turn)
                if extracted:
                    results.append((extracted[0], extracted[1], None))
        return results

    if not isinstance(msg, dict):
        return results

    # Both generations use the same tagged assistant variants.
    for role in ("user", "assistant"):
        turn = msg.get(role)
        if not isinstance(turn, dict):
            continue
        extracted = _extract_turn(turn)
        if extracted:
            results.append((extracted[0], extracted[1], None))
        elif (
            role == "assistant"
            and isinstance(turn.get("content"), str)
            and turn["content"]
        ):
            results.append(("assistant", turn["content"], None))

    # Preserve actual request/response timing; list entries have no metadata.
    meta = msg.get("request_metadata")
    if not isinstance(meta, dict):
        meta = {}
    request_ts = _epoch_ms_to_iso(meta.get("request_start_timestamp_ms"))
    response_ts = _epoch_ms_to_iso(meta.get("stream_end_timestamp_ms"))
    user = msg.get("user")
    user_ts = user.get("timestamp") if isinstance(user, dict) else None
    if isinstance(user_ts, str):
        try:
            datetime.fromisoformat(user_ts)
        except ValueError:
            user_ts = None
    else:
        user_ts = None
    results = [
        (
            role,
            text,
            (user_ts or request_ts) if role == "user" else response_ts,
        )
        for role, text, _ in results
    ]

    return results


def _epoch_ms_to_iso(ms: int | None) -> str | None:
    """Convert epoch-milliseconds to ISO 8601, or None."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


class KiroCliExporter:
    """Exporter for Kiro CLI sessions."""

    source_name = "kiro_cli"

    def is_available(self) -> bool:
        """Check if Kiro CLI data is available."""
        return KIRO_DB.exists()

    @capture_run("kiro-native-v1")
    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions with batching."""
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch: list[dict] = []
        batch_messages: list[dict] = []

        with sqlite3.connect(
            f"{KIRO_DB.resolve().as_uri()}?mode=ro", uri=True
        ) as kiro_conn:
            kiro_conn.row_factory = sqlite3.Row

            # Prefer conversations_v2, fall back to v1
            tables = [
                r[0]
                for r in kiro_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('conversations_v2','conversations')"
                ).fetchall()
            ]
            # v1 can contain conversations absent from v2. Prefer v2 only
            # for duplicate conversation IDs, rather than ignoring all v1.
            seen: set[str] = set()
            rows = (
                (table == "conversations_v2", row)
                for table in ("conversations_v2", "conversations")
                if table in tables
                for row in kiro_conn.execute(f"SELECT * FROM {table}")  # noqa: S608
            )
            for use_v2, row in rows:
                project_path = row["key"]

                # v2 has conversation_id as a column; v1 only in JSON
                conv_id_col = row["conversation_id"] if use_v2 else None

                try:
                    data = json.loads(row["value"])
                except (json.JSONDecodeError, TypeError):
                    stats.errors += 1
                    continue

                if not isinstance(data, dict):
                    stats.errors += 1
                    continue
                conv_id = conv_id_col or data.get("conversation_id")
                if not isinstance(conv_id, str) or not conv_id:
                    # Older records without an ID must remain stable across runs.
                    conv_id = str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"kiro:{project_path}")
                    )
                if conv_id in seen:
                    continue
                seen.add(conv_id)
                session_id = f"kiro_{conv_id}"

                # Timestamps from v2 columns (epoch ms)
                created_at = _epoch_ms_to_iso(row["created_at"]) if use_v2 else None
                updated_at = _epoch_ms_to_iso(row["updated_at"]) if use_v2 else None

                # Parser version invalidates previous incomplete imports even
                # when the upstream timestamp has not changed (or v1 has none).
                fingerprint = (
                    "kiro-v5:" + hashlib.sha256(row["value"].encode()).hexdigest()
                )
                existing = conn.execute(
                    "SELECT updated_at, metadata FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                try:
                    metadata = (
                        json.loads(existing["metadata"] or "{}") if existing else {}
                    )
                except (json.JSONDecodeError, TypeError):
                    metadata = {}
                if not isinstance(metadata, dict):
                    metadata = {}
                if (
                    existing
                    and incremental
                    and existing["updated_at"] == updated_at
                    and metadata.get("kiro_import_fingerprint") == fingerprint
                ):
                    stats.skipped += 1
                    continue
                status = "updated" if existing else "added"

                # Extract messages from conversation history
                history = data.get("history", [])
                if not isinstance(history, list):
                    stats.errors += 1
                    continue
                if not history:
                    stats.empty += 1
                    continue

                # Retain IDs for unchanged evidence, including repeated text.
                previous_ids: dict[tuple[str, str], deque[str]] = defaultdict(deque)
                positioned_ids: dict[tuple[int, str, str], str] = {}
                for old in conn.execute(
                    "SELECT id, role, content, metadata FROM messages WHERE session_id = ? ORDER BY seq, id",
                    (session_id,),
                ):
                    previous_ids[(old["role"], old["content"])].append(old["id"])
                    try:
                        message_metadata = json.loads(old["metadata"] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        message_metadata = {}
                    position = (
                        message_metadata.get("kiro_source_position")
                        if isinstance(message_metadata, dict)
                        else None
                    )
                    if isinstance(position, int) and not isinstance(position, bool):
                        positioned_ids.setdefault(
                            (position, old["role"], old["content"]), old["id"]
                        )
                reserved_ids = set(positioned_ids.values())
                used_ids: set[str] = set()
                messages = []
                native = NativeCollector(
                    session_id,
                    self.source_name,
                    str(KIRO_DB.resolve())
                    + "/"
                    + ("conversations_v2" if use_v2 else "conversations")
                    + "/"
                    + conv_id,
                    "kiro-native-v1",
                )
                seq = 0
                for entry_index, entry in enumerate(history):
                    native_start = len(native.sources)
                    kiro_entry(native, entry, entry_index)
                    # Entries are list-shaped (real format) or dict (legacy);
                    # _extract_text handles both. Skip other scalar junk.
                    if not isinstance(entry, (list, dict)):
                        continue
                    request_meta = (
                        entry.get("request_metadata")
                        if isinstance(entry, dict)
                        else None
                    )
                    model = (
                        request_meta.get("model_id")
                        if isinstance(request_meta, dict)
                        else None
                    )
                    if not isinstance(model, str):
                        model = None
                    for role, text, timestamp in _extract_text(entry):
                        seq += 1
                        ids = previous_ids[(role, text)]
                        message_id = positioned_ids.get((seq, role, text))
                        if message_id is None:
                            while ids and (
                                ids[0] in used_ids or ids[0] in reserved_ids
                            ):
                                ids.popleft()
                            message_id = (
                                ids.popleft()
                                if ids
                                else str(
                                    uuid.uuid5(
                                        uuid.NAMESPACE_URL,
                                        f"{session_id}:{seq}:{role}:{text}",
                                    )
                                )
                            )
                        used_ids.add(message_id)
                        messages.append(
                            {
                                "id": message_id,
                                "native_sources": [
                                    source
                                    for source in native.sources[native_start:]
                                    if source.native_kind.startswith("message:" + role)
                                ],
                                "session_id": session_id,
                                "role": role,
                                "content": text,
                                "model": model if role == "assistant" else None,
                                "timestamp": timestamp,
                                "metadata": json.dumps({"kiro_source_position": seq}),
                                "seq": seq,
                            }
                        )

                if messages or native.sources:
                    session_data = {
                        "id": session_id,
                        "native_sources": native.sources,
                        "source": "kiro_cli",
                        "project_path": project_path,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "status": status,
                        "metadata": json.dumps(
                            {
                                **metadata,
                                "kiro_import_fingerprint": fingerprint,
                                "source_path": str(KIRO_DB),
                                "kiro_transcript_entries": len(
                                    data.get("transcript", [])
                                )
                                if isinstance(data.get("transcript"), list)
                                else 0,
                                "kiro_has_summary": bool(data.get("latest_summary")),
                                "kiro_pending_message": bool(data.get("next_message")),
                            }
                        ),
                        "replace_messages": True,
                    }
                    batch.append(session_data)
                    batch_messages.extend(messages)
                    if len(batch) >= batch_size:
                        commit_batch(conn, batch, batch_messages, stats)
                        batch = []
                        batch_messages = []
                else:
                    # History exists but has no supported conversation or native
                    # records. Supported tool-only histories are captured above.
                    stats.empty += 1

        # Commit final batch
        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats
