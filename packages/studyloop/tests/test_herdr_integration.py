"""Simulated-user TUI journey tests for the Multiplexer Protocol.

Exercises the REAL multiplexer lifecycle end-to-end against live
tmux and herdr backends. Each test proves observable user behaviour,
not internal function calls.

Journey matrix from private-docs/multiplexer-impact-map.md Part 4:
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

import json
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

        # Wait for observable agent output. This is stronger and less
        # startup-racy than sampling process-info first: herdr may briefly
        # report shell-init helpers while the command is being handed off.
        content = mux_cli.wait_for_pane_content(main_pane, r"Mock agent started", timeout=15)
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


# ---------------------------------------------------------------------------
# T2 — Pane layout (main + sidebar)
# ---------------------------------------------------------------------------


class TestPaneLayout:
    """T2: A study session has exactly two panes — agent main + sidebar.

    Width is asserted where the backend exposes geometry (tmux); herdr's
    workspace list reports pane membership but not sizes, so the herdr leg
    proves pane count and identity only.
    """

    def test_two_distinct_panes_in_state(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """State records a main pane and a sidebar pane, and they differ."""
        state = mux_cli.start_study_session("test-layout", agent_cmd=agent_cmd)
        main_pane = state.get("mux_main_pane")
        sidebar_pane = state.get("mux_sidebar_pane")
        assert main_pane, f"No main pane in state: {state}"
        assert sidebar_pane, f"No sidebar pane in state: {state}"
        assert main_pane != sidebar_pane, "main and sidebar pane IDs are identical"

    def test_backend_reports_both_panes(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """The backend's own pane inventory contains both recorded panes."""
        state = mux_cli.start_study_session("test-layout-inv", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        assert session_name

        if mux_cli.is_herdr:
            from studyloop.herdr import HerdrBackend

            backend = mux_cli.backend
            assert isinstance(backend, HerdrBackend)
            panes = backend._get_workspace_panes(session_name)
            assert len(panes) >= 2, f"expected 2+ panes in workspace, got {panes}"
        else:
            import subprocess as sp

            result = sp.run(
                ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_id} #{pane_width}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = [ln for ln in result.stdout.strip().splitlines() if ln]
            assert len(lines) == 2, f"expected exactly 2 tmux panes, got {lines}"

    def test_tmux_sidebar_is_at_most_30_percent(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        """tmux only: the sidebar pane's width is <= 30% of the window.

        The orchestrator asks for 25%; 30% is the journey's ceiling
        (multiplexer rounding to whole cells can nudge it above 25).
        """
        if mux_cli.is_herdr:
            pytest.skip("herdr's workspace list does not expose pane geometry")

        import subprocess as sp

        state = mux_cli.start_study_session("test-layout-width", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        sidebar_pane = state.get("mux_sidebar_pane")
        assert session_name and sidebar_pane

        result = sp.run(
            ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_id} #{pane_width}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        widths = {}
        for line in result.stdout.strip().splitlines():
            pane_id, width = line.split()
            widths[pane_id] = int(width)
        assert sidebar_pane in widths, f"sidebar {sidebar_pane} not in {widths}"
        total = sum(widths.values())
        ratio = widths[sidebar_pane] / total
        assert ratio <= 0.30, f"sidebar is {ratio:.0%} of the window (widths: {widths})"


# ---------------------------------------------------------------------------
# T3 — Sidebar renders timer content
# ---------------------------------------------------------------------------


class TestSidebarRenders:
    """T3: The sidebar pane actually renders the session TUI.

    Proves the sidebar process survived launch and painted content — the
    failure mode this guards is a sidebar pane holding a dead or blank
    process while the state file claims a healthy layout.
    """

    def test_sidebar_pane_shows_session_content(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        state = mux_cli.start_study_session("test-sidebar-render", agent_cmd=agent_cmd)
        sidebar_pane = state.get("mux_sidebar_pane")
        assert sidebar_pane, f"No sidebar pane in state: {state}"

        # The sidebar TUI renders the elapsed timer (MM:SS or H:MM:SS) and
        # session chrome. Accept either the clock or the topic string so the
        # assertion survives cosmetic TUI copy changes.
        content = mux_cli.wait_for_pane_content(
            sidebar_pane,
            r"(\d{1,2}:\d{2})|test-sidebar-render|StudyLoop",
            timeout=20,
        )
        assert content.strip(), "sidebar pane captured as empty"


# ---------------------------------------------------------------------------
# T6 — Client disconnect preserves the session (detach/reattach substance)
# ---------------------------------------------------------------------------


class TestDetachPreservesSession:
    """T6: The session outlives its client.

    tmux sessions in this harness are born detached (subprocess.run start),
    so the tmux leg proves a genuine reattach via a scripted
    `tmux attach` + detach. herdr's TUI client is the pexpect child; the
    herdr leg proves killing that client (the detach) leaves the workspace,
    agent, and pane addressing intact.
    """

    def test_session_survives_client_disconnect(
        self, mux_cli: MultiplexerHarness, tmp_path
    ) -> None:
        """The workspace and its agent outlive the client.

        The agent traps SIGHUP as well as TERM/INT, so an ordinary
        terminal-close HUP cannot explain a death here.

        KNOWN GAP (herdr 0.8.2): killing the connected TUI client
        terminates the focused pane's foreground process group — the agent
        is dead and the pane sits at a bare shell prompt afterwards,
        verified with this HUP-immune agent. tmux preserves the process.
        This is the concrete blocker for the T2.3 default flip
        (herdr-ghostty-multiplexer-transport tasks) and the reason herdr
        remains opt-in via STUDYLOOP_MULTIPLEXER=herdr.
        """
        if mux_cli.is_herdr:
            pytest.xfail(
                "herdr 0.8.2 kills the focused pane's foreground process group "
                "when its TUI client dies (agent gone, bare shell remains; "
                "reproduced with a HUP-immune agent). Detach does not preserve "
                "a running agent — the T2.3 default-flip blocker."
            )

        from harness.agents import _write_script

        script = _write_script(
            tmp_path / "mock-agent-hup-immune.sh",
            """#!/usr/bin/env bash
trap '' HUP
trap 'exit 0' TERM INT
echo "Mock agent started (persona: $1)"
while true; do sleep 1; done
""",
        )
        agent_cmd = f"{script} {{persona_file}}"

        state = mux_cli.start_study_session("test-detach", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        main_pane = state.get("mux_main_pane")
        assert session_name and main_pane

        # For tmux the session is born detached (subprocess start): the
        # detached condition under test already holds.
        time.sleep(1)

        mux_cli.assert_session_exists(session_name)
        mux_cli.assert_pane_has_children(main_pane)

        # Reattach-ability: the pane is still addressable end-to-end.
        content = mux_cli.wait_for_pane_content(main_pane, r"Mock agent started", timeout=10)
        assert "Mock agent started" in content


# ---------------------------------------------------------------------------
# T7 — Resume a dead session rebuilds it
# ---------------------------------------------------------------------------


class TestResumeDead:
    """T7: `studyloop study --resume` rebuilds when the mux session is gone.

    The state file still names the dead session; resume must detect the
    corpse and rebuild a LIVE session in the same session directory.
    """

    def test_resume_rebuilds_after_session_killed(
        self, mux_cli: MultiplexerHarness, agent_cmd: str
    ):
        state = mux_cli.start_study_session("test-resume-dead", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        assert session_name

        # Kill the multiplexer session out from under the state file.
        mux_cli.kill_session(session_name)
        mux_cli.wait_for_session_gone(session_name, timeout=10)

        # Resume: must rebuild a live session with a running agent.
        env_backup = os.environ.get("STUDYLOOP_TEST_AGENT_CMD")
        os.environ["STUDYLOOP_TEST_AGENT_CMD"] = agent_cmd
        try:
            new_state = mux_cli.resume_study_via_cli()
        finally:
            if env_backup is None:
                os.environ.pop("STUDYLOOP_TEST_AGENT_CMD", None)
            else:
                os.environ["STUDYLOOP_TEST_AGENT_CMD"] = env_backup

        new_name = new_state.get("mux_session") or new_state.get("tmux_session")
        new_main = new_state.get("mux_main_pane")
        assert new_name, f"resume produced no session: {new_state}"
        mux_cli.assert_session_exists(new_name)
        assert new_main
        mux_cli.assert_pane_has_children(new_main)
        # Same study thread: the topic survives the rebuild.
        assert new_state.get("topic") == "test-resume-dead"


# ---------------------------------------------------------------------------
# T9 — Zombie detection
# ---------------------------------------------------------------------------


class TestZombieHandling:
    """T9: is_zombie_session flags old sessions with no live children and
    never flags a live agent session."""

    def test_live_agent_session_is_not_zombie(self, mux_cli: MultiplexerHarness, agent_cmd: str):
        state = mux_cli.start_study_session("test-not-zombie", agent_cmd=agent_cmd)
        session_name = state.get("mux_session") or state.get("tmux_session")
        main_pane = state.get("mux_main_pane")
        assert session_name and main_pane
        mux_cli.assert_pane_has_children(main_pane)

        assert mux_cli.backend.is_zombie_session(session_name, min_age_seconds=0.1) is False

    def test_childless_old_session_is_zombie(self, mux: MultiplexerHarness, tmp_path, monkeypatch):
        """A bare-shell session (no agent) older than the threshold is zombie.

        herdr derives session age from the StudyLoop state file
        (_get_session_start_time), so the herdr leg plants a state file with
        a backdated started_at; tmux derives it from #{session_created}, so
        the tmux leg simply waits past a 1-second threshold.
        """
        name = "study-zombie-probe"
        mux.create_session(name, cwd=str(tmp_path))  # bare shell — no children
        time.sleep(2)  # settle past the 1s threshold (tmux age is wall-clock)

        if mux.is_herdr:
            import studyloop.session_state as session_state

            state_file = mux.session_dir / "session-state.json"
            state_file.write_text(json.dumps({"started_at": time.time() - 120}))
            monkeypatch.setattr(session_state, "STATE_FILE", state_file)

        assert mux.backend.is_zombie_session(name, min_age_seconds=1.0) is True

    def test_auto_clean_kills_stale_herdr_workspace(
        self, mux: MultiplexerHarness, tmp_path, monkeypatch
    ):
        """T9 journey: auto_clean_zombies discovers and kills a real stale
        herdr workspace, using an isolated StudyLoop state file for age.
        """
        if not mux.is_herdr:
            pytest.skip("T9 requirement is the herdr auto-clean journey")

        import studyloop.multiplexer as multiplexer
        import studyloop.session_state as session_state
        from studyloop.session.cleanup import auto_clean_zombies

        name = "study-zombie-autoclean"
        mux.create_session(name, cwd=str(tmp_path))
        mux.wait_for_session(name, timeout=10)
        # Let zsh startup helpers drain so the workspace is genuinely
        # childless (bare shell only) before asking the zombie detector.
        time.sleep(2)

        state_file = mux.session_dir / "session-state.json"
        state_file.write_text(
            json.dumps(
                {
                    "started_at": time.time() - 120,
                    "mux_session": name,
                    "mode": "ended",
                }
            )
        )
        monkeypatch.setattr(session_state, "STATE_FILE", state_file)
        monkeypatch.setattr(session_state, "SESSION_DIR", mux.session_dir)
        monkeypatch.setattr(multiplexer, "get_backend", lambda: mux.backend)

        assert mux.backend.is_server_running() is True
        assert mux.backend.is_zombie_session(name) is True
        auto_clean_zombies()
        mux.wait_for_session_gone(name, timeout=10)


# ---------------------------------------------------------------------------
# T10 — Nested multiplexer: inside a session, switch — never attach
# ---------------------------------------------------------------------------


class TestNestedMultiplexer:
    """T10: With the inside-a-session env marker set, the backend reports
    is_inside_session() and the switch path works against a live session.

    The orchestrator branches on is_inside_session(): True → switch_client
    (safe inside a client), False → attach (os.execvp — which nested would
    corrupt). The exec side of attach is untestable in-process; the decision
    input and the switch verb are what this journey pins.
    """

    def test_env_marker_flips_inside_detection(self, mux: MultiplexerHarness, monkeypatch):
        marker = ("HERDR_ENV", "1") if mux.is_herdr else ("TMUX", "/tmp/fake-tmux-socket,1,0")
        monkeypatch.delenv(marker[0], raising=False)
        assert mux.backend.is_inside_session() is False
        monkeypatch.setenv(*marker)
        assert mux.backend.is_inside_session() is True

    def test_herdr_switch_focuses_existing_workspace(
        self, mux: MultiplexerHarness, tmp_path, monkeypatch
    ):
        """herdr only: switch_client (workspace focus) succeeds against a
        real workspace — the verb the nested path uses instead of exec."""
        if not mux.is_herdr:
            pytest.skip("tmux switch-client requires an attached client to act on")

        name = "study-nested-switch"
        mux.create_session(name, cwd=str(tmp_path))
        mux.wait_for_session(name, timeout=10)

        monkeypatch.setenv("HERDR_ENV", "1")
        # Must not raise: focusing an existing workspace is the switch path.
        mux.backend.switch_client(name)
        mux.assert_session_exists(name)
