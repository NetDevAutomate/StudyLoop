"""Session API routes — live study session dashboard."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from studyloop.session_state import (
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


# ---------------------------------------------------------------------------
# Start / End session from web UI
# ---------------------------------------------------------------------------


class StartSessionRequest(BaseModel):
    """Request body for POST /api/session/start."""

    topic: str
    energy: int = Field(default=5, ge=1, le=10)
    agent: str | None = None
    transport: str | None = Field(
        default=None,
        description=(
            "Session transport: 'pty' (default, new path) or 'ttyd' (legacy). "
            "STUDYLOOP_TRANSPORT env var takes precedence over this field — "
            "operators can force the legacy path without touching clients."
        ),
    )


_AGENT_INSTALL_HINTS: dict[str, str] = {
    "claude": "Install the Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code",
    "codex": "Install codex: npm i -g @openai/codex (or see https://github.com/openai/codex).",
    "gemini": ("Install the Gemini CLI: https://github.com/google-gemini/gemini-cli#installation"),
    "kiro": "Install Kiro CLI: https://kiro.dev/docs/cli",
    "opencode": "Install OpenCode: https://opencode.ai/docs/install",
}


def _resolve_transport(body_transport: str | None) -> str:
    """Decide between 'pty' and 'ttyd'. Env var wins for operator kill-switch."""
    import os

    env_override = os.environ.get("STUDYLOOP_TRANSPORT", "").strip().lower()
    if env_override in {"pty", "ttyd"}:
        return env_override
    if body_transport in {"pty", "ttyd"}:
        return body_transport
    return "pty"


def _build_pty_transport(config):  # type: ignore[no-untyped-def]
    """Return a zero-arg factory that constructs a ``PTYTransport`` for ``config``.

    Split out from ``_start_pty_session`` so tests can monkeypatch the
    whole factory without spawning a real PTY child. The production
    factory wraps the adapter's shell-string ``launch_cmd`` in
    ``/bin/sh -c``, since ``os.execvpe`` needs argv and our adapters
    return shell strings (with pipes, ``&&``, etc).
    """
    import shutil as _shutil
    from pathlib import Path

    from studyloop.agent_launcher import AGENTS
    from studyloop.session.transports.pty import PTYTransport

    adapter = AGENTS[config.agent]

    def _resolve_binary(_agent_name: str) -> str | None:
        # PTYTransport uses this to set the child's argv[0]. We pass argv
        # directly via build_launch_cmd, so the resolved binary is just
        # the shell — it does NOT need to match the agent binary.
        return _shutil.which("sh") or "/bin/sh"

    def _build_launch_cmd(_config) -> list[str]:  # type: ignore[no-untyped-def]
        # Test hatch: STUDYLOOP_TEST_AGENT_CMD lets CI / Playwright force a
        # known-good shell command (e.g. `/bin/sh -c 'echo ready; cat'`)
        # without needing the real agent binary installed. The hatch is
        # stripped from the child env by _build_child_env() so the child
        # cannot observe its own override key.
        import os as _os

        test_cmd = _os.environ.get("STUDYLOOP_TEST_AGENT_CMD")
        if test_cmd:
            shell_cmd = test_cmd.format(persona_file=_config.persona_file)
        else:
            claude_project_key = str(_config.cwd).replace("/", "-").lstrip("-")
            is_resuming = (Path.home() / ".claude" / "projects" / claude_project_key).exists()
            shell_cmd = adapter.launch_cmd(Path(_config.persona_file), is_resuming)
        return ["/bin/sh", "-c", shell_cmd]

    return lambda: PTYTransport(
        resolve_binary=_resolve_binary,
        build_launch_cmd=_build_launch_cmd,
    )


class SessionOption(BaseModel):
    """Selectable study target for the web start picker."""

    label: str
    value: str
    kind: str
    path: str | None = None
    parent: str | None = None


@router.post("/session/start")
def start_session(body: StartSessionRequest) -> JSONResponse:
    """Start a new study session from the web UI.

    Two transports are supported:

    - ``pty`` (default, plan §1.5b) — spawns the agent directly via
      ``PTYTransport`` + ``active.acquire`` and returns a ``ws_url``
      that the browser feeds to ``/api/session/ws``. No tmux, no ttyd.
    - ``ttyd`` (legacy, plan §1.9 fallback) — runs the original
      tmux+ttyd flow for one deprecation window. Enable explicitly via
      ``{"transport": "ttyd"}`` in the body or by exporting
      ``STUDYLOOP_TRANSPORT=ttyd``.
    """
    transport = _resolve_transport(body.transport)
    if transport == "pty":
        return _start_pty_session(body)
    return _start_ttyd_session(body)


def _start_pty_session(body: StartSessionRequest) -> JSONResponse:
    """PTY-backed start path — no tmux, no ttyd.

    1. Reject if a session is already active (``active.current()``).
    2. Resolve agent + check binary. 503 with ``install_hint`` on miss.
    3. Persona + DB + session_state writes (shared with legacy).
    4. ``active.acquire(config, factory)`` — atomic under asyncio.Lock.
    5. Return 201 with ``ws_url`` for the client to open.
    """
    import asyncio as _asyncio
    import os
    import shutil

    from studyloop.agent_launcher import AGENTS, detect_agents
    from studyloop.session import active as session_active
    from studyloop.session.transport import SessionAlreadyActiveError, SessionConfig

    # --- Agent resolution ---
    agent = body.agent
    if agent and agent not in AGENTS:
        return JSONResponse({"error": f"Unknown agent: {agent}"}, status_code=400)
    if not agent:
        available = detect_agents()
        if not available:
            return JSONResponse(
                {"error": "No AI agent found on this machine"},
                status_code=503,
            )
        agent = available[0]

    adapter = AGENTS[agent]
    if not shutil.which(adapter.binary):
        return JSONResponse(
            {
                "error": f"Agent '{agent}' binary not found: {adapter.binary}",
                "agent": agent,
                "binary": adapter.binary,
                "install_hint": _AGENT_INSTALL_HINTS.get(
                    agent,
                    f"Install the {agent!r} CLI and ensure {adapter.binary!r} is on PATH.",
                ),
            },
            status_code=503,
        )

    # --- Topic resolution (optional) ---
    topic_config = None
    try:
        from studyloop.logic.topic_resolver import resolve_topic
        from studyloop.settings import load_settings

        settings = load_settings()
        if settings.topics:
            result = resolve_topic(body.topic, settings.topics)
            topic_config = result.resolved or (result.matches[0] if result.matches else None)
    except Exception:
        pass

    # --- DB record ---
    from studyloop.history import start_study_session
    from studyloop.output import energy_to_label

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

    # --- Session dir + persona (no tmux) ---
    slug = body.topic.lower().replace(" ", "-")[:20]
    short_id = study_id[:8]
    session_dir = SESSION_DIR / "sessions" / f"pty-{slug}-{short_id}"

    from studyloop.agent_launcher import build_canonical_persona
    from studyloop.session.orchestrator import setup_session_dir

    setup_session_dir(session_dir, body.topic)
    canonical = build_canonical_persona("focus", body.topic, body.energy)
    persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]

    from studyloop.history.sessions import update_persona_hash

    update_persona_hash(study_id, persona_hash)

    persona_file = adapter.setup(canonical, session_dir)
    if adapter.mcp_setup:
        adapter.mcp_setup(session_dir)

    # --- Session state (no tmux metadata) ---
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
            "persona_file": str(persona_file),
            "session_dir": str(session_dir),
            "agent": agent,
            "persona_hash": persona_hash,
            "transport": "pty",
        }
    )
    TOPICS_FILE.touch(mode=0o600, exist_ok=True)
    PARKING_FILE.touch(mode=0o600, exist_ok=True)

    # --- Acquire the active-session singleton ---
    config = SessionConfig(
        study_session_id=study_id,
        agent=agent,
        persona_file=str(persona_file),
        cwd=str(session_dir),
        env=dict(os.environ),
        cols=80,
        rows=24,
    )
    factory = _build_pty_transport(config)

    try:
        _asyncio.run(session_active.acquire(config, factory))
    except SessionAlreadyActiveError:
        return JSONResponse(
            {"error": "A session is already active"},
            status_code=409,
        )
    except FileNotFoundError as exc:
        logger.exception("PTY start failed: binary missing")
        return JSONResponse(
            {"error": f"Agent binary not found: {exc}"},
            status_code=503,
        )
    except OSError:
        logger.exception("PTY start failed: fork/exec error")
        return JSONResponse(
            {"error": "Failed to start agent PTY"},
            status_code=500,
        )

    return JSONResponse(
        {
            "study_session_id": study_id,
            "topic": body.topic,
            "energy": body.energy,
            "agent": agent,
            "transport": "pty",
            "ws_url": f"/api/session/ws?study_session_id={study_id}",
        },
        status_code=201,
    )


def _start_ttyd_session(body: StartSessionRequest) -> JSONResponse:
    """Legacy tmux+ttyd start path (plan §1.9 emergency fallback).

    Kept as-is to guarantee a deprecation window. New development should
    target the PTY path above.
    """
    import os
    import shutil
    from pathlib import Path

    from studyloop.tmux import is_tmux_available, kill_session, session_exists

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

    from studyloop.agent_launcher import AGENTS, detect_agents

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
        from studyloop.logic.topic_resolver import resolve_topic
        from studyloop.settings import load_settings

        settings = load_settings()
        if settings.topics:
            result = resolve_topic(body.topic, settings.topics)
            topic_config = result.resolved or (result.matches[0] if result.matches else None)
    except Exception:
        pass  # Topic resolution is optional

    # --- Clean zombies ---

    try:
        from studyloop.session.cleanup import auto_clean_zombies

        auto_clean_zombies()
    except Exception:
        pass

    # --- Create DB session ---

    from studyloop.history import start_study_session
    from studyloop.output import energy_to_label

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

    from studyloop.agent_launcher import build_canonical_persona
    from studyloop.session.orchestrator import (
        build_wrapped_agent_cmd,
        create_tmux_environment,
        setup_session_dir,
        start_ttyd_background,
    )

    setup_session_dir(session_dir, body.topic)

    # Build persona
    canonical = build_canonical_persona("focus", body.topic, body.energy)
    persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]

    from studyloop.history.sessions import update_persona_hash

    update_persona_hash(study_id, persona_hash)

    persona_file = adapter.setup(canonical, session_dir)
    if adapter.mcp_setup:
        adapter.mcp_setup(session_dir)

    # Allow test injection
    test_agent_cmd = os.environ.get("STUDYLOOP_TEST_AGENT_CMD")
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
        sidebar=False,
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
        from studyloop.settings import load_settings as _ls_ttyd

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


@router.get("/session/options")
def get_session_options() -> dict[str, list[dict]]:
    """Return local study choices for the web session picker."""
    return {
        "session_types": [
            {"label": "Study Session", "value": "study", "kind": "session_type"},
            {"label": "Body Double", "value": "body_double", "kind": "session_type"},
        ],
        "topics": [option.model_dump() for option in _topic_options()],
        "vendors": [option.model_dump() for option in _vendor_options()],
        "courses": [option.model_dump() for option in _course_options()],
        "lessons": [option.model_dump() for option in _lesson_options()],
        "agents": _agent_options(),
    }


_WS_CLOSE_POLICY = 1008  # RFC 6455 Policy Violation


def _allowed_ws_origins() -> set[str]:
    """Return the allow-list for Origin on the live session WS.

    Localhost only by default — this is a single-user tool. Expand via
    ``STUDYLOOP_ALLOWED_ORIGINS`` (comma-separated) if the operator fronts
    the app behind a reverse proxy. See plan Blocker B1 (CSRF via cross-
    origin WS upgrade; RFC 6455 has no same-origin enforcement and CORS
    does not apply to WS).
    """
    import os

    defaults = {
        "http://127.0.0.1:8788",
        "http://localhost:8788",
        "http://127.0.0.1",
        "http://localhost",
    }
    extra = os.environ.get("STUDYLOOP_ALLOWED_ORIGINS", "").strip()
    if extra:
        return defaults | {o.strip() for o in extra.split(",") if o.strip()}
    return defaults


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    allowed = _allowed_ws_origins()
    if origin in allowed:
        return True
    # Allow any port on localhost / 127.0.0.1 (dev server port may vary).
    for prefix in ("http://127.0.0.1", "http://localhost"):
        if origin.startswith(prefix + ":") or origin == prefix:
            return True
    return False


@router.websocket("/session/ws")
async def live_session_socket(websocket: WebSocket) -> None:
    """Bidirectional live agent session socket (plan §1.5).

    The route binds an already-acquired ``active.ActiveSession`` to the
    WS client. Sessions are acquired via ``POST /api/session/start``
    (which calls ``active.acquire(config, PTYTransport)``); the WS then
    streams transport events out and pumps control frames in.

    Inbound JSON control frames:
    - ``{"type": "input", "data": "..."}``   → ``transport.send_input``
    - ``{"type": "resize", "cols": N, "rows": N}`` → ``transport.resize``
    - ``{"type": "stop"}``                    → ``transport.cancel``

    Outbound framing:
    - ``OutputBytes.data`` → **binary** frame (verbatim PTY bytes)
    - ``Started``/``Stopped``/``TransportError``/``AgentMessage`` → text
      JSON frames (``{"type": ..., ...}``)

    Close codes:
    - 1008 (Policy Violation) if Origin is disallowed, if no session is
      active, or if ``?study_session_id`` does not match the active one.
    - 1000 normal close on ``stop`` frame or transport-emitted ``Stopped``.
    """
    from studyloop.session import active as session_active
    from studyloop.session.transport import (
        AgentMessage,
        OutputBytes,
        Started,
        Stopped,
        TransportError,
    )

    # --- Pre-accept guards -----------------------------------------------

    # Origin check (plan Blocker B1). Must happen before accept() — the
    # handshake has not yet completed, so close-without-accept sends an
    # HTTP 403 response per Starlette semantics, which the client sees as
    # a failed upgrade. After accept() we can only send a WS close frame.
    origin = websocket.headers.get("origin", "")
    if not _origin_allowed(origin):
        logger.warning("WS /session/ws rejected: disallowed origin=%r", origin)
        await websocket.close(code=_WS_CLOSE_POLICY)
        return

    requested = websocket.query_params.get("study_session_id")
    current = await session_active.current()
    if current is None:
        await websocket.close(code=_WS_CLOSE_POLICY)
        return
    if requested and requested != current.study_session_id:
        logger.warning(
            "WS /session/ws rejected: requested=%r active=%r",
            requested,
            current.study_session_id,
        )
        await websocket.close(code=_WS_CLOSE_POLICY)
        return

    await websocket.accept()
    transport = current.transport

    async def pty_to_ws() -> None:
        """Pump transport events → WS frames until the session ends."""
        async for event in transport.events():
            if isinstance(event, OutputBytes):
                await websocket.send_bytes(event.data)
            elif isinstance(event, Started):
                await websocket.send_json({"type": "started", "agent": event.agent})
            elif isinstance(event, Stopped):
                await websocket.send_json(
                    {
                        "type": "stopped",
                        "returncode": event.returncode,
                        "reason": event.reason,
                    }
                )
                return  # Stopped is terminal — stop pumping.
            elif isinstance(event, TransportError):
                await websocket.send_json({"type": "transport_error", "message": event.message})
            elif isinstance(event, AgentMessage):
                await websocket.send_json(
                    {"type": "agent_message", "kind": event.kind, "payload": event.payload}
                )

    async def ws_to_pty() -> None:
        """Read WS control frames and forward to transport."""
        while True:
            frame = await websocket.receive_json()
            ftype = frame.get("type")
            if ftype == "input":
                data = frame.get("data", "")
                if isinstance(data, str):
                    await transport.send_input(data.encode("utf-8"))
            elif ftype == "resize":
                try:
                    cols = int(frame.get("cols", 80))
                    rows = int(frame.get("rows", 24))
                except (TypeError, ValueError):
                    continue
                await transport.resize(cols, rows)
            elif ftype == "stop":
                await transport.cancel()
                return
            # Silently drop unknown frame types — no error channel needed.

    # --- Pump with TaskGroup (plan Blocker B5) ---------------------------
    #
    # TaskGroup raises ExceptionGroup on any child exception; the WS
    # disconnect paths come up as ExceptionGroup[WebSocketDisconnect,
    # ConnectionClosedOK, ...]. ``except*`` unpacks cleanly without
    # reaching for .exceptions.

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(pty_to_ws(), name="ws-pty-to-ws")
            tg.create_task(ws_to_pty(), name="ws-ws-to-pty")
    except* WebSocketDisconnect:
        pass
    except* OSError as eg:
        logger.error("PTY I/O error on /session/ws: %s", eg.exceptions)
    except* Exception as eg:  # pragma: no cover — defensive
        logger.exception("unexpected error on /session/ws: %s", eg.exceptions)
    finally:
        await session_active.release()


@router.post("/session/end")
def end_session() -> JSONResponse:
    """End the current study session from the web UI."""
    state = read_session_state()

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


def _study_roots() -> list[Path]:
    candidates: list[Path] = []
    try:
        from studyloop.settings import load_settings

        settings = load_settings()
        candidates.extend(Path(path).expanduser() for path in settings.content.study_paths)
        candidates.extend(
            [
                settings.obsidian_base / "Personal" / "Study",
                settings.obsidian_base / "Personal" / "2-Areas" / "Study",
            ]
        )
        candidates.extend(topic.obsidian_path for topic in settings.topics)
    except Exception:
        candidates.extend(
            [
                Path("~/Obsidian/Personal/Study").expanduser(),
                Path("~/Obsidian/Personal/2-Areas/Study").expanduser(),
            ]
        )
    return _existing_unique_dirs(candidates)


def _topic_options() -> list[SessionOption]:
    options: list[SessionOption] = []
    for root in _study_roots():
        if not root.exists():
            continue
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() and not child.name.startswith("."):
                options.append(
                    SessionOption(
                        label=child.name.replace("_", " "),
                        value=child.name,
                        kind="topic",
                        path=str(child),
                    )
                )
    return options


def _vendor_options() -> list[SessionOption]:
    vendors: list[SessionOption] = []
    seen: set[Path] = set()
    for courses_root in _courses_roots():
        for vendor in sorted(courses_root.iterdir(), key=lambda p: p.name.lower()):
            resolved = vendor.resolve()
            if resolved in seen or not vendor.is_dir() or vendor.name.startswith("."):
                continue
            seen.add(resolved)
            vendors.append(
                SessionOption(
                    label=vendor.name.replace("_", " "),
                    value=vendor.name,
                    kind="vendor",
                    path=str(vendor),
                )
            )
    return vendors


def _course_options() -> list[SessionOption]:
    courses: list[SessionOption] = []
    for vendor in _vendor_options():
        vendor_path = Path(vendor.path or "")
        if not vendor_path.exists():
            continue
        for course in sorted(vendor_path.iterdir(), key=lambda p: p.name.lower()):
            if course.is_dir() and not course.name.startswith("."):
                courses.append(
                    SessionOption(
                        label=course.name.replace("_", " "),
                        value=f"{vendor.value}/{course.name}",
                        kind="course",
                        path=str(course),
                        parent=vendor.value,
                    )
                )
    return courses


def _lesson_options() -> list[SessionOption]:
    lessons: list[SessionOption] = []
    for course in _course_options():
        course_path = Path(course.path or "")
        if not course_path.exists():
            continue
        for lesson in sorted(course_path.iterdir(), key=lambda p: p.name.lower()):
            if lesson.is_dir() and not lesson.name.startswith("."):
                lessons.append(
                    SessionOption(
                        label=lesson.name.replace("_", " "),
                        value=f"{course.value}/{lesson.name}",
                        kind="lesson",
                        path=str(lesson),
                        parent=course.value,
                    )
                )
    return lessons


def _courses_roots() -> list[Path]:
    candidates = [root / "Courses" for root in _study_roots()]
    candidates.extend(
        [
            Path("~/Obsidian/Personal/Study/Courses").expanduser(),
            Path("~/Obsidian/Personal/2-Areas/Study/Courses").expanduser(),
        ]
    )
    return _existing_unique_dirs(candidates)


def _existing_unique_dirs(paths: list[Path]) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        expanded = path.expanduser()
        if not expanded.exists() or not expanded.is_dir():
            continue
        resolved = expanded.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(expanded)
    return roots


def _agent_options() -> list[dict[str, object]]:
    try:
        from studyloop.agent_launcher import AGENTS, detect_agents

        detected = set(detect_agents())
        return [
            {
                "label": _agent_label(name),
                "value": name,
                "available": name in detected,
                "supports_acp": name in {"kiro", "gemini"},
                "acp_ready": False,
                "recommended_transport": "ttyd",
                "binary": adapter.binary,
            }
            for name, adapter in AGENTS.items()
            if name in {"codex", "claude", "gemini", "kiro", "opencode"}
        ]
    except Exception:
        return []


def _agent_label(name: str) -> str:
    return {
        "claude": "Claude Code",
        "codex": "Codex",
        "gemini": "Gemini",
        "kiro": "Kiro",
        "opencode": "OpenCode",
    }.get(name, name)
