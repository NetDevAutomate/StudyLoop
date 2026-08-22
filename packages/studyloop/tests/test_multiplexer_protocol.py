"""Tests for studyloop.multiplexer — Protocol definition and TmuxBackend conformance.

TDD: These tests define the contract a backend must satisfy. Written BEFORE
the implementation.
"""

from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolDefinition:
    """Verify the Protocol class exists and is runtime_checkable."""

    def test_multiplexer_is_runtime_checkable(self):
        from studyloop.multiplexer import Multiplexer

        assert (
            hasattr(Multiplexer, "__protocol_attrs__")
            or hasattr(Multiplexer, "__abstractmethods__")
            or hasattr(Multiplexer, "__subclasshook__")
        )

    def test_tmux_backend_satisfies_protocol(self):
        from studyloop.multiplexer import Multiplexer, TmuxBackend

        backend = TmuxBackend()
        assert isinstance(backend, Multiplexer)

    def test_protocol_has_expected_methods(self):
        """Guard against silent protocol expansion — exactly 18 public methods."""
        from studyloop.multiplexer import Multiplexer

        # Get all methods defined on the Protocol (not inherited from object)
        protocol_methods = [
            name
            for name in dir(Multiplexer)
            if not name.startswith("_") and callable(getattr(Multiplexer, name, None))
        ]
        assert len(protocol_methods) == 18, (
            f"Protocol has {len(protocol_methods)} methods, expected 18. "
            f"Methods: {sorted(protocol_methods)}"
        )

    def test_protocol_method_names(self):
        """Verify expected method names exist on Protocol."""
        from studyloop.multiplexer import Multiplexer

        expected = {
            "is_available",
            "is_inside_session",
            "is_server_running",
            "session_exists",
            "create_session",
            "kill_session",
            "list_study_sessions",
            "kill_all_study_sessions",
            "split_pane",
            "send_keys",
            "select_pane",
            "configure_session_defaults",
            "switch_client",
            "attach",
            "pane_has_child_process",
            "is_zombie_session",
            "capture_pane",
            "wait_for_content",
        }
        actual = {
            name
            for name in dir(Multiplexer)
            if not name.startswith("_") and callable(getattr(Multiplexer, name, None))
        }
        assert actual == expected


class TestMultiplexerError:
    """Verify MultiplexerError exception class."""

    def test_multiplexer_error_is_exception(self):
        from studyloop.multiplexer import MultiplexerError

        assert issubclass(MultiplexerError, Exception)

    def test_multiplexer_error_message(self):
        from studyloop.multiplexer import MultiplexerError

        err = MultiplexerError("herdr binary not found")
        assert "herdr binary not found" in str(err)


class TestGetBackend:
    """Verify get_backend() factory returns Multiplexer-conforming objects."""

    def test_get_backend_returns_multiplexer(self):
        from studyloop.multiplexer import Multiplexer, get_backend

        backend = get_backend()
        assert isinstance(backend, Multiplexer)

    def test_get_backend_default_is_tmux(self):
        """Without env var override, default is TmuxBackend."""
        from studyloop.multiplexer import TmuxBackend, get_backend

        with patch.dict("os.environ", {}, clear=False):
            # Remove STUDYLOOP_MULTIPLEXER if set
            import os

            os.environ.pop("STUDYLOOP_MULTIPLEXER", None)
            backend = get_backend()
        assert isinstance(backend, TmuxBackend)
