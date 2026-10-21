"""The server-cookie helpers out-of-band test clients use (F-WEB-20 follow-up).

``studyloop web`` mints a per-process secret: ``GET /`` sets it as the
``studyloop_auth`` cookie, and ``/api/*`` (403) and both WebSockets (1008)
refuse a request without it. ``server_cookie_header`` / ``server_opener`` /
``server_session`` in ``_playwright_helpers`` are how a test that drives a real
server with urllib, requests or websockets loads ``/`` and presents the cookie.

The unit tests serve the REAL ``RequestBoundaryMiddleware`` (wrapping a tiny
app, so no ``create_app`` lifespan runs) over a real loopback socket: the
helpers speak HTTP, so an in-process ``TestClient`` could not exercise them.
The one ``e2e`` test runs the helpers against a real ``studyloop web`` child.
"""

from __future__ import annotations

import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import pytest
from _playwright_helpers import (
    server_cookie_header,
    server_opener,
    server_session,
    start_web_server,
)

from studyloop.web.app import RequestBoundaryMiddleware
from studyloop.web.ws_origin import AUTH_COOKIE

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

#: Minted per run, as ``studyloop web`` mints its own at start.
SECRET = secrets.token_urlsafe(16)


def _inner_app(*, password: str = ""):  # type: ignore[no-untyped-def]
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse
    from starlette.routing import Route, WebSocketRoute

    async def index(_request):  # type: ignore[no-untyped-def]
        return HTMLResponse("<!doctype html><title>studyloop</title>")

    async def ping(_request):  # type: ignore[no-untyped-def]
        return JSONResponse({"ok": True})

    async def socket_endpoint(websocket):  # type: ignore[no-untyped-def]
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/api/ping", ping),
            WebSocketRoute("/api/session/ws", socket_endpoint),
        ]
    )
    if password:
        from studyloop.web.auth import BasicAuthMiddleware

        return BasicAuthMiddleware(app, username="study", password=password)
    return app


@pytest.fixture()
def serve() -> Generator[Callable[..., str], None, None]:
    """Start ``RequestBoundaryMiddleware`` on a loopback socket; return its base URL."""
    import uvicorn

    running: list[tuple[uvicorn.Server, threading.Thread]] = []

    def _serve(*, secret: str = SECRET, password: str = "") -> str:
        app = RequestBoundaryMiddleware(_inner_app(password=password), server_secret=secret)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        running.append((server, thread))
        deadline = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("uvicorn did not start within 10s")
            time.sleep(0.02)
        return f"http://127.0.0.1:{port}"

    try:
        yield _serve
    finally:
        for server, thread in running:
            server.should_exit = True
            thread.join(timeout=10)


def test_cookie_header_carries_the_secret_that_slash_sets(serve) -> None:
    base = serve()
    assert server_cookie_header(base) == f"{AUTH_COOKIE}={SECRET}"
    # A trailing slash on the base URL is the same server.
    assert server_cookie_header(base + "/") == f"{AUTH_COOKIE}={SECRET}"


def test_opener_presents_the_cookie_a_bare_urlopen_lacks(serve) -> None:
    base = serve()
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(f"{base}/api/ping", timeout=5)
    assert refused.value.code == 403

    with server_opener(base).open(f"{base}/api/ping", timeout=5) as response:
        assert response.status == 200


def test_session_presents_the_cookie_a_bare_requests_call_lacks(serve) -> None:
    requests = pytest.importorskip("requests")
    base = serve()
    assert requests.get(f"{base}/api/ping", timeout=5).status_code == 403
    with server_session(base) as session:
        response = session.get(f"{base}/api/ping", timeout=5)
        assert response.status_code == 200, response.text
        # 405, not 403: the POST got past the cookie gate to the router.
        assert session.post(f"{base}/api/ping", timeout=5).status_code == 405


def test_websocket_opens_with_the_cookie_header_and_not_without(serve) -> None:
    from websockets.exceptions import InvalidStatus
    from websockets.sync.client import connect

    base = serve()
    ws_url = base.replace("http://", "ws://") + "/api/session/ws"

    with pytest.raises(InvalidStatus):
        connect(ws_url, open_timeout=5, additional_headers={"Origin": base})

    headers = {"Origin": base, "Cookie": server_cookie_header(base)}
    with connect(ws_url, open_timeout=5, additional_headers=headers) as ws:
        assert ws.recv(timeout=5) == "hello"


def test_a_slash_that_sets_no_cookie_is_reported_as_a_server_regression(serve) -> None:
    # Empty secret: the gate is off and / sets nothing. The helper must say so
    # instead of returning a header that would only fail later as a 403.
    base = serve(secret="")
    with pytest.raises(RuntimeError, match=AUTH_COOKIE):
        server_cookie_header(base)


def test_basic_auth_is_sent_on_the_slash_load_and_by_the_clients(serve) -> None:
    requests = pytest.importorskip("requests")
    base = serve(password="pw")
    with pytest.raises(urllib.error.HTTPError) as unauthorised:
        server_cookie_header(base)
    assert unauthorised.value.code == 401

    creds = ("study", "pw")
    assert server_cookie_header(base, basic_auth=creds) == f"{AUTH_COOKIE}={SECRET}"
    with server_opener(base, basic_auth=creds).open(f"{base}/api/ping", timeout=5) as response:
        assert response.status == 200
    with server_session(base, basic_auth=creds) as session:
        assert session.get(f"{base}/api/ping", timeout=5).status_code == 200
    # Basic auth alone is not the server cookie.
    assert requests.get(f"{base}/api/ping", auth=creds, timeout=5).status_code == 403


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.e2e
def test_real_studyloop_web_accepts_the_helpers_cookie_and_refuses_without() -> None:
    """The helpers against the real CLI: its minted secret, its whole app stack."""
    import json

    port = _free_port()
    proc = start_web_server(port)
    base = f"http://127.0.0.1:{port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(f"{base}/api/session/state", timeout=10)
        assert refused.value.code == 403
        assert json.loads(refused.value.read())["code"] == "server_secret_required"

        with server_opener(base).open(f"{base}/api/session/state", timeout=10) as response:
            assert response.status == 200
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)
