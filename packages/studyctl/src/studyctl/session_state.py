"""Session state management — read/write IPC files for the live dashboard.

The AI agent writes to these files during a study session.
Viewports (TUI, Web PWA) poll them for live updates.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

SESSION_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = SESSION_DIR / "session-state.json"
TOPICS_FILE = SESSION_DIR / "session-topics.md"
PARKING_FILE = SESSION_DIR / "session-parking.md"
_LOCK_FILE = SESSION_DIR / ".session-state.lock"


@dataclass
class TopicEntry:
    """A parsed topic entry from session-topics.md."""

    time: str  # "HH:MM"
    topic: str  # topic name
    status: str  # learning, struggling, insight, win, parked
    note: str  # description


@dataclass
class ParkingEntry:
    """A parsed parking lot entry from session-parking.md."""

    question: str
    topic_tag: str | None = None
    context: str | None = None


def read_session_state() -> dict:
    """Read session state JSON. Returns {} if no active session or file missing."""
    try:
        return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _ensure_session_dir() -> None:
    """Ensure SESSION_DIR exists with 0700 permissions (owner-only access)."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.chmod(0o700)


def _write_file_secure(path: Path, content: str) -> None:
    """Write content atomically with 0600 permissions.

    Writes to a temp file then replaces the target, preventing partial
    reads and the truncation race where two concurrent O_TRUNC opens
    leave trailing bytes from the longer write.
    """
    tmp = str(path) + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, str(path))


_state_lock = threading.Lock()


def write_session_state(updates: dict) -> None:
    """Atomic read-merge-write of session state. Creates file if missing.

    Thread-safe via threading.Lock (within process) AND cross-process-safe
    via fcntl.flock on a dedicated lock file. Without the file lock, the
    agent, sidebar TUI, and web server can race on read-merge-write and
    the last writer silently clobbers other updates.
    """
    _ensure_session_dir()
    with _state_lock:
        lock_fd = os.open(str(_LOCK_FILE), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            current = read_session_state()
            current.update(updates)
            _write_file_secure(STATE_FILE, json.dumps(current, indent=2, default=str))
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


def parse_topics_file() -> list[TopicEntry]:
    """Parse session-topics.md into structured entries.

    Expected format per line:
    - [HH:MM] topic name | status:learning | Some note about progress
    """
    if not TOPICS_FILE.exists():
        return []
    entries = []
    for line in TOPICS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or not line.startswith("- ["):
            continue
        try:
            # Parse: - [HH:MM] topic | status:X | note
            # Remove leading "- "
            rest = line[2:]
            # Extract time
            time_end = rest.index("]")
            time_str = rest[1:time_end]
            rest = rest[time_end + 2 :]  # skip "] "

            # Split by " | "
            parts = [p.strip() for p in rest.split(" | ")]
            topic = parts[0] if parts else ""
            status = "learning"
            note = ""
            for part in parts[1:]:
                if part.startswith("status:"):
                    status = part[7:]
                else:
                    note = part
            entries.append(TopicEntry(time=time_str, topic=topic, status=status, note=note))
        except (ValueError, IndexError):
            continue  # skip malformed lines
    return entries


def parse_parking_file() -> list[ParkingEntry]:
    """Parse session-parking.md into structured entries.

    Expected format per line:
    - Question text here
    """
    if not PARKING_FILE.exists():
        return []
    entries = []
    for line in PARKING_FILE.read_text().splitlines():
        line = line.strip()
        if not line or not line.startswith("- "):
            continue
        question = line[2:].strip()
        if question:
            entries.append(ParkingEntry(question=question))
    return entries


def append_topic(time: str, topic: str, status: str, note: str) -> None:
    """Append a topic entry to session-topics.md."""
    _ensure_session_dir()
    fd = os.open(str(TOPICS_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(f"- [{time}] {topic} | status:{status} | {note}\n")


def append_parking(question: str) -> None:
    """Append a parking lot entry to session-parking.md."""
    _ensure_session_dir()
    fd = os.open(str(PARKING_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(f"- {question}\n")


def clear_session_files(*, keep_state: bool = False) -> None:
    """Remove IPC files at session end.

    Args:
        keep_state: If True, preserve STATE_FILE so the dashboard can
                    render a summary view before the next session starts.
    """
    targets = (TOPICS_FILE, PARKING_FILE) if keep_state else (STATE_FILE, TOPICS_FILE, PARKING_FILE)
    for f in targets:
        if f.exists():
            f.unlink()


def is_session_active() -> bool:
    """Check if there's an active session (not ended, not stale)."""
    state = read_session_state()
    if not state.get("study_session_id"):
        return False
    # Session marked as ended by cleanup — not active
    return state.get("mode") != "ended"
