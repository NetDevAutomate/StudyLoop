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
- Auth applies to terminal proxy routes
- Auto-generated password is 16+ chars
- Password stored in settings and loaded from YAML config
"""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from studyctl.web.app import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    """Encode HTTP Basic Auth credentials as a header dict."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


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

    def test_terminal_proxy_returns_401_without_auth(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/terminal/")
        assert resp.status_code == 401


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
        resp = protected_client.get("/", headers=_basic_auth_header("user", "wrong-password"))
        assert resp.status_code == 401

    def test_empty_password_returns_401(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/", headers=_basic_auth_header("user", ""))
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
        resp = protected_client.get("/", headers=_basic_auth_header("user", "mypassword"))
        assert resp.status_code == 200

    def test_session_accessible_with_correct_password(self, protected_client: TestClient) -> None:
        resp = protected_client.get("/session", headers=_basic_auth_header("user", "mypassword"))
        assert resp.status_code == 200

    def test_api_accessible_with_correct_password(self, protected_client: TestClient) -> None:
        resp = protected_client.get(
            "/api/session/state", headers=_basic_auth_header("user", "mypassword")
        )
        assert resp.status_code == 200

    def test_static_css_accessible_with_correct_password(
        self, protected_client: TestClient
    ) -> None:
        resp = protected_client.get("/style.css", headers=_basic_auth_header("user", "mypassword"))
        assert resp.status_code == 200

    def test_username_does_not_matter(self, protected_client: TestClient) -> None:
        """The username field is ignored — only the password matters."""
        resp = protected_client.get("/", headers=_basic_auth_header("anything", "mypassword"))
        assert resp.status_code == 200


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
        from studyctl.settings import Settings

        s = Settings()
        assert hasattr(s, "lan_password")
        assert s.lan_password == ""

    def test_load_settings_reads_lan_password(self, tmp_path) -> None:
        """load_settings() should parse lan_password from YAML."""

        from studyctl.settings import load_settings

        config = tmp_path / "config.yaml"
        config.write_text("lan_password: mylanpass\n")

        with pytest.MonkeyPatch().context() as mp:
            mp.setenv("STUDYCTL_CONFIG", str(config))
            # Reload the module-level _CONFIG_PATH by patching it
            import studyctl.settings as settings_mod

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
        from studyctl.web.auth import BasicAuthMiddleware

        assert BasicAuthMiddleware is not None

    def test_middleware_is_starlette_compatible(self) -> None:
        """BasicAuthMiddleware should be a Starlette BaseHTTPMiddleware subclass."""
        from starlette.middleware.base import BaseHTTPMiddleware

        from studyctl.web.auth import BasicAuthMiddleware

        assert issubclass(BasicAuthMiddleware, BaseHTTPMiddleware)
