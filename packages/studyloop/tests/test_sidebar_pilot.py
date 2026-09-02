"""Textual Pilot tests for the sidebar app.

Tests sidebar widget behaviour, key bindings, and action logic
WITHOUT needing tmux. Runs headlessly via Textual's test framework.
Fast, deterministic, CI-safe.

Run with:
    uv run pytest tests/test_sidebar_pilot.py -v
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

# These tests DON'T need tmux — they run the Textual app headlessly.
# They DO need the studyloop package importable.


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Redirect session state to a temp directory."""
    state_dir = tmp_path / "studyloop"
    state_dir.mkdir()

    monkeypatch.setattr("studyloop.session_state.SESSION_DIR", state_dir)
    monkeypatch.setattr("studyloop.session_state.STATE_FILE", state_dir / "session-state.json")
    monkeypatch.setattr("studyloop.session_state.TOPICS_FILE", state_dir / "session-topics.md")
    monkeypatch.setattr("studyloop.session_state.PARKING_FILE", state_dir / "session-parking.md")

    # Also patch the sidebar's imported references
    monkeypatch.setattr("studyloop.tui.sidebar.SESSION_DIR", state_dir)
    monkeypatch.setattr("studyloop.tui.sidebar.STATE_FILE", state_dir / "session-state.json")
    monkeypatch.setattr("studyloop.tui.sidebar.TOPICS_FILE", state_dir / "session-topics.md")
    monkeypatch.setattr("studyloop.tui.sidebar.PARKING_FILE", state_dir / "session-parking.md")

    return state_dir


def _write_state(state_dir: Path, state: dict) -> None:
    """Write a session state file."""
    (state_dir / "session-state.json").write_text(json.dumps(state))


def _write_topics(state_dir: Path, lines: list[str]) -> None:
    """Write topic entries to the topics IPC file."""
    (state_dir / "session-topics.md").write_text("\n".join(lines) + "\n")


class TestSidebarRendering:
    """Test that the sidebar renders widgets correctly."""

    @pytest.mark.asyncio
    async def test_sidebar_shows_timer_widget(self, state_dir):
        """The sidebar should render a timer display."""
        from studyloop.tui.sidebar import SidebarApp

        _write_state(
            state_dir,
            {
                "study_session_id": "test-123",
                "topic": "Test Topic",
                "energy": 7,
                "mode": "study",
                "started_at": "2026-04-02T12:00:00+00:00",
                "timer_mode": "elapsed",
            },
        )

        async with SidebarApp().run_test(size=(40, 20)) as pilot:
            await pilot.pause()  # let mount + compose complete
            # Timer widget should exist
            timer = pilot.app.query_one("#timer")
            assert timer is not None

    @pytest.mark.asyncio
    async def test_sidebar_shows_status_bar(self, state_dir):
        """The sidebar should show the key binding hints."""
        from studyloop.tui.sidebar import SidebarApp

        _write_state(
            state_dir,
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "mode": "study",
                "started_at": "2026-04-02T12:00:00+00:00",
            },
        )

        async with SidebarApp().run_test(size=(40, 20)) as pilot:
            await pilot.pause()  # let mount + compose complete
            status = pilot.app.query_one("#status")
            assert "pause" in str(status.render()).lower() or "p:" in str(status.render())


