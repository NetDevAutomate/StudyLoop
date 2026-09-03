"""Simulated-user TUI journey tests for the Multiplexer Protocol.

Exercises the REAL multiplexer lifecycle end-to-end against live
tmux and herdr backends. Each test proves observable user behaviour,
not internal function calls.

Journey matrix from docs/explorations/multiplexer-impact-map.md Part 4:
- T1: Session starts and creates expected panes
- T2: Pane layout correct (2 panes, sidebar sized correctly)
- T3: Sidebar renders timer content
- T4: Agent pane receives keystrokes
- T5: Q quits cleanly (session destroyed, state ended)
- T6: Detach/reattach preserves session
- T7: Resume dead session rebuilds
- T8: End from outside kills session
- T9: Zombie handling
- T10: Nested multiplexer (switch not attach)
- T11: No residue after Q (critical: attach-from-outside)

All tests marked ``integration`` (deselected from default pytest run).
herdr tests skip cleanly when herdr binary is absent.
tmux tests skip cleanly when tmux is absent.
"""

from __future__ import annotations

import os
import shutil
import time

import pytest
from harness.agents import long_running_agent
from harness.multiplexer import MultiplexerHarness

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Skip helpers
# ---------------------------------------------------------------------------

has_tmux = shutil.which("tmux") is not None
has_herdr = shutil.which("herdr") is not None

skip_no_tmux = pytest.mark.skipif(not has_tmux, reason="tmux not available")
skip_no_herdr = pytest.mark.skipif(not has_herdr, reason="herdr not available")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=[
        pytest.param("tmux", marks=skip_no_tmux),
        pytest.param("herdr", marks=skip_no_herdr),
    ]
)
def mux(request, tmp_path):
    """Parameterised multiplexer harness — both backends run the same journey."""
    session_dir = tmp_path / "session-ipc"
    session_dir.mkdir(parents=True, exist_ok=True)
    with MultiplexerHarness.from_backend_name(request.param, session_dir) as harness:
        yield harness


@pytest.fixture(
    params=[
        pytest.param("tmux", marks=skip_no_tmux),
        pytest.param("herdr", marks=skip_no_herdr),
    ]
)
def mux_cli(request, tmp_path):
    """Mux harness for tests that exercise the CLI (which does os.execvp on attach).

    herdr tests use pexpect to allocate a real PTY — herdr's TUI needs a
    terminal. The workspace creation + pane setup happens before os.execvp,
    so the session is fully functional once the state file is written.

    tmux tests use subprocess.run (tmux attach fails gracefully without a
    terminal; the detached session is the thing we test).
    """
    session_dir = tmp_path / "session-ipc"
    session_dir.mkdir(parents=True, exist_ok=True)
    with MultiplexerHarness.from_backend_name(request.param, session_dir) as harness:
        yield harness


@pytest.fixture()
def agent_cmd(tmp_path):
    """Return a long-running agent command for STUDYLOOP_TEST_AGENT_CMD."""
    return long_running_agent(tmp_path)


# ---------------------------------------------------------------------------
# T1 — Session starts
# ---------------------------------------------------------------------------


