"""Policy tests for the opt-in real-harness browser release gate."""

from __future__ import annotations

import importlib

import pytest


def test_strict_live_harness_gate_fails_when_a_harness_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claimed live-harness release must not pass with missing evidence."""
    gate = importlib.import_module("test_web_live_harness_rendering")
    monkeypatch.setenv("STUDYLOOP_STRICT_LIVE_HARNESSES", "1")

    with pytest.raises(pytest.fail.Exception, match=r"gemini.*not installed"):
        gate._unavailable_harness("gemini", "not installed")
