"""UAT tests — drive real terminal sessions via pexpect.

These tests replicate exactly what a user does: spawn studyctl study,
attach to the tmux session, press Q, verify the session dies.

Catches bugs that mock-agent tests miss (kill races, pane persistence,
nested tmux issues).

Requires: tmux installed + pexpect. Marked as integration (skipped on CI).

Run with:
    uv run pytest tests/test_uat_terminal.py -v
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Add tests/ to sys.path for harness imports
_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

import pytest  # noqa: E402
from harness.agents import long_running_agent  # noqa: E402
from harness.terminal import TerminalSession  # noqa: E402

pytestmark = [
    pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
    pytest.mark.integration,
]


@pytest.fixture
def terminal(tmp_path):
    """Provide a TerminalSession that cleans up after itself."""
    session = TerminalSession()
    yield session
    session.cleanup()


class TestQuitViaTerminal:
    """The critical UAT: Q must kill the tmux session from a real terminal."""

    def test_q_kills_session_from_attached_terminal(self, terminal, tmp_path):
        """Spawn study, attach via pexpect, send Q, verify session dies.

        This is the exact user flow that was failing: pressing Q in the
        sidebar while attached to the tmux session.
        """
        agent_cmd = long_running_agent(tmp_path)
        terminal.spawn_study("UAT Test", energy=5, agent_cmd=agent_cmd)

        assert terminal.session_exists(), "tmux session should exist after spawn"

        # Attach and send Q — this is what the user does
        killed = terminal.attach_and_send_q(timeout=15)

        assert killed, "tmux session should have been killed after Q"
        assert not terminal.session_exists(), "tmux session still exists after Q"

    def test_session_state_ended_after_q(self, terminal, tmp_path):
        """After Q, the state file should show mode=ended."""
        import json

        agent_cmd = long_running_agent(tmp_path)
        terminal.spawn_study("UAT State Test", energy=5, agent_cmd=agent_cmd)
        terminal.attach_and_send_q(timeout=15)

        state_file = Path.home() / ".config" / "studyctl" / "session-state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            assert state.get("mode") == "ended", f"Expected mode='ended', got {state.get('mode')!r}"


class TestResumeViaTerminal:
    """UAT: --resume should work after Q kills a session."""

    def test_resume_after_q_creates_new_session(self, terminal, tmp_path):
        """Start → Q → resume should create a new working session."""
        agent_cmd = long_running_agent(tmp_path)
        terminal.spawn_study("Resume UAT", energy=5, agent_cmd=agent_cmd)
        # Kill via Q
        terminal.attach_and_send_q(timeout=15)
        assert not terminal.session_exists(), "Session should be dead after Q"

        # Resume — should create new session
        terminal.spawn_study("Resume UAT", energy=5, agent_cmd=agent_cmd)
        assert terminal.session_exists(), "Resumed session should exist"


class TestCleanTmuxExit:
    """UAT: Q must leave zero tmux residue for non-technical users."""

    def test_q_leaves_no_study_sessions(self, terminal, tmp_path):
        """After Q, no study-* tmux sessions should remain."""
        agent_cmd = long_running_agent(tmp_path)
        terminal.spawn_study("Clean Exit", energy=5, agent_cmd=agent_cmd)
        terminal.attach_and_send_q(timeout=15)

        # Verify zero study sessions remain
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            study_sessions = [
                n for n in result.stdout.strip().splitlines() if n.startswith("study-")
            ]
            assert not study_sessions, f"Stale study sessions remain after Q: {study_sessions}"

    def test_q_cleans_stale_sessions(self, terminal, tmp_path):
        """Q should kill not just the current session but ALL stale study-* sessions."""
        # Create a stale session first
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", "study-stale-old-one"],
            capture_output=True,
        )
        assert (
            subprocess.run(
                ["tmux", "has-session", "-t", "study-stale-old-one"],
                capture_output=True,
            ).returncode
            == 0
        ), "Stale session should exist"

        # Start a real study session
        agent_cmd = long_running_agent(tmp_path)
        terminal.spawn_study("Stale Cleanup", energy=5, agent_cmd=agent_cmd)

        # Q should kill BOTH sessions
        terminal.attach_and_send_q(timeout=15)

        # Verify the stale session is also gone
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            study_sessions = [
                n for n in result.stdout.strip().splitlines() if n.startswith("study-")
            ]
            assert not study_sessions, f"Stale sessions survived Q: {study_sessions}"

    def test_q_detaches_client_not_switches(self, terminal, tmp_path):
        """With a non-study session present, Q should detach (exit tmux),
        NOT switch the client to the other session.

        This tests detach-on-destroy=on. Without it, tmux switches the
        client to user-workspace and the user is stranded in tmux.
        """
        import time

        import pexpect

        # Create a non-study session (simulates user's regular work)
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", "user-workspace"],
            capture_output=True,
        )

        try:
            # Start study session
            agent_cmd = long_running_agent(tmp_path)
            terminal.spawn_study("Detach Test", energy=5, agent_cmd=agent_cmd)
            session_name = terminal.session_name

            # Attach via pexpect — this is the real tmux client
            child = pexpect.spawn(
                f"tmux attach-session -t {session_name}",
                timeout=20,
                encoding="utf-8",
            )
            time.sleep(2)

            # Read sidebar pane and send Q
            import json
            from pathlib import Path

            state_file = Path.home() / ".config" / "studyctl" / "session-state.json"
            state = json.loads(state_file.read_text())
            sidebar_pane = state.get("tmux_sidebar_pane")

            if sidebar_pane:
                subprocess.run(
                    ["tmux", "send-keys", "-t", sidebar_pane, "Q"],
                    capture_output=True,
                )

            # KEY ASSERTION: pexpect should see EOF — client exited,
            # not switched to user-workspace. This proves detach-on-destroy.
            try:
                child.expect(pexpect.EOF, timeout=15)
                client_exited = True
            except pexpect.TIMEOUT:
                client_exited = False
            finally:
                if child.isalive():
                    child.close(force=True)
                else:
                    child.close()

            assert client_exited, (
                "tmux client did NOT exit after Q — it switched to another session "
                "instead of detaching. detach-on-destroy may not be set."
            )

            # Non-study session should still be alive
            assert (
                subprocess.run(
                    ["tmux", "has-session", "-t", "user-workspace"],
                    capture_output=True,
                ).returncode
                == 0
            ), "user-workspace should survive Q (only study-* killed)"

        finally:
            # Clean up the non-study session
            subprocess.run(
                ["tmux", "kill-session", "-t", "user-workspace"],
                capture_output=True,
            )
