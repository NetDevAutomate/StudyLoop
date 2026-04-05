"""Tests for the LLM client (Ollama + OpenAI-compatible APIs).

All tests use unittest.mock to avoid real HTTP. No conftest.py fixtures —
everything is inline per project convention.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from studyctl.eval.llm_client import LLMClient, LLMClientError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(data: dict, status: int = 200) -> MagicMock:
    """Create a mock urllib response context-manager."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    mock.status = status
    return mock


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://localhost/test",
        code=code,
        msg=f"Error {code}",
        hdrs={},  # type: ignore[arg-type]
        fp=None,
    )


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


class TestOllamaChatSuccess:
    def test_ollama_chat_success(self) -> None:
        """Ollama response shape → returns assistant content string."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        mock_resp = _mock_response({"message": {"content": "test response"}})

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.chat([{"role": "user", "content": "hello"}])

        assert result == "test response"

    def test_openai_chat_success(self) -> None:
        """OpenAI-compat response shape → returns assistant content string."""
        client = LLMClient(
            base_url="http://api.example.com",
            model="gpt-4o-mini",
            provider="openai-compat",
        )
        mock_resp = _mock_response({"choices": [{"message": {"content": "test"}}]})

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = client.chat([{"role": "user", "content": "hello"}])

        assert result == "test"


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------


class TestPayloadShape:
    def test_ollama_sends_correct_payload(self) -> None:
        """Ollama POST body includes model, messages, stream=False, options.temperature."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        mock_resp = _mock_response({"message": {"content": "ok"}})
        captured: list[bytes] = []

        def capturing_urlopen(req: urllib.request.Request, timeout: int):
            captured.append(req.data)  # type: ignore[arg-type]
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
            client.chat([{"role": "user", "content": "hi"}], temperature=0.3)

        body = json.loads(captured[0])
        assert body["model"] == "gemma3:4b"
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert body["stream"] is False
        assert body["options"]["temperature"] == pytest.approx(0.3)

    def test_openai_sends_correct_payload(self) -> None:
        """OpenAI POST body includes model, messages, temperature (no stream key)."""
        client = LLMClient(
            base_url="http://api.example.com",
            model="gpt-4o-mini",
            provider="openai-compat",
        )
        mock_resp = _mock_response({"choices": [{"message": {"content": "ok"}}]})
        captured: list[bytes] = []

        def capturing_urlopen(req: urllib.request.Request, timeout: int):
            captured.append(req.data)  # type: ignore[arg-type]
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
            client.chat([{"role": "user", "content": "hi"}], temperature=0.5)

        body = json.loads(captured[0])
        assert body["model"] == "gpt-4o-mini"
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert body["temperature"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


class TestAuthHeader:
    def test_api_key_in_header(self) -> None:
        """openai-compat provider with api_key → Authorization header is set."""
        client = LLMClient(
            base_url="http://api.example.com",
            model="gpt-4o-mini",
            api_key="sk-secret",  # pragma: allowlist secret
            provider="openai-compat",
        )
        mock_resp = _mock_response({"choices": [{"message": {"content": "ok"}}]})
        captured_headers: list[dict] = []

        def capturing_urlopen(req: urllib.request.Request, timeout: int):
            captured_headers.append(dict(req.headers))
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
            client.chat([{"role": "user", "content": "hi"}])

        assert captured_headers[0].get("Authorization") == "Bearer sk-secret"

    def test_no_api_key_no_header(self) -> None:
        """Ollama provider with no api_key → no Authorization header."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        mock_resp = _mock_response({"message": {"content": "ok"}})
        captured_headers: list[dict] = []

        def capturing_urlopen(req: urllib.request.Request, timeout: int):
            captured_headers.append(dict(req.headers))
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=capturing_urlopen):
            client.chat([{"role": "user", "content": "hi"}])

        assert "Authorization" not in captured_headers[0]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_connection_error_raises(self) -> None:
        """URLError (e.g. connection refused) → raises LLMClientError."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("Connection refused"),
            ),
            pytest.raises(LLMClientError, match="Connection error"),
        ):
            client.chat([{"role": "user", "content": "hi"}])

    def test_timeout_raises(self) -> None:
        """TimeoutError → raises LLMClientError."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        with (
            patch("urllib.request.urlopen", side_effect=TimeoutError()),
            pytest.raises(LLMClientError, match="timed out"),
        ):
            client.chat([{"role": "user", "content": "hi"}])

    def test_no_retry_on_400(self) -> None:
        """HTTP 400 → raises LLMClientError immediately, no retry."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        with (
            patch("urllib.request.urlopen", side_effect=_http_error(400)) as mock_open,
            patch("time.sleep") as mock_sleep,
            pytest.raises(LLMClientError, match="HTTP 400"),
        ):
            client.chat([{"role": "user", "content": "hi"}])

        # Called exactly once — no retry
        assert mock_open.call_count == 1
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    def test_retry_on_429(self) -> None:
        """HTTP 429 on first attempt → sleeps 5s → retries → returns result."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        success = _mock_response({"message": {"content": "retried ok"}})

        with (
            patch(
                "urllib.request.urlopen",
                side_effect=[_http_error(429), success],
            ),
            patch("time.sleep") as mock_sleep,
        ):
            result = client.chat([{"role": "user", "content": "hi"}])

        assert result == "retried ok"
        mock_sleep.assert_called_once_with(5)

    def test_retry_on_503(self) -> None:
        """HTTP 503 on first attempt → sleeps 5s → retries → returns result."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        success = _mock_response({"message": {"content": "service restored"}})

        with (
            patch(
                "urllib.request.urlopen",
                side_effect=[_http_error(503), success],
            ),
            patch("time.sleep") as mock_sleep,
        ):
            result = client.chat([{"role": "user", "content": "hi"}])

        assert result == "service restored"
        mock_sleep.assert_called_once_with(5)


# ---------------------------------------------------------------------------
# Malformed responses
# ---------------------------------------------------------------------------


class TestMalformedResponses:
    def test_malformed_ollama_response(self) -> None:
        """Ollama returns {} (missing 'message' key) → raises LLMClientError."""
        client = LLMClient(
            base_url="http://localhost:11434",
            model="gemma3:4b",
            provider="ollama",
        )
        mock_resp = _mock_response({})

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(LLMClientError, match="Unexpected Ollama response"),
        ):
            client.chat([{"role": "user", "content": "hi"}])

    def test_malformed_openai_response(self) -> None:
        """OpenAI returns {'choices': []} (empty list) → raises LLMClientError."""
        client = LLMClient(
            base_url="http://api.example.com",
            model="gpt-4o-mini",
            provider="openai-compat",
        )
        mock_resp = _mock_response({"choices": []})

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(LLMClientError, match="Unexpected OpenAI response"),
        ):
            client.chat([{"role": "user", "content": "hi"}])
