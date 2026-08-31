"""Product-boundary contracts for live data and release packaging."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path


def test_production_package_contains_no_fixture_backed_extractor() -> None:
    assert importlib.util.find_spec("studyloop.extractors.stub") is None


def test_production_package_contains_no_fake_agent_or_content_backend() -> None:
    assert importlib.util.find_spec("studyloop.adapters.fake") is None
    assert importlib.util.find_spec("studyloop.content.generators.stub") is None


def test_out_of_scope_first_party_harness_modules_are_absent() -> None:
    for module_name in ("gemini", "grok", "ollama", "lmstudio"):
        assert importlib.util.find_spec(f"studyloop.adapters.{module_name}") is None


def test_release_wheel_excludes_source_test_helpers() -> None:
    package_root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((package_root / "pyproject.toml").read_text())
    assert not (package_root / "src/studyloop/testing").exists()
    assert "studyloop-fake-agent" not in project["project"]["scripts"]


def test_live_extractor_exports_no_account_specific_defaults() -> None:
    from studyloop.extractors import llm

    assert not hasattr(llm, "DEFAULT_MODEL")
    assert not hasattr(llm, "DEFAULT_PROFILE")
    assert not hasattr(llm, "DEFAULT_REGION")
