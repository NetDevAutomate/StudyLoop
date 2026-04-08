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


def _persist_session_data(
    study_id: str,
    state: dict,
    topic_entries: list,
    notes: str,
    *,
    auto_persist: bool,
) -> None:
    """Persist session data: backlog, flashcards, and DB record.

    All three operations are individually guarded so a failure in one does
    not prevent the others from running.
    """
    from studyctl.history import end_study_session

    # Auto-persist struggled topics to backlog.
    # Log on failure — silent suppression here means struggled topics are lost.
    if auto_persist:
        try:
            from studyctl.services.backlog import auto_persist_struggled

            auto_persist_struggled(study_id, topic_entries)
        except Exception:
            logger.exception("Failed to auto-persist struggled topics")

    # Generate flashcards from session wins/insights
    try:
        topic_slug = state.get("topic_slug")
        if topic_slug and topic_entries:
            from studyctl.services.flashcard_writer import write_session_flashcards
            from studyctl.settings import load_settings

            settings = load_settings()
            count = write_session_flashcards(
                settings.content.base_path,
                topic_slug,
                study_id,
                topic_entries,
            )
            if count:
                logger.info("Generated %d flashcards from session wins", count)
    except Exception:
        logger.warning("Failed to generate session flashcards", exc_info=True)

    # End the DB session with captured notes and structured counts
    win_count = sum(1 for t in topic_entries if t.status in ("win", "insight"))
    struggle_count = sum(1 for t in topic_entries if t.status == "struggling")
    try:
        end_study_session(study_id, notes=notes, win_count=win_count, struggle_count=struggle_count)
    except Exception:
        logger.exception("Failed to end study session in DB")


def _signal_dashboard_ended() -> None:
    """Write mode=ended to session state so the dashboard shows a summary."""
    import contextlib

    from studyctl.session_state import write_session_state

    with contextlib.suppress(Exception):
        write_session_state({"mode": "ended"})


def _teardown_agent(state: dict) -> None:
    """Run agent-specific teardown (e.g. Kiro restores backed-up JSON)."""
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


def _kill_background_processes(state: dict) -> None:
    """Kill web dashboard and ttyd processes by PID, then by port as fallback.

    PID-based kill is tried first (fast). Port-based kill handles orphaned
    processes whose PIDs were lost between code paths.
    """
    import contextlib
    import os
    import subprocess as _sp

    # PID-based kill — verify command matches to guard against PID recycling.
    # "studyctl" matches both the binary and "python -m studyctl.cli".
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

    # Port-based fallback
    from studyctl.session.orchestrator import _kill_port_occupant

    ttyd_port = state.get("ttyd_port")
    if ttyd_port:
        with contextlib.suppress(Exception):
            _kill_port_occupant(int(ttyd_port), expected_cmd="ttyd")
    web_port = state.get("web_port")
    if web_port:
        with contextlib.suppress(Exception):
            _kill_port_occupant(int(web_port), expected_cmd="studyctl")


def _cleanup_tmux_and_files(session_name: str | None, persona_file: str | None) -> None:
    """Kill tmux study sessions and remove transient IPC files.

    Keeps session-state.json (mode=ended) so the dashboard can render a
    summary view before the next session starts.
    """
    import contextlib
    import os

    from studyctl.session_state import PARKING_FILE, SESSION_DIR, TOPICS_FILE
    from studyctl.tmux import kill_all_study_sessions

    # Remove persona temp file
    if persona_file:
        with contextlib.suppress(OSError):
            os.unlink(persona_file)

    oneline = SESSION_DIR / "session-oneline.txt"
    with contextlib.suppress(OSError):
        oneline.unlink()

    # Kill all study tmux sessions
    with contextlib.suppress(Exception):
        kill_all_study_sessions(current_session=session_name)

    # Clear transient IPC files but KEEP session-state.json (mode=ended)
    for f in [TOPICS_FILE, PARKING_FILE, oneline]:
        with contextlib.suppress(OSError):
            f.unlink()


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
    from studyctl.session_state import parse_parking_file, parse_topics_file

    study_id = state.get("study_session_id")
    topic = state.get("topic", "unknown")

    if not study_id:
        return None

    # Capture session context as notes
    topic_entries = parse_topics_file()
    notes = build_session_notes(topic_entries, parse_parking_file())

    _persist_session_data(study_id, state, topic_entries, notes, auto_persist=auto_persist)
    _signal_dashboard_ended()
    _teardown_agent(state)
    _kill_background_processes(state)
    _cleanup_tmux_and_files(
        session_name=state.get("tmux_session"),
        persona_file=state.get("persona_file"),
    )

    return topic


def auto_clean_zombies() -> None:
    """Silently kill zombie study sessions before starting a new one.

    Handles tmux-resurrect restoring previously killed sessions.
    Uses the FCIS clean logic -- gather data, decide, execute.
    Runs quietly: no output unless something goes wrong.
    """
    import contextlib
    import shutil

    from studyctl.logic.clean_logic import DirInfo, plan_clean
    from studyctl.output import console
    from studyctl.session_state import SESSION_DIR, STATE_FILE, read_session_state
    from studyctl.tmux import (
        is_tmux_server_running,
        is_zombie_session,
        kill_session,
        list_study_sessions,
    )

    with contextlib.suppress(Exception):
        tmux_running = is_tmux_server_running()
        if not tmux_running:
            return

        study_sessions = list_study_sessions()
        zombie_sessions = [s for s in study_sessions if is_zombie_session(s)]

        sessions_dir = SESSION_DIR / "sessions"
        session_dirs = (
            [
                DirInfo(name=d.name, path=d, is_symlink=d.is_symlink())
                for d in sorted(sessions_dir.iterdir())
                if d.is_dir() or d.is_symlink()
            ]
            if sessions_dir.exists()
            else []
        )

        plan = plan_clean(
            tmux_running=True,
            zombie_sessions=zombie_sessions,
            session_dirs=session_dirs,
            live_tmux_names=set(study_sessions),
            state=read_session_state(),
            state_file_exists=STATE_FILE.exists(),
        )

        if not plan.has_work:
            return

        for name in plan.sessions_to_kill:
            kill_session(name)
        for path in plan.dirs_to_remove:
            shutil.rmtree(path, ignore_errors=True)
        if plan.state_to_clean:
            STATE_FILE.unlink(missing_ok=True)

        if plan.sessions_to_kill:
            console.print(
                f"[dim]Cleaned {len(plan.sessions_to_kill)} "
                f"stale session{'s' if len(plan.sessions_to_kill) != 1 else ''} "
                f"(tmux-resurrect)[/dim]"
            )


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
