"""Session dashboard HTTP routes (state, SSE, settings, end)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import Request  # noqa: TC002 - FastAPI needs Request at runtime for injection.
from fastapi.responses import JSONResponse, StreamingResponse

from studyloop.session_state import PARKING_FILE, STATE_FILE, TOPICS_FILE
from studyloop.web.routes.session._ipc import _get_full_state
from studyloop.web.routes.session._render import _render_update
from studyloop.web.routes.session._router import router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


@router.get("/session/state")
async def get_session_state() -> dict:
    """JSON endpoint for initial session state load.

    The live in-process slot (``session/active.py``) is the source of truth for
    "is a session running?". When a slot is held, overlay it on the IPC file so
    this endpoint can never disagree with ``POST /session/start``: report the
    slot even when the file is gone or an out-of-process end left
    ``mode=ended``, and surface the same ``detached`` / ``reattach_url``
    affordance the 409 carries. When no slot is held, fall back to the file
    verbatim so legacy ttyd sessions (which never touch the slot) still show.
    """
    from studyloop.session import active as session_active
    from studyloop.web.routes.session import _grace

    state = _get_full_state()
    current = await session_active.current()
    if current is None:
        # Nothing is held: surface WHY the previous session ended. _grace has
        # recorded this all along and its docstring says this endpoint reads it,
        # but the wiring was never added — so a learner whose session vanished on
        # grace expiry got an empty dashboard and no explanation, which is the
        # exact guessing the record exists to prevent.
        release = _grace.last_release()
        if release is not None:
            state["last_release"] = release
        return state

    session_id = current.study_session_id
    if state.get("study_session_id") != session_id:
        # File is gone, empty, or describes a stale/other session — don't let
        # its fields masquerade as this slot's. Keep only the list panels.
        state = {
            "topics": state.get("topics", []),
            "parking": state.get("parking", []),
            "study_session_id": session_id,
            "agent": current.config.agent,
            "mode": "focus",
        }
    else:
        state = dict(state)
        if not state.get("agent"):
            state["agent"] = current.config.agent
        if state.get("mode") == "ended":
            # An out-of-process end marked the file ended, but the slot is live.
            state["mode"] = "focus"
    state["detached"] = _grace.has_pending_release(session_id)
    state["reattach_url"] = f"/api/session/ws?study_session_id={session_id}"
    return state


@router.get("/session/last")
def get_last_session() -> dict:
    """Most recent study session (topic/energy/times), or {} when none.

    Powers the Today panel's "Resume: <topic>" shortcut when no session is
    currently live — start-again-same-topic, not tmux reattach.

    This is a convenience lookup hit on every page load, so a DB problem must
    degrade to "no previous session" rather than surfacing a 500 as a console
    error and an error toast. Catch narrowly — a locked/drifted SQLite DB
    (``sqlite3.Error``) or a missing agent-session-tools install
    (``ImportError``) — and let any other exception propagate so real bugs
    stay visible.
    """
    import sqlite3

    try:
        from studyloop.history.sessions import get_last_study_session

        return get_last_study_session() or {}
    except (sqlite3.Error, ImportError):
        logger.warning("session/last lookup failed; degrading to no-session", exc_info=True)
        return {}


@router.get("/session/stream")
async def session_stream(request: Request) -> StreamingResponse:
    """SSE endpoint for live session updates.

    Polls IPC files every 2 seconds and pushes HTML fragments
    when changes are detected. HTMX SSE extension swaps the
    primary target; OOB attributes update counters and metadata.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        last_mtimes: tuple[float, float, float] = (0.0, 0.0, 0.0)
        while True:
            if await request.is_disconnected():
                break
            # O(1) change detection: 3 stat() calls instead of full JSON serialisation
            mtimes = tuple(
                f.stat().st_mtime if f.exists() else 0.0
                for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE)
            )
            if mtimes != last_mtimes:
                state = _get_full_state()
                html = _render_update(state)
                # SSE format: event name + data (newlines in data escaped)
                escaped = html.replace("\n", "")
                yield f"event: session-update\ndata: {escaped}\n\n"
                last_mtimes = mtimes  # type: ignore[assignment]
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Topics list (for topic picker UI)
# ---------------------------------------------------------------------------


@router.get("/session/topics")
def get_topics() -> list[dict]:
    """Return configured topics for the start-session picker."""
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        return [{"name": t.name, "slug": t.slug, "tags": t.tags} for t in settings.topics]
    except Exception:
        return []


@router.get("/settings/pomodoro")
def get_pomodoro_settings() -> dict:
    """Return pomodoro timer defaults from config.

    The web UI uses these as defaults, overridden by localStorage.
    """
    try:
        from studyloop.settings import load_settings

        pomo = load_settings().pomodoro
        return {
            "focus": pomo.focus,
            "short_break": pomo.short_break,
            "long_break": pomo.long_break,
            "cycles": pomo.cycles,
        }
    except Exception:
        return {"focus": 25, "short_break": 5, "long_break": 15, "cycles": 4}


@router.post("/session/end")
async def end_session() -> JSONResponse:
    """End the current study session from the web UI.

    Declared async so the PTY path can ``await active.release()`` to
    tear down the active-session singleton + transport. Without this,
    a follow-up ``/session/start`` would 409 even though the tmux/DB
    side is cleaned up.
    """
    from studyloop.session import active as session_active
    from studyloop.web.routes import session as session_pkg
    from studyloop.web.routes.session import _grace

    state = session_pkg.read_session_state()

    # Cancel any grace timer FIRST, before releasing the singleton. A socket
    # that disconnected moments ago has scheduled a release for this session;
    # ending the session now must not leave that timer armed, or it fires later
    # against a slot that has already moved on. _grace.release_now is the
    # documented path for "end arrived during the grace window" and leaves no
    # orphan timer behind.
    session_id = state.get("study_session_id")
    if session_id:
        await _grace.release_now(str(session_id), reason="ended-by-user")

    # Release the PTY singleton first — idempotent, safe when the session
    # was a legacy ttyd flow that never touched active.py.
    await session_active.release()

    if not state.get("study_session_id"):
        return JSONResponse(
            {"error": "No active session"},
            status_code=404,
        )

    from studyloop.session.cleanup import end_session_common

    topic = end_session_common(state)

    return JSONResponse(
        {"ended": True, "topic": topic or "Unknown"},
        status_code=200,
    )
