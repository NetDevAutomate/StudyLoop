"""Session state management — read/write IPC files for the live dashboard.

The AI agent writes to these files during a study session.
Viewports (TUI, Web PWA) poll them for live updates.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

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
    # Read first and handle failure, rather than checking exists() and then
    # reading: session release calls clear_session_files() on an executor
    # thread, exactly the race 28a431b fixed for parse_topics_file/
    # parse_parking_file below. The exists() check here was already
    # redundant -- FileNotFoundError is an OSError, already caught -- but a
    # future edit that narrowed this except clause (e.g. to just
    # json.JSONDecodeError, "since exists() already guards missing files")
    # would silently reopen the exact race (R-08).
    try:
        state = json.loads(STATE_FILE.read_text())
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


def reclaim_log_message(state: dict) -> str:
    """The "reclaiming a stale claim" warning both start paths log,
    identically (R-01b required exact-wording parity between the CLI and
    web paths; building it once here, rather than duplicating it, keeps
    that guarantee mechanical instead of a promise to remember).

    C4 (council): appends the previous owner's recorded ``child_pid`` when
    present, so a human (or `clean`/`doctor`, R-01g, 0.2.0) reading the log
    has it to hand -- reclaim itself never acts on ``child_pid`` (pid
    reuse makes killing an old child unsafe, and it may be the user's own
    still-useful agent).
    """
    session_id = state.get("study_session_id")
    transport = state.get("transport", "cli")
    child_pid = state.get("child_pid")
    base = f"Reclaiming stale session claim id={session_id} transport={transport}"
    if child_pid is not None:
        base += f" child_pid={child_pid}"
    return base + " — its owner is no longer alive"


def _claim_exists(state: dict) -> bool:
    """Whether ``state`` names a claim that hasn't been explicitly ended."""
    return bool(state.get("study_session_id")) and state.get("mode") != "ended"


def _cli_owned_claim_is_live(state: dict) -> bool:
    """Whether a CLI-owned claim's recorded multiplexer session still exists.

    Shared by :func:`claim_blocks_web_start` and :func:`claim_blocks_cli_start`
    — both ask the same question of a CLI-owned claim, just from different
    callers. No name recorded, or the multiplexer backend can't be reached,
    means "can't confirm it's alive" — treated conservatively as NOT
    blocking (stale), same as a session whose tmux server was killed
    outside StudyLoop.
    """
    session_name = state.get("mux_session") or state.get("tmux_session")
    if not session_name:
        return False

    from studyloop.multiplexer import get_backend

    try:
        return bool(get_backend().session_exists(session_name))
    except Exception as exc:
        # C5 (council): fail open is correct here -- a backend that cannot
        # be reached has no live sessions FROM HERE, and blocking a start
        # forever because tmux itself is broken would be worse than a
        # false reclaim. But silently swallowing the exception hid a
        # broken backend from anyone debugging "why did this reclaim when
        # I expected it to block" -- log it.
        logger.warning(
            "could not confirm liveness of multiplexer session %s: %s",
            session_name,
            exc,
        )
        return False


def _pid_is_alive(pid: object) -> bool:
    """Whether ``pid`` names a process this machine still has running.

    ``os.kill(pid, 0)`` sends no signal, only asks the kernel whether the
    pid exists and is reachable: ``ProcessLookupError`` means it doesn't
    (dead); ``PermissionError`` means it does but is owned by someone else
    (still counts as alive — a real process is sitting on that pid, and
    treating it as free risks two processes touching the state file at
    once). Any other failure, or a non-int ``pid`` (a claim written before
    this field existed will not reach here — callers check for it first —
    but a corrupt file might), is treated as dead: invalid input can't name
    a live process.
    """
    if not isinstance(pid, int):
        return False
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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
      (``mux_session``/``tmux_session``) still exists (see
      :func:`_cli_owned_claim_is_live`).
    - A web-owned claim (``transport`` in ``{"pty", "acp"}``) is normally
      stale once the singleton is ruled out — this codebase runs one web
      server process per machine (see ``session/active.py``'s own
      docstring), so most reaching claims here are this process's own
      earlier, crashed instance (the crash-then-restart cell). **C3
      (council):** since R-01b started recording ``pid`` on every web
      claim, a SECOND, still-alive web server process — a different port,
      or a restart racing the old one before it exits — is now cheap to
      detect: blocks iff ``pid`` is recorded, alive
      (:func:`_pid_is_alive`), AND not this process's own pid. No ``pid``
      recorded, or the recorded pid IS this process, still never blocks
      (unchanged) — the former is a pre-R-01b claim shape, the latter is
      this process's own stale claim, which is exactly the
      crash-then-restart case, not a foreign live server.
    """
    if not _claim_exists(state):
        return False
    if state.get("transport") in ("pty", "acp"):
        pid = state.get("pid")
        if pid is None or pid == os.getpid():
            return False
        return _pid_is_alive(pid)
    return _cli_owned_claim_is_live(state)


def claim_blocks_cli_start(state: dict) -> bool:
    """Whether a file claim should block a new CLI (``studyloop study``) start.

    The CLI's own start path (R-01b) has no in-process singleton to rule a
    web-owned claim out with, unlike :func:`claim_blocks_web_start` — so it
    checks both owner shapes for real:

    - No claim at all never blocks.
    - A CLI-owned claim blocks iff its recorded multiplexer session still
      exists (:func:`_cli_owned_claim_is_live`, shared with
      ``claim_blocks_web_start``).
    - A web-owned claim (``transport`` in ``{"pty", "acp"}``), read
      cross-process from the CLI: live iff its recorded ``pid`` (the web
      server process that holds the claim) is still alive
      (:func:`_pid_is_alive`). **No ``pid`` recorded blocks
      conservatively** — a claim written by a build before this field
      existed can't be verified either way, and the existing "already
      active" message already tells the user how to end it explicitly,
      which is safer than silently reclaiming a claim this process cannot
      confirm is actually dead.

    Residual risk, accepted: pid reuse. If the web server process dies and
    the OS recycles its pid for an unrelated process before this check
    runs, that unrelated process reads as "alive" and the claim still
    blocks — a false block, not a false reclaim, so the failure mode is
    "tell the user to run `--end`", not "clobber a live session's state".
    """
    if not _claim_exists(state):
        return False
    if state.get("transport") not in ("pty", "acp"):
        return _cli_owned_claim_is_live(state)
    pid = state.get("pid")
    if pid is None:
        return True
    return _pid_is_alive(pid)
