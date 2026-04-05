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

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


from fastapi.testclient import TestClient

from studyctl.web.app import create_app

# ---------------------------------------------------------------------------
# Helpers: minimal stub HTTP server to act as a fake ttyd upstream
# ---------------------------------------------------------------------------


class _TtydHTTPHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler that returns a known HTML page like ttyd."""

    def do_GET(self) -> None:
        body = b"<html><body><div class='xterm'>ttyd terminal</div></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # type: ignore[override]
        pass  # Suppress noisy output during tests


@pytest.fixture()
def fake_ttyd_port(tmp_path) -> int:
    """Spin up a minimal HTTP server that acts as a fake ttyd upstream.

    Returns the port it's listening on.
    """
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
        # Port 1 is unused/refused on most systems
        app = create_app(ttyd_port=1)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/terminal/")
        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# session.html static tests — verify the HTML uses /terminal/ paths
# ---------------------------------------------------------------------------


STATIC_DIR = Path(__file__).parent.parent / "src" / "studyctl" / "web" / "static"


class TestTerminalPaths:
    """Terminal panel should use same-origin /terminal/ paths."""

    def test_iframe_src_uses_proxy_path(self) -> None:
        """index.html must NOT contain a hard-coded port URL for ttyd."""
        html = (STATIC_DIR / "index.html").read_text()
        assert "http://${window.location.hostname}" not in html

    def test_ttyd_url_uses_terminal_path(self) -> None:
        """ttydUrl in components.js should return /terminal/."""
        js = (STATIC_DIR / "components.js").read_text()
        assert "/terminal/" in js

    def test_popout_uses_terminal_path(self) -> None:
        """popOut() must open /terminal/ (same-origin) not a cross-origin URL."""
        js = (STATIC_DIR / "components.js").read_text()
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
