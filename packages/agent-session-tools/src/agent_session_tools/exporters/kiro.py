"""Kiro CLI session exporter.

Kiro stores conversations in a SQLite database with two table generations:
- ``conversations`` (v1): columns (key TEXT, value TEXT)
- ``conversations_v2`` (v2): columns (key TEXT, conversation_id TEXT,
  value TEXT, created_at INTEGER, updated_at INTEGER)

Both tables store the same JSON blob in ``value``.  History entries use a
nested structure — each item has ``user``, ``assistant``, and
``request_metadata`` keys (NOT a flat ``role``/``content`` layout).

User text lives at   ``msg["user"]["content"]["Prompt"]["prompt"]``.
Assistant text lives at ``msg["assistant"]["ToolUse"]["content"]``.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .base import ExportStats, commit_batch

# Kiro CLI database location
KIRO_DB = Path.home() / "Library/Application Support/kiro-cli/data.sqlite3"


def _extract_text(msg: dict) -> list[tuple[str, str, str | None]]:
    """Extract (role, text, timestamp_iso) tuples from a Kiro history entry."""
    results: list[tuple[str, str, str | None]] = []

    # User message
    user = msg.get("user")
    if isinstance(user, dict):
        content = user.get("content", {})
        if isinstance(content, dict):
            prompt = content.get("Prompt", {})
            if isinstance(prompt, dict) and prompt.get("prompt"):
                results.append(("user", prompt["prompt"], None))

    # Assistant message — text is inside ToolUse.content
    assistant = msg.get("assistant")
    if isinstance(assistant, dict):
        tool_use = assistant.get("ToolUse")
        if isinstance(tool_use, dict) and tool_use.get("content"):
            results.append(("assistant", tool_use["content"], None))
        # Fall back to top-level content if present and non-empty
        elif assistant.get("content") and isinstance(assistant["content"], str):
            results.append(("assistant", assistant["content"], None))

    # Extract timestamp from request_metadata if available
    meta = msg.get("request_metadata", {})
    if isinstance(meta, dict) and meta.get("request_start_timestamp_ms"):
        ts_ms = meta["request_start_timestamp_ms"]
        try:
            ts_iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
            # Back-fill timestamp onto results from this entry
            results = [(r, t, ts_iso if ts is None else ts) for r, t, ts in results]
        except (ValueError, OSError):
            pass

    return results


def _epoch_ms_to_iso(ms: int | None) -> str | None:
    """Convert epoch-milliseconds to ISO 8601, or None."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return None


class KiroCliExporter:
    """Exporter for Kiro CLI sessions."""

    source_name = "kiro_cli"

    def is_available(self) -> bool:
        """Check if Kiro CLI data is available."""
        return KIRO_DB.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions with batching."""
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch: list[dict] = []
        batch_messages: list[dict] = []

        with sqlite3.connect(KIRO_DB) as kiro_conn:
            kiro_conn.row_factory = sqlite3.Row

            # Prefer conversations_v2, fall back to v1
            tables = [
                r[0]
                for r in kiro_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('conversations_v2','conversations')"
                ).fetchall()
            ]
            use_v2 = "conversations_v2" in tables
            table = "conversations_v2" if use_v2 else "conversations"

            if not tables:
                return stats

            for row in kiro_conn.execute(f"SELECT * FROM {table}"):  # noqa: S608
                project_path = row["key"]

                # v2 has conversation_id as a column; v1 only in JSON
                conv_id_col = row["conversation_id"] if use_v2 else None

                try:
                    data = json.loads(row["value"])
                except json.JSONDecodeError:
                    stats.errors += 1
                    continue

                conv_id = conv_id_col or data.get("conversation_id", str(uuid.uuid4()))
                session_id = f"kiro_{conv_id}"

                # Timestamps from v2 columns (epoch ms)
                created_at = _epoch_ms_to_iso(row["created_at"]) if use_v2 else None
                updated_at = _epoch_ms_to_iso(row["updated_at"]) if use_v2 else None

                # Check if already imported (incremental)
                existing = conn.execute(
                    "SELECT updated_at FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()

                if existing and incremental:
                    # If the session hasn't been updated, skip it
                    if existing["updated_at"] == updated_at:
                        stats.skipped += 1
                        continue
                    # Otherwise we'll re-import (updated)
                    status = "updated"
                    conn.execute(
                        "DELETE FROM messages WHERE session_id = ?", (session_id,)
                    )
                else:
                    status = "added"

                # Extract messages from conversation history
                history = data.get("history", [])
                if not history:
                    stats.skipped += 1
                    continue

                messages = []
                seq = 0
                for entry in history:
                    if not isinstance(entry, dict):
                        continue
                    for role, text, timestamp in _extract_text(entry):
                        seq += 1
                        messages.append(
                            {
                                "id": str(uuid.uuid4()),
                                "session_id": session_id,
                                "role": role,
                                "content": text,
                                "model": None,
                                "timestamp": timestamp,
                                "metadata": json.dumps({}),
                                "seq": seq,
                            }
                        )

                if messages:
                    session_data = {
                        "id": session_id,
                        "source": "kiro_cli",
                        "project_path": project_path,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "status": status,
                    }
                    batch.append(session_data)
                    batch_messages.extend(messages)
                    if len(batch) >= batch_size:
                        commit_batch(conn, batch, batch_messages, stats)
                        batch = []
                        batch_messages = []

        # Commit final batch
        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats
