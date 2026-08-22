"""WebSocket /session/ws — live PTY/ACP byte and message stream."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect

from studyloop.web.routes.session._router import router
from studyloop.web.routes.session._transport import _PermissionResponder
from studyloop.web.ws_origin import origin_allowed

logger = logging.getLogger(__name__)

_WS_CLOSE_POLICY = 1008  # RFC 6455 Policy Violation

#: Sent to a socket that just lost the consumer slot to a newer one, on its own
#: connection, so the learner is told where the live terminal went.
_SUPERSEDED_MESSAGE = (
    "This study session was opened in another tab or window, "
    "which now has the live terminal."
)


class _Superseded(Exception):
    """Raised inside the pump TaskGroup when a newer socket takes the slot.

    Collapses the group so the ``except*`` arm can send the displaced client
    its ``attach_superseded`` frame and close. Never escapes the route.
    """


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
    from studyloop.web.routes.session import _grace

    # --- Pre-accept guards -----------------------------------------------

    # Origin check (plan Blocker B1). Must happen before accept() — the
    # handshake has not yet completed, so close-without-accept sends an
    # HTTP 403 response per Starlette semantics, which the client sees as
    # a failed upgrade. After accept() we can only send a WS close frame.
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    if not origin_allowed(origin, host=host):
        logger.warning("WS /session/ws rejected: disallowed origin=%r host=%r", origin, host)
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
    session_id = current.study_session_id

    # A reconnect inside the grace window stands the release timer down, then
    # claiming the consumer slot displaces any socket still holding it. The slot
    # is what guarantees the event-stream drain is never split between two
    # terminals (see _grace.py: events() is a drain, one event per consumer).
    _grace.cancel_pending_release(session_id)
    mine, _displaced = await _grace.acquire_consumer(session_id)

    stopped = False  # session is over: Stopped event, stop frame, or drained stream
    superseded = False  # a newer socket took the consumer slot from us

    async def pty_to_ws() -> None:
        """Pump transport events → WS frames until the session ends.

        The next event is pulled as its own task so the loop can also poll
        ``mine.superseded`` every ``SUPERSEDE_POLL_S`` while the stream is idle
        (a live agent with nothing to say still has to notice a takeover). The
        poll lives here rather than in a third TaskGroup task on purpose: once
        the stream ends this coroutine returns and its pull task is cancelled
        synchronously, leaving only ``ws_to_pty`` blocked on receive — the same
        shape the plain-pump WS tests rely on for a clean client-close teardown.
        """
        nonlocal stopped, superseded
        events = transport.events()
        nxt = asyncio.ensure_future(events.__anext__())
        try:
            while True:
                await asyncio.wait({nxt}, timeout=_grace.SUPERSEDE_POLL_S)
                if mine.superseded:
                    superseded = True
                    raise _Superseded()
                if not nxt.done():
                    continue  # nothing yet — poll again.
                exc = nxt.exception()
                if isinstance(exc, StopAsyncIteration):
                    # Stream drained with no Stopped event (end() pushed the
                    # queue sentinel). The session is over, so release now rather
                    # than hold a dead agent for the whole grace window.
                    stopped = True
                    return
                if exc is not None:
                    raise exc
                event = nxt.result()
                if isinstance(event, Stopped):
                    await websocket.send_json(
                        {
                            "type": "stopped",
                            "returncode": event.returncode,
                            "reason": event.reason,
                        }
                    )
                    stopped = True  # agent exit — release now, not after the window.
                    return  # Stopped is terminal — stop pumping.
                nxt = asyncio.ensure_future(events.__anext__())
                if isinstance(event, OutputBytes):
                    await websocket.send_bytes(event.data)
                elif isinstance(event, Started):
                    await websocket.send_json({"type": "started", "agent": event.agent})
                elif isinstance(event, TransportError):
                    await websocket.send_json(
                        {"type": "transport_error", "message": event.message}
                    )
                elif isinstance(event, AgentMessage):
                    await websocket.send_json(
                        {"type": "agent_message", "kind": event.kind, "payload": event.payload}
                    )
        finally:
            if not nxt.done():
                nxt.cancel()
            with contextlib.suppress(BaseException):
                await events.aclose()

    async def ws_to_pty() -> None:
        """Read WS control frames and forward to transport."""
        nonlocal stopped
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
                # Explicit learner intent, not a disconnect — end immediately
                # with no grace window (a disconnect would get one).
                await transport.cancel()
                stopped = True
                return
            elif ftype == "permission_response":
                # ACP permission response (U6.5). Duck-typed guard: PTYTransport
                # has no send_permission_response and must NOT get one added to
                # the Protocol (would fail structural checks). Only ACPTransport
                # implements the method; future transports opt-in by name.
                #
                # Frame shape from browser: {type, requestId, outcome}
                # where outcome is {"outcome": "selected", "optionId": "..."}
                # or {"outcome": "cancelled"}.
                request_id = frame.get("requestId", "")
                outcome = frame.get("outcome")
                if not isinstance(request_id, str) or not request_id:
                    # Missing requestId — silently drop, can't correlate.
                    pass
                elif isinstance(transport, _PermissionResponder) and isinstance(outcome, dict):
                    await transport.send_permission_response(
                        request_id,
                        cast("dict[str, Any]", outcome),
                    )
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
    except* _Superseded:
        # A newer socket took over. Tell this (older) client where its session
        # went, on its own connection, then close with a policy-violation code.
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "type": "attach_superseded",
                    "reason": "taken_over",
                    "message": _SUPERSEDED_MESSAGE,
                }
            )
            await websocket.close(code=_WS_CLOSE_POLICY)
    except* WebSocketDisconnect:
        pass
    except* OSError as eg:
        logger.error("PTY I/O error on /session/ws: %s", eg.exceptions)
    except* Exception as eg:  # pragma: no cover — defensive
        logger.exception("unexpected error on /session/ws: %s", eg.exceptions)
    finally:
        # Give up our own claim (identity-checked in _grace: a no-op on the
        # session slot once we have been superseded, so the successor keeps it).
        _grace.release_consumer(mine)
        if superseded:
            # The successor owns the session now — leave it running for them.
            pass
        elif stopped:
            # Agent exited or the learner pressed Stop — release at once.
            await _grace.release_now(session_id, reason="session ended")
        else:
            # A plain disconnect (reload, closed lid, lost wifi). Hold the
            # session for the grace window so a returning client can reattach
            # instead of losing a live agent to an accidental ⌘R.
            _grace.schedule_release(session_id)

