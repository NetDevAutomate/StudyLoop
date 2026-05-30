"""Tests for the secrets REST API surface.

Verifies:
- POST with bad key returns structured 4xx (not 500)
- Raw key values NEVER appear in any response body
- DELETE removes the stored entry
- GET returns configured/missing split (names only)
- Bedrock is rejected with 422
- Unknown provider returns 422
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app  # noqa: E402

if TYPE_CHECKING:
    from pytest import MonkeyPatch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Isolate the secrets store for every test."""
    config_file = tmp_path / "studyloop" / "config.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_file))
    return tmp_path / "studyloop"


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/content/secrets
# ---------------------------------------------------------------------------


class TestGetSecrets:
    def test_empty_store_all_missing(self, client: TestClient, monkeypatch: MonkeyPatch) -> None:
        """When no keys are configured, all providers appear in missing_for_providers."""
        # Ensure env vars don't bleed in
        for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                    "GEMINI_API_KEY", "MINIMAX_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        resp = client.get("/api/content/secrets")
        assert resp.status_code == 200
        data = resp.json()
        assert "configured" in data
        assert "missing_for_providers" in data
        assert data["configured"] == []
        assert len(data["missing_for_providers"]) > 0

    def test_configured_provider_appears(self, client: TestClient, monkeypatch: MonkeyPatch) -> None:
        """A stored key moves the provider from missing to configured."""
        from studyloop.secrets import set_secret

        # Clear env vars to avoid noise
        for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                    "GEMINI_API_KEY", "MINIMAX_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        set_secret("openai", "sk-test-key")

        resp = client.get("/api/content/secrets")
        assert resp.status_code == 200
        data = resp.json()
        assert "openai" in data["configured"]
        assert "openai" not in data["missing_for_providers"]

    def test_values_never_in_response(self, client: TestClient) -> None:
        """Raw key values must not appear anywhere in the GET response."""
        from studyloop.secrets import set_secret

        set_secret("openai", "sk-super-secret-key-value-12345")

        resp = client.get("/api/content/secrets")
        assert "sk-super-secret-key-value-12345" not in resp.text


# ---------------------------------------------------------------------------
# POST /api/content/secrets
# ---------------------------------------------------------------------------