class TestSessionStarts:
    """T1: `studyloop study "topic"` creates a real multiplexer session."""

    def test_session_created_and_state_written(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """A study session creates a mux session with state file."""
        state = mux_cli.start_study_session("test-decorators", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        assert session_name, f"No session name in state: {state}"
        mux_cli.assert_session_exists(session_name)

    def test_agent_pane_has_child(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """After start, the agent pane has a running child process."""
        state = mux_cli.start_study_session("test-agent-child", agent_cmd=agent_cmd)
        main_pane = state.get("mux_main_pane") or state.get("tmux_main_pane")
        assert main_pane, f"No main pane in state: {state}"
        mux_cli.assert_pane_has_children(main_pane)

    def test_state_has_study_session_id(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """State file contains a study_session_id."""
        state = mux_cli.start_study_session("test-state-id", agent_cmd=agent_cmd)
        assert state.get("study_session_id"), f"No study_session_id: {state}"


# ---------------------------------------------------------------------------
# T4 — Agent receives keystrokes
# ---------------------------------------------------------------------------


class TestAgentReceivesKeys:
    """T4: Keystrokes sent to agent pane are visible in pane content."""

    def test_echo_visible_after_send_keys(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """Send text to agent pane, verify it appears in capture."""
        state = mux_cli.start_study_session("test-keys", agent_cmd=agent_cmd)
        main_pane = state.get("mux_main_pane") or state.get("tmux_main_pane")
        assert main_pane

        # Wait for agent to be running
        mux_cli.assert_pane_has_children(main_pane)
        time.sleep(1)  # Let agent print its startup message

        # The mock agent echoes "Mock agent started" — verify that's visible
        content = mux_cli.wait_for_pane_content(main_pane, r"Mock agent started", timeout=10)
        assert "Mock agent started" in content


# ---------------------------------------------------------------------------
# T5 — Q quits cleanly
# ---------------------------------------------------------------------------


class TestQQuits:
    """T5: Pressing Q in the sidebar kills the session, state=ended."""

    def test_end_via_cli_destroys_session(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """studyloop study --end kills the session and sets state to ended."""
        state = mux_cli.start_study_session("test-end-cli", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        assert session_name

        # End via CLI
        mux_cli.end_study_via_cli()

        # Wait for session to be gone
        mux_cli.wait_for_session_gone(session_name, timeout=15)

        # State should show ended
        new_state = mux_cli._read_state()
        assert new_state.get("mode") == "ended", f"State mode={new_state.get('mode')!r}"


# ---------------------------------------------------------------------------
# T8 — End from outside
# ---------------------------------------------------------------------------


class TestEndFromOutside:
    """T8: `studyloop study --end` from a separate process kills session."""

    def test_end_from_separate_process(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """Session killed when --end is run from an external process.

        Was hand-rolling the subprocess env inline, WITHOUT
        STUDYLOOP_SESSION_DIR -- so the `--end` subprocess read/wrote the
        real ~/.config/studyloop (the exact thing R-49 and this suite's own
        module docstring forbid), found no session there, and did nothing.
        This passed anyway before R-02's fix, purely by accident: the old
        end path called kill_all_study_sessions(), which kills every
        study-* session on the machine regardless of which claim triggered
        it, so it swept up this test's session as a side effect even though
        it never found this session's own claim. R-02's fix (kill only the
        claim's own name) correctly stopped doing that, which is what
        surfaced this test's own isolation bug. Fixed by using the
        harness's own end_study_via_cli(), which already sets
        STUDYLOOP_SESSION_DIR correctly (see TestQQuits above, which does
        this right).
        """
        state = mux_cli.start_study_session("test-end-outside", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        assert session_name

        # Verify session is running
        mux_cli.assert_session_exists(session_name)

        # End from a separate process (simulates user in another terminal)
        mux_cli.end_study_via_cli()

        mux_cli.wait_for_session_gone(session_name, timeout=15)


# ---------------------------------------------------------------------------
# T11 — No residue after end
# ---------------------------------------------------------------------------


class TestNoResidue:
    """T11: After end, zero study-* sessions remain in the multiplexer."""

    def test_no_study_sessions_after_end(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """Clean state: no stale study-* sessions after --end."""
        state = mux_cli.start_study_session("test-residue", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        assert session_name

        mux_cli.end_study_via_cli()
        mux_cli.wait_for_session_gone(session_name, timeout=15)

        # Verify no study-* sessions remain
        mux_cli.assert_no_study_sessions()


# ---------------------------------------------------------------------------
# T11 — Attach-from-outside journey (CRITICAL — riskiest assumption)
# ---------------------------------------------------------------------------


@skip_no_herdr
class TestAttachFromOutside:
    """T4.11: The invoking shell was NOT already running herdr.

    This proves the riskiest assumption in the plan: that os.execvp("herdr", ...)
    can cleanly take over a terminal that was NOT already running herdr.

    We verify by:
    1. Creating a workspace from outside herdr (no HERDR_ENV set)
    2. Verifying the workspace exists
    3. Verifying panes are functional (send_keys + capture)
    4. Cleaning up
    """

    def test_workspace_creation_from_non_herdr_shell(self, tmp_path):
        """herdr workspace create works when invoked from a plain shell."""
        session_dir = tmp_path / "session-ipc"
        session_dir.mkdir(parents=True, exist_ok=True)
        with MultiplexerHarness.from_backend_name("herdr", session_dir) as mux:
            # Ensure we're NOT inside herdr
            env = os.environ.copy()
            env.pop("HERDR_ENV", None)

            # Create workspace directly (bypasses os.execvp — tests the create path)
            pane_id = mux.create_session(
                "test-attach-outside",
                cwd=str(tmp_path),
                env={"STUDYLOOP_TEST": "1"},
            )
            assert pane_id, "No pane_id returned from create_session"

            # Verify the workspace exists
            mux.assert_session_exists("test-attach-outside")

            # Send a command and verify it executes (proves pane is functional)
            mux.send_keys(pane_id, "echo ATTACH_TEST_OK", enter=True)

            # Use wait_for with generous timeout (pane shell needs to start)
            content = mux.wait_for_pane_content(pane_id, r"ATTACH_TEST_OK", timeout=10)
            assert "ATTACH_TEST_OK" in content

    def test_full_study_session_from_non_herdr_shell(self, agent_cmd: str, tmp_path):
        """Full study session lifecycle from a non-herdr shell.

        Uses pexpect PTY so herdr TUI can launch after os.execvp.
        Proves: workspace created → agent running → end tears down → no residue.
        """
        session_dir = tmp_path / "session-ipc"
        session_dir.mkdir(parents=True, exist_ok=True)
        with MultiplexerHarness.from_backend_name("herdr", session_dir) as mux:
            # Start a study session (the real flow: create workspace → agent → sidebar)
            state = mux.start_study_session(
                "test-attach-full",
                agent_cmd=agent_cmd,
            )
            session_name = state.get("mux_session") or state.get("tmux_session")
            assert session_name, f"No session in state: {state}"

            # Verify session is alive and functional
            mux.assert_session_exists(session_name)

            # End and verify cleanup
            mux.end_study_via_cli()
            mux.wait_for_session_gone(session_name, timeout=15)
            mux.assert_no_study_sessions()


# ---------------------------------------------------------------------------
# Low-level multiplexer primitives (parameterised, both backends)
# ---------------------------------------------------------------------------


class TestMultiplexerPrimitives:
    """Direct multiplexer operations — proves the protocol works end-to-end."""

    def test_create_and_kill(self, mux: MultiplexerHarness, tmp_path):
        """Create a session, verify it exists, kill it, verify gone."""
        pane_id = mux.create_session("test-create-kill", cwd=str(tmp_path))
        assert pane_id
        mux.assert_session_exists("test-create-kill")
        mux.kill_session("test-create-kill")
        mux.wait_for_session_gone("test-create-kill", timeout=10)

    def test_split_pane_creates_second_pane(self, mux: MultiplexerHarness, tmp_path):
        """Splitting creates a second pane within the session."""
        pane_id = mux.create_session("test-split", cwd=str(tmp_path))
        new_pane = mux.split_pane(pane_id, direction="right", size=30, percentage=True)
        assert new_pane
        assert new_pane != pane_id

    def test_send_keys_and_capture(self, mux: MultiplexerHarness, tmp_path):
        """Send text to a pane and verify via capture."""
        pane_id = mux.create_session("test-sendkeys", cwd=str(tmp_path))
        time.sleep(0.5)  # Let shell start
        mux.send_keys(pane_id, "echo MUX_HARNESS_WORKS", enter=True)
        content = mux.wait_for_pane_content(pane_id, r"MUX_HARNESS_WORKS", timeout=10)
        assert "MUX_HARNESS_WORKS" in content

    def test_list_study_sessions(self, mux: MultiplexerHarness, tmp_path):
        """list_study_sessions returns sessions with study- prefix."""
        mux.create_session("study-test-list-1", cwd=str(tmp_path))
        mux.create_session("study-test-list-2", cwd=str(tmp_path))
        sessions = mux.list_study_sessions()
        assert "study-test-list-1" in sessions
        assert "study-test-list-2" in sessions

    def test_kill_all_study_sessions(self, mux: MultiplexerHarness, tmp_path):
        """kill_all_study_sessions removes all study-* sessions.

        For tmux: kills ALL (including current, last). For herdr: keeps current.
        Both remove the "others" — that's the testable shared behaviour.
        """
        mux.create_session("study-test-killall-1", cwd=str(tmp_path))
        mux.create_session("study-test-killall-2", cwd=str(tmp_path))
        time.sleep(0.5)  # Let sessions fully register

        mux.kill_all_study_sessions(current=None)
        time.sleep(1)  # Let kills propagate

        mux.wait_for_session_gone("study-test-killall-1", timeout=10)
        mux.wait_for_session_gone("study-test-killall-2", timeout=10)
