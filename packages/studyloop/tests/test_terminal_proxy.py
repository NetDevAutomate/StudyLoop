"""Tests for the same-origin terminal proxy (Task 1).

The proxy reverse-proxies ttyd through FastAPI so all traffic is same-origin,
fixing iframe WebSocket drops when popping out the terminal.

Tests:
- GET /terminal/ proxies to upstream ttyd
- WebSocket /terminal/ws relays messages
- session.html uses /terminal/ path (same-origin), not http://hostname:port
- X-Frame-Options is SAMEORIGIN (not DENY)
- Security headers preserved on proxied routes
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import ClassVar

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app

# ---------------------------------------------------------------------------
# Helpers: minimal stub HTTP server to act as a fake ttyd upstream
# ---------------------------------------------------------------------------


class _TtydHTTPHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that returns a known HTML page like ttyd."""

    received_headers: ClassVar[dict[str, str]] = {}

    def do_GET(self) -> None:
        type(self).received_headers = dict(self.headers.items())
        body = b"<html><body><div class='xterm'>ttyd terminal</div></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", "ttyd-session=must-not-reach-browser")
        self.send_header("Authorization", "Bearer must-not-reach-browser")
        self.send_header("X-CSRF-Token", "must-not-reach-browser")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # type: ignore[override]
        pass  # Suppress noisy output during tests


@pytest.fixture()
def fake_ttyd_port(tmp_path) -> Generator[int, None, None]:
    """Spin up a minimal HTTP server that acts as a fake ttyd upstream.

    Yields the port it's listening on.
    """
    _TtydHTTPHandler.received_headers = {}
    server = HTTPServer(("127.0.0.1", 0), _TtydHTTPHandler)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield port

    server.shutdown()


@pytest.fixture()
def proxy_client(fake_ttyd_port: int) -> TestClient:
    """FastAPI TestClient with the proxy configured to point at fake_ttyd_port."""
    app = create_app(ttyd_port=fake_ttyd_port)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Security header tests
# ---------------------------------------------------------------------------


