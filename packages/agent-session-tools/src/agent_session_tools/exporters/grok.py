"""Import Grok's local chat_history.jsonl conversations without model calls."""

import json
import logging
import os
import sqlite3
from pathlib import Path

from ..utils import file_fingerprint
from .base import ExportStats, commit_batch

logger = logging.getLogger(__name__)


class GrokExporter:
    source_name = "grok"

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self.sessions_dir = (
            sessions_dir
            or Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok")))
            / "sessions"
        )

    def is_available(self) -> bool:
        return self.sessions_dir.exists()

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        stats = ExportStats()
        for history in sorted(self.sessions_dir.rglob("chat_history.jsonl")):
            try:
                summary_path = history.parent / "summary.json"
                summary = json.loads(summary_path.read_text())
                info = summary.get("info", {})
                session_id = "grok_" + str(info.get("id") or history.parent.name)
                fingerprint = (
                    "grok-v1:"
                    + file_fingerprint(history)
                    + ":"
                    + file_fingerprint(summary_path)
                )
                existing = conn.execute(
                    "SELECT import_fingerprint FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                if incremental and existing and existing[0] == fingerprint:
                    stats.skipped += 1
                    continue
                messages = []
                # Parse the complete file before writing. A partially written or
                # corrupt JSONL line must not replace the last good import.
                for index, line in enumerate(history.read_text().splitlines()):
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    role = record.get("type")
                    if role not in {"user", "assistant"} or record.get(
                        "synthetic_reason"
                    ):
                        continue
                    content = record.get("content")
                    if isinstance(content, list):
                        content = "\n".join(
                            part["text"]
                            for part in content
                            if isinstance(part, dict)
                            and part.get("type") == "text"
                            and isinstance(part.get("text"), str)
                        )
                    if not isinstance(content, str) or not content.strip():
                        continue
                    messages.append(
                        {
                            "id": f"{session_id}-{index + 1}",
                            "session_id": session_id,
                            "role": role,
                            "content": content,
                            "model": record.get("model_id"),
                            "timestamp": record.get("timestamp"),
                            "seq": index + 1,
                            "metadata": json.dumps({"line": index + 1}),
                        }
                    )
                after = (
                    "grok-v1:"
                    + file_fingerprint(history)
                    + ":"
                    + file_fingerprint(summary_path)
                )
                if after != fingerprint:
                    raise ValueError("Source changed while being read; retry export")
                if not messages:
                    stats.empty += 1
                    continue
                session = {
                    "id": session_id,
                    "source": self.source_name,
                    "project_path": info.get("cwd"),
                    "git_branch": summary.get("head_branch"),
                    "created_at": summary.get("created_at"),
                    "updated_at": summary.get("updated_at"),
                    "import_fingerprint": fingerprint,
                    "metadata": json.dumps({"history_file": str(history)}),
                    "status": "updated" if existing else "added",
                    "replace_messages": True,
                }
                commit_batch(conn, [session], messages, stats)
            except (OSError, ValueError, TypeError, AttributeError, sqlite3.Error):
                conn.rollback()
                stats.errors += 1
                logger.warning("Unable to import Grok history %s", history)
        return stats
