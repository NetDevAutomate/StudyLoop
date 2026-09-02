"""POST /session/start — PTY and ACP session start."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from fastapi import Request  # noqa: TC002 - FastAPI needs Request at runtime for injection.
from fastapi.responses import JSONResponse

from studyloop.session_state import (
    PARKING_FILE,
    SESSION_DIR,
    TOPICS_FILE,
    _ensure_session_dir,
    write_session_state,
)
from studyloop.web.routes.session._models import _AGENT_INSTALL_HINTS, StartSessionRequest
from studyloop.web.routes.session._router import router
from studyloop.web.routes.session._transport import (
    UnsupportedTransportError,
    _resolve_transport,
)
from studyloop.web.services.session_start import (
    build_session_state_payload,
    session_dir_name,
)

logger = logging.getLogger(__name__)

# Which view started the session: the Study Session picker ('study', the
# default) or the Body Double view ('body-double'). Persisted into the session
# state payload and echoed by GET /api/session/state so the frontend's two
# origin-scoped liveAgentConsole() instances each only react to their own
# view's start (see body-double-own-agent-picker, ADR-0002).
_ALLOWED_ORIGINS: frozenset[str] = frozenset({"study", "body-double"})
_DEFAULT_ORIGIN = "study"


def _active_session_topic(session_id: str) -> str | None:
    """The active session's topic from the IPC file, or None.

    Only trusts the file when its id matches the slot that actually holds the
    session. A mismatched id means the file belongs to a different (stale or
    replaced) session, and presenting its topic as this session's is exactly
    the "your last topic" desync the reconcile work exists to kill.
    """
    from studyloop.web.routes import session as session_pkg

    try:
        state = session_pkg.read_session_state()
    except Exception:  # pragma: no cover - defensive
        return None
    if state.get("study_session_id") != session_id:
        return None
    topic = state.get("topic")
    return topic if isinstance(topic, str) else None


def _conflict_response(
    *,
    session_id: str,
    topic: str | None,
    agent: str | None,
    detached: bool,
) -> JSONResponse:
    """The 409 body shared by every start path blocked by an active session.

    Name the topic in the message itself, not only in the `topic` field. The
    learner reads the error text, and "a session is already active" without
    saying WHICH is the difference between a clear refusal and a dead end —
    especially mid-study, when the blocking session may be one they forgot in
    another tab.
    """
    subject = f' on "{topic}"' if topic else ""
    return JSONResponse(
        {
            "error": (
                f"A session is already active{subject} — its browser tab may have "
                "closed but the agent is still running. Reattach to it, or end it "
                "first."
            ),
            "study_session_id": session_id,
            "topic": topic,
            "agent": agent,
            "detached": detached,
            "reattach_url": f"/api/session/ws?study_session_id={session_id}",
        },
        status_code=409,
    )


async def _session_conflict() -> JSONResponse | None:
    """Build the 409 for a start blocked by an already-active session.

    Checks BOTH claims to the single-session slot (R-01): the in-process
    singleton (``session/active.py``, this process's own PTY/ACP session) and
    the cross-process file claim (``session-state.json``, written by the
    CLI's ``studyloop study`` or a PTY/ACP session that outlived a crashed web
    server process). See docs/architecture/session-authority.md clause 2 for
    the full liveness contract.

    Reports the *blocking* session's own topic and reattach URL so the UI can
    offer "reattach or end" instead of the desync fallback string. The topic
    is looked up via :func:`_active_session_topic` for the in-process case
    (which never borrows a different session's topic), or read directly from
    the file claim for the cross-process case (same guarantee — the claim
    dict IS that session's own state).

    Returns ``None`` when nothing live is blocking the start — including when
    the file names a claim whose owner is no longer alive. A stale claim is
    RECLAIMED (logged, never blocking) rather than refused forever; see
    clause 2's crash-then-restart case.
    """
    from studyloop.session import active as session_active
    from studyloop.web.routes.session import _grace

    current = await session_active.current()
    if current is not None:
        session_id = current.study_session_id
        return _conflict_response(
            session_id=session_id,
            topic=_active_session_topic(session_id),
            agent=current.config.agent,
            detached=_grace.has_pending_release(session_id),
        )

    # No in-process singleton holds the slot: consult the cross-process file
    # claim. is_session_active() here would only tell us a claim EXISTS —
    # claim_blocks_web_start() also asks whether its recorded owner is still
    # alive, which is exactly the check the ttyd-only branch used to do and
    # every other branch skipped (R-01).
    from studyloop import session_state
    from studyloop.web.routes import session as session_pkg

    state = session_pkg.read_session_state()
    if not session_state.claim_blocks_web_start(state):
        if state.get("study_session_id") and state.get("mode") != "ended":
            logger.warning(
                "Reclaiming stale session claim id=%s transport=%s — its owner is no longer alive",
                state.get("study_session_id"),
                state.get("transport", "cli"),
            )
        return None

    session_id = str(state.get("study_session_id"))
    topic = state.get("topic")
    return _conflict_response(
        session_id=session_id,
        topic=topic if isinstance(topic, str) else None,
        agent=state.get("agent") if isinstance(state.get("agent"), str) else None,
        detached=_grace.has_pending_release(session_id),
    )


async def _resolve_origin(request: Request) -> str:
    """Return the validated ``origin`` from the start request body.

    ``origin`` is read from the raw request body rather than from
    ``StartSessionRequest`` because that model lives in ``_models.py`` (outside
    this stage's ownership) and Pydantic drops unknown fields, so the value
    never reaches ``body``. Starlette caches the request body, so re-reading it
    here after FastAPI's own parse is safe. Absent/blank origin defaults to
    ``'study'``. An out-of-set value raises 400 rather than silently coercing.
    """
    try:
        payload = await request.json()
    except Exception:
        return _DEFAULT_ORIGIN
    if not isinstance(payload, dict):
        return _DEFAULT_ORIGIN
    origin = payload.get("origin")
    if origin is None or origin == "":
        return _DEFAULT_ORIGIN
    if origin not in _ALLOWED_ORIGINS:
        raise ValueError(origin)
    return origin


@router.post("/session/start")
async def start_session(body: StartSessionRequest, request: Request) -> JSONResponse:
    """Start a new study session from the web UI.

    Two transports are supported:

    - ``pty`` (default, plan §1.5b) — spawns the agent directly via
      ``PTYTransport`` + ``active.acquire`` and returns a ``ws_url``
      that the browser feeds to ``/api/session/ws``. No tmux, no ttyd.
    - ``acp`` (Agent Client Protocol, available for Kiro) — body-only,
      never selectable via ``STUDYLOOP_TRANSPORT``.

    ``transport`` is validated structurally by ``StartSessionRequest``
    (``Literal["pty", "acp"]``), so an unrecognised body value — including
    the retired ``ttyd`` — never reaches this handler; FastAPI rejects it
    with 422 first. ``STUDYLOOP_TRANSPORT`` is checked at runtime by
    ``_resolve_transport`` and raises :class:`UnsupportedTransportError` for
    the same reason: a caller asking for a transport that no longer exists
    must see an error, not silently get ``pty`` instead (R-05).

    Declared ``async`` so the PTY path's ``active.acquire`` runs on the
    FastAPI event loop — installing the SIGCHLD signal handler requires
    a loop owned by the main thread, which ``asyncio.run`` in a worker
    thread cannot provide.
    """
    try:
        origin = await _resolve_origin(request)
    except ValueError as exc:
        return JSONResponse(
            {"error": f"Invalid origin: {exc.args[0]!r}. Allowed: {sorted(_ALLOWED_ORIGINS)}"},
            status_code=400,
        )

    try:
        transport = _resolve_transport(body.transport)
    except UnsupportedTransportError as exc:
        return JSONResponse(
            {"error": f"Unsupported transport: {exc.args[0]!r}. Allowed: ['pty', 'acp']"},
            status_code=422,
        )

    if transport == "acp":
        return await _start_acp_session(body, origin)
    return await _start_pty_session(body, origin)


async def _start_pty_session(
    body: StartSessionRequest, origin: str = _DEFAULT_ORIGIN
) -> JSONResponse:
    """PTY-backed start path — no tmux, no ttyd.

    1. Reject if a session is already active -- in-process singleton OR a live
       cross-process file claim (``_session_conflict()``, R-01).
    2. Resolve agent + check binary. 503 with ``install_hint`` on miss.
    3. Persona + DB record creation (shared with legacy).
    4. ``await active.acquire(config, factory)`` — atomic under asyncio.Lock.
    5. Write IPC session_state only after the transport starts, then return
       201 with ``ws_url`` for the client to open.
    """
    import os
    import shutil

    from studyloop.agent_launcher import AGENTS, detect_agents
    from studyloop.session import active as session_active
    from studyloop.session.transport import SessionAlreadyActiveError, SessionConfig

    conflict = await _session_conflict()
    if conflict is not None:
        return conflict

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
    test_agent_cmd = os.environ.get("STUDYLOOP_TEST_AGENT_CMD")
    if not test_agent_cmd and not shutil.which(adapter.binary):
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
    session_dir = SESSION_DIR / "sessions" / session_dir_name(body.topic, study_id)

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
    from studyloop.web.routes import session as session_pkg

    factory = session_pkg._build_pty_transport(config)

    try:
        await session_active.acquire(config, factory)
    except SessionAlreadyActiveError:
        from studyloop.history import abort_study_session

        abort_study_session(study_id, "Startup failed: another session is already active")
        return JSONResponse(
            {"error": "A session is already active"},
            status_code=409,
        )
    except FileNotFoundError as exc:
        from studyloop.history import abort_study_session

        abort_study_session(study_id, f"Startup failed: agent binary not found: {exc}")
        logger.exception("PTY start failed: binary missing")
        return JSONResponse(
            {"error": f"Agent binary not found: {exc}"},
            status_code=503,
        )
    except OSError:
        from studyloop.history import abort_study_session

        abort_study_session(study_id, "Startup failed: failed to start agent PTY")
        logger.exception("PTY start failed: fork/exec error")
        return JSONResponse(
            {"error": "Failed to start agent PTY"},
            status_code=500,
        )

    try:
        # --- Session state (no tmux metadata) ---
        _ensure_session_dir()
        pty_state = build_session_state_payload(
            study_id=study_id,
            topic=body.topic,
            energy=body.energy,
            energy_label=energy_label,
            agent=agent,
            persona_file=str(persona_file),
            session_dir=str(session_dir),
            persona_hash=persona_hash,
            transport="pty",
            now=datetime.now(UTC),
        )
        # origin distinguishes Study Session ('study') from Body Double
        # ('body-double') starts. Merged in here rather than in
        # build_session_state_payload (owned by another stage) so it flows
        # through write_session_state → read_session_state → /api/session/state.
        pty_state["origin"] = origin
        write_session_state(pty_state)
        TOPICS_FILE.touch(mode=0o600, exist_ok=True)
        PARKING_FILE.touch(mode=0o600, exist_ok=True)
    except OSError:
        from studyloop.history import abort_study_session

        await session_active.release()
        abort_study_session(study_id, "Startup failed: failed to finalise session state")
        logger.exception("PTY start failed: session state finalisation error")
        return JSONResponse(
            {"error": "Failed to finalise session state"},
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


async def _start_acp_session(
    body: StartSessionRequest, origin: str = _DEFAULT_ORIGIN
) -> JSONResponse:
    """ACP-backed start path (plan §2.2 — Amendment #10).

    Mirrors ``_start_pty_session`` but drops tmux and PTY-specific
    adapter steps. Persona and MCP files are NOT written here — ACP
    agents receive context via ``session/prompt``, not argv; a future
    refinement may inject the persona as the first prompt, but for
    §2.2 we let the frontend send it.

    1. Reject if a session is already active -- in-process singleton OR a live
       cross-process file claim (``_session_conflict()``, R-01).
    2. Resolve agent + check binary. 503 with ``install_hint`` on miss.
    3. DB record creation (no tmux metadata, no persona file).
    4. ``await active.acquire(config, factory)`` — atomic under asyncio.Lock.
    5. Write IPC session_state only after the transport starts, then return
       201 with ``ws_url`` for the client to open.
    """
    import os
    import shutil

    from studyloop.agent_launcher import AGENTS, detect_agents
    from studyloop.session import active as session_active
    from studyloop.session.transport import SessionAlreadyActiveError, SessionConfig

    conflict = await _session_conflict()
    if conflict is not None:
        return conflict

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

    # --- ACP capability guard ---
    # Fail early (before spawn) if the resolved agent has no ACP transport.
    # Claude Code and Codex are PTY-only; forcing ACP on them dead-ends in a
    # spawn failure with an opaque message. Surface the cause + repair instead.
    from studyloop.web.services.session_start import ACP_CAPABLE_AGENTS

    if agent not in ACP_CAPABLE_AGENTS:
        return JSONResponse(
            {
                "error": f"Agent '{agent}' does not support the ACP transport.",
                "agent": agent,
                "supported_agents": sorted(ACP_CAPABLE_AGENTS),
                "repair": (
                    f"Use transport 'pty' for {agent}, or pick an ACP-capable "
                    f"agent ({', '.join(sorted(ACP_CAPABLE_AGENTS))})."
                ),
            },
            status_code=400,
        )

    adapter = AGENTS[agent]
    # STUDYLOOP_TEST_ACP_CMD bypasses the binary check entirely — the test
    # test agent (tests/_stub_acp_agent.py) is the argv we spawn, so the real
    # Kiro binary doesn't need to be installed. Parity with the
    # PTY test hatch behaviour (which dodges the check by routing every
    # launch through /bin/sh anyway).
    test_acp_cmd = os.environ.get("STUDYLOOP_TEST_ACP_CMD")
    if not test_acp_cmd and not shutil.which(adapter.binary):
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

    # --- Topic resolution (optional, same as PTY) ---
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

    # --- Session dir (for cwd — no persona/MCP file written) ---
    session_dir = SESSION_DIR / "sessions" / session_dir_name(body.topic, study_id, prefix="acp")

    from studyloop.agent_launcher import build_canonical_persona
    from studyloop.session.orchestrator import setup_session_dir

    setup_session_dir(session_dir, body.topic)

    # Persona is built here and returned inline in the response so the
    # browser can ship it as the first invisible session/prompt on WS open.
    # No persona file is written to disk: ACP agents receive context via
    # session/prompt, not via argv/env, so a file would just be dead weight.
    persona_text = build_canonical_persona("focus", body.topic, body.energy)
    persona_hash = hashlib.sha256(persona_text.encode()).hexdigest()[:16]

    from studyloop.history.sessions import update_persona_hash

    update_persona_hash(study_id, persona_hash)

    # --- Acquire the active-session singleton ---
    config = SessionConfig(
        study_session_id=study_id,
        agent=agent,
        persona_file="",  # ACP ignores this; kept for Protocol parity.
        cwd=str(session_dir),
        env=dict(os.environ),
        cols=80,
        rows=24,
    )
    from studyloop.web.routes import session as session_pkg

    factory = session_pkg._build_acp_transport(config)

    try:
        await session_active.acquire(config, factory)
    except SessionAlreadyActiveError:
        from studyloop.history import abort_study_session

        abort_study_session(study_id, "Startup failed: another session is already active")
        return JSONResponse(
            {"error": "A session is already active"},
            status_code=409,
        )
    except FileNotFoundError as exc:
        from studyloop.history import abort_study_session

        abort_study_session(study_id, f"Startup failed: agent binary not found: {exc}")
        logger.exception("ACP start failed: binary missing")
        return JSONResponse(
            {"error": f"Agent binary not found: {exc}"},
            status_code=503,
        )
    except OSError:
        from studyloop.history import abort_study_session

        abort_study_session(study_id, "Startup failed: failed to start ACP agent")
        logger.exception("ACP start failed: spawn error")
        return JSONResponse(
            {"error": "Failed to start ACP agent"},
            status_code=500,
        )

    try:
        # --- Session state (no tmux, no persona_file path; hash only) ---
        _ensure_session_dir()
        acp_state = build_session_state_payload(
            study_id=study_id,
            topic=body.topic,
            energy=body.energy,
            energy_label=energy_label,
            agent=agent,
            session_dir=str(session_dir),
            persona_hash=persona_hash,
            transport="acp",
            now=datetime.now(UTC),
        )
        # See PTY path: origin merged here, not in build_session_state_payload.
        acp_state["origin"] = origin
        write_session_state(acp_state)
        TOPICS_FILE.touch(mode=0o600, exist_ok=True)
        PARKING_FILE.touch(mode=0o600, exist_ok=True)
    except OSError:
        from studyloop.history import abort_study_session

        await session_active.release()
        abort_study_session(study_id, "Startup failed: failed to finalise session state")
        logger.exception("ACP start failed: session state finalisation error")
        return JSONResponse(
            {"error": "Failed to finalise session state"},
            status_code=500,
        )

    return JSONResponse(
        {
            "study_session_id": study_id,
            "topic": body.topic,
            "energy": body.energy,
            "agent": agent,
            "transport": "acp",
            "ws_url": f"/api/session/ws?study_session_id={study_id}",
            # persona_text is shipped inline so the browser can send it as
            # the first invisible session/prompt frame after WS open. ACP
            # agents have no argv/env hook for context; the prompt channel
            # is the only injection point.
            "persona_text": persona_text,
            "persona_hash": persona_hash,
        },
        status_code=201,
    )
