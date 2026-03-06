"""Aider session exporter."""

import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from ..config_loader import load_config
from .base import ExportStats

BATCH_SIZE = 100


def commit_batch(
    conn: sqlite3.Connection,
    batch: list[dict],
    batch_messages: list[dict],
    stats: ExportStats,
) -> None:
    """Commit a batch of sessions and messages."""
    if not batch:
        return

    try:
        # Upsert sessions
        conn.executemany(
            """
            INSERT OR REPLACE INTO sessions
            (id, source, project_path, git_branch, created_at, updated_at, metadata)
            VALUES (:id, :source, :project_path, :git_branch, :created_at, :updated_at, :metadata)
            """,
            batch,
        )

        # Upsert messages
        if batch_messages:
            conn.executemany(
                """
                INSERT OR REPLACE INTO messages
                (id, session_id, role, content, model, timestamp, metadata, seq)
                VALUES (:id, :session_id, :role, :content, :model, :timestamp, :metadata, :seq)
                """,
                batch_messages,
            )

        conn.commit()

        # Update stats
        for s in batch:
            if s["status"] == "added":
                stats.added += 1
            elif s["status"] == "updated":
                stats.updated += 1
            elif s["status"] == "skipped":
                stats.skipped += 1

    except Exception:
        stats.errors += len(batch)


def stable_id(prefix: str, key: str) -> str:
    """Generate stable, deterministic ID from prefix and key."""
    import hashlib

    normalized = str(Path(key).resolve()).lower()
    hash_bytes = hashlib.sha256(normalized.encode()).hexdigest()[:12]
    return f"{prefix}_{hash_bytes}"


class AiderExporter:
    """Exporter for Aider markdown history files."""

    source_name = "aider"

    def __init__(self, search_paths: list[Path] | None = None):
        """Initialize Aider exporter.

        Args:
            search_paths: Directories to search for .aider.chat.history.md files
        """
        self.search_paths = search_paths or [
            Path.home() / "code",
            Path.home() / "projects",
            Path.home() / "dev",
            Path.home() / "src",
            Path.cwd(),
        ]

    def is_available(self) -> bool:
        """Check if any search paths exist."""
        return any(path.exists() for path in self.search_paths)

    def export_all(self, conn: sqlite3.Connection, incremental: bool = True) -> ExportStats:
        """Export all Aider sessions with batching."""
        stats = ExportStats(added=0, updated=0, skipped=0, errors=0)
        batch = []
        batch_messages = []
        seen_files: set[str] = set()

        # Load excluded directories from config
        config = load_config()
        excluded_dirs = set(config.get("excluded_dirs", []))

        for base_path in self.search_paths:
            if not base_path.exists():
                continue

            # Use os.walk with exclusion filtering instead of rglob
            for history_file in self._walk_with_exclusions(base_path, excluded_dirs):
                file_key = str(history_file.resolve())
                if file_key in seen_files:
                    continue
                seen_files.add(file_key)

                try:
                    session_data, msgs = self._process_history_file(history_file, incremental, conn)
                    if session_data:
                        if session_data.get("status") == "skipped":
                            stats.skipped += 1
                        else:
                            batch.append(session_data)
                            batch_messages.extend(msgs)
                            if len(batch) >= BATCH_SIZE:
                                commit_batch(conn, batch, batch_messages, stats)
                                batch = []
                                batch_messages = []
                except Exception:
                    stats.errors += 1

        # Commit final batch
        if batch:
            commit_batch(conn, batch, batch_messages, stats)

        return stats

    def _walk_with_exclusions(self, base_path: Path, excluded_dirs: set[str]) -> list[Path]:
        """Walk directory tree, skipping excluded directories.

        Uses os.walk with in-place directory filtering to avoid
        traversing cloud storage, node_modules, .venv, etc.
        """
        target_file = ".aider.chat.history.md"
        results = []

        for dirpath, dirnames, filenames in os.walk(base_path, topdown=True):
            # Filter out excluded directories in-place to prevent descent
            dirnames[:] = [
                d
                for d in dirnames
                if d not in excluded_dirs and not any(excl in d for excl in excluded_dirs)
            ]

            if target_file in filenames:
                results.append(Path(dirpath) / target_file)

        return results

    def _process_history_file(
        self, history_file: Path, incremental: bool, conn: sqlite3.Connection | None = None
    ) -> tuple[dict | None, list[dict]]:
        """Process single file and return session data and messages."""
        project_path = str(history_file.parent)
        session_id = stable_id("aider", project_path)

        # Check if already imported (use file modification time)
        file_mtime = datetime.fromtimestamp(history_file.stat().st_mtime).isoformat()
        existing = None

        if incremental and conn:
            existing = conn.execute(
                "SELECT updated_at FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing and existing[0] == file_mtime:
                return {"id": session_id, "status": "skipped"}, []

        try:
            content = history_file.read_text()
        except OSError:
            return None, []

        messages = self._parse_aider_markdown(content)
        if not messages:
            return {"id": session_id, "status": "skipped"}, []

        # Build session record
        session_data = {
            "id": session_id,
            "source": "aider",
            "project_path": project_path,
            "git_branch": None,
            "created_at": file_mtime,
            "updated_at": file_mtime,
            "metadata": "{}",
            "status": "added" if not existing else "updated",
        }

        return session_data, [
            {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "role": m["role"],
                "content": m["content"],
                "model": None,
                "timestamp": None,
                "metadata": m["metadata"],
                "seq": idx + 1,
            }
            for idx, m in enumerate(messages)
        ]

    def _parse_aider_markdown(self, content: str) -> list[dict]:
        """Parse Aider markdown format into messages."""
        messages = []
        current_role = None
        current_content: list[str] = []

        for line in content.split("\n"):
            if line.startswith("#### "):
                # Save previous message
                if current_role and current_content:
                    messages.append(
                        {
                            "id": str(uuid.uuid4()),
                            "role": current_role,
                            "content": "\n".join(current_content).strip(),
                            "model": None,
                            "timestamp": None,
                            "metadata": "{}",
                        }
                    )

                # Start new message
                role_text = line[5:].strip().lower()
                current_role = "user" if "user" in role_text else "assistant"
                current_content = []
            else:
                current_content.append(line)

        # Don't forget the last message
        if current_role and current_content:
            messages.append(
                {
                    "id": str(uuid.uuid4()),
                    "role": current_role,
                    "content": "\n".join(current_content).strip(),
                    "model": None,
                    "timestamp": None,
                    "metadata": "{}",
                }
            )

        return messages
