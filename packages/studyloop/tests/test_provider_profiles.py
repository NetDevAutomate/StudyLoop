"""Tests for the provider profile registry (U1.5)."""

from __future__ import annotations

import pytest

from studyloop.content.generators.provider_profiles import (
    PROFILES,
    ModelEntry,
    ProviderProfile,
    ProviderProfileError,
    default_model,
    get_model,
    get_profile,
)


class TestRegistryShape:
    def test_all_expected_providers_present(self) -> None:
        expected = {"openai", "openrouter", "gemini", "minimax", "anthropic"}
        assert expected.issubset(set(PROFILES)), (
            f"missing providers: {expected - set(PROFILES)}"
        )

    def test_every_profile_has_at_least_one_model(self) -> None:
        for slug, profile in PROFILES.items():
            assert profile.models, f"profile {slug!r} has no curated models"

    def test_every_profile_uses_known_adapter(self) -> None:
        known = {"openai_compat", "anthropic_compat", "bedrock", "ollama"}
        for profile in PROFILES.values():
            assert profile.adapter in known

    def test_minimax_routes_to_anthropic_adapter(self) -> None:
        # Captures the design decision from the plan: MiniMax exposes an
        # /anthropic shim, so it must use the Anthropic adapter, not
        # OpenAI-compat.
        assert PROFILES["minimax"].adapter == "anthropic_compat"
        assert PROFILES["minimax"].base_url.endswith("/anthropic")
        assert PROFILES["minimax"].auth_env == "MINIMAX_API_KEY"


class TestGetProfile:
    def test_known_slug_returns_profile(self) -> None:
        p = get_profile("openrouter")
        assert isinstance(p, ProviderProfile)
        assert p.slug == "openrouter"

    def test_unknown_slug_lists_available(self) -> None:
        with pytest.raises(ProviderProfileError) as exc:
            get_profile("does-not-exist")
        msg = str(exc.value)
        # Available list is in the error so the user can fix the typo
        # without searching docs.
        for known in ("openai", "openrouter", "gemini", "minimax", "anthropic"):
            assert known in msg


class TestGetModel:
    def test_known_model_returns_entry(self) -> None:
        profile = get_profile("anthropic")
        entry = get_model(profile, "claude-haiku-4-5")
        assert isinstance(entry, ModelEntry)
        assert entry.cost_tier == "cheap"

    def test_unknown_model_lists_available(self) -> None:
        profile = get_profile("anthropic")
        with pytest.raises(ProviderProfileError) as exc:
            get_model(profile, "not-a-real-model")
        msg = str(exc.value)
        # All curated models for the profile show up in the error.
        for entry in profile.models:
            assert entry.id in msg


class TestDefaultModel:
    def test_returns_first_cheap_when_present(self) -> None:
        profile = get_profile("openai")
        entry = default_model(profile)
        assert entry.cost_tier == "cheap"

    def test_falls_back_to_first_when_no_cheap(self) -> None:
        # Synthetic profile with no cheap-tier entries -- exercises the
        # fallback branch without needing to mutate the global registry.
        profile = ProviderProfile(
            slug="x",
            label="X",
            adapter="openai_compat",
            base_url="https://example.com",
            auth_env="X_KEY",
            models=[
                ModelEntry(id="only-balanced", label="Only", cost_tier="balanced"),
            ],
        )
        assert default_model(profile).id == "only-balanced"

    def test_empty_profile_raises(self) -> None:
        profile = ProviderProfile(
            slug="empty",
            label="Empty",
            adapter="openai_compat",
            base_url="https://example.com",
            auth_env="X_KEY",
            models=[],
        )
        with pytest.raises(ProviderProfileError, match="no curated models"):
            default_model(profile)


class TestBedrockAndOllamaProfiles:
    """bedrock and ollama are now first-class registry entries (moved out of
    the ad-hoc route append)."""

    def test_bedrock_in_profiles(self) -> None:
        from studyloop.content.generators.provider_profiles import PROFILES

        assert "bedrock" in PROFILES
        p = PROFILES["bedrock"]
        assert p.adapter == "bedrock"
        assert len(p.models) >= 1

    def test_ollama_in_profiles(self) -> None:
        from studyloop.content.generators.provider_profiles import PROFILES

        assert "ollama" in PROFILES
        p = PROFILES["ollama"]
        assert p.adapter == "ollama"
        assert p.base_url == "http://localhost:11434"
        assert p.auth_env == ""
        assert len(p.models) >= 1

    def test_get_profile_resolves_new_slugs(self) -> None:
        from studyloop.content.generators.provider_profiles import get_profile

        assert get_profile("bedrock").slug == "bedrock"
        assert get_profile("ollama").slug == "ollama"
