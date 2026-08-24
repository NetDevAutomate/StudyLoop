"""Policy tests for the opt-in real-harness browser release gate."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[3]


def test_strict_live_harness_gate_fails_when_a_harness_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claimed live-harness release must not pass with missing evidence."""
    gate = importlib.import_module("test_web_live_harness_rendering")
    monkeypatch.setenv("STUDYLOOP_STRICT_LIVE_HARNESSES", "1")

    with pytest.raises(pytest.fail.Exception, match=r"gemini.*not installed"):
        gate._unavailable_harness("gemini", "not installed")


def test_release_gate_provisions_a_pinned_gemini_cli() -> None:
    """The local release proof must not depend on a global or floating Gemini CLI."""
    justfile = (_REPO_ROOT / "Justfile").read_text(encoding="utf-8")

    assert "npx --yes --package @google/gemini-cli@0.56.0 env" in justfile