class TestXFrameOptions:
    """X-Frame-Options must be SAMEORIGIN so the iframe can embed ttyd."""

    def test_root_page_has_sameorigin(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/")
        assert resp.status_code == 200
        assert resp.headers["x-frame-options"] == "SAMEORIGIN"

    def test_session_page_has_sameorigin(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/session")
        assert resp.status_code == 200
        assert resp.headers["x-frame-options"] == "SAMEORIGIN"

    def test_x_content_type_options_preserved(self, proxy_client: TestClient) -> None:
        resp = proxy_client.get("/")
        assert resp.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# HTTP proxy route tests
# ---------------------------------------------------------------------------


class TestTerminalProxyHTTP:
    """GET /terminal/{path} should be proxied to the upstream ttyd server."""

    def test_get_terminal_root_proxied(self, proxy_client: TestClient) -> None:
        """GET /terminal/ should proxy to the fake upstream and return its content."""
        resp = proxy_client.get("/terminal/")
        assert resp.status_code == 200
        assert b"xterm" in resp.content or b"ttyd" in resp.content

    def test_get_terminal_path_proxied(self, proxy_client: TestClient) -> None:
        """GET /terminal/index.html should proxy to upstream."""
        resp = proxy_client.get("/terminal/index.html")
        assert resp.status_code == 200

    def test_no_upstream_returns_502(self) -> None:
        """If ttyd is not running, the proxy should return 502."""
        # Claim an ephemeral port then immediately close it, guaranteeing the
        # port is closed for the duration of the test. Hardcoding a "probably
        # unused" port (e.g. 1) is flaky: any stray process bound to it makes
        # the proxy connect successfully and forward a 200 instead of 502.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            closed_port = probe.getsockname()[1]
        # `probe` is closed here — nothing is listening on closed_port.
        app = create_app(ttyd_port=closed_port)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/terminal/")
        assert resp.status_code == 502

    def test_real_upstream_receives_no_browser_authority_headers(self, fake_ttyd_port: int) -> None:
        """Forwarding auth, cookies, or CSRF data to loopback ttyd must fail this test."""
        from studyloop.learner_credentials import hash_password

        password = "terminal-boundary-password"  # pragma: allowlist secret
        app = create_app(
            ttyd_port=fake_ttyd_port,
            password_verifier=hash_password(password),
        )
        client = TestClient(app)
        token = __import__("base64").b64encode(f"study:{password}".encode()).decode()
        try:
            response = client.get(
                "/terminal/",
                headers={
                    "Authorization": f"Basic {token}",
                    "Cookie": "studyloop_learner=browser-session; studyloop_csrf=csrf-cookie",
                    "X-CSRF-Token": "csrf-header",
                    "X-XSRF-Token": "xsrf-header",
                },
            )
        finally:
            client.close()

        received = {
            key.casefold(): value for key, value in _TtydHTTPHandler.received_headers.items()
        }
        assert response.status_code == 200
        assert "authorization" not in received
        assert "cookie" not in received
        assert "x-csrf-token" not in received
        assert "x-xsrf-token" not in received
        assert "set-cookie" not in {key.casefold() for key in response.headers}
        assert "authorization" not in {key.casefold() for key in response.headers}
        assert "x-csrf-token" not in {key.casefold() for key in response.headers}


class TestTerminalProxyWebSocket:
    def test_real_upstream_receives_no_browser_authority_headers(self) -> None:
        """Forwarding browser Basic Auth to loopback ttyd WS must fail this test."""
        from websockets.sync.server import ServerConnection, serve
        from websockets.typing import Subprotocol

        from studyloop.learner_credentials import hash_password

        received: Queue[dict[str, str]] = Queue()

        def handler(connection: ServerConnection) -> None:
            request = connection.request
            assert request is not None
            received.put(dict(request.headers.raw_items()))
            try:
                message = connection.recv(timeout=2)
                connection.send(message)
            except Exception:
                pass

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with serve(handler, sock=listener, subprotocols=[Subprotocol("tty")]) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()

                password = "websocket-boundary-password"  # pragma: allowlist secret
                app = create_app(
                    ttyd_port=port,
                    password_verifier=hash_password(password),
                )
                token = __import__("base64").b64encode(f"study:{password}".encode()).decode()
                client = TestClient(app)
                try:
                    with client.websocket_connect(
                        "/terminal/ws",
                        headers={
                            "Authorization": f"Basic {token}",
                            "Cookie": (
                                "studyloop_learner=browser-session; studyloop_csrf=csrf-cookie"
                            ),
                            "X-CSRF-Token": "csrf-header",
                            "Host": "127.0.0.1:8567",
                            "Origin": "http://127.0.0.1:8567",
                            "Sec-WebSocket-Protocol": "tty",
                        },
                    ) as websocket:
                        websocket.send_text("boundary-check")
                        assert websocket.receive_text() == "boundary-check"
                finally:
                    client.close()
                    server.shutdown()
                    thread.join(timeout=2)

        upstream = {key.casefold(): value for key, value in received.get(timeout=2).items()}
        assert "authorization" not in upstream
        assert "cookie" not in upstream
        assert "x-csrf-token" not in upstream


# ---------------------------------------------------------------------------
# session.html static tests — verify the HTML uses /terminal/ paths
# ---------------------------------------------------------------------------


STATIC_DIR = Path(__file__).parent.parent / "src" / "studyloop" / "web" / "static"


class TestTerminalPaths:
    """Terminal panel should use same-origin /terminal/ paths."""

    def test_iframe_src_uses_proxy_path(self) -> None:
        """index.html must NOT contain a hard-coded port URL for ttyd."""
        html = (STATIC_DIR / "index.html").read_text()
        assert "http://${window.location.hostname}" not in html

    def test_ttyd_url_uses_terminal_path(self) -> None:
        """ttydUrl must return the same-origin /terminal/ path."""
        # terminalPanel owns the ttydUrl getter and moved out of index.html's
        # inline script into its own ES module, so this reads the module.
        js = (STATIC_DIR / "js" / "components" / "terminal-panel.js").read_text()
        assert "/terminal/" in js

    def test_popout_uses_terminal_path(self) -> None:
        """popOut() must open /terminal/ (same-origin) not a cross-origin URL."""
        # terminalPanel moved out of index.html's inline script into its own ES
        # module. The requirement is unchanged - this test just has to look where
        # the code now lives, rather than asserting the source text is embedded in
        # the served HTML, which was only ever true because of the monolith.
        js = (STATIC_DIR / "js" / "components" / "terminal-panel.js").read_text()
        assert "popOut" in js
        import re

        popout_match = re.search(r"popOut\(\).*?\}", js, re.DOTALL)
        assert popout_match, "popOut() function not found"
        popout_body = popout_match.group(0)
        assert "http://" not in popout_body


# ---------------------------------------------------------------------------
# create_app interface test — ttyd_port parameter
# ---------------------------------------------------------------------------


class TestCreateAppInterface:
    """create_app() must accept a ttyd_port parameter."""

    def test_create_app_accepts_ttyd_port(self) -> None:
        """create_app(ttyd_port=...) should not raise."""
        app = create_app(ttyd_port=9999)
        assert app is not None

    def test_create_app_ttyd_port_stored_on_state(self) -> None:
        """The ttyd_port should be accessible on app.state."""
        app = create_app(ttyd_port=7777)
        assert app.state.ttyd_port == 7777

    def test_create_app_default_ttyd_port(self) -> None:
        """Default ttyd_port should be 7681."""
        app = create_app()
        assert app.state.ttyd_port == 7681
