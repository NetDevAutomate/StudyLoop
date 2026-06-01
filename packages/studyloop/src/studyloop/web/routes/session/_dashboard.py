"""Session dashboard HTTP routes (state, SSE, settings, end)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse, StreamingResponse

from studyloop.session_state import PARKING_FILE, STATE_FILE, TOPICS_FILE
from studyloop.web.routes.session._ipc import _get_full_state
from studyloop.web.routes.session._render import _render_update
from studyloop.web.routes.session._router import router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import Request

logger = logging.getLogger(__name__)


@router.get("/session/state")
def get_session_state() -> dict:
    """JSON endpoint for initial session state load."""
    return _get_full_state()


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

    state = session_pkg.read_session_state()

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
