"""Unit tests for studyloop.secrets — encrypted API key store.

Coverage:
- Round-trip set/get/delete
- Resolution order: encrypted store wins over env var
- Resolution order: env var used when store absent
- File permissions (0600 for secrets.bin and seed file)
- Corrupted secrets file fails clean (does not raise unhandled exceptions)
- list_secret_names never returns values
- Bedrock skips provider auth test
- test_provider_auth: per-provider HTTP mocking (success + failure)
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pytest import MonkeyPatch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Point STUDYLOOP_CONFIG at a fresh tmp directory for every test.

    The secrets module derives its paths from STUDYLOOP_CONFIG, so this
    ensures tests never touch the real ~/.config/studyloop/.
    """
    config_file = tmp_path / "studyloop" / "config.yaml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("")
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_file))

    # Force reimport of the module's cached path helpers on each test.
    # (The module-level functions call _config_dir() lazily so env-var
    # overrides take effect without needing to reload the module.)
    return tmp_path / "studyloop"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_dir(tmp_path: Path) -> Path:
    """Return the config dir under tmp_path for assertions."""
    return tmp_path / "studyloop"


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_set_then_get(self) -> None:
        from studyloop.secrets import get_secret, set_secret

        set_secret("openai", "sk-test-1234")
        assert get_secret("openai") == "sk-test-1234"

    def test_set_overwrite(self) -> None:
        from studyloop.secrets import get_secret, set_secret

        set_secret("openai", "sk-first")
        set_secret("openai", "sk-second")
        assert get_secret("openai") == "sk-second"

    def test_delete_removes_secret(self) -> None:
        from studyloop.secrets import delete_secret, get_secret, set_secret

        set_secret("openai", "sk-delete-me")
        assert get_secret("openai") is not None
        delete_secret("openai")
        # After delete, falls through to env var (which is not set here)
        assert get_secret("openai") is None

    def test_delete_nonexistent_is_noop(self) -> None:
        from studyloop.secrets import delete_secret

        # Should not raise
        delete_secret("openai")

    def test_multiple_providers(self) -> None:
        from studyloop.secrets import get_secret, list_secret_names, set_secret

        set_secret("openai", "sk-openai-key")
        set_secret("anthropic", "sk-ant-key")
        names = list_secret_names()
        assert "openai" in names
        assert "anthropic" in names

    def test_list_never_returns_values(self) -> None:
        from studyloop.secrets import list_secret_names, set_secret

        set_secret("openai", "sk-secret-value")
        names = list_secret_names()
        # Names are strings; the actual key value must not appear
        assert all(len(n) < 30 for n in names), "list_secret_names returned values, not names"
        assert "sk-secret-value" not in names


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------


class TestResolutionOrder:
    def test_encrypted_store_wins_over_env_var(self, monkeypatch: MonkeyPatch) -> None:
        """Encrypted store takes precedence over OS environment variable."""
        from studyloop.secrets import get_secret, set_secret

        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        set_secret("openai", "encrypted-key")
        result = get_secret("openai")
        assert result == "encrypted-key"

    def test_env_var_used_when_store_absent(self, monkeypatch: MonkeyPatch) -> None:
        """Environment variable is used when the provider is not in the encrypted store."""
        from studyloop.secrets import get_secret

        monkeypatch.setenv("OPENAI_API_KEY", "env-key-only")
        result = get_secret("openai")
        assert result == "env-key-only"

    def test_returns_none_when_neither_set(self, monkeypatch: MonkeyPatch) -> None:
        """Returns None when neither the store nor env var is set."""
        from studyloop.secrets import get_secret

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = get_secret("openai")
        assert result is None

    def test_env_var_for_each_provider(self, monkeypatch: MonkeyPatch) -> None:
        """Each provider maps to the correct env variable."""
        from studyloop.secrets import get_secret

        env_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "minimax": "MINIMAX_API_KEY",
        }
        for provider, env_var in env_map.items():
            monkeypatch.setenv(env_var, f"test-key-{provider}")

        for provider, env_var in env_map.items():
            assert get_secret(provider) == f"test-key-{provider}"


