"""Session IPC file reads and zombie tmux detection."""

from __future__ import annotations

import logging

from studyloop.session_state import PARKING_FILE, STATE_FILE, TOPICS_FILE

logger = logging.getLogger(__name__)


def _is_tmux_session_alive(session_name: str) -> bool:
    """Check if a multiplexer session exists. Returns False if not running."""
    if not session_name:
        return False
    from studyloop.multiplexer import get_backend

    mux = get_backend()
    return mux.session_exists(session_name)


def _get_full_state() -> dict:
    """Read all IPC files into a single state dict.

    If the state file claims a session is active but the tmux session
    is gone (zombie), clears state and returns empty. Used to also kill a
    stale ttyd process here first; ttyd is no longer spawned (ttyd
    retirement stage 2), so there is nothing left to kill — a leftover
    ``ttyd_pid`` key in an old state file (from before the retirement) is
    just inert data that gets cleared along with everything else.
    """
    # Resolve via the package so tests can patch ``studyloop.web.routes.session.*``.
    from studyloop.web.routes import session as session_pkg

    state = session_pkg.read_session_state()

    # Zombie detection: state says active but multiplexer session is dead
    mux_session = state.get("mux_session") or state.get("tmux_session")
    if mux_session and state.get("mode") != "ended" and not _is_tmux_session_alive(mux_session):
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
