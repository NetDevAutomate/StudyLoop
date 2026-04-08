"""Session API routes — live study session dashboard."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from studyctl.session_state import (
    PARKING_FILE,
    SESSION_DIR,
    STATE_FILE,
    TOPICS_FILE,
    _ensure_session_dir,
    is_session_active,
    parse_parking_file,
    parse_topics_file,
    read_session_state,
    write_session_state,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

router = APIRouter()

# Shape → symbol mapping (matches session-protocol.md visual language)
STATUS_SHAPES: dict[str, tuple[str, str]] = {
    "win": ("\u2713", "status-win"),  # ✓
    "insight": ("\u2605", "status-insight"),  # ★
    "learning": ("\u25c6", "status-learning"),  # ◆
    "struggling": ("\u25b2", "status-struggling"),  # ▲
    "parked": ("\u25cb", "status-parked"),  # ○
}


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
    state = read_session_state()

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

    topics = parse_topics_file()
    parking = parse_parking_file()
    return {
        **state,
        "topics": [
            {"time": t.time, "topic": t.topic, "status": t.status, "note": t.note} for t in topics
        ],
        "parking": [{"question": p.question} for p in parking],
    }


def _render_activity_feed(state: dict) -> str:
    """Render the activity feed HTML fragment (inner content only).

    The SSE swap target already has id="activity-feed", so this returns
    only the *content* to be placed inside that element — not a wrapper div.
    Including a wrapper with the same id would create a duplicate ID when
    HTMX replaces innerHTML of the target.
    """
    topics = state.get("topics", [])
    parking = state.get("parking", [])

    if not topics and not parking:
        return '<p class="activity-empty">Waiting for session activity...</p>'

    items: list[str] = []
    for t in topics:
        status = t.get("status", "learning")
        shape, css_class = STATUS_SHAPES.get(status, ("\u25c6", "status-learning"))
        time_str = escape(t.get("time", ""))
        topic = escape(t.get("topic", ""))
        note = escape(t.get("note", ""))
        display = f"{topic} &mdash; {note}" if note else topic
        items.append(
            f'<div class="activity-item {css_class}">'
            f'<span class="activity-shape">{shape}</span>'
            f'<span class="activity-time">[{time_str}]</span>'
            f'<span class="activity-text">{display}</span>'
            f"</div>"
        )

    for p in parking:
        shape, css_class = STATUS_SHAPES["parked"]
        question = escape(p.get("question", ""))
        items.append(
            f'<div class="activity-item {css_class}">'
            f'<span class="activity-shape">{shape}</span>'
            f'<span class="activity-text">Parked: {question}</span>'
            f"</div>"
        )

    return "\n".join(items)


def _render_counters(state: dict) -> str:
    """Render OOB counter bar fragments."""
    topics = state.get("topics", [])
    wins = sum(1 for t in topics if t.get("status") in ("win", "insight"))
    review = sum(1 for t in topics if t.get("status") == "struggling")
    parked = len(state.get("parking", []))

    return (
        f'<span id="counter-wins" hx-swap-oob="true">'
        f"\u2713 WINS: {wins}</span>"
        f'<span id="counter-parked" hx-swap-oob="true">'
        f"\u25cb PARKED: {parked}</span>"
        f'<span id="counter-review" hx-swap-oob="true">'
        f"\u25b2 REVIEW: {review}</span>"
    )


def _render_session_meta(state: dict) -> str:
    """Render OOB session metadata (energy, topic)."""
    topic = escape(state.get("topic", "No active session"))
    energy = state.get("energy", 5)
    mode = state.get("mode", "")

    if mode == "ended":
        return (
            f'<div id="session-meta" hx-swap-oob="true">'
            f'<span class="meta-topic">{topic}</span>'
            f'<span class="meta-status">Session complete</span>'
            f"</div>"
        )

    return (
        f'<div id="session-meta" hx-swap-oob="true">'
        f'<span class="meta-topic">{topic}</span>'
        f'<span class="meta-energy">'
        f"\u26a1 Energy: {energy}/10</span>"
        f"</div>"
    )


def _render_summary(state: dict) -> str:
    """Render the session-complete summary view."""
    topics = state.get("topics", [])
    parking = state.get("parking", [])
    topic = escape(state.get("topic", "Study Session"))

    wins = [t for t in topics if t.get("status") in ("win", "insight")]
    struggles = [t for t in topics if t.get("status") == "struggling"]

    wins_html = ""
    if wins:
        win_items = "".join(
            f'<li class="status-win">\u2713 {escape(w.get("topic", ""))}'
            f"{' &mdash; ' + escape(w.get('note', '')) if w.get('note') else ''}"
            f"</li>"
            for w in wins
        )
        wins_html = f"<h3>\u2713 Wins</h3><ul>{win_items}</ul>"

    struggles_html = ""
    if struggles:
        struggle_items = "".join(
            f'<li class="status-struggling">\u25b2 {escape(s.get("topic", ""))}</li>'
            for s in struggles
        )
        struggles_html = f"<h3>\u25b2 For Next Session</h3><ul>{struggle_items}</ul>"

    parked_html = ""
    if parking:
        parked_items = "".join(
            f'<li class="status-parked">\u25cb {escape(p.get("question", ""))}</li>'
            for p in parking
        )
        parked_html = f"<h3>\u25cb Parked Topics</h3><ul>{parked_items}</ul>"

    return (
        f'<div class="session-summary">'
        f'<div class="summary-header">'
        f"<h2>Session Complete: {topic}</h2>"
        f"</div>"
        f"{wins_html}{struggles_html}{parked_html}"
        f'<p class="summary-cta">'
        f"Stand up. Walk to the kitchen. Your brain needs a break.</p>"
        f"</div>"
    )


def _render_update(state: dict) -> str:
    """Render a full SSE update payload (activity + OOB counters + meta)."""
    if state.get("mode") == "ended":
        return _render_summary(state) + _render_counters(state)
    return _render_activity_feed(state) + _render_counters(state) + _render_session_meta(state)


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
        from studyctl.settings import load_settings

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
        from studyctl.settings import load_settings

        pomo = load_settings().pomodoro
        return {
            "focus": pomo.focus,
            "short_break": pomo.short_break,
            "long_break": pomo.long_break,
            "cycles": pomo.cycles,
        }
    except Exception:
        return {"focus": 25, "short_break": 5, "long_break": 15, "cycles": 4}


# ---------------------------------------------------------------------------
# Start / End session from web UI
# ---------------------------------------------------------------------------


class StartSessionRequest(BaseModel):
    """Request body for POST /api/session/start."""

    topic: str
    energy: int = Field(default=5, ge=1, le=10)
    agent: str | None = None


@router.post("/session/start")
def start_session(body: StartSessionRequest) -> JSONResponse:
    """Start a new study session from the web UI.

    Creates the DB record, tmux environment, and ttyd process.
    The session runs headless — the user interacts via the browser
    (SSE activity feed + ttyd terminal iframe).
    """
    import os
    import shutil
    from pathlib import Path

    from studyctl.tmux import is_tmux_available, kill_session, session_exists

    # --- Pre-flight ---

    if not is_tmux_available():
        return JSONResponse(
            {"error": "tmux 3.1+ is required but not found"},
            status_code=503,
        )

    if is_session_active():
        return JSONResponse(
            {"error": "A session is already active"},
            status_code=409,
        )

    # --- Resolve agent ---

    from studyctl.agent_launcher import AGENTS, detect_agents

    agent = body.agent
    if agent and agent not in AGENTS:
        return JSONResponse(
            {"error": f"Unknown agent: {agent}"},
            status_code=400,
        )
    if not agent:
        available = detect_agents()
        if not available:
            return JSONResponse(
                {"error": "No AI agent found on this machine"},
                status_code=503,
            )
        agent = available[0]

    # Check agent binary is installed
    adapter = AGENTS[agent]
    if not shutil.which(adapter.binary):
        return JSONResponse(
            {"error": f"Agent '{agent}' binary not found: {adapter.binary}"},
            status_code=503,
        )

    # --- Resolve topic config ---

    topic_config = None
    try:
        from studyctl.logic.topic_resolver import resolve_topic
        from studyctl.settings import load_settings

        settings = load_settings()
        if settings.topics:
            result = resolve_topic(body.topic, settings.topics)
            topic_config = result.resolved or (result.matches[0] if result.matches else None)
    except Exception:
        pass  # Topic resolution is optional

    # --- Clean zombies ---

    try:
        from studyctl.session.cleanup import auto_clean_zombies

        auto_clean_zombies()
    except Exception:
        pass

    # --- Create DB session ---

    from studyctl.history import start_study_session
    from studyctl.output import energy_to_label

    energy_label = energy_to_label(body.energy)
    study_id = start_study_session(
        body.topic,
        energy_label,
        topic_slug=topic_config.slug if topic_config else None,
    )
    if not study_id:
        return JSONResponse(
            {"error": "Failed to create session record"},
            status_code=500,
        )

    # --- Write session state ---

    _ensure_session_dir()
    now = datetime.now(UTC).isoformat()
    write_session_state(
        {
            "study_session_id": study_id,
            "topic": body.topic,
            "energy": body.energy,
            "energy_label": energy_label,
            "mode": "focus",
            "timer_mode": "energy",
            "started_at": now,
            "start_time": now,
            "paused_at": None,
            "total_paused_seconds": 0,
        }
    )
    TOPICS_FILE.touch(mode=0o600, exist_ok=True)
    PARKING_FILE.touch(mode=0o600, exist_ok=True)

    # --- Session directory + tmux ---

    slug = body.topic.lower().replace(" ", "-")[:20]
    short_id = study_id[:8]
    session_name = f"study-{slug}-{short_id}"
    session_dir = SESSION_DIR / "sessions" / session_name

    if session_exists(session_name):
        kill_session(session_name)

    from studyctl.agent_launcher import build_canonical_persona
    from studyctl.session.orchestrator import (
        build_wrapped_agent_cmd,
        create_tmux_environment,
        setup_session_dir,
        start_ttyd_background,
    )

    setup_session_dir(session_dir, body.topic)

    # Build persona
    canonical = build_canonical_persona("focus", body.topic, body.energy)
    persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]

    from studyctl.history.sessions import update_persona_hash

    update_persona_hash(study_id, persona_hash)

    persona_file = adapter.setup(canonical, session_dir)
    if adapter.mcp_setup:
        adapter.mcp_setup(session_dir)

    # Allow test injection
    test_agent_cmd = os.environ.get("STUDYCTL_TEST_AGENT_CMD")
    if test_agent_cmd:
        agent_cmd = test_agent_cmd.format(persona_file=persona_file)
    else:
        # Check if session dir has prior agent history (resuming)
        claude_project_key = str(session_dir).replace("/", "-").lstrip("-")
        claude_project_dir = Path.home() / ".claude" / "projects" / claude_project_key
        is_resuming = claude_project_dir.exists()
        agent_cmd = adapter.launch_cmd(persona_file, is_resuming)

    wrapped_cmd = build_wrapped_agent_cmd(session_dir, agent_cmd)

    result = create_tmux_environment(
        session_name=session_name,
        session_dir=session_dir,
        wrapped_agent_cmd=wrapped_cmd,
        session_state_dir=SESSION_DIR,
    )

    # Persist tmux metadata
    state_update: dict = {
        "tmux_session": session_name,
        "tmux_main_pane": result["tmux_main_pane"],
        "tmux_sidebar_pane": result["tmux_sidebar_pane"],
        "persona_file": str(persona_file),
        "session_dir": str(session_dir),
        "agent": agent,
        "persona_hash": persona_hash,
    }
    if topic_config:
        state_update["topic_slug"] = topic_config.slug
        state_update["topic_config_name"] = topic_config.name
    write_session_state(state_update)

    # Start ttyd for terminal access (with auth from config if available)
    ttyd_username = ""
    ttyd_password = ""
    try:
        from studyctl.settings import load_settings as _ls_ttyd

        _ttyd_settings = _ls_ttyd()
        ttyd_username = _ttyd_settings.lan_username or ""
        ttyd_password = _ttyd_settings.lan_password or ""
    except Exception:
        pass
    start_ttyd_background(session_name, username=ttyd_username, password=ttyd_password)

    return JSONResponse(
        {
            "study_session_id": study_id,
            "topic": body.topic,
            "energy": body.energy,
            "session_name": session_name,
            "agent": agent,
        },
        status_code=201,
    )


@router.post("/session/end")
def end_session() -> JSONResponse:
    """End the current study session from the web UI."""
    state = read_session_state()

    if not state.get("study_session_id"):
        return JSONResponse(
            {"error": "No active session"},
            status_code=404,
        )

    from studyctl.session.cleanup import end_session_common

    topic = end_session_common(state)

    return JSONResponse(
        {"ended": True, "topic": topic or "Unknown"},
        status_code=200,
    )
