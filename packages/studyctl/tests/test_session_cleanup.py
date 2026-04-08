"""Tests for studyctl.session.cleanup — extracted helper functions.

No conftest.py is used. Fixtures are inlined per project convention.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from studyctl.session_state import ParkingEntry, TopicEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_topic(topic: str, status: str) -> TopicEntry:
    return TopicEntry(time="10:00", topic=topic, status=status, note="")


def _make_parking(question: str) -> ParkingEntry:
    return ParkingEntry(question=question)


# ---------------------------------------------------------------------------
# _persist_session_data
# ---------------------------------------------------------------------------


class TestPersistSessionData:
    """_persist_session_data runs backlog, flashcard, and DB steps independently.

    All three sub-imports are local inside the function, so they must be patched
    at their canonical module paths, not at studyctl.session.cleanup.*.
    """

    def _call(self, study_id, state, topic_entries, notes, auto_persist=True):
        from studyctl.session.cleanup import _persist_session_data

        _persist_session_data(study_id, state, topic_entries, notes, auto_persist=auto_persist)

    def test_calls_end_study_session_with_counts(self):
        """win/struggle counts are derived from topic entries and passed to DB."""
        topics = [
            _make_topic("Closures", "win"),
            _make_topic("Decorators", "insight"),
            _make_topic("GIL", "struggling"),
        ]
        mock_end = MagicMock()
        with (
            patch("studyctl.history.end_study_session", mock_end),
            patch("studyctl.services.backlog.auto_persist_struggled"),
        ):
            self._call("sess-1", {}, topics, "notes")

        mock_end.assert_called_once_with("sess-1", notes="notes", win_count=2, struggle_count=1)

    def test_auto_persist_skipped_when_disabled(self):
        """auto_persist=False must not call auto_persist_struggled."""
        mock_backlog = MagicMock()
        with (
            patch("studyctl.history.end_study_session"),
            patch("studyctl.services.backlog.auto_persist_struggled", mock_backlog),
        ):
            self._call("sess-1", {}, [], "notes", auto_persist=False)

        mock_backlog.assert_not_called()

    def test_auto_persist_called_when_enabled(self):
        """auto_persist=True must call auto_persist_struggled with correct args."""
        topics = [_make_topic("Closures", "struggling")]
        mock_backlog = MagicMock()
        with (
            patch("studyctl.history.end_study_session"),
            patch("studyctl.services.backlog.auto_persist_struggled", mock_backlog),
        ):
            self._call("sess-2", {}, topics, "notes", auto_persist=True)

        mock_backlog.assert_called_once_with("sess-2", topics)

    def test_backlog_failure_does_not_abort_db_end(self):
        """A crash in auto_persist_struggled must not prevent end_study_session."""
        mock_end = MagicMock()
        with (
            patch("studyctl.history.end_study_session", mock_end),
            patch(
                "studyctl.services.backlog.auto_persist_struggled",
                side_effect=RuntimeError("boom"),
            ),
        ):
            self._call("sess-3", {}, [], "notes")

        mock_end.assert_called_once()

    def test_flashcard_generation_called_with_slug(self):
        """write_session_flashcards is called when topic_slug is present."""
        topics = [_make_topic("Closures", "win")]
        state = {"topic_slug": "python-closures"}
        mock_writer = MagicMock(return_value=3)
        mock_settings = MagicMock()
        mock_settings.content.base_path = "/some/path"

        with (
            patch("studyctl.history.end_study_session"),
            patch("studyctl.services.flashcard_writer.write_session_flashcards", mock_writer),
            patch("studyctl.settings.load_settings", return_value=mock_settings),
            patch("studyctl.services.backlog.auto_persist_struggled"),
        ):
            self._call("sess-4", state, topics, "notes")

        mock_writer.assert_called_once_with("/some/path", "python-closures", "sess-4", topics)

    def test_flashcard_generation_skipped_when_no_slug(self):
        """write_session_flashcards is NOT called when topic_slug is absent."""
        topics = [_make_topic("Closures", "win")]
        mock_writer = MagicMock()
        with (
            patch("studyctl.history.end_study_session"),
            patch("studyctl.services.flashcard_writer.write_session_flashcards", mock_writer),
            patch("studyctl.services.backlog.auto_persist_struggled"),
        ):
            self._call("sess-5", {}, topics, "notes")

        mock_writer.assert_not_called()

    def test_flashcard_failure_does_not_abort_db_end(self):
        """A crash in write_session_flashcards must not prevent end_study_session."""
        state = {"topic_slug": "python-closures"}
        mock_end = MagicMock()

        with (
            patch("studyctl.history.end_study_session", mock_end),
            patch(
                "studyctl.services.flashcard_writer.write_session_flashcards",
                side_effect=RuntimeError("boom"),
            ),
            patch("studyctl.settings.load_settings"),
            patch("studyctl.services.backlog.auto_persist_struggled"),
        ):
            self._call("sess-6", state, [_make_topic("X", "win")], "notes")

        mock_end.assert_called_once()

    def test_db_failure_is_logged_not_raised(self):
        """A crash in end_study_session must be caught, not re-raised."""
        with (
            patch(
                "studyctl.history.end_study_session",
                side_effect=OSError("db locked"),
            ),
            patch("studyctl.services.backlog.auto_persist_struggled"),
        ):
            # Should not raise
            self._call("sess-7", {}, [], "notes")


# ---------------------------------------------------------------------------
# _signal_dashboard_ended
# ---------------------------------------------------------------------------


class TestSignalDashboardEnded:
    def test_writes_mode_ended(self):
        """_signal_dashboard_ended writes {mode: ended} to session state."""
        mock_write = MagicMock()
        with patch("studyctl.session_state.write_session_state", mock_write):
            from studyctl.session.cleanup import _signal_dashboard_ended

            _signal_dashboard_ended()

        mock_write.assert_called_once_with({"mode": "ended"})

    def test_write_failure_is_suppressed(self):
        """A crash in write_session_state must not propagate."""
        with patch(
            "studyctl.session_state.write_session_state",
            side_effect=OSError("disk full"),
        ):
            from studyctl.session.cleanup import _signal_dashboard_ended

            _signal_dashboard_ended()  # must not raise


# ---------------------------------------------------------------------------
# _teardown_agent
# ---------------------------------------------------------------------------


class TestTeardownAgent:
    def test_calls_adapter_teardown_with_session_dir(self, tmp_path):
        """When an adapter has a teardown method, it is called with the session dir."""
        mock_teardown = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.teardown = mock_teardown

        state = {"agent": "kiro", "session_dir": str(tmp_path)}

        with patch("studyctl.agent_launcher.AGENTS", {"kiro": mock_adapter}):
            from studyctl.session.cleanup import _teardown_agent

            _teardown_agent(state)

        from pathlib import Path

        mock_teardown.assert_called_once_with(Path(tmp_path))

    def test_skips_when_no_adapter_found(self):
        """Unknown agent name must not raise."""
        state = {"agent": "unknown-agent", "session_dir": "/some/dir"}
        with patch("studyctl.agent_launcher.AGENTS", {}):
            from studyctl.session.cleanup import _teardown_agent

            _teardown_agent(state)  # must not raise

    def test_skips_when_adapter_has_no_teardown(self):
        """Adapter without a teardown attr (None/falsy) is silently skipped."""
        mock_adapter = MagicMock()
        mock_adapter.teardown = None
        state = {"agent": "gemini", "session_dir": "/some/dir"}
        with patch("studyctl.agent_launcher.AGENTS", {"gemini": mock_adapter}):
            from studyctl.session.cleanup import _teardown_agent

            _teardown_agent(state)  # must not raise

    def test_teardown_exception_is_logged_not_raised(self):
        """A crash inside adapter.teardown must be caught, not re-raised."""
        mock_teardown = MagicMock(side_effect=RuntimeError("teardown failed"))
        mock_adapter = MagicMock()
        mock_adapter.teardown = mock_teardown
        state = {"agent": "kiro", "session_dir": "/some/dir"}
        with patch("studyctl.agent_launcher.AGENTS", {"kiro": mock_adapter}):
            from studyctl.session.cleanup import _teardown_agent

            _teardown_agent(state)  # must not raise


# ---------------------------------------------------------------------------
# _kill_background_processes
# ---------------------------------------------------------------------------


class TestKillBackgroundProcesses:
    # The function uses local imports (import os / import subprocess as _sp /
    # from orchestrator import _kill_port_occupant), so patches must target the
    # canonical module paths, not the cleanup module namespace.

    def test_sends_sigterm_to_matching_web_pid(self):
        """PID with matching command receives SIGTERM."""
        state = {"web_pid": 9999}
        mock_run = MagicMock()
        mock_run.return_value.stdout = "python -m studyctl.cli web"
        mock_kill = MagicMock()

        with (
            patch("subprocess.run", mock_run),
            patch("os.kill", mock_kill),
            patch("studyctl.session.orchestrator._kill_port_occupant"),
        ):
            from studyctl.session.cleanup import _kill_background_processes

            _kill_background_processes(state)

        mock_kill.assert_called_once_with(9999, 15)

    def test_does_not_kill_pid_when_command_mismatch(self):
        """PID whose command does not match the expected string is left alone."""
        state = {"web_pid": 1234}
        mock_run = MagicMock()
        mock_run.return_value.stdout = "nginx -g daemon"
        mock_kill = MagicMock()

        with (
            patch("subprocess.run", mock_run),
            patch("os.kill", mock_kill),
            patch("studyctl.session.orchestrator._kill_port_occupant"),
        ):
            from studyctl.session.cleanup import _kill_background_processes

            _kill_background_processes(state)

        mock_kill.assert_not_called()

    def test_port_fallback_called_for_ttyd(self):
        """_kill_port_occupant is called for ttyd_port when present."""
        state = {"ttyd_port": 7681}
        mock_kill_port = MagicMock()

        with (
            patch("subprocess.run", MagicMock(return_value=MagicMock(stdout=""))),
            patch("os.kill"),
            patch("studyctl.session.orchestrator._kill_port_occupant", mock_kill_port),
        ):
            from studyctl.session.cleanup import _kill_background_processes

            _kill_background_processes(state)

        mock_kill_port.assert_any_call(7681, expected_cmd="ttyd")

    def test_port_fallback_called_for_web(self):
        """_kill_port_occupant is called for web_port when present."""
        state = {"web_port": 8567}
        mock_kill_port = MagicMock()

        with (
            patch("subprocess.run", MagicMock(return_value=MagicMock(stdout=""))),
            patch("os.kill"),
            patch("studyctl.session.orchestrator._kill_port_occupant", mock_kill_port),
        ):
            from studyctl.session.cleanup import _kill_background_processes

            _kill_background_processes(state)

        mock_kill_port.assert_any_call(8567, expected_cmd="studyctl")

    def test_port_fallback_skipped_when_ports_absent(self):
        """_kill_port_occupant is not called when ports are absent from state."""
        state = {}
        mock_kill_port = MagicMock()

        with (
            patch("subprocess.run", MagicMock(return_value=MagicMock(stdout=""))),
            patch("os.kill"),
            patch("studyctl.session.orchestrator._kill_port_occupant", mock_kill_port),
        ):
            from studyctl.session.cleanup import _kill_background_processes

            _kill_background_processes(state)

        mock_kill_port.assert_not_called()


# ---------------------------------------------------------------------------
# _cleanup_tmux_and_files
# ---------------------------------------------------------------------------


class TestCleanupTmuxAndFiles:
    # kill_all_study_sessions and the IPC path constants are imported locally
    # inside the function, so they must be patched at their canonical locations.

    def test_unlinks_persona_file(self, tmp_path):
        """persona_file is deleted if it exists."""
        persona = tmp_path / "persona.md"
        persona.write_text("# Persona")

        with (
            patch("studyctl.tmux.kill_all_study_sessions"),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
        ):
            from studyctl.session.cleanup import _cleanup_tmux_and_files

            _cleanup_tmux_and_files(session_name=None, persona_file=str(persona))

        assert not persona.exists()

    def test_no_error_when_persona_file_absent(self, tmp_path):
        """Missing persona_file does not raise."""
        with (
            patch("studyctl.tmux.kill_all_study_sessions"),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
        ):
            from studyctl.session.cleanup import _cleanup_tmux_and_files

            _cleanup_tmux_and_files(session_name=None, persona_file=None)  # must not raise

    def test_kills_tmux_sessions(self, tmp_path):
        """kill_all_study_sessions is called with the current session name."""
        mock_kill = MagicMock()
        with (
            patch("studyctl.tmux.kill_all_study_sessions", mock_kill),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
        ):
            from studyctl.session.cleanup import _cleanup_tmux_and_files

            _cleanup_tmux_and_files(session_name="study-python-abc", persona_file=None)

        mock_kill.assert_called_once_with(current_session="study-python-abc")

    def test_ipc_files_removed(self, tmp_path):
        """TOPICS_FILE and PARKING_FILE are deleted if they exist."""
        topics = tmp_path / "session-topics.md"
        parking = tmp_path / "session-parking.md"
        topics.write_text("- [10:00] foo | status:win | bar")
        parking.write_text("- Why does Python have the GIL?")

        with (
            patch("studyctl.tmux.kill_all_study_sessions"),
            patch("studyctl.session_state.TOPICS_FILE", topics),
            patch("studyctl.session_state.PARKING_FILE", parking),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
        ):
            from studyctl.session.cleanup import _cleanup_tmux_and_files

            _cleanup_tmux_and_files(session_name=None, persona_file=None)

        assert not topics.exists()
        assert not parking.exists()

    def test_ipc_removal_ignores_missing_files(self, tmp_path):
        """Unlinking already-absent IPC files does not raise."""
        with (
            patch("studyctl.tmux.kill_all_study_sessions"),
            patch("studyctl.session_state.TOPICS_FILE", tmp_path / "topics.md"),
            patch("studyctl.session_state.PARKING_FILE", tmp_path / "parking.md"),
            patch("studyctl.session_state.SESSION_DIR", tmp_path),
        ):
            from studyctl.session.cleanup import _cleanup_tmux_and_files

            _cleanup_tmux_and_files(session_name=None, persona_file=None)  # must not raise


# ---------------------------------------------------------------------------
# end_session_common — orchestrator contract
# ---------------------------------------------------------------------------


class TestEndSessionCommon:
    """Public API contract: signature unchanged, helpers called in order."""

    def test_returns_none_when_no_study_id(self):
        """Returns None immediately when study_session_id is absent."""
        from studyctl.session.cleanup import end_session_common

        result = end_session_common({})
        assert result is None

    def test_returns_topic_on_success(self):
        """Returns the topic string when study_session_id is present."""
        from studyctl.session.cleanup import end_session_common

        state = {"study_session_id": "abc", "topic": "Closures"}
        with (
            patch("studyctl.session_state.parse_topics_file", return_value=[]),
            patch("studyctl.session_state.parse_parking_file", return_value=[]),
            patch("studyctl.session.cleanup._persist_session_data"),
            patch("studyctl.session.cleanup._signal_dashboard_ended"),
            patch("studyctl.session.cleanup._teardown_agent"),
            patch("studyctl.session.cleanup._kill_background_processes"),
            patch("studyctl.session.cleanup._cleanup_tmux_and_files"),
        ):
            result = end_session_common(state)

        assert result == "Closures"

    def test_returns_unknown_when_topic_absent(self):
        """Defaults to 'unknown' when topic key is missing from state."""
        from studyctl.session.cleanup import end_session_common

        state = {"study_session_id": "abc"}
        with (
            patch("studyctl.session_state.parse_topics_file", return_value=[]),
            patch("studyctl.session_state.parse_parking_file", return_value=[]),
            patch("studyctl.session.cleanup._persist_session_data"),
            patch("studyctl.session.cleanup._signal_dashboard_ended"),
            patch("studyctl.session.cleanup._teardown_agent"),
            patch("studyctl.session.cleanup._kill_background_processes"),
            patch("studyctl.session.cleanup._cleanup_tmux_and_files"),
        ):
            result = end_session_common(state)

        assert result == "unknown"

    def test_all_helpers_called(self):
        """All five helper functions are invoked by the orchestrator."""
        from studyctl.session.cleanup import end_session_common

        state = {"study_session_id": "abc", "topic": "X", "tmux_session": "study-x"}
        persist_mock = MagicMock()
        signal_mock = MagicMock()
        teardown_mock = MagicMock()
        kill_mock = MagicMock()
        cleanup_mock = MagicMock()

        with (
            patch("studyctl.session_state.parse_topics_file", return_value=[]),
            patch("studyctl.session_state.parse_parking_file", return_value=[]),
            patch("studyctl.session.cleanup._persist_session_data", persist_mock),
            patch("studyctl.session.cleanup._signal_dashboard_ended", signal_mock),
            patch("studyctl.session.cleanup._teardown_agent", teardown_mock),
            patch("studyctl.session.cleanup._kill_background_processes", kill_mock),
            patch("studyctl.session.cleanup._cleanup_tmux_and_files", cleanup_mock),
        ):
            end_session_common(state)

        persist_mock.assert_called_once()
        signal_mock.assert_called_once()
        teardown_mock.assert_called_once_with(state)
        kill_mock.assert_called_once_with(state)
        cleanup_mock.assert_called_once()

    def test_auto_persist_forwarded_to_persist_helper(self):
        """auto_persist=False is passed through to _persist_session_data."""
        from studyctl.session.cleanup import end_session_common

        state = {"study_session_id": "abc", "topic": "X"}
        persist_mock = MagicMock()

        with (
            patch("studyctl.session_state.parse_topics_file", return_value=[]),
            patch("studyctl.session_state.parse_parking_file", return_value=[]),
            patch("studyctl.session.cleanup._persist_session_data", persist_mock),
            patch("studyctl.session.cleanup._signal_dashboard_ended"),
            patch("studyctl.session.cleanup._teardown_agent"),
            patch("studyctl.session.cleanup._kill_background_processes"),
            patch("studyctl.session.cleanup._cleanup_tmux_and_files"),
        ):
            end_session_common(state, auto_persist=False)

        _, kwargs = persist_mock.call_args
        assert kwargs["auto_persist"] is False
