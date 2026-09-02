"""Session state management — read/write IPC files for the live dashboard.

The AI agent writes to these files during a study session.
Viewports (TUI, Web PWA) poll them for live updates.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

SESSION_DIR = Path(os.environ.get("STUDYLOOP_SESSION_DIR", Path.home() / ".config" / "studyloop"))
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
    """Read session state JSON. Returns {} if no active session or file missing.

    Performs key migration: reads ``mux_session`` first, falls back to legacy
    ``tmux_session``. Same for ``mux_main_pane``/``mux_sidebar_pane``.
    This allows both old and new writers to coexist during migration.
    """
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}

    # Key migration: prefer mux_* keys, fall back to tmux_* keys
    if "mux_session" not in state and "tmux_session" in state:
        state["mux_session"] = state["tmux_session"]
    if "mux_main_pane" not in state and "tmux_main_pane" in state:
        state["mux_main_pane"] = state["tmux_main_pane"]
    if "mux_sidebar_pane" not in state and "tmux_sidebar_pane" in state:
        state["mux_sidebar_pane"] = state["tmux_sidebar_pane"]

    # A PTY/ACP session owns no multiplexer. ``write_session_state`` is a
    # read-merge-write, so a PTY session started after a CLI tmux session
    # (``studyloop study``) inherits that session's dead ``tmux_session`` key.
    # Left in place, zombie detection then classifies the live PTY session as
    # a dead tmux session and deletes its state file. Drop the inherited
    # multiplexer keys so a live PTY session is never mistaken for a dead
    # tmux session. (Renamed from "legacy ttyd session" during ttyd
    # retirement stage 5 — the leak was never ttyd-specific, any tmux-backed
    # CLI session triggers it.)
    if state.get("transport") in ("pty", "acp"):
        state.pop("tmux_session", None)
        state.pop("mux_session", None)

    return state


def _ensure_session_dir() -> None:
    """Ensure SESSION_DIR exists with 0700 permissions (owner-only access)."""
    created = not SESSION_DIR.exists()
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    if created:
        with suppress(OSError):
            SESSION_DIR.chmod(0o700)


def _lock_file() -> Path:
    """Return the current lock file path derived from SESSION_DIR."""
    return SESSION_DIR / ".session-state.lock"


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
        lock_fd = os.open(str(_lock_file()), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            current = read_session_state()
            # Don't resurrect a deleted state file just to record that a
            # session ended. An id-less ``{"mode": "ended"}`` marker is litter —
            # no id, no topic, nothing the dashboard summary needs — that
            # outlives the session and confuses the next desync diagnosis. An
            # end-marker for a session whose file already exists (or any update
            # carrying real session state) still writes normally.
            merged = {**current, **updates}
            if (
                not STATE_FILE.exists()
                and merged.get("mode") == "ended"
                and not merged.get("study_session_id")
            ):
                return
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
    # Read first and handle failure, rather than checking exists() and then
    # reading: session release calls clear_session_files() on an executor
    # thread, so the file can be unlinked between the two. That raced a
    # request and surfaced as HTTP 500 from GET /api/session/state.
    # FileNotFoundError is an OSError, so this also covers "no session yet".
    try:
        raw = TOPICS_FILE.read_text()
    except OSError:
        return []
    entries = []
    for line in raw.splitlines():
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
    # Same deletion race as parse_topics_file: clear_session_files() unlinks
    # PARKING_FILE from an executor thread, so read-then-handle rather than
    # exists-then-read.
    try:
        raw = PARKING_FILE.read_text()
    except OSError:
        return []
    entries = []
    for line in raw.splitlines():
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
            with suppress(OSError):
                f.unlink()


def is_session_active() -> bool:
    """Check if there's an active session (not ended, not stale)."""
    state = read_session_state()
    if not state.get("study_session_id"):
        return False
    # Session marked as ended by cleanup — not active
    return state.get("mode") != "ended"


def claim_blocks_web_start(state: dict) -> bool:
    """Whether a file claim should block a new web PTY/ACP session start.

    Call this only AFTER confirming the in-process singleton
    (``session/active.py``) is empty — see
    docs/architecture/session-authority.md clause 2 (R-01) for the full
    contract. Given that precondition:

    - No claim at all (``study_session_id`` unset, or ``mode == "ended"``)
      never blocks.
    - A CLI-owned claim (no ``transport`` key, or one outside
      ``{"pty", "acp"}``) blocks iff its recorded multiplexer session
      (``mux_session``/``tmux_session``) still exists. No name recorded, or
      the multiplexer backend can't be reached, means "can't confirm it's
      alive" — treated conservatively as NOT blocking (stale), same as a
      session whose tmux server was killed outside StudyLoop.
    - A web-owned claim (``transport`` in ``{"pty", "acp"}``) can only be
      genuinely live via the singleton the caller already ruled out — this
      codebase runs one web server process per machine (see
      ``session/active.py``'s own docstring). Reaching this function with
      such a claim therefore proves it is stale (the crash-then-restart
      cell): it never blocks.
    """
    if not state.get("study_session_id") or state.get("mode") == "ended":
        return False
    if state.get("transport") in ("pty", "acp"):
        return False
    session_name = state.get("mux_session") or state.get("tmux_session")
    if not session_name:
        return False
    import contextlib

    from studyloop.multiplexer import get_backend

    with contextlib.suppress(Exception):
        return bool(get_backend().session_exists(session_name))
    return False
