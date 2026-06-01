"""pi coding agent and oh-my-pi (omp) session exporter.

Both harnesses use an identical on-disk JSONL format and differ only in their
storage roots:

  pi  sessions:  ~/.pi/agent/sessions/<cwd-slug>/<ISO-ts>_<uuid>.jsonl
  omp sessions:  ~/.omp/agent/sessions/<cwd-slug>/<ISO-ts>_<uuid>.jsonl

**File format (version 3)**
============================
Line 1 — session header::

    {"type": "session", "version": 3, "id": "<uuid>",
     "timestamp": "<ISO8601 with ms+Z>", "cwd": "/abs/path"}

  ``timestamp`` may be absent on some omp headers; fall back to the session-id's
  embedded time or the first message timestamp.

Subsequent lines::

    {"type": "message", "id": "…", "parentId": "…", "timestamp": "<ISO>",
     "message": { … }}

  type=="message" carries a nested ``.message`` object:
    - user:       {"role":"user","content":[{"type":"text","text":"…"}],
                   "timestamp":<ms epoch>}
    - assistant:  {"role":"assistant","content":[…],"model":"…","provider":"…",…,
                   "timestamp":<ms epoch>}
    - toolResult: {"role":"toolResult","toolCallId":"…","toolName":"…",
                   "content":[{"type":"text","text":"…"}],
                   "timestamp":<ms epoch>}

Text extraction: join ``.text`` from ``type=="text"`` parts; skip ``type=="thinking"``
and ``type=="toolCall"`` parts (mirrors other exporters that exclude thinking).
Messages whose content produces no text are silently skipped.

**Deduplication**: updated_at comparison (last-message timestamp or header
timestamp), matching the opencode.py approach.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .base import ExportStats, commit_batch

# Module-level constants — monkeypatched in tests
PI_SESSIONS = Path.home() / ".pi" / "agent" / "sessions"
OMP_SESSIONS = Path.home() / ".omp" / "agent" / "sessions"


def _ms_to_iso(ms: int | float | None) -> str | None:
    """Convert a millisecond-epoch timestamp to an ISO-8601 string."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _extract_text(msg_obj: dict) -> str | None:
    """Extract plain text from a pi/omp message object.

    Concatenates all ``type=="text"`` parts from the ``content`` array.
    Skips ``thinking`` and ``toolCall`` parts.
    Returns None when no extractable text is found.
    """
    content = msg_obj.get("content")
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text = part.get("text", "")
            if text:
                parts.append(text)

    return "\n".join(parts) if parts else None


def _parse_header(line: str) -> dict | None:
    """Parse the first line of a JSONL file as the session header.

    Returns the parsed dict when the line is a valid session header.
    Raises ``ValueError`` for a completely malformed (un-parseable) first line so
    the caller's per-file try/except can count it as an error.
    Returns None when the line parses as JSON but is not a session-type object
    (treated as a silent skip rather than an error).
    """
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSONL header: {exc}") from exc
    if not isinstance(obj, dict):
        return None
    if obj.get("type") != "session":
        return None
    return obj


def _header_timestamp(header: dict) -> str | None:
    """Extract a timestamp string from the session header, if present."""
    ts = header.get("timestamp")
    if not ts:
        return None
    # Already an ISO string
    if isinstance(ts, str):
        return ts
    return None