class TestPostSecrets:
    def test_valid_key_stored_on_success(self, client: TestClient) -> None:
        """POST with auth-test success stores the key and returns ok=true."""
        # Patch at the source module — content_gen imports these lazily inside
        # the handler so module-level patching of content_gen won't work.
        with patch("studyloop.secrets.test_provider_auth") as mock_test:
            mock_test.return_value = (True, "Auth successful")
            with patch("studyloop.secrets.set_secret") as mock_set:
                resp = client.post(
                    "/api/content/secrets",
                    json={"provider": "openai", "key": "sk-valid-key"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        mock_set.assert_called_once_with("openai", "sk-valid-key")

    def test_bad_key_returns_400_not_500(self, client: TestClient) -> None:
        """POST with auth-test failure returns 400, not 500."""
        with patch("studyloop.secrets.test_provider_auth") as mock_test:
            mock_test.return_value = (False, "Invalid API key (HTTP 401)")
            resp = client.post(
                "/api/content/secrets",
                json={"provider": "openai", "key": "sk-bad-key"},
            )

        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data
        assert "401" in data["detail"] or "invalid" in data["detail"].lower()

    def test_bad_key_not_stored(self, client: TestClient) -> None:
        """When auth test fails, the key must NOT be persisted."""
        with patch("studyloop.secrets.test_provider_auth") as mock_test:
            mock_test.return_value = (False, "Invalid")
            with patch("studyloop.secrets.set_secret") as mock_set:
                resp = client.post(
                    "/api/content/secrets",
                    json={"provider": "openai", "key": "sk-should-not-persist"},
                )

        assert resp.status_code == 400
        mock_set.assert_not_called()

    def test_key_never_in_success_response(self, client: TestClient) -> None:
        """Raw key value must not appear in the POST success response."""
        secret_value = "sk-this-must-not-appear-in-response"
        with patch("studyloop.secrets.test_provider_auth") as mock_test:
            mock_test.return_value = (True, "Auth successful")
            with patch("studyloop.secrets.set_secret"):
                resp = client.post(
                    "/api/content/secrets",
                    json={"provider": "openai", "key": secret_value},
                )

        assert secret_value not in resp.text

    def test_key_never_in_failure_response(self, client: TestClient) -> None:
        """Raw key value must not appear in the POST failure response."""
        secret_value = "sk-this-must-not-appear-in-error"
        with patch("studyloop.secrets.test_provider_auth") as mock_test:
            mock_test.return_value = (False, "Invalid API key")
            resp = client.post(
                "/api/content/secrets",
                json={"provider": "openai", "key": secret_value},
            )

        assert secret_value not in resp.text

    def test_bedrock_returns_422(self, client: TestClient) -> None:
        """Bedrock uses SDK auth — sending a key should return 422."""
        resp = client.post(
            "/api/content/secrets",
            json={"provider": "bedrock", "key": "any-key"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert "bedrock" in data["detail"].lower() or "aws" in data["detail"].lower()

    def test_unknown_provider_returns_422(self, client: TestClient) -> None:
        """Unknown provider name returns 422."""
        resp = client.post(
            "/api/content/secrets",
            json={"provider": "unknown-provider", "key": "any-key"},
        )
        assert resp.status_code == 422

    def test_missing_key_field_returns_422(self, client: TestClient) -> None:
        """Pydantic validation: missing key field returns 422."""
        resp = client.post("/api/content/secrets", json={"provider": "openai"})
        assert resp.status_code == 422

    def test_missing_provider_field_returns_422(self, client: TestClient) -> None:
        """Pydantic validation: missing provider field returns 422."""
        resp = client.post("/api/content/secrets", json={"key": "sk-test"})
        assert resp.status_code == 422

    def test_empty_key_returns_422(self, client: TestClient) -> None:
        """Pydantic validation: empty key string returns 422."""
        resp = client.post("/api/content/secrets", json={"provider": "openai", "key": ""})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/content/secrets/{provider}
# ---------------------------------------------------------------------------


class TestDeleteSecrets:
    def test_delete_removes_key(self, client: TestClient, monkeypatch: MonkeyPatch) -> None:
        """DELETE removes the stored key; subsequent GET shows it as missing."""
        for var in ("OPENAI_API_KEY",):
            monkeypatch.delenv(var, raising=False)

        from studyloop.secrets import set_secret

        set_secret("openai", "sk-to-delete")

        resp = client.delete("/api/content/secrets/openai")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Confirm it's gone from the status endpoint
        status = client.get("/api/content/secrets")
        data = status.json()
        assert "openai" not in data["configured"]

    def test_delete_nonexistent_returns_ok(self, client: TestClient) -> None:
        """DELETE on a non-configured provider returns ok=true (idempotent)."""
        resp = client.delete("/api/content/secrets/anthropic")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_unknown_provider_returns_422(self, client: TestClient) -> None:
        """DELETE on a completely unknown provider name returns 422."""
        resp = client.delete("/api/content/secrets/noexist")
        assert resp.status_code == 422

    def test_delete_bedrock_returns_422(self, client: TestClient) -> None:
        """DELETE on bedrock returns 422 (bedrock is not a key-based provider)."""
        resp = client.delete("/api/content/secrets/bedrock")
        assert resp.status_code == 422

    def test_delete_response_has_no_key_values(self, client: TestClient) -> None:
        """DELETE response body never contains key values."""
        from studyloop.secrets import set_secret

        set_secret("gemini", "AIzaVerySecretKey12345")
        resp = client.delete("/api/content/secrets/gemini")
        assert "AIzaVerySecretKey12345" not in resp.text
