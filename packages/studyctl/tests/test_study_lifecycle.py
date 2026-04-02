"""Lifecycle tests for studyctl study — uses the test harness.

Tests the full study command lifecycle: start → validate → interact → end.
Uses real tmux sessions with mock agents for deterministic, fast tests.

Requires: tmux installed. Marked as integration (skipped on CI).

Run with:
    uv run pytest tests/test_study_lifecycle.py -v
    uv run pytest tests/test_study_lifecycle.py -v -k "start"
    uv run pytest tests/test_study_lifecycle.py -v -k "quit"
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Add tests/ to sys.path so the harness package is importable.
# Cannot use conftest.py because the agent-session-tools package also has
# tests/conftest.py, causing a pluggy namespace collision.
_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

import pytest  # noqa: E402
from harness.agents import fast_exit_agent, parking_agent, topic_logger_agent  # noqa: E402
from harness.study import StudySession  # noqa: E402

# Skip entire module if tmux is not installed
pytestmark = [
    pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
    pytest.mark.integration,
]


@pytest.fixture
def study_session(tmp_path):
    """Provide a StudySession that cleans up after itself."""
    with StudySession(tmp_path) as session:
        yield session


# ======================================================================
# Session Start
# ======================================================================


class TestSessionStart:
    """Verify that studyctl study creates the expected tmux environment."""

    def test_creates_tmux_session_with_two_panes(self, study_session):
        """A new session should have exactly 2 panes: agent + sidebar."""
        study_session.start("Test Topic")
        study_session.assert_pane_count(2)

    def test_agent_pane_has_running_process(self, study_session):
        """The agent (mock) should be running in the main pane."""
        study_session.start("Test Topic")
        study_session.assert_agent_running()

    def test_sidebar_pane_has_running_process(self, study_session):
        """The Textual sidebar should be running in the right pane."""
        study_session.start("Test Topic")
        study_session.assert_sidebar_running()

    def test_state_file_has_expected_fields(self, study_session):
        """The session state file should contain all required fields."""
        study_session.start("Decorators", energy=7)
        study_session.assert_state_has(
            topic="Decorators",
            energy=7,
            mode="study",
        )
        state = study_session.state
        assert state.get("study_session_id"), "Missing study_session_id"
        assert state.get("tmux_session"), "Missing tmux_session"
        assert state.get("tmux_main_pane"), "Missing tmux_main_pane"
        assert state.get("tmux_sidebar_pane"), "Missing tmux_sidebar_pane"

    def test_agent_pane_shows_output(self, study_session):
        """The agent pane should show the mock agent's output."""
        study_session.start("Test Topic")
        study_session.assert_pane_contains("main", "Mock agent started")

    def test_sidebar_shows_timer(self, study_session):
        """The sidebar should render a timer display."""
        study_session.start("Test Topic")
        # Timer format is HH:MM or MM:SS — look for digits:digits
        study_session.assert_pane_contains("sidebar", r"\d+:\d+")


# ======================================================================
# Sidebar Updates
# ======================================================================


class TestSidebarUpdates:
    """Verify that agent activity appears in the sidebar."""

    def test_topics_appear_in_sidebar(self, study_session, tmp_path):
        """Topics logged by the agent should appear in the sidebar feed."""
        agent = topic_logger_agent(tmp_path, [("Closures", "learning", "basics")])
        study_session.start("Test Topic", agent_cmd=agent)
        # Wait for the topic to propagate through IPC → sidebar poll
        study_session.assert_pane_contains("sidebar", "Closures", timeout=20)

    def test_parking_appears_in_sidebar(self, study_session, tmp_path):
        """Parked questions should appear in the sidebar."""
        agent = parking_agent(tmp_path)
        study_session.start("Test Topic", agent_cmd=agent)
        study_session.assert_pane_contains("sidebar", "metaclasses", timeout=20)

    def test_win_counter_updates(self, study_session, tmp_path):
        """Win counter should update when a topic is marked as win."""
        agent = topic_logger_agent(tmp_path, [("Closures", "win", "nailed it")])
        study_session.start("Test Topic", agent_cmd=agent)
        # Counter format: ✓ 1  (at least 1 win)
        study_session.assert_pane_contains("sidebar", r"[✓✔] 1", timeout=20)


# ======================================================================
# Quit Flow
# ======================================================================


class TestQuitFlow:
    """Verify that Q in the sidebar cleanly ends everything."""

    def test_q_kills_tmux_session(self, study_session):
        """Pressing Q should kill the tmux session."""
        study_session.start("Test Topic")
        study_session.assert_agent_running()
        study_session.end_via_q()
        # Session should be gone
        assert not study_session.tmux.session_exists(study_session.session_name)

    def test_state_set_to_ended_after_q(self, study_session):
        """After Q, the state file should have mode=ended."""
        study_session.start("Test Topic")
        study_session.end_via_q()
        study_session.assert_session_ended()


# ======================================================================
# Agent Exit / Cleanup
# ======================================================================


class TestAgentExit:
    """Verify cleanup when the agent exits on its own."""

    def test_fast_exit_triggers_cleanup(self, study_session, tmp_path):
        """When the agent exits, _cleanup_session should fire via the wrapper."""
        agent = fast_exit_agent(tmp_path)
        study_session.start("Test Topic", agent_cmd=agent)
        # The fast agent exits after ~2s; cleanup should set mode=ended
        study_session.tmux.wait_for(
            lambda: study_session.state.get("mode") == "ended",
            timeout=15,
            msg="mode not set to ended after agent exit",
        )

    def test_crash_agent_still_cleans_up(self, study_session, tmp_path):
        """Even if the agent crashes (exit 1), cleanup should still run."""
        from harness.agents import crash_agent

        agent = crash_agent(tmp_path)
        study_session.start("Test Topic", agent_cmd=agent)
        study_session.tmux.wait_for(
            lambda: study_session.state.get("mode") == "ended",
            timeout=15,
            msg="mode not set to ended after agent crash",
        )


# ======================================================================
# Resume Flow
# ======================================================================


class TestResumeFlow:
    """Verify --resume behaviour in various scenarios."""

    def test_resume_reconnects_to_live_session(self, study_session):
        """If the tmux session is alive with agent running, just reconnect."""
        study_session.start("Test Topic")
        study_session.assert_agent_running()
        original_session = study_session.session_name
        # Resume should find the existing session
        study_session.resume()
        assert study_session.session_name == original_session

    def test_resume_rebuilds_after_kill(self, study_session):
        """If the agent died but session dir exists, rebuild with -r."""
        study_session.start("Test Topic")
        study_session.assert_agent_running()
        # Kill the agent (simulate crash)
        study_session.kill_agent()
        # Wait for agent to actually die
        study_session.tmux.wait_for(
            lambda: not study_session.tmux.pane_has_children(study_session.main_pane),
            timeout=10,
            msg="agent didn't die after kill",
        )
        # Resume should detect zombie and rebuild
        study_session.resume()
        study_session.assert_agent_running()
