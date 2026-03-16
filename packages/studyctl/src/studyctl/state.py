"""Sync state — tracks what's been synced to prevent duplication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .settings import get_state_dir, get_state_file


@dataclass
class SyncedSource:
    """A file that has been synced to NotebookLM."""

    path: str  # Relative to home
    content_hash: str
    source_id: str  # NotebookLM source ID
    synced_at: str
    notebook_id: str


@dataclass
class TopicState:
    """State for a single topic/notebook."""

    topic_name: str
    notebook_id: str | None = None
    notebook_title: str = ""
    sources: dict[str, SyncedSource] = field(default_factory=dict)  # path → SyncedSource
    last_sync: str = ""
    last_audio_generated: str = ""


class SyncState:
    """Persistent state for the sync pipeline."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {"version": 1, "topics": {}}
        self._load()

    def _load(self) -> None:
        if get_state_file().exists():
            try:
                self._data = json.loads(get_state_file().read_text())
            except json.JSONDecodeError:
                import sys

                print(
                    f"[studyctl] Corrupt state file {get_state_file()}, using defaults",
                    file=sys.stderr,
                )

    def save(self) -> None:
        import os

        get_state_dir().mkdir(parents=True, exist_ok=True)
        get_state_file().write_text(json.dumps(self._data, indent=2) + "\n")
        os.chmod(get_state_file(), 0o600)

    def get_topic(self, name: str) -> TopicState:
        raw = self._data.setdefault("topics", {}).get(name, {})
        sources = {}
        for path, s in raw.get("sources", {}).items():
            sources[path] = SyncedSource(**s)
        return TopicState(
            topic_name=name,
            notebook_id=raw.get("notebook_id"),
            notebook_title=raw.get("notebook_title", ""),
            sources=sources,
            last_sync=raw.get("last_sync", ""),
            last_audio_generated=raw.get("last_audio_generated", ""),
        )

    def set_topic(self, state: TopicState) -> None:
        self._data.setdefault("topics", {})[state.topic_name] = {
            "notebook_id": state.notebook_id,
            "notebook_title": state.notebook_title,
            "sources": {p: asdict(s) for p, s in state.sources.items()},
            "last_sync": state.last_sync,
            "last_audio_generated": state.last_audio_generated,
        }

    def set_notebook_id(self, topic_name: str, notebook_id: str, title: str) -> None:
        ts = self.get_topic(topic_name)
        ts.notebook_id = notebook_id
        ts.notebook_title = title
        self.set_topic(ts)

    def record_sync(
        self, topic_name: str, path: str, content_hash: str, source_id: str, notebook_id: str
    ) -> None:
        ts = self.get_topic(topic_name)
        ts.sources[path] = SyncedSource(
            path=path,
            content_hash=content_hash,
            source_id=source_id,
            synced_at=datetime.now(UTC).isoformat(),
            notebook_id=notebook_id,
        )
        ts.last_sync = datetime.now(UTC).isoformat()
        self.set_topic(ts)

    def needs_sync(self, path: Path) -> bool:
        """Check if a file has changed since last sync."""
        rel = str(path.relative_to(Path.home()))
        current_hash = file_hash(path)
        for topic_data in self._data.get("topics", {}).values():
            for synced_path, source in topic_data.get("sources", {}).items():
                if synced_path == rel and source.get("content_hash") == current_hash:
                    return False
        return True


def file_hash(path: Path) -> str:
    """SHA256 of file content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
