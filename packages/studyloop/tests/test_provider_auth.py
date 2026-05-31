"""Unit tests for studyloop.provider_auth — heavy credential tests.

All boto3 / Ollama interaction is mocked: no real AWS spend, no GPU, no
network. The security-critical assertion is that the Bedrock bearer token
never lingers in ``os.environ`` after the call — even on exception.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pytest import MonkeyPatch

_BEARER_ENV = "AWS_BEARER_TOKEN_BEDROCK"


@pytest.fixture(autouse=True)
def _clear_bearer_env(monkeypatch: MonkeyPatch) -> None:
    """Ensure the bearer env var is unset before each test."""
    monkeypatch.delenv(_BEARER_ENV, raising=False)


# ---------------------------------------------------------------------------
# _with_bearer_env
# ---------------------------------------------------------------------------


class TestWithBearerEnv:
    def test_sets_then_restores_absent(self) -> None:
        from studyloop.provider_auth import _with_bearer_env

        assert _BEARER_ENV not in os.environ
        with _with_bearer_env("tok"):
            assert os.environ[_BEARER_ENV] == "tok"
        assert _BEARER_ENV not in os.environ

    def test_restores_prior_value(self, monkeypatch: MonkeyPatch) -> None:
        from studyloop.provider_auth import _with_bearer_env

        monkeypatch.setenv(_BEARER_ENV, "original")
        with _with_bearer_env("temp"):
            assert os.environ[_BEARER_ENV] == "temp"
        assert os.environ[_BEARER_ENV] == "original"

    def test_restores_on_exception(self) -> None:
        from studyloop.provider_auth import _with_bearer_env

        with pytest.raises(RuntimeError), _with_bearer_env("tok"):
            raise RuntimeError("boom")
        assert _BEARER_ENV not in os.environ


# ---------------------------------------------------------------------------
# test_bedrock_bearer
# ---------------------------------------------------------------------------


class TestBedrockBearer:
    def test_empty_token_fails(self) -> None:
        from studyloop.provider_auth import test_bedrock_bearer

        ok, msg = test_bedrock_bearer("")
        assert ok is False
        assert "no bearer token" in msg.lower()

    def test_valid_token_returns_ok(self) -> None:
        from studyloop import provider_auth

        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {}}
        with patch.object(provider_auth, "_with_bearer_env"), \
                patch("boto3.client", return_value=mock_client):
            ok, _msg = provider_auth.test_bedrock_bearer("tok-valid")
        assert ok is True
        mock_client.converse.assert_called_once()
        # maxTokens=1 — the minimal probe
        _, kwargs = mock_client.converse.call_args
        assert kwargs["inferenceConfig"]["maxTokens"] == 1

    def test_invalid_token_returns_false(self) -> None:
        from botocore.exceptions import ClientError

        from studyloop import provider_auth

        err = ClientError(
            {"Error": {"Code": "UnrecognizedClientException", "Message": "bad"}},
            "Converse",
        )
        mock_client = MagicMock()
        mock_client.converse.side_effect = err
        with patch("boto3.client", return_value=mock_client):
            ok, msg = provider_auth.test_bedrock_bearer("tok-bad")
        assert ok is False
        assert "UnrecognizedClientException" in msg

    def test_non_auth_clienterror_still_ok(self) -> None:
        """A ValidationException proves the token authenticated."""
        from botocore.exceptions import ClientError

        from studyloop import provider_auth

        err = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "tiny req"}},
            "Converse",
        )
        mock_client = MagicMock()
        mock_client.converse.side_effect = err
        with patch("boto3.client", return_value=mock_client):
            ok, _ = provider_auth.test_bedrock_bearer("tok-ok")
        assert ok is True

    def test_token_not_leaked_to_env_on_success(self) -> None:
        from studyloop import provider_auth

        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {}}
        with patch("boto3.client", return_value=mock_client):
            provider_auth.test_bedrock_bearer("tok-secret")
        assert _BEARER_ENV not in os.environ

    def test_token_not_leaked_to_env_on_exception(self) -> None:
        from studyloop import provider_auth

        mock_client = MagicMock()
        mock_client.converse.side_effect = RuntimeError("network blew up")
        with patch("boto3.client", return_value=mock_client):
            ok, _ = provider_auth.test_bedrock_bearer("tok-secret")
        assert ok is False
        assert _BEARER_ENV not in os.environ

    def test_boto3_missing_returns_clean_error(self) -> None:
        import builtins

        from studyloop import provider_auth

        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object):
            if name == "boto3":
                raise ImportError("no boto3")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        with patch("builtins.__import__", side_effect=fake_import):
            ok, msg = provider_auth.test_bedrock_bearer("tok")
        assert ok is False
        assert "boto3" in msg.lower()


# ---------------------------------------------------------------------------
# test_ollama_generate
# ---------------------------------------------------------------------------


class TestOllamaGenerate:
    def _deck(self, n_cards: int):
        from studyloop.content.schemas import FlashcardDeck, FlashcardItem

        cards = [
            FlashcardItem(front=f"Q{i}", back=f"A{i}") for i in range(n_cards)
        ]
        return FlashcardDeck(title="Test", cards=cards) if cards else None

    def test_success_with_valid_deck(self) -> None:
        from studyloop import provider_auth

        mock_gen = MagicMock()
        mock_gen.generate_flashcards.return_value = self._deck(3)
        with patch(
            "studyloop.content.generators.ollama.OllamaGenerator",
            return_value=mock_gen,
        ):
            ok, msg = provider_auth.test_ollama_generate(model="qwen2.5:7b")
        assert ok is True
        assert "3 cards" in msg

    def test_unreachable_returns_false(self) -> None:
        from studyloop import provider_auth
        from studyloop.content.generators import CardGenerationError

        with patch(
            "studyloop.content.generators.ollama.OllamaGenerator",
            side_effect=CardGenerationError("connection refused"),
        ):
            ok, msg = provider_auth.test_ollama_generate(model="qwen2.5:7b")
        assert ok is False
        assert "failed" in msg.lower()

    def test_tries_recommended_models_in_order(self) -> None:
        """Empty model → first recommended fails, second succeeds."""
        from studyloop import provider_auth
        from studyloop.content.generators import CardGenerationError

        attempts: list[str] = []

        def make_gen(config):
            attempts.append(config.ollama.model)
            gen = MagicMock()
            if config.ollama.model == provider_auth.OLLAMA_RECOMMENDED_MODELS[0]:
                gen.generate_flashcards.side_effect = CardGenerationError("not pulled")
            else:
                gen.generate_flashcards.return_value = self._deck(2)
            return gen

        with patch(
            "studyloop.content.generators.ollama.OllamaGenerator",
            side_effect=make_gen,
        ):
            ok, _ = provider_auth.test_ollama_generate()
        assert ok is True
        assert attempts[0] == provider_auth.OLLAMA_RECOMMENDED_MODELS[0]
        assert attempts[1] == provider_auth.OLLAMA_RECOMMENDED_MODELS[1]
