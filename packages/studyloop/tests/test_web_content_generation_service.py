"""Tests for content-generation service helpers."""

from __future__ import annotations

from studyloop.web.services.content_generation import (
    ProviderAvailabilityInput,
    provider_is_available,
    queue_terminal_frame,
)


def test_provider_is_available_for_key_provider_with_stored_key() -> None:
    data = ProviderAvailabilityInput(
        slug="openai",
        auth_env="OPENAI_API_KEY",
        env_value="",
        stored_secret="sk-stored",
        bedrock_credentials=False,
        ollama_reachable=False,
    )
    assert provider_is_available(data) is True


def test_provider_is_available_for_key_provider_with_env_value() -> None:
    data = ProviderAvailabilityInput(
        slug="openai",
        auth_env="OPENAI_API_KEY",
        env_value="sk-env",
        stored_secret=None,
        bedrock_credentials=False,
        ollama_reachable=False,
    )
    assert provider_is_available(data) is True


def test_provider_is_unavailable_without_key_or_env() -> None:
    data = ProviderAvailabilityInput(
        slug="openai",
        auth_env="OPENAI_API_KEY",
        env_value="",
        stored_secret=None,
        bedrock_credentials=False,
        ollama_reachable=False,
    )
    assert provider_is_available(data) is False


def test_bedrock_available_with_credentials() -> None:
    data = ProviderAvailabilityInput(
        slug="bedrock",
        auth_env="AWS_BEARER_TOKEN_BEDROCK",
        env_value="",
        stored_secret=None,
        bedrock_credentials=True,
        ollama_reachable=False,
    )
    assert provider_is_available(data) is True


def test_ollama_availability_uses_reachability() -> None:
    data = ProviderAvailabilityInput(
        slug="ollama",
        auth_env="",
        env_value="",
        stored_secret=None,
        bedrock_credentials=False,
        ollama_reachable=True,
    )
    assert provider_is_available(data) is True


def test_queue_terminal_frame_drops_oldest_when_full() -> None:
    queue = [{"type": "progress", "n": 1}, {"type": "progress", "n": 2}]
    queue_terminal_frame(queue, {"type": "all_done"}, max_size=2)
    assert queue == [{"type": "progress", "n": 2}, {"type": "all_done"}]
