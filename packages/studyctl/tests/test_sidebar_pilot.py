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
# They DO need the studyctl package importable.


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Redirect session state to a temp directory."""
    state_dir = tmp_path / "studyctl"
    state_dir.mkdir()

    monkeypatch.setattr("studyctl.session_state.SESSION_DIR", state_dir)
    monkeypatch.setattr("studyctl.session_state.STATE_FILE", state_dir / "session-state.json")
    monkeypatch.setattr("studyctl.session_state.TOPICS_FILE", state_dir / "session-topics.md")
    monkeypatch.setattr("studyctl.session_state.PARKING_FILE", state_dir / "session-parking.md")

    # Also patch the sidebar's imported references
    monkeypatch.setattr("studyctl.tui.sidebar.SESSION_DIR", state_dir)
    monkeypatch.setattr("studyctl.tui.sidebar.STATE_FILE", state_dir / "session-state.json")
    monkeypatch.setattr("studyctl.tui.sidebar.TOPICS_FILE", state_dir / "session-topics.md")
    monkeypatch.setattr("studyctl.tui.sidebar.PARKING_FILE", state_dir / "session-parking.md")

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
        from studyctl.tui.sidebar import SidebarApp

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
        from studyctl.tui.sidebar import SidebarApp

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
            status = pilot.app.query_one("#status")
            assert "pause" in str(status.render()).lower() or "p:" in str(status.render())


class TestSidebarKeyBindings:
    """Test that key bindings trigger the correct actions."""

    @pytest.mark.asyncio
    async def test_q_triggers_end_session_action(self, state_dir):
        """Pressing Q should call action_end_session."""
        from studyctl.tui.sidebar import SidebarApp

        _write_state(
            state_dir,
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "mode": "study",
                "tmux_session": "study-test-123",
                "tmux_main_pane": "%0",
                "started_at": "2026-04-02T12:00:00+00:00",
            },
        )

        def _tmux_side_effect(*args, **_kwargs):
            """Mock tmux: list-sessions returns the study session name."""
            if args and args[0] == "list-sessions":
                return MagicMock(returncode=0, stdout="study-test-123\n")
            return MagicMock(returncode=0, stdout="")

        with (
            patch("studyctl.tmux._tmux", side_effect=_tmux_side_effect) as mock_tmux,
            patch("studyctl.session.cleanup.cleanup_on_exit"),
        ):
            async with SidebarApp().run_test(size=(40, 20)) as pilot:
                await pilot.press("Q")
                await pilot.pause()

                # Verify kill-session was called for the study session
                kill_calls = [
                    call
                    for call in mock_tmux.call_args_list
                    if len(call.args) >= 2 and call.args[0] == "kill-session"
                ]
                assert len(kill_calls) > 0, (
                    f"kill-session not called. tmux calls: {mock_tmux.call_args_list}"
                )

    @pytest.mark.asyncio
    async def test_q_sends_exit_to_agent_pane(self, state_dir):
        """Pressing Q should send /exit to the agent pane before killing."""
        from studyctl.tui.sidebar import SidebarApp

        _write_state(
            state_dir,
            {
                "study_session_id": "test-123",
                "topic": "Test",
                "energy": 5,
                "mode": "study",
                "tmux_session": "study-test-123",
                "tmux_main_pane": "%0",
                "started_at": "2026-04-02T12:00:00+00:00",
            },
        )

        with patch("studyctl.tmux._tmux") as mock_tmux:
            mock_tmux.return_value = MagicMock(returncode=0)

            with patch("studyctl.session.cleanup.cleanup_on_exit"):
                async with SidebarApp().run_test(size=(40, 20)) as pilot:
                    await pilot.press("Q")
                    await pilot.pause()

                    # Check that send-keys with /exit was called
                    send_calls = [
                        call
                        for call in mock_tmux.call_args_list
                        if len(call.args) >= 4
                        and call.args[0] == "send-keys"
                        and "/exit" in call.args
                    ]
                    assert len(send_calls) > 0, (
                        f"/exit not sent. tmux calls: {mock_tmux.call_args_list}"
                    )

    @pytest.mark.asyncio
    async def test_p_toggles_pause(self, state_dir):
        """Pressing p should toggle the pause state."""
        from studyctl.tui.sidebar import SidebarApp

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
