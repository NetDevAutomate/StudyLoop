"""RepoPrompt session exporter."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils import file_fingerprint
from .base import ExportStats, commit_batch

# RepoPrompt uses macOS Core Foundation epoch (Jan 1, 2001)
CF_EPOCH_OFFSET = 978307200


def cf_timestamp_to_iso(cf_ts: float | None) -> str | None:
    """Convert Core Foundation timestamp to ISO format string."""
    if cf_ts is None:
        return None
    try:
        unix_ts = cf_ts + CF_EPOCH_OFFSET
        dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, OSError, OverflowError):
        return None


# RepoPrompt directories
REPOPROMPT_DIR = Path.home() / "Library" / "Application Support" / "RepoPrompt"


class RepoPromptExporter:
    """Exporter for RepoPrompt chat sessions."""

    source_name = "repoprompt"

    def __init__(self, app_support_dir: Path | None = None):
        """Initialize RepoPrompt exporter.

        Args:
            app_support_dir: Override default RepoPrompt Application Support directory
        """
        self.app_support_dir = app_support_dir or REPOPROMPT_DIR
        self._workspace_names: dict[str, str] = {}

    def is_available(self) -> bool:
        """Check if RepoPrompt data is available."""
        workspaces_dir = self.app_support_dir / "Workspaces"
        return workspaces_dir.exists()

    def _load_workspace_mapping(self) -> dict[str, str]:
        """Load workspace ID to name mapping from windowSessions.json."""
        if self._workspace_names:
            return self._workspace_names

        sessions_file = self.app_support_dir / "windowSessions.json"
        if sessions_file.exists():
            try:
                with open(sessions_file) as f:
                    data = json.load(f)
                for window in data.get("windows", []):
                    ws_id = window.get("workspaceID")
                    ws_name = window.get("workspaceName")
                    if ws_id and ws_name:
                        self._workspace_names[ws_id] = ws_name
            except (json.JSONDecodeError, OSError):
                pass

        return self._workspace_names

    def _extract_workspace_name(self, workspace_path: Path) -> str:
        """Extract workspace name from path or mapping."""
        # Try to extract from windowSessions.json mapping
        mapping = self._load_workspace_mapping()
        for ws_id, ws_name in mapping.items():
            if ws_id in workspace_path.name:
                return ws_name

        # Fallback: parse from directory name (Workspace-<name>-<uuid>)
        dir_name = workspace_path.name
        if dir_name.startswith("Workspace-"):
            parts = dir_name.split("-")
            if len(parts) >= 2:
                # Name is everything between first "Workspace-" and the UUID at the end
                # UUID is 5 parts: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
                if len(parts) > 6:
                    return "-".join(parts[1:-5])
                return parts[1]

        return dir_name

    def export_all(
        self, conn: sqlite3.Connection, incremental: bool = True, batch_size: int = 50
    ) -> ExportStats:
        """Export all sessions with batch commits."""
        if not self.is_available():
            return ExportStats()

        stats = ExportStats()
        batch = []
        batch_messages = []

        workspaces_dir = self.app_support_dir / "Workspaces"

        for workspace_path in workspaces_dir.iterdir():
            if not workspace_path.is_dir():
                continue

            chats_dir = workspace_path / "Chats"
            if not chats_dir.exists():
                continue

            workspace_name = self._extract_workspace_name(workspace_path)

            for chat_file in chats_dir.glob("ChatSession-*.json"):
                try:
                    session_data, msgs = self._process_chat_file(
                        conn, chat_file, workspace_name, incremental
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

    def _process_chat_file(
        self,
        conn: sqlite3.Connection,
        chat_file: Path,
        workspace_name: str,
        incremental: bool,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Process a single chat session file."""
        fingerprint = file_fingerprint(chat_file)

        # Parse JSON file
        try:
            with open(chat_file) as f:
                chat_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None, []

        session_id = chat_data.get("id")
        if not session_id:
            return None, []

        # Check if already imported with same fingerprint (incremental mode)
        if incremental:
            existing = conn.execute(
                "SELECT metadata FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing:
                try:
                    meta = json.loads(existing[0] or "{}")
                    if meta.get("fingerprint") == fingerprint:
                        return None, []
                except json.JSONDecodeError:
                    pass

        # Extract messages
        raw_messages = chat_data.get("messages", [])
        if not raw_messages:
            return None, []

        messages = []
        first_ts = None
        last_ts = None

        for msg in raw_messages:
            msg_ts = msg.get("timestamp")
            iso_ts = cf_timestamp_to_iso(msg_ts)

            if iso_ts:
                if not first_ts:
                    first_ts = iso_ts
                last_ts = iso_ts

            role = "user" if msg.get("isUser") else "assistant"
            content = msg.get("rawText", "")
            model = msg.get("modelName")

            messages.append(
                {
                    "id": msg.get("id"),
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "model": model,
                    "timestamp": iso_ts,
                    "metadata": json.dumps(
                        {
                            "sequenceIndex": msg.get("sequenceIndex"),
                            "promptTokens": msg.get("promptTokens"),
                            "completionTokens": msg.get("completionTokens"),
                            "cost": msg.get("cost"),
                        }
                    ),
                    "seq": (msg.get("sequenceIndex") or 0) + 1,
                }
            )

        # Use savedAt for updated_at if available
        saved_at = chat_data.get("savedAt")
        updated_at = cf_timestamp_to_iso(saved_at) if saved_at else last_ts

        # Check if this is an update or new insert
        is_update = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

        session_data = {
            "id": session_id,
            "source": "repoprompt",
            "project_path": workspace_name,
            "git_branch": None,
            "created_at": first_ts,
            "updated_at": updated_at,
            "metadata": json.dumps(
                {
                    "fingerprint": fingerprint,
                    "name": chat_data.get("name"),
                    "shortID": chat_data.get("shortID"),
                    "workspaceID": chat_data.get("workspaceID"),
                    "preferredAIModel": chat_data.get("preferredAIModel"),
                    "selectedFilePaths": chat_data.get("selectedFilePaths"),
                }
            ),
            "status": "added" if not is_update else "updated",
        }

        return session_data, messages
