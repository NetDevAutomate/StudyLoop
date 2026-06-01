"""WebSocket /session/ws — live PTY/ACP byte and message stream."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect

from studyloop.web.routes.session._router import router
from studyloop.web.routes.session._transport import _PermissionResponder
from studyloop.web.ws_origin import origin_allowed

logger = logging.getLogger(__name__)

_WS_CLOSE_POLICY = 1008  # RFC 6455 Policy Violation


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
    except* WebSocketDisconnect:
        pass
    except* OSError as eg:
        logger.error("PTY I/O error on /session/ws: %s", eg.exceptions)
    except* Exception as eg:  # pragma: no cover — defensive
        logger.exception("unexpected error on /session/ws: %s", eg.exceptions)
    finally:
        await session_active.release()
