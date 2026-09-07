"""Claude Code session exporter."""

import json
import logging
import sqlite3
import hashlib
import os
from pathlib import Path

from ..utils import file_fingerprint
from ..context.capture import capture_run
from .base import ExportStats, commit_batch, flush_batch
from .native import NativeCollector, claude_record


# Claude Code directories
CLAUDE_DIR = Path.home() / ".claude"


class ClaudeCodeExporter:
    """Exporter for Claude Code JSONL sessions."""

    source_name = "claude_code"

    def __init__(self, projects_dir: Path | None = None):
        """Initialize Claude Code exporter.

        Args:
            projects_dir: Override default Claude projects directory
        """
        self.projects_dir = projects_dir or (
            Path(os.environ.get("CLAUDE_CONFIG_DIR", str(CLAUDE_DIR))) / "projects"
        )

    def is_available(self) -> bool:
        """Check if Claude Code data is available."""
        return self.projects_dir.exists()

    @capture_run("claude-native-v1")
    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions with batch commits."""
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch = []
        batch_messages = []
        # Forks/subagents may repeat a source UUID. Reserve ownership across
        # the pending batch too, so one conversation cannot steal another's row.
        self._message_owners = dict(conn.execute("SELECT id, session_id FROM messages"))

        for agent_file in sorted(self.projects_dir.rglob("*.jsonl")):
            try:
                session_data, msgs, reason = self._process_session_file(
                    conn, agent_file, incremental
                )
                if session_data:
                    batch.append(session_data)
                    batch_messages.extend(msgs)
                    if len(batch) >= batch_size:
                        ready, ready_messages = batch, batch_messages
                        batch, batch_messages = [], []
                        commit_batch(conn, ready, ready_messages, stats)
                elif reason == "skipped":
                    stats.skipped += 1
                elif reason == "empty":
                    stats.empty += 1
            except Exception as exc:
                stats.errors += 1
                logging.getLogger(__name__).warning(
                    "Session export deferred (%s): %s", type(exc).__name__, exc
                )

        # Commit final batch
        flush_batch(conn, batch, batch_messages, stats, source=self.source_name)

        return stats

    def _process_session_file(
        self, conn: sqlite3.Connection, agent_file: Path, incremental: bool
    ) -> tuple[dict | None, list[dict], str | None]:
        """Return ``(session_data, messages, reason)``.

        ``reason`` explains a ``None`` session: ``"skipped"`` (unchanged
        fingerprint) or ``"empty"`` (no supported native records). It is ``None``
        when a session is returned for import.
        """
        project_path = str(agent_file.parent).replace(str(self.projects_dir) + "/", "")
        session_id = agent_file.stem
        fingerprint = "claude-v3:" + file_fingerprint(agent_file)

        # Check if already imported with same fingerprint (incremental mode)
        if incremental:
            existing = conn.execute(
                "SELECT import_fingerprint FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing and existing[0] == fingerprint:
                return None, [], "skipped"

        native = NativeCollector(
            session_id, self.source_name, str(agent_file.resolve()), "claude-native-v1"
        )

        # Parse JSONL file
        messages = []
        first_ts = last_ts = None
        git_branch = None
        source_session_id = None
        cwd_found = False

        with open(agent_file, encoding="utf-8") as f:
            for line_number, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line.strip())
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "Malformed transcript JSON; source retained for retry"
                    ) from exc

                if not isinstance(entry, dict):
                    continue
                if not cwd_found and isinstance(entry.get("cwd"), str) and entry["cwd"]:
                    project_path = entry["cwd"]
                    cwd_found = True
                source_session_id = source_session_id or entry.get("sessionId")
                native_start = len(native.sources)
                claude_record(native, entry, line_number)
                msg = entry.get("message")
                if not isinstance(msg, dict) or msg.get("role") not in {
                    "user",
                    "assistant",
                }:
                    continue
                ts = entry.get("timestamp")
                if ts:
                    if not first_ts:
                        first_ts = ts
                    last_ts = ts

                if not git_branch:
                    git_branch = entry.get("gitBranch")

                role = msg.get("role", "unknown")
                content = msg.get("content")

                # Flatten content array to text
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                if isinstance(item.get("text"), str):
                                    text_parts.append(item["text"])
                            elif item.get("type") == "tool_use":
                                text_parts.append(f"[tool:{item.get('name')}]")
                        elif isinstance(item, str):
                            text_parts.append(item)
                    content = "\n".join(text_parts)

                if not isinstance(content, str) or not content.strip():
                    continue

                message_id = (
                    entry.get("uuid")
                    or f"{session_id}-line-{line_number}-{hashlib.sha256(line.encode()).hexdigest()[:16]}"
                )
                owners = getattr(self, "_message_owners", {})
                owner = owners.get(message_id)
                if owner is None:
                    row = conn.execute(
                        "SELECT session_id FROM messages WHERE id = ?", (message_id,)
                    ).fetchone()
                    owner = row[0] if row else None
                if owner is not None and owner != session_id:
                    message_id = f"claude:{session_id}:{message_id}"
                owners[message_id] = session_id
                messages.append(
                    {
                        "id": message_id,
                        "native_sources": native.sources[native_start:],
                        "parent_id": entry.get("parentUuid"),
                        "role": role,
                        "content": content,
                        "model": entry.get("message", {}).get("model"),
                        "timestamp": ts,
                        "metadata": json.dumps(
                            {
                                **{
                                    k: v
                                    for k, v in entry.items()
                                    if k
                                    not in (
                                        "message",
                                        "uuid",
                                        "parentUuid",
                                        "timestamp",
                                    )
                                },
                                "source_message_id": entry.get("uuid"),
                                "source_parent_id": entry.get("parentUuid"),
                            }
                        ),
                    }
                )

        if fingerprint != "claude-v3:" + file_fingerprint(agent_file):
            raise ValueError("Transcript changed during export; retry when stable")

        if not messages and not native.sources:
            return None, [], "empty"

        # Check if this is an update or new insert
        is_update = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        session_data = {
            "id": session_id,
            "native_sources": native.sources,
            "source": "claude_code",
            "project_path": project_path,
            "git_branch": git_branch,
            "created_at": first_ts,
            "updated_at": last_ts,
            "import_fingerprint": fingerprint,
            "metadata": json.dumps(
                {
                    "fingerprint": fingerprint,
                    "source_file": str(agent_file),
                    "source_session_id": source_session_id,
                    "encoded_project_path": agent_file.relative_to(
                        self.projects_dir
                    ).parts[0],
                }
            ),
            "replace_messages": True,
            "status": "added" if not is_update else "updated",
        }

        return (
            session_data,
            [
                {
                    "id": m["id"],
                    "native_sources": m["native_sources"],
                    "session_id": session_id,
                    "role": m["role"],
                    "content": m["content"],
                    "model": m["model"],
                    "timestamp": m["timestamp"],
                    "metadata": m["metadata"],
                    "seq": idx + 1,
                }
                for idx, m in enumerate(messages)
            ],
            None,
        )