class PiFamilyExporter:
    """Parametrised exporter for pi and oh-my-pi (omp) JSONL session files.

    Instantiate with a ``source_name`` ("pi" or "omp") and the corresponding
    session root directory.  Two concrete instances are provided as module-level
    constants: ``PiExporter`` and ``OhMyPiExporter``.
    """

    def __init__(self, source_name: str, root: Path) -> None:
        self._source_name = source_name
        self._root = root

    @property
    def source_name(self) -> str:
        """Unique identifier stored in the ``sessions.source`` column."""
        return self._source_name

    def is_available(self) -> bool:
        """Return True when the session root directory exists."""
        return self._root.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions found under the session root.

        Each ``.jsonl`` file is one session.  Processing is incremental by
        default (skip when ``updated_at`` is unchanged).  Per-file errors are
        swallowed and counted in ``stats.errors``; they never abort the run.
        """
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch: list[dict] = []
        batch_messages: list[dict] = []

        for session_file in sorted(self._root.rglob("*.jsonl")):
            try:
                session_data, msgs, reason = self._process_file(
                    conn, session_file, incremental
                )
                if session_data is not None:
                    batch.append(session_data)
                    batch_messages.extend(msgs)
                    if len(batch) >= batch_size:
                        commit_batch(conn, batch, batch_messages, stats)
                        batch = []
                        batch_messages = []
                elif reason == "skipped":
                    stats.skipped += 1
                elif reason == "empty":
                    stats.empty += 1
            except Exception:
                stats.errors += 1

        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _process_file(
        self,
        conn: sqlite3.Connection,
        session_file: Path,
        incremental: bool,
    ) -> tuple[dict | None, list[dict], str | None]:
        """Parse one JSONL session file.

        Returns ``(session_dict, message_rows, reason)``. ``reason`` explains a
        ``None`` session: ``"skipped"`` (unchanged ``updated_at``) or ``"empty"``
        (no header, no id, or no extractable messages). It is ``None`` when a
        session is returned for import.
        """
        lines = session_file.read_text(encoding="utf-8").splitlines()
        if not lines:
            return None, [], "empty"

        header = _parse_header(lines[0])
        if header is None:
            # File does not start with a valid session header — skip
            return None, [], "empty"

        session_id = header.get("id", "")
        if not session_id:
            return None, [], "empty"

        header_ts = _header_timestamp(header)
        cwd = header.get("cwd", "")
        version = header.get("version", 3)

        # Parse message lines
        messages: list[dict] = []
        first_user_text: str | None = None

        for raw_line in lines[1:]:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            if not isinstance(obj, dict):
                continue
            if obj.get("type") != "message":
                continue

            msg_obj = obj.get("message")
            if not isinstance(msg_obj, dict):
                continue

            role = msg_obj.get("role", "")
            if role not in ("user", "assistant", "toolResult"):
                continue

            text = _extract_text(msg_obj)
            if not text:
                continue

            # Timestamp: prefer ms-epoch on the inner message; fall back to ISO on
            # the outer line object
            inner_ts_ms = msg_obj.get("timestamp")
            if isinstance(inner_ts_ms, (int, float)):
                timestamp = _ms_to_iso(inner_ts_ms)
            else:
                outer_ts = obj.get("timestamp")
                timestamp = outer_ts if isinstance(outer_ts, str) else None

            msg_id = obj.get("id", "")
            if not msg_id:
                # Generate a stable id from session_id + seq
                msg_id = f"{session_id}_{len(messages) + 1}"

            if first_user_text is None and role == "user":
                first_user_text = text

            messages.append(
                {
                    "id": msg_id,
                    "session_id": session_id,
                    "role": role,
                    "content": text,
                    "model": msg_obj.get("model"),
                    "timestamp": timestamp,
                    "metadata": json.dumps(
                        {
                            "provider": msg_obj.get("provider"),
                        }
                    ),
                    "seq": 0,  # filled in below
                }
            )

        if not messages:
            # No extractable content — caller counts this as "empty".
            return None, [], "empty"

        # Assign sequence numbers
        for idx, m in enumerate(messages):
            m["seq"] = idx + 1

        # Derive updated_at from last message timestamp or header
        last_ts = messages[-1]["timestamp"]
        updated_at = last_ts or header_ts

        # Incremental check
        existing = conn.execute(
            "SELECT updated_at FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        if existing and incremental:
            if existing["updated_at"] == updated_at:
                return None, [], "skipped"
            # Updated — delete stale messages
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            status = "updated"
        else:
            status = "added"

        # Derive created_at from first message timestamp or header
        created_at = messages[0]["timestamp"] or header_ts

        # Title: first 60 chars of the first user message, or session_id
        title = (first_user_text or session_id)[:60]

        session_data: dict = {
            "id": session_id,
            "source": self._source_name,
            "project_path": cwd,
            "git_branch": None,
            "created_at": created_at,
            "updated_at": updated_at,
            "metadata": json.dumps({"title": title, "version": version}),
            "status": status,
        }

        return session_data, messages, None


# Concrete instances used by the exporter registry
PiExporter = PiFamilyExporter("pi", PI_SESSIONS)
OhMyPiExporter = PiFamilyExporter("omp", OMP_SESSIONS)
