"""Claude Code session exporter."""

import json
import sqlite3
import uuid
from pathlib import Path

from ..utils import file_fingerprint
from .base import ExportStats, commit_batch


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
        self.projects_dir = projects_dir or (CLAUDE_DIR / "projects")

    def is_available(self) -> bool:
        """Check if Claude Code data is available."""
        return self.projects_dir.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions with batch commits."""
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch = []
        batch_messages = []

        for agent_file in self.projects_dir.rglob("agent-*.jsonl"):
            try:
                session_data, msgs = self._process_session_file(
                    conn, agent_file, incremental
                )
                if session_data:
                    batch.append(session_data)
                    batch_messages.extend(msgs)
                    if len(batch) >= batch_size:
                        commit_batch(conn, batch, batch_messages, stats)
                        batch = []
                        batch_messages = []
            except Exception:
                stats.errors += 1

        # Commit final batch
        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats

    def _process_session_file(
        self, conn: sqlite3.Connection, agent_file: Path, incremental: bool
    ) -> tuple[dict | None, list[dict]]:
        """Return session data and messages instead of direct commit."""
        project_path = str(agent_file.parent).replace(str(self.projects_dir) + "/", "")
        session_id = agent_file.stem
        fingerprint = file_fingerprint(agent_file)

        # Check if already imported with same fingerprint (incremental mode)
        if incremental:
            existing = conn.execute(
                "SELECT import_fingerprint FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing and existing[0] == fingerprint:
                return None, []

        # Parse JSONL file
        messages = []
        first_ts = last_ts = None
        git_branch = None

        with open(agent_file) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue

                ts = entry.get("timestamp")
                if ts:
                    if not first_ts:
                        first_ts = ts
                    last_ts = ts

                if not git_branch:
                    git_branch = entry.get("gitBranch")

                msg = entry.get("message", {})
                role = msg.get("role", "unknown")
                content = msg.get("content")

                # Flatten content array to text
                if isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                text_parts.append(item.get("text", ""))
                            elif item.get("type") == "tool_use":
                                text_parts.append(f"[tool:{item.get('name')}]")
                        elif isinstance(item, str):
                            text_parts.append(item)
                    content = "\n".join(text_parts)

                messages.append(
                    {
                        "id": entry.get("uuid", str(uuid.uuid4())),
                        "parent_id": entry.get("parentUuid"),
                        "role": role,
                        "content": content,
                        "model": entry.get("message", {}).get("model"),
                        "timestamp": ts,
                        "metadata": json.dumps(
                            {
                                k: v
                                for k, v in entry.items()
                                if k
                                not in ("message", "uuid", "parentUuid", "timestamp")
                            }
                        ),
                    }
                )

        if not messages:
            return None, []

        # Check if this is an update or new insert
        is_update = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        session_data = {
            "id": session_id,
            "source": "claude_code",
            "project_path": project_path,
            "git_branch": git_branch,
            "created_at": first_ts,
            "updated_at": last_ts,
            "import_fingerprint": fingerprint,
            "metadata": json.dumps({"fingerprint": fingerprint}),
            "status": "added" if not is_update else "updated",
        }

        return session_data, [
            {
                "id": m["id"],
                "session_id": session_id,
                "role": m["role"],
                "content": m["content"],
                "model": m["model"],
                "timestamp": m["timestamp"],
                "metadata": m["metadata"],
                "seq": idx + 1,
            }
            for idx, m in enumerate(messages)
        ]
