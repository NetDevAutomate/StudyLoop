"""Tests for LAN password protection (Task 2).

When --lan is used, the web server must be protected with HTTP Basic Auth.
If no password is provided, one is auto-generated and displayed.

Tests:
- No auth middleware when no password set
- 401 returned when password set but no credentials sent
- 401 returned when wrong password sent
- 200 returned when correct password sent
- Auth applies to API routes
- Auth applies to static files
- Auto-generated password is 16+ chars
- Password stored in settings and loaded from YAML config
"""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("fastapi")

from _helpers import run_async
from _stub_transport import StubTransport
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]
from starlette.websockets import WebSocketDisconnect

from studyloop.session import active
from studyloop.session.transport import SessionConfig, Started
from studyloop.web.app import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    """Encode HTTP Basic Auth credentials as a header dict."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _session_config(tmp_path) -> SessionConfig:
    return SessionConfig(
        study_session_id="study-1",
        agent="claude",
        persona_file=str(tmp_path / "persona.md"),
        cwd=str(tmp_path),
        env={},
        cols=80,
        rows=24,
    )


@pytest.fixture(autouse=True)
def _reset_active_session():
    run_async(active.release())
    yield
    run_async(active.release())


# ---------------------------------------------------------------------------
# WebSocket origin helper
# ---------------------------------------------------------------------------


class TestWebSocketOriginHelper:
    def test_allows_origin_matching_request_host(self) -> None:
        from studyloop.web.ws_origin import origin_allowed

        assert origin_allowed(
            origin="http://192.168.1.20:8567",
            host="192.168.1.20:8567",
        )

    def test_rejects_cross_origin_lan_request(self) -> None:
        from studyloop.web.ws_origin import origin_allowed

        assert not origin_allowed(
            origin="https://evil.example.com",
            host="192.168.1.20:8567",
        )


# ---------------------------------------------------------------------------
# No password → no auth
# ---------------------------------------------------------------------------


class TestNoPasswordNoAuth:
    """When no password is configured, all routes are accessible without auth."""

    def test_root_accessible_without_auth(self) -> None:
        app = create_app(password="")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200

    def test_session_accessible_without_auth(self) -> None:
        app = create_app(password="")
        client = TestClient(app)
        resp = client.get("/session")
        assert resp.status_code == 200

    def test_api_accessible_without_auth(self) -> None:
        app = create_app(password="")
        client = TestClient(app)
        resp = client.get("/api/session/state")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Password set → 401 without credentials
# ---------------------------------------------------------------------------


class TestPasswordProtection:
    """When a password is set, unauthenticated requests get 401."""

    @pytest.fixture()
    def protected_client(self) -> TestClient:
        app = create_app(password="s3cr3t")
        return TestClient(app, raise_server_exceptions=False)

    def test_root_returns_401_without_auth(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/")
        assert resp.status_code == 401

    def test_401_has_www_authenticate_header(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/")
        assert "www-authenticate" in resp.headers
        assert resp.headers["www-authenticate"].startswith("Basic")

    def test_session_page_returns_401_without_auth(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/session")
        assert resp.status_code == 401

    def test_api_returns_401_without_auth(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/api/session/state")
        assert resp.status_code == 401

    def test_static_css_returns_401_without_auth(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/style.css")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Password set -> WebSocket scopes are protected too
# ---------------------------------------------------------------------------


class TestWebSocketPasswordProtection:
    """The LAN password middleware must run for WebSocket scopes, not just HTTP."""

    @pytest.fixture()
    def protected_client(self) -> TestClient:
        app = create_app(password="s3cr3t")
        return TestClient(app, raise_server_exceptions=False)

    @pytest.mark.parametrize(
        "path",
        [
            "/api/session/ws?study_session_id=study-1",
            "/api/content/generate/ws?job_id=gen-x",
        ],
    )
    def test_websocket_without_auth_closes_1008(
        self, protected_client: TestClient, path: str
    ) -> None:
        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            protected_client.websocket_connect(
                path,
                headers={
                    "Host": "192.168.1.42:8567",
                    "Origin": "http://192.168.1.42:8567",
                },
            ) as ws,
        ):
            ws.receive_json()
        assert exc_info.value.code == 1008

    def test_websocket_with_valid_auth_and_lan_origin_reaches_session_route(
        self, tmp_path, protected_client: TestClient
    ) -> None:
        config = _session_config(tmp_path)
        stub = StubTransport(events=[Started(agent="claude")])
        run_async(active.acquire(config, lambda: stub))

        headers = {
            **_basic_auth_header("study", "s3cr3t"),
            "Host": "192.168.1.42:8567",
            "Origin": "http://192.168.1.42:8567",
        }
        with protected_client.websocket_connect(
            "/api/session/ws?study_session_id=study-1",
            headers=headers,
        ) as ws:
            assert ws.receive_json() == {"type": "started", "agent": "claude"}


# ---------------------------------------------------------------------------
# Wrong password → 401
# ---------------------------------------------------------------------------


class TestWrongPassword:
    """Wrong credentials still get 401."""

    @pytest.fixture()
    def protected_client(self) -> TestClient:
        app = create_app(password="correct-password")
        return TestClient(app, raise_server_exceptions=False)

    def test_wrong_password_returns_401(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/", headers=_basic_auth_header("study", "wrong-password"))
        assert resp.status_code == 401

    def test_empty_password_returns_401(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/", headers=_basic_auth_header("study", ""))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Correct password → 200
# ---------------------------------------------------------------------------


class TestCorrectPassword:
    """Correct credentials grant access."""

    @pytest.fixture()
    def protected_client(self) -> TestClient:
        app = create_app(password="mypassword")
        return TestClient(app, raise_server_exceptions=False)

    def test_root_accessible_with_correct_password(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/", headers=_basic_auth_header("study", "mypassword"))
        assert resp.status_code == 200

    def test_session_accessible_with_correct_password(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/session", headers=_basic_auth_header("study", "mypassword"))
        assert resp.status_code == 200

    def test_api_accessible_with_correct_password(self, protected_client: TestClient) -> None:
        resp = protected_client.get(
            "/api/session/state", headers=_basic_auth_header("study", "mypassword")
        )
        assert resp.status_code == 200

    def test_static_css_accessible_with_correct_password(
        self, protected_client: TestClient
    ) -> None:
        resp = protected_client.get("/style.css", headers=_basic_auth_header("study", "mypassword"))
        assert resp.status_code == 200

    def test_wrong_username_returns_401(self, protected_client: TestClient) -> None:
        """Wrong username is rejected even with correct password."""
        resp = protected_client.get("/", headers=_basic_auth_header("wrong-user", "mypassword"))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Auto-generated password strength
# ---------------------------------------------------------------------------


class TestAutoGeneratedPassword:
    """The auto-generated password must be sufficiently strong."""

    def test_generated_password_is_16_or_more_chars(self) -> None:
        import secrets

        pwd = secrets.token_urlsafe(16)
        assert len(pwd) >= 16

    def test_generated_password_is_unique(self) -> None:
        import secrets

        pwd1 = secrets.token_urlsafe(16)
        pwd2 = secrets.token_urlsafe(16)
        assert pwd1 != pwd2


# ---------------------------------------------------------------------------
# Settings: lan_password field
# ---------------------------------------------------------------------------


class TestSettingsLanPassword:
    """Settings dataclass must have a lan_password field."""

    def test_settings_has_lan_password_field(self) -> None:
        from studyloop.settings import Settings

        s = Settings()
        assert hasattr(s, "lan_password")
        assert s.lan_password == ""

    def test_load_settings_reads_lan_password(self, tmp_path) -> None:
        """load_settings() should parse lan_password from YAML."""

        from studyloop.settings import load_settings

        config = tmp_path / "config.yaml"
        config.write_text("lan_password: mylanpass\n")

        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("STUDYLOOP_CONFIG", str(config))
            # Reload the module-level _CONFIG_PATH by patching it
            import studyloop.settings as settings_mod

            original = settings_mod._CONFIG_PATH
            settings_mod._CONFIG_PATH = config
            try:
                s = load_settings()
                assert s.lan_password == "mylanpass"  # pragma: allowlist secret
            finally:
                settings_mod._CONFIG_PATH = original


# ---------------------------------------------------------------------------
# BasicAuthMiddleware import
# ---------------------------------------------------------------------------


class TestBasicAuthMiddlewareExists:
    """The BasicAuthMiddleware must be importable from web.auth."""

    def test_import_basic_auth_middleware(self) -> None:
        from studyloop.web.auth import BasicAuthMiddleware

        assert BasicAuthMiddleware is not None

    def test_middleware_is_asgi_compatible(self) -> None:
        """BasicAuthMiddleware should be callable ASGI middleware."""
        from studyloop.web.auth import BasicAuthMiddleware

        assert callable(BasicAuthMiddleware)


# ---------------------------------------------------------------------------
# The practice_check hop is not a browser and holds no password
# ---------------------------------------------------------------------------


def test_the_practice_check_hop_is_not_asked_for_the_basic_password() -> None:
    """``studyloop drill`` posts with the owner-only capability only (hop.py never sends
    ``Authorization``); a password-gated server must let that reach the route, which
    then judges loopback + token itself. Before the fix every ``--bind``/``--lan``
    session answered 401 and the mentor was never told.
    """
    from fastapi.testclient import TestClient

    from studyloop.modules import hop
    from studyloop.web.app import create_app

    app = create_app(study_dirs=[], username="study", password="pw", server_secret="s" * 40)
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = {hop.TOKEN_HEADER: "x" * 43, "Host": "127.0.0.1:8567"}

    response = client.post(hop.ROUTE, json={}, headers=headers)

    assert response.status_code != 401 or "www-authenticate" not in response.headers, (
        "Basic auth answered before the hop route could"
    )
    # Positive control: the same request WITHOUT the hop header is still gated.
    plain = client.post(hop.ROUTE, json={}, headers={"Host": "127.0.0.1:8567"})
    assert plain.status_code == 401 and plain.headers.get("www-authenticate", "").startswith(
        "Basic"
    )
    # And any other path still is, hop header or not (the exemption is the one route).
    other = client.get("/", headers=headers)
    assert other.status_code == 401 and other.headers.get("www-authenticate", "").startswith(
        "Basic"
    )


def test_only_a_post_hop_with_the_header_bypasses_basic() -> None:
    """The exemption is one request shape: POST to the hop route carrying the capability
    header. Any other method on that path keeps the Basic challenge, header or not; the
    route has only a POST handler, so without this a GET with the header reached the
    router's 404 instead of the password gate (council pass 4, gpt-6-astra).
    """
    from fastapi.testclient import TestClient

    from studyloop.modules import hop
    from studyloop.web.app import create_app

    app = create_app(study_dirs=[], username="study", password="pw", server_secret="s" * 40)
    client = TestClient(app, client=("127.0.0.1", 50000))
    headers = {hop.TOKEN_HEADER: "x" * 43, "Host": "127.0.0.1:8567"}

    for method in ("GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"):
        response = client.request(method, hop.ROUTE, headers=headers)
        assert response.status_code == 401, f"{method} with the hop header bypassed Basic auth"
        assert response.headers.get("www-authenticate", "").startswith("Basic"), method
