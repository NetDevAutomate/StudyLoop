"""Tests for ``GET /api/content/providers`` (U10.5).

Returns the curated registry augmented with per-provider availability
(based on env-var presence). Drives the WebUI dropdown's enabled state.

Bug-fix coverage:
- Bug A: ``stub`` must NOT appear in the provider list (test/CI backend only).
- Bug D: ``bedrock`` MUST appear (uses boto3, not an API-key env var).
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from studyloop.web.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest import MonkeyPatch


# All known provider env vars; cleared in the fixture so tests start
# from a deterministic "nothing configured" baseline regardless of the
# developer's actual ``.env`` file.
_PROVIDER_ENV_VARS = (
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture
def client(monkeypatch: MonkeyPatch) -> Iterator[TestClient]:
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Pin the bedrock credential helper to False so tests are deterministic
    # on machines where the developer has AWS credentials configured.
    with patch(
        "studyloop.web.routes.content_gen._bedrock_credentials_available",
        return_value=False,
    ):
        yield TestClient(create_app(study_dirs=[]))


class TestProvidersRoute:
    def test_returns_all_known_providers(self, client: TestClient) -> None:
        resp = client.get("/api/content/providers")
        assert resp.status_code == 200
        slugs = {entry["slug"] for entry in resp.json()}
        assert {"openai", "openrouter", "gemini", "anthropic"} <= slugs
        assert "minimax" not in slugs  # removed 2026-06-01

    def test_stub_not_in_provider_list(self, client: TestClient) -> None:
        """Bug A: stub is a test/CI backend — never user-facing."""
        data = client.get("/api/content/providers").json()
        slugs = {entry["slug"] for entry in data}
        assert "stub" not in slugs, (
            f"'stub' appeared in /api/content/providers: {slugs!r}. "
            "stub is a CI-only backend and must be hidden from the user-facing dropdown."
        )

    def test_provider_available_from_encrypted_store(self, monkeypatch: MonkeyPatch) -> None:
        """A key in the encrypted store (no env var) makes the provider available.

        Regression for the audit gap: the availability flag checked os.environ
        only, so a key added via the Generate panel still showed the provider
        as disabled in the dropdown.
        """
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        # openai has a stored key; everything else has nothing.
        with (
            patch(
                "studyloop.web.routes.content_gen._bedrock_credentials_available",
                return_value=False,
            ),
            patch(
                "studyloop.web.routes.content_gen.get_secret",
                side_effect=lambda name: "stored" if name == "openai" else None,
            ),
        ):
            cl = TestClient(create_app(study_dirs=[]))
            data = cl.get("/api/content/providers").json()
        by_slug = {e["slug"]: e for e in data}
        assert by_slug["openai"]["available"] is True, "stored key should enable openai"
        assert by_slug["anthropic"]["available"] is False, "no key -> still disabled"

    def test_bedrock_in_provider_list(self, monkeypatch: MonkeyPatch) -> None:
        """Bug D: Bedrock (boto3 path) must appear as a selectable provider."""
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        with patch(
            "studyloop.web.routes.content_gen._bedrock_credentials_available",
            return_value=True,
        ):
            cl = TestClient(create_app(study_dirs=[]))
            data = cl.get("/api/content/providers").json()
        slugs = {entry["slug"] for entry in data}
        assert "bedrock" in slugs, f"'bedrock' missing from /api/content/providers: {slugs!r}"
        bedrock = next(e for e in data if e["slug"] == "bedrock")
        assert bedrock["available"] is True
        assert bedrock["label"] == "AWS Bedrock"
        assert len(bedrock["models"]) >= 1
        first = bedrock["models"][0]
        assert {"id", "label", "cost_tier", "thinking", "notes"} <= first.keys()

    def test_bedrock_unavailable_when_no_credentials(self, monkeypatch: MonkeyPatch) -> None:
        """Bedrock entry shows available=False when no creds AND no bearer token."""
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
        with (
            patch(
                "studyloop.web.routes.content_gen._bedrock_credentials_available",
                return_value=False,
            ),
            patch(
                "studyloop.web.routes.content_gen.get_secret",
                return_value=None,
            ),
        ):
            cl = TestClient(create_app(study_dirs=[]))
            data = cl.get("/api/content/providers").json()
        bedrock = next((e for e in data if e["slug"] == "bedrock"), None)
        assert bedrock is not None, "Bedrock entry should always be present"
        assert bedrock["available"] is False

    def test_each_entry_has_models_with_metadata(self, client: TestClient) -> None:
        data = client.get("/api/content/providers").json()
        # Pick a known-stable provider for shape assertion.
        anthropic = next(e for e in data if e["slug"] == "anthropic")
        assert anthropic["adapter"] == "anthropic_compat"
        assert anthropic["auth_env"] == "ANTHROPIC_API_KEY"
        assert len(anthropic["models"]) >= 1
        first = anthropic["models"][0]
        assert {"id", "label", "cost_tier", "thinking", "notes"} <= first.keys()

    def test_available_flag_false_when_env_var_unset(self, monkeypatch: MonkeyPatch) -> None:
        # Clear API-key env, the Bedrock bearer token, and force the local-only
        # checks (bedrock SigV4, ollama reachability) off so nothing is
        # available.
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
        with (
            patch(
                "studyloop.web.routes.content_gen._bedrock_credentials_available",
                return_value=False,
            ),
            patch(
                "studyloop.web.routes.content_gen._ollama_reachable",
                return_value=False,
            ),
            patch(
                "studyloop.web.routes.content_gen.get_secret",
                return_value=None,
            ),
        ):
            cl = TestClient(create_app(study_dirs=[]))
            data = cl.get("/api/content/providers").json()
        assert all(not entry["available"] for entry in data)

    def test_available_flag_true_when_env_var_set(self, monkeypatch: MonkeyPatch) -> None:
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

    def test_no_duplicate_providers(self, client: TestClient) -> None:
        """Each slug appears exactly once.

        Regression: bedrock used to be appended ad-hoc after the PROFILES loop;
        now it lives in PROFILES, so the append was removed. Guard against it
        coming back (which would double the bedrock entry).
        """
        data = client.get("/api/content/providers").json()
        slugs = [e["slug"] for e in data]
        assert len(slugs) == len(set(slugs)), f"duplicate provider slug(s): {slugs}"

    def test_every_entry_has_auth_kind(self, client: TestClient) -> None:
        data = client.get("/api/content/providers").json()
        valid = {"api_key", "bedrock_bearer", "local_keyless"}
        for entry in data:
            assert entry.get("auth_kind") in valid, entry

    def test_ollama_in_provider_list(self, client: TestClient) -> None:
        data = client.get("/api/content/providers").json()
        ollama = next((e for e in data if e["slug"] == "ollama"), None)
        assert ollama is not None
        assert ollama["auth_kind"] == "local_keyless"
        assert "base_url" in ollama

    def test_ollama_available_when_reachable(self) -> None:
        with patch("studyloop.web.routes.content_gen._ollama_reachable", return_value=True):
            cl = TestClient(create_app(study_dirs=[]))
            data = cl.get("/api/content/providers").json()
        ollama = next(e for e in data if e["slug"] == "ollama")
        assert ollama["available"] is True

    def test_ollama_unavailable_when_unreachable(self) -> None:
        with patch("studyloop.web.routes.content_gen._ollama_reachable", return_value=False):
            cl = TestClient(create_app(study_dirs=[]))
            data = cl.get("/api/content/providers").json()
        ollama = next(e for e in data if e["slug"] == "ollama")
        assert ollama["available"] is False

    def test_bedrock_available_when_bearer_token_stored(self, monkeypatch: MonkeyPatch) -> None:
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        with patch(
            "studyloop.web.routes.content_gen.get_secret",
            return_value="tok-bearer",
        ):
            cl = TestClient(create_app(study_dirs=[]))
            data = cl.get("/api/content/providers").json()
        bedrock = next(e for e in data if e["slug"] == "bedrock")
        assert bedrock["available"] is True

    def test_local_provider_probes_run_once_per_request(self, monkeypatch: MonkeyPatch) -> None:
        """Provider list must stay fast; local probes are shared across entries."""
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        with (
            patch(
                "studyloop.web.routes.content_gen._bedrock_credentials_available",
                return_value=False,
            ) as bedrock_probe,
            patch(
                "studyloop.web.routes.content_gen._ollama_reachable",
                return_value=False,
            ) as ollama_probe,
            patch("studyloop.web.routes.content_gen.get_secret", return_value=None),
        ):
            cl = TestClient(create_app(study_dirs=[]))
            resp = cl.get("/api/content/providers")

        assert resp.status_code == 200
        assert bedrock_probe.call_count == 1
        assert ollama_probe.call_count == 1

    def test_bedrock_credentials_false_when_boto3_missing(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """Missing optional boto3 must disable Bedrock, not crash the Web UI."""
        from studyloop.web.routes.content_gen._catalog import _bedrock_credentials_available

        for var in [
            "AWS_ACCESS_KEY_ID",
            "AWS_PROFILE",
            "AWS_DEFAULT_PROFILE",
        ]:
            monkeypatch.delenv(var, raising=False)

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "boto3" or name.startswith("botocore"):
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        assert _bedrock_credentials_available() is False


class TestContentCoursesRoute:
    """``/api/content/courses`` — distinct from ``/api/courses``.

    Lists *source* courses on disk so the Generate panel can target
    fresh courses before any decks exist. A bug surfaced by U8 e2e:
    ``/api/courses`` only enumerates courses that already have JSON
    decks for the reviewer.
    """

    def test_returns_course_subdirs_under_base_path(
        self, tmp_path, monkeypatch: MonkeyPatch
    ) -> None:
        from studyloop.settings import ContentConfig, Settings

        study = tmp_path / "Study"
        (study / "DataCamp").mkdir(parents=True)
        (study / "PythonForDataScience").mkdir()
        (study / ".obsidian").mkdir()  # dot dir — must be skipped
        (study / "flashcards").mkdir()  # output dir — must be skipped

        s = Settings()
        s.content = ContentConfig(base_path=study)
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)

        client = TestClient(create_app(study_dirs=[]))
        data = client.get("/api/content/courses").json()
        names = {entry["name"] for entry in data}
        assert names == {"DataCamp", "PythonForDataScience"}

    def test_returns_empty_when_base_path_missing(self, tmp_path, monkeypatch: MonkeyPatch) -> None:
        from studyloop.settings import ContentConfig, Settings

        s = Settings()
        s.content = ContentConfig(base_path=tmp_path / "does-not-exist")
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)

        client = TestClient(create_app(study_dirs=[]))
        assert client.get("/api/content/courses").json() == []

    def test_rejects_publisher_path_traversal(self, tmp_path, monkeypatch: MonkeyPatch) -> None:
        from studyloop.settings import ContentConfig, Settings

        study = tmp_path / "Study"
        study.mkdir()
        s = Settings()
        s.content = ContentConfig(base_path=study)
        monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)

        client = TestClient(create_app(study_dirs=[]))
        resp = client.get("/api/content/courses?publisher=../outside")
        assert resp.status_code == 400
        assert "must not contain" in resp.json()["detail"]
