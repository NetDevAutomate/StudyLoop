"""Session cleanup — end DB record, kill tmux, clear IPC files."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_session_notes(
    topics: list,
    parking: list,
) -> str:
    """Build a summary of the session for the DB notes field.

    This is what ``--resume`` uses to give the agent context about
    where the conversation was when the session ended.
    """
    lines: list[str] = []

    wins = [t for t in topics if t.status in ("win", "insight")]
    struggles = [t for t in topics if t.status == "struggling"]
    learning = [t for t in topics if t.status == "learning"]

    if wins:
        lines.append("Wins: " + ", ".join(t.topic for t in wins))
    if learning:
        lines.append("In progress: " + ", ".join(t.topic for t in learning))
    if struggles:
        lines.append("Struggling: " + ", ".join(t.topic for t in struggles))
    if parking:
        lines.append("Parked: " + ", ".join(p.question for p in parking))

    if not lines:
        lines.append("No topics recorded during session.")

    return "\n".join(lines)


def end_session_common(
    state: dict,
    *,
    auto_persist: bool = True,
) -> str | None:
    """Shared session-ending logic used by both _handle_end and cleanup_on_exit.

    Captures session notes, ends the DB record, cleans up temp files, kills
    tmux sessions, and clears IPC files. Returns the topic name or None.

    The caller controls user-facing output and error handling -- this function
    only does the work.
    """
    import contextlib
    import os

    from studyctl.history import end_study_session
    from studyctl.session_state import (
        PARKING_FILE,
        SESSION_DIR,
        TOPICS_FILE,
        parse_parking_file,
        parse_topics_file,
        write_session_state,
    )
    from studyctl.tmux import kill_all_study_sessions

    study_id = state.get("study_session_id")
    session_name = state.get("tmux_session")
    persona_file = state.get("persona_file")
    topic = state.get("topic", "unknown")

    if not study_id:
        return None

    # Capture session context as notes
    topic_entries = parse_topics_file()
    notes = build_session_notes(topic_entries, parse_parking_file())

    # Auto-persist struggled topics to backlog.
    # Log on failure — silent suppression here means struggled topics are lost.
    if auto_persist:
        try:
            from studyctl.services.backlog import auto_persist_struggled

            auto_persist_struggled(study_id, topic_entries)
        except Exception:
            logger.exception("Failed to auto-persist struggled topics")

    # End the DB session with captured notes
    try:
        end_study_session(study_id, notes=notes)
    except Exception:
        logger.exception("Failed to end study session in DB")

    # Signal dashboard summary view
    with contextlib.suppress(Exception):
        write_session_state({"mode": "ended"})

    # Run agent-specific teardown (e.g. Kiro restores backed-up JSON)
    try:
        from studyctl.agent_launcher import AGENTS

        adapter = AGENTS.get(state.get("agent", ""))
        if adapter and adapter.teardown:
            session_dir_path = state.get("session_dir")
            if session_dir_path:
                from pathlib import Path

                adapter.teardown(Path(session_dir_path))
    except Exception:
        logger.exception("Agent teardown failed")

    # Clean up temp files
    if persona_file:
        with contextlib.suppress(OSError):
            os.unlink(persona_file)
    oneline = SESSION_DIR / "session-oneline.txt"
    with contextlib.suppress(OSError):
        oneline.unlink()

    # Kill background processes (web dashboard, ttyd).
    # Verify PID identity before killing to guard against PID recycling:
    # if the process exited and its PID was reused by an unrelated process,
    # we'd kill the wrong thing.
    import subprocess as _sp

    pid_checks = {"web_pid": "studyctl", "ttyd_pid": "ttyd"}
    for pid_key, expected in pid_checks.items():
        pid = state.get(pid_key)
        if not pid:
            continue
        try:
            result = _sp.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if expected in result.stdout:
                os.kill(pid, 15)  # SIGTERM
        except (OSError, _sp.TimeoutExpired):
            pass

    # Kill all study tmux sessions
    with contextlib.suppress(Exception):
        kill_all_study_sessions(current_session=session_name)

    # Clear transient IPC files but KEEP session-state.json (mode=ended)
    for f in [TOPICS_FILE, PARKING_FILE, oneline]:
        with contextlib.suppress(OSError):
            f.unlink()

    return topic


def cleanup_on_exit() -> None:
    """Auto-cleanup when the agent process exits.

    Called by the wrapper shell command in the main tmux pane. This runs
    inside the tmux session, so tmux will SIGHUP us when sessions are
    killed -- all operations are wrapped in contextlib.suppress via
    end_session_common().
    """
    import contextlib

    from studyctl.session_state import read_session_state

    with contextlib.suppress(Exception):
        state = read_session_state()
        end_session_common(state)