# ---------------------------------------------------------------------------
# File permissions
# ---------------------------------------------------------------------------


class TestFilePermissions:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_secrets_file_is_0600(self, tmp_path: Path) -> None:
        from studyloop.secrets import set_secret

        set_secret("openai", "sk-perm-test")

        secrets_path = tmp_path / "studyloop" / "secrets.bin"
        assert secrets_path.exists(), f"secrets.bin not created at {secrets_path}"
        mode = stat.S_IMODE(secrets_path.stat().st_mode)
        assert mode == 0o600, f"secrets.bin has mode {oct(mode)}, expected 0o600"

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_seed_file_is_0600(self, tmp_path: Path) -> None:
        from studyloop.secrets import set_secret

        set_secret("openai", "sk-perm-test")

        seed_path = tmp_path / "studyloop" / ".secrets-key"
        assert seed_path.exists(), f".secrets-key not created at {seed_path}"
        mode = stat.S_IMODE(seed_path.stat().st_mode)
        assert mode == 0o600, f".secrets-key has mode {oct(mode)}, expected 0o600"

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions only")
    def test_config_dir_is_0700(self, tmp_path: Path) -> None:
        from studyloop.secrets import set_secret

        set_secret("openai", "sk-perm-test")

        config_dir = tmp_path / "studyloop"
        mode = stat.S_IMODE(config_dir.stat().st_mode)
        assert mode == 0o700, f"config dir has mode {oct(mode)}, expected 0o700"


# ---------------------------------------------------------------------------
# Corrupt store
# ---------------------------------------------------------------------------


class TestCorruptStore:
    def test_corrupted_file_does_not_raise_on_get(self, tmp_path: Path) -> None:
        """get_secret falls through to env var gracefully on corrupt store."""
        from studyloop.secrets import get_secret

        # Write garbage to secrets.bin
        secrets_path = tmp_path / "studyloop" / "secrets.bin"
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        secrets_path.write_bytes(b"this is not a valid fernet token")

        # Should not raise — falls through to env var (returns None here)
        result = get_secret("openai")
        assert result is None

    def test_corrupted_file_does_not_raise_on_list(self, tmp_path: Path) -> None:
        """list_secret_names returns [] gracefully on corrupt store."""
        from studyloop.secrets import list_secret_names

        secrets_path = tmp_path / "studyloop" / "secrets.bin"
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        secrets_path.write_bytes(b"garbage")

        result = list_secret_names()
        assert result == []

    def test_corrupted_file_overwritten_on_set(self, tmp_path: Path) -> None:
        """set_secret on a corrupt store overwrites it rather than raising."""
        from studyloop.secrets import get_secret, set_secret

        secrets_path = tmp_path / "studyloop" / "secrets.bin"
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        secrets_path.write_bytes(b"garbage bytes that are not fernet")

        # Should not raise; should overwrite with a valid store
        set_secret("openai", "sk-after-corrupt")
        assert get_secret("openai") == "sk-after-corrupt"


# ---------------------------------------------------------------------------
# Provider auth tests — HTTP layer mocked
# ---------------------------------------------------------------------------


class TestProviderAuthBedrock:
    def test_bedrock_skipped(self) -> None:
        """Bedrock always returns (True, message) — no HTTP call."""
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("bedrock", "any-key")
        assert ok is True
        assert "AWS" in msg or "bedrock" in msg.lower()