class TestSidebarKeyBindings:
    """Test that key bindings trigger the correct actions."""

    @pytest.mark.asyncio
    async def test_q_triggers_end_session_action(self, state_dir):
        """Pressing Q should call action_end_session and run cleanup --
        never the blanket kill_all_study_sessions sweep (R-02b: this test
        used to assert the opposite, pinning the bug it now guards against;
        see docs/architecture/session-authority.md clause 4)."""
        from studyloop.tui.sidebar import SidebarApp

        _write_state(
            state_dir,
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "mode": "study",
                "tmux_session": "study-test-123",
                "tmux_main_pane": "%0",
                "mux_session": "study-test-123",
                "mux_main_pane": "%0",
                "started_at": "2026-04-02T12:00:00+00:00",
            },
        )

        mock_backend = MagicMock()
        mock_backend.list_study_sessions.return_value = ["study-test-123"]
        mock_cleanup = MagicMock()

        with (
            patch("studyloop.multiplexer.get_backend", return_value=mock_backend),
            patch("studyloop.session.cleanup.cleanup_on_exit", mock_cleanup),
        ):
            async with SidebarApp().run_test(size=(40, 20)) as pilot:
                await pilot.press("Q")
                await pilot.pause()

                mock_cleanup.assert_called_once()
                mock_backend.kill_all_study_sessions.assert_not_called()

    @pytest.mark.asyncio
    async def test_end_session_leaves_an_unrelated_study_session_alive(self, state_dir):
        """R-02b: End Session used to call kill_all_study_sessions() directly
        (in addition to cleanup_on_exit's own, now correctly-scoped kill),
        which kills every study-* session on the machine. With a second,
        unrelated study-* session also present, ending THIS one must leave
        the other alive -- the same guarantee R-02 already made for the web
        and CLI end paths.

        cleanup_on_exit runs for real here (not mocked away) so the actual
        _cleanup_tmux_and_files scoping is exercised end to end; every DB
        write it touches is mocked so nothing reaches a real database.
        """
        from studyloop.tui.sidebar import SidebarApp

        _write_state(
            state_dir,
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "mode": "study",
                "tmux_session": "study-test-123",
                "tmux_main_pane": "%0",
                "mux_session": "study-test-123",
                "mux_main_pane": "%0",
                "started_at": "2026-04-02T12:00:00+00:00",
            },
        )

        mock_backend = MagicMock()
        # Two fake study-* sessions exist: this one, and an unrelated other.
        mock_backend.list_study_sessions.return_value = ["study-test-123", "study-other-999"]
        mock_backend.kill_session.return_value = True

        with (
            patch("studyloop.multiplexer.get_backend", return_value=mock_backend),
            patch("studyloop.history.end_study_session"),
            patch("studyloop.history.record_progress"),
            patch("studyloop.services.backlog.auto_persist_struggled"),
        ):
            async with SidebarApp().run_test(size=(40, 20)) as pilot:
                await pilot.press("Q")
                await pilot.pause()

        mock_backend.kill_all_study_sessions.assert_not_called()
        killed_names = [c.args[0] for c in mock_backend.kill_session.call_args_list]
        assert "study-other-999" not in killed_names

    @pytest.mark.asyncio
    async def test_q_sends_exit_to_agent_pane(self, state_dir):
        """Pressing Q should send /exit to the agent pane before killing."""
        from studyloop.tui.sidebar import SidebarApp

        _write_state(
            state_dir,
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "mode": "study",
                "tmux_session": "study-test-123",
                "tmux_main_pane": "%0",
                "mux_session": "study-test-123",
                "mux_main_pane": "%0",
                "started_at": "2026-04-02T12:00:00+00:00",
            },
        )

        mock_backend = MagicMock()

        with (
            patch("studyloop.multiplexer.get_backend", return_value=mock_backend),
            patch("studyloop.session.cleanup.cleanup_on_exit"),
        ):
            async with SidebarApp().run_test(size=(40, 20)) as pilot:
                await pilot.press("Q")
                await pilot.pause()

                # Check that send_keys was called with /exit
                exit_calls = [
                    call for call in mock_backend.send_keys.call_args_list if "/exit" in call.args
                ]
                assert len(exit_calls) > 0, (
                    f"/exit not sent. send_keys calls: {mock_backend.send_keys.call_args_list}"
                )

    @pytest.mark.asyncio
    async def test_p_toggles_pause(self, state_dir):
        """Pressing p should toggle the pause state."""
        from studyloop.tui.sidebar import SidebarApp

        _write_state(
            state_dir,
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "mode": "study",
                "started_at": "2026-04-02T12:00:00+00:00",
                "paused_at": None,
                "total_paused_seconds": 0,
            },
        )

        async with SidebarApp().run_test(size=(40, 20)) as pilot:
            await pilot.press("p")
            await pilot.pause()

            # State file should now have paused_at set
            state = json.loads((state_dir / "session-state.json").read_text())
            assert state.get("paused_at") is not None, "paused_at should be set after pressing p"
