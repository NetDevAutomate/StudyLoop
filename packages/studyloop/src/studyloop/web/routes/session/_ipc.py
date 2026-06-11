"""Session IPC file reads and zombie tmux detection."""

from __future__ import annotations

import logging

from studyloop.session_state import PARKING_FILE, STATE_FILE, TOPICS_FILE

logger = logging.getLogger(__name__)


def _is_tmux_session_alive(session_name: str) -> bool:
    """Check if a tmux session exists. Returns False if tmux isn't running."""
    import subprocess

    if not session_name:
        return False
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _kill_stale_ttyd(state: dict) -> None:
    """Kill a stale ttyd process if the tmux session it attaches to is gone."""
    import os
    import subprocess as _sp

    ttyd_pid = state.get("ttyd_pid")
    if not ttyd_pid:
        return
    try:
        result = _sp.run(
            ["ps", "-p", str(ttyd_pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "ttyd" in result.stdout:
            os.kill(ttyd_pid, 15)  # SIGTERM
    except (OSError, _sp.TimeoutExpired):
        pass


def _get_full_state() -> dict:
    """Read all IPC files into a single state dict.

    If the state file claims a session is active but the tmux session
    is gone (zombie), kills stale ttyd, clears state, and returns empty.
    """
    # Resolve via the package so tests can patch ``studyloop.web.routes.session.*``.
    from studyloop.web.routes import session as session_pkg

    state = session_pkg.read_session_state()

    # Zombie detection: state says active but tmux session is dead
    tmux_session = state.get("tmux_session")
    if tmux_session and state.get("mode") != "ended" and not _is_tmux_session_alive(tmux_session):
        # Kill orphaned ttyd before clearing state
        _kill_stale_ttyd(state)
        # Clear stale IPC files
        for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE):
            if f.exists():
                f.unlink(missing_ok=True)
        return {"topics": [], "parking": []}

    topics = session_pkg.parse_topics_file()
    parking = session_pkg.parse_parking_file()
    return {
        **state,
        "topics": [
            {"time": t.time, "topic": t.topic, "status": t.status, "note": t.note} for t in topics
        ],
        "parking": [{"question": p.question} for p in parking],
    }
