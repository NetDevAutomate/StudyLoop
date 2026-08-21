"""Tests for backend selection logic in studyloop.multiplexer.get_backend().

Covers the env → config → availability → default cascade.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestBackendSelectionEnvVar:
    """STUDYLOOP_MULTIPLEXER env var controls backend selection."""

    def test_env_tmux_returns_tmux_backend(self):
        from studyloop.multiplexer import TmuxBackend, get_backend

        with patch.dict(os.environ, {"STUDYLOOP_MULTIPLEXER": "tmux"}):
            backend = get_backend()
        assert isinstance(backend, TmuxBackend)

    def test_env_herdr_available_returns_herdr_backend(self):
        """When HerdrBackend exists and herdr binary is on PATH, get_backend returns it.

        Until T2 lands herdr.py, this test verifies the ImportError path
        raises MultiplexerError with an informative message. Once T2 lands,
        this test should be updated to assert isinstance(backend, HerdrBackend).
        """
        from studyloop.multiplexer import MultiplexerError, get_backend

        with (
            patch.dict(os.environ, {"STUDYLOOP_MULTIPLEXER": "herdr"}),
            patch("shutil.which", return_value="/usr/local/bin/herdr"),
        ):
            try:
                backend = get_backend()
                # If T2 has landed, verify it's not TmuxBackend
                from studyloop.multiplexer import TmuxBackend

                assert not isinstance(backend, TmuxBackend)
            except MultiplexerError as e:
                # T2 not landed yet — verify informative error
                assert "not yet implemented" in str(e)

    def test_env_herdr_not_available_raises(self):
        from studyloop.multiplexer import MultiplexerError, get_backend

        with (
            patch.dict(os.environ, {"STUDYLOOP_MULTIPLEXER": "herdr"}),
            patch("shutil.which", return_value=None),pytest.raises(MultiplexerError, match="herdr")
        ):
            get_backend()

    def test_env_invalid_value_raises(self):
        from studyloop.multiplexer import MultiplexerError, get_backend

        with (
            patch.dict(os.environ, {"STUDYLOOP_MULTIPLEXER": "zellij"}),
            pytest.raises(MultiplexerError, match="zellij"),
        ):
            get_backend()


class TestBackendSelectionDefault:
    """Without env var, tmux is always the default (herdr not flipped yet)."""

    def test_no_env_herdr_available_returns_tmux(self):
        """Even with herdr installed, default is tmux until flag is flipped."""
        from studyloop.multiplexer import TmuxBackend, get_backend

        env = os.environ.copy()
        env.pop("STUDYLOOP_MULTIPLEXER", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch("shutil.which", return_value="/usr/local/bin/herdr"),
        ):
            backend = get_backend()
        assert isinstance(backend, TmuxBackend)

    def test_no_env_herdr_not_available_returns_tmux(self):
        from studyloop.multiplexer import TmuxBackend, get_backend

        env = os.environ.copy()
        env.pop("STUDYLOOP_MULTIPLEXER", None)
        with patch.dict(os.environ, env, clear=True):
            backend = get_backend()
        assert isinstance(backend, TmuxBackend)
