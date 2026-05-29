"""Tests for ``GET /api/content/providers`` (U10.5).

Returns the curated registry augmented with per-provider availability
(based on env-var presence). Drives the WebUI dropdown's enabled state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app  # noqa: E402

if TYPE_CHECKING:
    from pytest import MonkeyPatch


# All known provider env vars; cleared in the fixture so tests start
# from a deterministic "nothing configured" baseline regardless of the
# developer's actual ``.env`` file.
_PROVIDER_ENV_VARS = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "MINIMAX_API_KEY",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture
def client(monkeypatch: MonkeyPatch) -> TestClient:
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return TestClient(create_app(study_dirs=[]))


class TestProvidersRoute:
    def test_returns_all_known_providers(self, client: TestClient) -> None:
        resp = client.get("/api/content/providers")
        assert resp.status_code == 200
        slugs = {entry["slug"] for entry in resp.json()}
        assert {"openai", "openrouter", "gemini", "minimax", "anthropic"} <= slugs

    def test_each_entry_has_models_with_metadata(self, client: TestClient) -> None:
        data = client.get("/api/content/providers").json()
        # Pick a known-stable provider for shape assertion.
        anthropic = next(e for e in data if e["slug"] == "anthropic")
        assert anthropic["adapter"] == "anthropic_compat"
        assert anthropic["auth_env"] == "ANTHROPIC_API_KEY"
        assert len(anthropic["models"]) >= 1
        first = anthropic["models"][0]
        assert {"id", "label", "cost_tier", "thinking", "notes"} <= first.keys()

    def test_available_flag_false_when_env_var_unset(self, client: TestClient) -> None:
        data = client.get("/api/content/providers").json()
        # Fixture cleared all keys, so every provider is unavailable.
        assert all(not entry["available"] for entry in data)

    def test_available_flag_true_when_env_var_set(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        # Set just one var; only that provider should flip to available.
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake")
        client = TestClient(create_app(study_dirs=[]))

        data = client.get("/api/content/providers").json()
        availability = {e["slug"]: e["available"] for e in data}
        assert availability["openrouter"] is True
        assert availability["openai"] is False
        assert availability["anthropic"] is False