class TestProviderAuthMocked:
    """Per-provider fixtures that monkeypatch the HTTP layer."""

    @pytest.fixture()
    def mock_openai_success(self):  # type: ignore[no-untyped-def]
        """Mock OpenAI /v1/models returning 200."""
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://api.openai.com/v1/models").mock(
                return_value=_httpx.Response(200, json={"object": "list", "data": []})
            )
            yield mock

    @pytest.fixture()
    def mock_openai_failure(self):  # type: ignore[no-untyped-def]
        """Mock OpenAI /v1/models returning 401."""
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://api.openai.com/v1/models").mock(
                return_value=_httpx.Response(401, json={"error": {"message": "Invalid API key"}})
            )
            yield mock

    @pytest.fixture()
    def mock_anthropic_success(self):  # type: ignore[no-untyped-def]
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://api.anthropic.com/v1/models").mock(
                return_value=_httpx.Response(200, json={"data": []})
            )
            yield mock

    @pytest.fixture()
    def mock_anthropic_failure(self):  # type: ignore[no-untyped-def]
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://api.anthropic.com/v1/models").mock(
                return_value=_httpx.Response(401, json={"error": {"type": "authentication_error"}})
            )
            yield mock

    @pytest.fixture()
    def mock_openrouter_success(self):  # type: ignore[no-untyped-def]
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://openrouter.ai/api/v1/models").mock(
                return_value=_httpx.Response(200, json={"data": []})
            )
            yield mock

    @pytest.fixture()
    def mock_gemini_success(self):  # type: ignore[no-untyped-def]
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
                return_value=_httpx.Response(200, json={"models": []})
            )
            yield mock

    @pytest.fixture()
    def mock_gemini_failure(self):  # type: ignore[no-untyped-def]
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
                return_value=_httpx.Response(400, json={"error": {"message": "API key not valid"}})
            )
            yield mock

    @pytest.fixture()
    def mock_minimax_success(self):  # type: ignore[no-untyped-def]
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.post("https://api.minimax.io/v1/text/chatcompletion_v2").mock(
                return_value=_httpx.Response(200, json={"choices": []})
            )
            yield mock

    @pytest.fixture()
    def mock_minimax_failure(self):  # type: ignore[no-untyped-def]
        import respx
        import httpx as _httpx

        with respx.mock(assert_all_called=False) as mock:
            mock.post("https://api.minimax.io/v1/text/chatcompletion_v2").mock(
                return_value=_httpx.Response(401, json={"error": "unauthorized"})
            )
            yield mock

    # --- OpenAI ---
    def test_openai_success(self, mock_openai_success: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("openai", "sk-test")
        assert ok is True
        assert "openai" in msg.lower()

    def test_openai_failure(self, mock_openai_failure: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("openai", "sk-bad")
        assert ok is False
        assert "401" in msg or "invalid" in msg.lower() or "key" in msg.lower()

    # --- Anthropic ---
    def test_anthropic_success(self, mock_anthropic_success: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("anthropic", "sk-ant-test")
        assert ok is True

    def test_anthropic_failure(self, mock_anthropic_failure: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("anthropic", "sk-ant-bad")
        assert ok is False

    # --- OpenRouter ---
    def test_openrouter_success(self, mock_openrouter_success: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("openrouter", "sk-or-test")
        assert ok is True

    # --- Gemini ---
    def test_gemini_success(self, mock_gemini_success: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("gemini", "AIzaTest")
        assert ok is True

    def test_gemini_failure(self, mock_gemini_failure: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("gemini", "AIzaBad")
        assert ok is False

    # --- MiniMax ---
    def test_minimax_success(self, mock_minimax_success: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("minimax", "mm-test-key")
        assert ok is True

    def test_minimax_failure(self, mock_minimax_failure: object) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("minimax", "mm-bad-key")
        assert ok is False

    def test_unknown_provider_returns_false(self) -> None:
        from studyloop.secrets import test_provider_auth

        ok, msg = test_provider_auth("unknown-provider", "any-key")
        assert ok is False
        assert "unknown" in msg.lower() or "unknown-provider" in msg

    def test_network_timeout_returns_false(self) -> None:
        """Network timeout is caught and returns (False, message)."""
        import httpx as _httpx

        from studyloop.secrets import test_provider_auth

        with patch("studyloop.secrets.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.side_effect = _httpx.TimeoutException("timed out")

            ok, msg = test_provider_auth("openai", "sk-timeout-test")
        assert ok is False
        assert "timeout" in msg.lower() or "network" in msg.lower()
