"""Same-origin reverse proxy for ttyd.

Proxies all /terminal/{path} HTTP requests and /terminal/ws WebSocket
connections to the local ttyd process. This keeps everything same-origin,
preventing iframe WebSocket drops when the terminal is popped out.

HTTP proxying uses httpx.AsyncClient.
WebSocket proxying uses websockets (bidirectional relay).
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from studyctl.session_state import read_session_state

router = APIRouter()

# Headers that must not be forwarded between proxy and upstream (hop-by-hop).
_HOP_BY_HOP = frozenset(
    {"connection", "keep-alive", "transfer-encoding", "te", "trailers", "upgrade"}
)
# Additional headers to strip from upstream responses:
# content-encoding: httpx decompresses for us; content-length may no longer be accurate.
_STRIP_FROM_RESPONSE = _HOP_BY_HOP | frozenset({"content-encoding", "content-length"})


def _ttyd_base(request: Request) -> str:
    """Get the ttyd base URL from app state."""
    port: int = getattr(request.app.state, "ttyd_port", 7681)
    return f"http://127.0.0.1:{port}"


def _session_matches(request: Request) -> bool:
    """Return False when a terminal iframe is for an old study session."""
    requested_session = request.query_params.get("session")
    if not requested_session:
        return True
    state = read_session_state()
    return requested_session == state.get("study_session_id")


# ---------------------------------------------------------------------------
# HTTP proxy — forwards GET/HEAD/POST etc. to ttyd
# ---------------------------------------------------------------------------


@router.api_route("/terminal/{path:path}", methods=["GET", "HEAD", "POST"])
async def proxy_terminal_http(path: str, request: Request) -> Response:
    """Proxy HTTP requests to the local ttyd server.

    Maps /terminal/{path} → http://127.0.0.1:{ttyd_port}/{path}
    """
    if not _session_matches(request):
        return Response(
            content=b"Terminal session is no longer active",
            status_code=409,
            media_type="text/plain",
            headers={"Cache-Control": "no-store"},
        )

    upstream_url = f"{_ttyd_base(request)}/{path}"

    # Forward query string
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    # Forward the body for POST requests
    body = await request.body()

    # Strip hop-by-hop headers before forwarding
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "host"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream_resp = await client.request(
                method=request.method,
                url=upstream_url,
                headers=headers,
                content=body,
                follow_redirects=True,
            )
    except (httpx.ConnectError, httpx.ConnectTimeout, OSError):
        return Response(
            content=b"Terminal unavailable (ttyd not running)",
            status_code=502,
            media_type="text/plain",
        )
    except Exception:
        return Response(
            content=b"Proxy error",
            status_code=502,
            media_type="text/plain",
        )

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items() if k.lower() not in _STRIP_FROM_RESPONSE
    }
    resp_headers["Cache-Control"] = "no-store"

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=resp_headers,
    )


# ---------------------------------------------------------------------------
# WebSocket proxy — bidirectional relay to ttyd
# ---------------------------------------------------------------------------


@router.websocket("/terminal/ws")
async def proxy_terminal_ws(ws: WebSocket) -> None:
    """Proxy WebSocket connections to the local ttyd /ws endpoint.

    ttyd's WebSocket protocol is relayed verbatim (binary + text frames).
    """
    import websockets

    port: int = getattr(ws.app.state, "ttyd_port", 7681)
    upstream_ws_base = f"ws://127.0.0.1:{port}"

    requested_session = ws.query_params.get("session")
    if requested_session and requested_session != read_session_state().get("study_session_id"):
        await ws.close(code=1008)
        return

    # Accept the connection, forwarding the subprotocol if present (ttyd uses "tty")
    subprotocol = None
    if ws.headers.get("sec-websocket-protocol"):
        # Pass the first subprotocol the client requests
        subprotocol = ws.headers["sec-websocket-protocol"].split(",")[0].strip()
    await ws.accept(subprotocol=subprotocol)

    upstream_ws_url = f"{upstream_ws_base}/ws"
    if ws.query_params:
        qs = "&".join(f"{k}={v}" for k, v in ws.query_params.items())
        upstream_ws_url = f"{upstream_ws_url}?{qs}"

    # Connect to upstream with the same subprotocol.
    # Forward the Authorization header so ttyd's -c auth is satisfied.
    upstream_kwargs: dict = {}
    if subprotocol:
        upstream_kwargs["subprotocols"] = [subprotocol]
    auth_header = ws.headers.get("authorization")
    if auth_header:
        upstream_kwargs["additional_headers"] = {"Authorization": auth_header}

    try:
        async with websockets.connect(upstream_ws_url, **upstream_kwargs) as upstream:

            async def client_to_upstream() -> None:
                try:
                    while True:
                        msg = await ws.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        if msg.get("bytes"):
                            await upstream.send(msg["bytes"])
                        elif msg.get("text"):
                            await upstream.send(msg["text"])
                except (WebSocketDisconnect, Exception):
                    pass

            async def upstream_to_client() -> None:
                try:
                    async for msg in upstream:
                        if isinstance(msg, bytes):
                            await ws.send_bytes(msg)
                        else:
                            await ws.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(
                client_to_upstream(),
                upstream_to_client(),
                return_exceptions=True,
            )
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
