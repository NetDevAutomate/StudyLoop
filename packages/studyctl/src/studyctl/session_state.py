"""Session state management — read/write IPC files for the live dashboard.

The AI agent writes to these files during a study session.
Viewports (TUI, Web PWA) poll them for live updates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SESSION_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = SESSION_DIR / "session-state.json"
TOPICS_FILE = SESSION_DIR / "session-topics.md"
PARKING_FILE = SESSION_DIR / "session-parking.md"


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


def write_session_state(updates: dict) -> None:
    """Atomic read-merge-write of session state. Creates file if missing."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    current = read_session_state()
    current.update(updates)
    STATE_FILE.write_text(json.dumps(current, indent=2, default=str))


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
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    with TOPICS_FILE.open("a") as f:
        f.write(f"- [{time}] {topic} | status:{status} | {note}\n")


def append_parking(question: str) -> None:
    """Append a parking lot entry to session-parking.md."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    with PARKING_FILE.open("a") as f:
        f.write(f"- {question}\n")


def clear_session_files() -> None:
    """Remove IPC files at session end."""
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
        if f.exists():
            f.unlink()


def is_session_active() -> bool:
    """Check if there's an active session (state file exists with a study_session_id)."""
    state = read_session_state()
    return bool(state.get("study_session_id"))
