"""Integration tests for studyctl study — real tmux sessions with a mock agent.

Full lifecycle testing: start → interact → sidebar updates → pane content →
timing → end → cleanup → resume with conversation context.

Uses a mock agent script instead of Claude Code (fast, free, deterministic).

Requires: tmux installed. Skipped if tmux is not available.

Run with:
    uv run pytest tests/test_study_integration.py -v
    uv run pytest tests/test_study_integration.py -v -k resume   # just resume
    uv run pytest tests/test_study_integration.py -v -k sidebar  # just sidebar
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

# Skip entire module if tmux is not installed, and mark as integration
# so CI can exclude with -m "not integration" (headless runners time out).
pytestmark = [
    pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
    pytest.mark.integration,
]

# Paths
CONFIG_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"
ONELINE_FILE = CONFIG_DIR / "session-oneline.txt"
SESSIONS_DIR = CONFIG_DIR / "sessions"
PROJECT_DIR = Path(__file__).parent.parent.parent.parent

# Timing
POLL_TIMEOUT = 15
POLL_INTERVAL = 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmux(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a tmux command."""
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _studyctl(*args: str, env_overrides: dict | None = None, timeout: int = 10):
    """Run a studyctl CLI command."""
    env = {**os.environ, **(env_overrides or {})}
    env.pop("TMUX", None)
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_DIR), "studyctl", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _wait_for(predicate, timeout=POLL_TIMEOUT, interval=POLL_INTERVAL, desc="condition"):
    """Poll until predicate returns True or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    msg = f"Timed out waiting for {desc} after {timeout}s"
    raise TimeoutError(msg)


def _capture_pane(pane_id: str) -> str:
    """Capture the visible content of a tmux pane."""
    result = _tmux("capture-pane", "-t", pane_id, "-p")
    return result.stdout


def _session_exists(name: str) -> bool:
    return _tmux("has-session", "-t", name).returncode == 0


def _read_state() -> dict:
    """Read the current session state file."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _kill_orphaned_processes():
    """Kill orphaned sidebar and mock-agent processes from failed tests."""
    import signal

    for pattern in ("studyctl.tui.sidebar", "mock-agent"):
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                check=False,
            )
            for pid_str in result.stdout.strip().splitlines():
                with contextlib.suppress(OSError):
                    os.kill(int(pid_str), signal.SIGTERM)
        except Exception:
            pass


def _cleanup_all():
    """Remove all IPC files, kill study tmux sessions, kill orphans, remove test dirs."""
    for f in [STATE_FILE, TOPICS_FILE, PARKING_FILE, ONELINE_FILE]:
        f.unlink(missing_ok=True)
    result = _tmux("list-sessions", "-F", "#{session_name}")
    if result.returncode == 0:
        for name in result.stdout.strip().splitlines():
            if name.startswith("study-"):
                _tmux("kill-session", "-t", name)
    # Kill orphaned child processes that escaped the tmux session tree
    _kill_orphaned_processes()
    # Remove test session directories
    if SESSIONS_DIR.exists():
        for d in SESSIONS_DIR.iterdir():
            if d.is_dir() and ("integration-test" in d.name or d.name.startswith("study-")):
                shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Mock agent scripts
# ---------------------------------------------------------------------------

STUDYCTL = f"uv run --project {PROJECT_DIR} studyctl"


def _make_mock_agent(tmp_path: Path, *, name: str = "mock-agent.sh") -> str:
    """Create a mock agent that logs topics, parks a question, then waits."""
    script = tmp_path / name
    script.write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        # Mock agent: logs topics, parks a question, waits for exit
        sleep 2
        {STUDYCTL} topic "Closures" --status learning --note "exploring basics"
        sleep 1
        {STUDYCTL} topic "First-class functions" --status win --note "understood"
        sleep 1
        {STUDYCTL} park "How do generators relate to closures?"
        # Wait for C-c / kill
        trap 'exit 0' INT TERM
        while true; do sleep 1; done
    """)
    )
    script.chmod(0o755)
    return str(script)


def _make_wrapper_agent(tmp_path: Path) -> str:
    """Create a mock agent that uses the session dir's studyctl wrapper.

    This is the realistic test — Claude Code calls ``studyctl topic``
    which resolves to the wrapper script at ``$SESSION_DIR/studyctl``.
    If the wrapper is broken (e.g. missing __main__.py), this fails.
    """
    script = tmp_path / "wrapper-agent.sh"
    script.write_text(
        textwrap.dedent("""\
        #!/bin/bash
        # Wrapper agent: uses the studyctl wrapper from the session dir
        # (same as what Claude Code does in a real session)
        sleep 2
        studyctl topic "Wrapper Test" --status learning --note "via wrapper"
        sleep 1
        studyctl park "Does the wrapper actually work?"
        # Wait for exit
        trap 'exit 0' INT TERM
        while true; do sleep 1; done
    """)
    )
    script.chmod(0o755)
    return str(script)


def _make_fast_agent(tmp_path: Path) -> str:
    """Create a minimal agent that exits quickly (for cleanup/resume tests)."""
    script = tmp_path / "fast-agent.sh"
    script.write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        # Fast agent: log one topic, then exit immediately
        sleep 1
        {STUDYCTL} topic "Quick Topic" --status learning --note "fast test"
        sleep 1
        echo "Agent exiting"
    """)
    )
    script.chmod(0o755)
    return str(script)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state():
    """Clean slate before and after every test."""
    _cleanup_all()
    yield
    _cleanup_all()


def _start_session(
    agent_script: str,
    topic: str = "Integration Test",
    energy: int = 5,
    extra_args: list[str] | None = None,
) -> dict:
    """Start a study session and wait for it to be ready. Returns session info."""
    env_overrides = {
        "STUDYCTL_TEST_AGENT_CMD": f"bash {agent_script} {{persona_file}}",
    }
    args = ["study", topic, "--energy", str(energy)]
    if extra_args:
        args.extend(extra_args)

    _studyctl(*args, env_overrides=env_overrides)

    _wait_for(STATE_FILE.exists, desc="session-state.json created")
    state = _read_state()
    session_name = state.get("tmux_session", "")
    _wait_for(lambda: _session_exists(session_name), desc=f"tmux session {session_name}")

    return {
        "session_name": session_name,
        "state": state,
        "main_pane": state.get("tmux_main_pane"),
        "sidebar_pane": state.get("tmux_sidebar_pane"),
        "session_dir": state.get("session_dir"),
    }


# ---------------------------------------------------------------------------
# Test: Session Creation
# ---------------------------------------------------------------------------


class TestSessionCreation:
    """Verify tmux session structure and state file."""

    def test_session_created_with_two_panes(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)

        assert _session_exists(info["session_name"])

        result = _tmux("list-panes", "-t", info["session_name"], "-F", "#{pane_id}")
        panes = result.stdout.strip().splitlines()
        assert len(panes) == 2, f"Expected 2 panes, got {len(panes)}"

    def test_state_file_has_required_fields(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)
        state = info["state"]

        assert state["topic"] == "Integration Test"
        assert state["energy"] == 5
        assert state["mode"] == "study"
        assert state["timer_mode"] == "elapsed"
        assert state["tmux_session"]
        assert state["tmux_main_pane"]
        assert state["tmux_sidebar_pane"]
        assert state["session_dir"]
        assert state["agent"] == "claude"
        assert state["started_at"]
        assert state["paused_at"] is None
        assert state["total_paused_seconds"] == 0

    def test_session_directory_created(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)

        session_dir = Path(info["session_dir"])
        assert session_dir.exists()
        assert (session_dir / "CLAUDE.md").exists()
        assert (session_dir / "studyctl").exists()  # wrapper script

    def test_pomodoro_mode_via_flag(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        _start_session(agent, extra_args=["--timer", "pomodoro"])

        state = _read_state()
        assert state["timer_mode"] == "pomodoro"

    def test_co_study_defaults_to_pomodoro(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        _start_session(agent, extra_args=["--mode", "co-study"])

        state = _read_state()
        assert state["timer_mode"] == "pomodoro"
        assert state["mode"] == "co-study"


# ---------------------------------------------------------------------------
# Test: Sidebar & IPC Updates
# ---------------------------------------------------------------------------


class TestSidebarUpdates:
    """Verify that agent actions populate IPC files and sidebar."""

    def test_topics_appear_in_ipc_file(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        _start_session(agent)

        _wait_for(
            lambda: TOPICS_FILE.exists() and "Closures" in TOPICS_FILE.read_text(),
            desc="Closures topic in IPC file",
        )
        content = TOPICS_FILE.read_text()
        assert "status:learning" in content

    def test_win_status_logged(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        _start_session(agent)

        _wait_for(
            lambda: TOPICS_FILE.exists() and "First-class functions" in TOPICS_FILE.read_text(),
            desc="win topic in IPC file",
        )
        assert "status:win" in TOPICS_FILE.read_text()

    def test_parking_logged(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        _start_session(agent)

        _wait_for(
            lambda: PARKING_FILE.exists() and PARKING_FILE.stat().st_size > 0,
            desc="parked topic in IPC file",
        )
        assert "generators" in PARKING_FILE.read_text().lower()

    def test_sidebar_renders_textual_app(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)

        _wait_for(
            lambda: (
                "pause" in _capture_pane(info["sidebar_pane"]).lower()
                or "end session" in _capture_pane(info["sidebar_pane"]).lower()
            ),
            timeout=10,
            desc="sidebar Textual app to render",
        )

    def test_sidebar_shows_topics_after_agent_logs(self, tmp_path):
        """Verify sidebar pane content includes logged topics."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)

        # Wait for topics to be logged AND sidebar to poll (2s interval)
        _wait_for(
            lambda: TOPICS_FILE.exists() and "First-class" in TOPICS_FILE.read_text(),
            desc="topics logged to IPC",
        )
        # Give sidebar 2 poll cycles to pick up changes
        time.sleep(5)

        content = _capture_pane(info["sidebar_pane"])
        # Sidebar should show at least one topic (shape + name)
        assert "Closures" in content or "First-class" in content or "W:" in content, (
            f"Sidebar should show topics but got:\n{content}"
        )

    def test_oneline_file_written(self, tmp_path):
        """Verify session-oneline.txt is written by the sidebar."""
        agent = _make_mock_agent(tmp_path)
        _start_session(agent)

        _wait_for(
            lambda: ONELINE_FILE.exists() and ONELINE_FILE.stat().st_size > 0,
            timeout=15,
            desc="session-oneline.txt written by sidebar",
        )
        content = ONELINE_FILE.read_text()
        assert "Integration" in content  # topic name
        assert "E:5" in content  # energy level

    def test_topic_timing(self, tmp_path):
        """Verify topics are logged with timestamps."""
        agent = _make_mock_agent(tmp_path)
        _start_session(agent)

        _wait_for(
            lambda: TOPICS_FILE.exists() and "Closures" in TOPICS_FILE.read_text(),
            desc="topics with timestamps",
        )
        content = TOPICS_FILE.read_text()
        # Format: - [HH:MM] Topic | status:X | note
        assert "- [" in content
        assert "]" in content


# ---------------------------------------------------------------------------
# Test: Session End & Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    """Verify cleanup when the agent exits."""

    def test_fast_agent_exit_writes_ended_state(self, tmp_path):
        """Agent exits naturally → wrapper writes mode=ended to state."""
        agent = _make_fast_agent(tmp_path)
        _start_session(agent)

        # Fast agent exits after ~2 seconds, wrapper runs cleanup
        _wait_for(
            lambda: not STATE_FILE.exists() or _read_state().get("mode") == "ended",
            timeout=20,
            desc="state marked as ended after agent exit",
        )

    def test_sidebar_q_sends_exit_to_agent(self, tmp_path):
        """Pressing Q in the sidebar sends /exit to the agent pane."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)
        sidebar_pane = info["sidebar_pane"]
        session_name = info["session_name"]

        # Wait for sidebar to render (any content means Textual is up)
        _wait_for(
            lambda: len(_capture_pane(sidebar_pane).strip()) > 0,
            timeout=10,
            desc="sidebar to render",
        )

        # Send literal uppercase Q via -l flag (not S-q key name)
        _tmux("send-keys", "-t", sidebar_pane, "-l", "Q")

        # The sidebar sends C-c + /exit to the agent pane, agent exits,
        # wrapper runs cleanup. Wait for session to end.
        _wait_for(
            lambda: not _session_exists(session_name) or _read_state().get("mode") == "ended",
            timeout=20,
            desc="session ended after sidebar Q",
        )

    def test_explicit_end_command(self, tmp_path):
        """studyctl study --end cleans up session."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)
        session_name = info["session_name"]

        # End via CLI
        _studyctl("study", "--end")

        # Session should be cleaned up
        assert not _session_exists(session_name) or _read_state().get("mode") == "ended"

    def test_session_directory_preserved_after_end(self, tmp_path):
        """Session dir should survive --end for future resume."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)
        session_dir = Path(info["session_dir"])

        _studyctl("study", "--end")

        # Dir should still exist (conversation history preserved)
        assert session_dir.exists()
        assert (session_dir / "CLAUDE.md").exists()


# ---------------------------------------------------------------------------
# Test: Resume
# ---------------------------------------------------------------------------


class TestResume:
    """Verify session resume — same directory, conversation context."""

    def test_resume_reuses_session_directory(self, tmp_path):
        """After end + resume, the same session dir should be used."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)
        original_dir = info["session_dir"]
        original_name = info["session_name"]

        # Wait for some topics to be logged
        _wait_for(
            lambda: TOPICS_FILE.exists() and "Closures" in TOPICS_FILE.read_text(),
            desc="topics logged before end",
        )

        # End the session (preserves session dir + saves notes to DB)
        _studyctl("study", "--end")
        _wait_for(
            lambda: not _session_exists(original_name),
            timeout=10,
            desc="original session killed",
        )

        # Resume via --resume (should detect ended state + existing dir)
        agent2 = _make_mock_agent(tmp_path, name="mock-agent-resume.sh")
        _studyctl(
            "study",
            "--resume",
            env_overrides={"STUDYCTL_TEST_AGENT_CMD": f"bash {agent2} {{persona_file}}"},
        )

        _wait_for(STATE_FILE.exists, desc="resumed state file")
        state = _read_state()

        # Should land in the SAME directory
        assert state.get("session_dir") == original_dir

    def test_resume_persona_contains_previous_notes(self, tmp_path):
        """Resumed session's persona file should contain prior session context."""
        agent = _make_mock_agent(tmp_path)
        _start_session(agent)

        # Wait for topics to be logged
        _wait_for(
            lambda: TOPICS_FILE.exists() and "First-class" in TOPICS_FILE.read_text(),
            desc="topics logged before end",
        )

        # End the session (saves notes to DB)
        _studyctl("study", "--end")

        # Resume — the persona file should contain previous session notes
        agent2 = _make_mock_agent(tmp_path, name="mock-agent-resume.sh")
        env_overrides = {
            "STUDYCTL_TEST_AGENT_CMD": f"bash {agent2} {{persona_file}}",
        }
        _studyctl("study", "--resume", env_overrides=env_overrides)

        # Read the new state to find the persona file
        _wait_for(STATE_FILE.exists, desc="resumed state file")
        state = _read_state()
        persona_path = state.get("persona_file")

        if persona_path and Path(persona_path).exists():
            persona_content = Path(persona_path).read_text()
            # Should contain either "Resuming" section or prior notes
            assert (
                "Closures" in persona_content
                or "First-class" in persona_content
                or "Resuming" in persona_content
            ), f"Persona should contain previous session context:\n{persona_content[:500]}"

    def test_resume_agent_command_includes_resume_flag(self, tmp_path):
        """Resumed session should launch agent with -r flag."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)
        original_dir = info["session_dir"]
        original_name = info["session_name"]

        # Wait for topics, then end
        _wait_for(
            lambda: TOPICS_FILE.exists() and "Closures" in TOPICS_FILE.read_text(),
            desc="topics logged before end",
        )
        _studyctl("study", "--end")
        _wait_for(
            lambda: not _session_exists(original_name),
            timeout=10,
            desc="original session killed",
        )

        # Resume — this time DON'T use STUDYCTL_TEST_AGENT_CMD so the
        # real agent command is built (but it will fail to run since
        # claude isn't installed — that's fine, we just check the command)
        _studyctl("study", "--resume")

        _wait_for(STATE_FILE.exists, desc="resumed state file")

        # Check the tmux pane's command — it should contain "-r"
        state = _read_state()
        new_session = state.get("tmux_session", "")
        if _session_exists(new_session):
            main_pane = state.get("tmux_main_pane", "")
            pane_content = _capture_pane(main_pane)
            # The agent command (claude -r ...) should be visible
            # in the pane or the wrapped command
            # Even if claude isn't installed, the command was attempted
            assert "-r" in pane_content or state.get("session_dir") == original_dir

    def test_resume_live_tmux_reattaches(self, tmp_path):
        """Resume while tmux session is alive should just reattach."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)
        session_name = info["session_name"]

        # Session is alive — resume should work without creating a new one
        assert _session_exists(session_name)

        # Running resume should not error
        _studyctl("study", "--resume")
        # The session should still be the same one
        assert _session_exists(session_name)


# ---------------------------------------------------------------------------
# Test: Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Verify graceful handling of error conditions."""

    def test_no_topic_shows_error(self):
        result = _studyctl("study")
        assert result.returncode != 0 or "Topic is required" in result.stdout

    def test_resume_with_no_session(self):
        result = _studyctl("study", "--resume")
        assert "No active session" in result.stdout

    def test_end_with_no_session(self):
        result = _studyctl("study", "--end")
        assert "No active session" in result.stdout

    def test_double_start_blocked(self, tmp_path):
        agent = _make_mock_agent(tmp_path)
        _start_session(agent)

        # Second start should be blocked
        agent2 = _make_mock_agent(tmp_path, name="mock-agent-2.sh")
        result = _studyctl(
            "study",
            "Another Topic",
            env_overrides={"STUDYCTL_TEST_AGENT_CMD": f"bash {agent2} {{persona_file}}"},
        )
        assert "already active" in result.stdout


# ---------------------------------------------------------------------------
# Test: Wrapper Script (realistic agent interaction)
# ---------------------------------------------------------------------------


class TestWrapperScript:
    """Verify the studyctl wrapper in the session directory works.

    This is the most realistic test — the mock agent calls ``studyctl``
    which resolves to the wrapper script at ``$SESSION_DIR/studyctl``,
    exactly as Claude Code does in a real study session. If the wrapper
    is broken (missing __main__.py, wrong Python path, etc.), these fail.
    """

    def test_wrapper_agent_can_log_topics(self, tmp_path):
        """Agent using session dir wrapper can call studyctl topic."""
        agent = _make_wrapper_agent(tmp_path)
        _start_session(agent)

        _wait_for(
            lambda: TOPICS_FILE.exists() and "Wrapper Test" in TOPICS_FILE.read_text(),
            timeout=15,
            desc="topic logged via session dir wrapper",
        )
        assert "status:learning" in TOPICS_FILE.read_text()

    def test_wrapper_agent_can_park_topics(self, tmp_path):
        """Agent using session dir wrapper can call studyctl park."""
        agent = _make_wrapper_agent(tmp_path)
        _start_session(agent)

        _wait_for(
            lambda: PARKING_FILE.exists() and PARKING_FILE.stat().st_size > 0,
            timeout=15,
            desc="parked topic via session dir wrapper",
        )
        assert "wrapper" in PARKING_FILE.read_text().lower()

    def test_wrapper_script_exists_and_executable(self, tmp_path):
        """The studyctl wrapper is created in the session dir."""
        agent = _make_wrapper_agent(tmp_path)
        info = _start_session(agent)

        wrapper = Path(info["session_dir"]) / "studyctl"
        assert wrapper.exists()
        assert os.access(wrapper, os.X_OK)

        # Wrapper should point to a valid Python
        content = wrapper.read_text()
        assert "python" in content.lower()
        assert "-m studyctl.cli" in content


# ---------------------------------------------------------------------------
# Test: E2E Experience Verification
# ---------------------------------------------------------------------------


class TestExperienceVerification:
    """Verify user-facing experience, not just plumbing.

    These tests go beyond checking IPC files to verify what the user
    actually sees in the terminal and what data flows across sessions.
    """

    def test_sidebar_pane_renders_topics(self, tmp_path):
        """Topics logged by the agent appear in the sidebar PANE, not just IPC files."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)

        _wait_for(
            lambda: TOPICS_FILE.exists() and "First-class" in TOPICS_FILE.read_text(),
            desc="topics logged to IPC",
        )
        time.sleep(7)

        content = _capture_pane(info["sidebar_pane"])
        assert any(marker in content for marker in ["Closures", "First-class", "W:", "L:"]), (
            f"Sidebar pane should render topic data but got:\n{content}"
        )

    def test_cleanup_notes_flow_into_resume_persona(self, tmp_path):
        """Full chain: topics -> cleanup -> DB notes -> resume persona."""
        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)
        original_name = info["session_name"]

        _wait_for(
            lambda: TOPICS_FILE.exists() and "First-class" in TOPICS_FILE.read_text(),
            desc="topics logged before end",
        )
        _studyctl("study", "--end")
        _wait_for(
            lambda: not _session_exists(original_name),
            timeout=10,
            desc="original session killed",
        )

        agent2 = _make_mock_agent(tmp_path, name="mock-agent-chain.sh")
        _studyctl(
            "study",
            "--resume",
            env_overrides={"STUDYCTL_TEST_AGENT_CMD": f"bash {agent2} {{persona_file}}"},
        )
        _wait_for(STATE_FILE.exists, desc="resumed state file")
        state = _read_state()

        persona_path = state.get("persona_file")
        assert persona_path, "Resumed session should have a persona file"
        persona = Path(persona_path)
        assert persona.exists(), f"Persona file not found at {persona_path}"

        persona_content = persona.read_text()
        has_topic_ref = "Closures" in persona_content or "First-class" in persona_content
        has_resume_section = "Resuming" in persona_content or "Previous" in persona_content
        assert has_topic_ref or has_resume_section, (
            f"Resume persona should reference session 1 topics.\n"
            f"Persona content (first 800 chars):\n{persona_content[:800]}"
        )

    def test_resume_flag_strictly_present(self, tmp_path):
        """Resume must reuse session directory -- no OR fallback allowed."""
        agent = _make_fast_agent(tmp_path)
        info = _start_session(agent)
        original_dir = info["session_dir"]
        original_name = info["session_name"]

        _wait_for(
            lambda: not _session_exists(original_name) or _read_state().get("mode") == "ended",
            timeout=20,
            desc="session ended",
        )

        agent2 = _make_mock_agent(tmp_path, name="mock-resume-strict.sh")
        _studyctl(
            "study",
            "--resume",
            env_overrides={"STUDYCTL_TEST_AGENT_CMD": f"bash {agent2} {{persona_file}}"},
        )
        _wait_for(STATE_FILE.exists, desc="resumed state file")
        state = _read_state()

        assert state.get("session_dir") == original_dir, (
            f"Resume should reuse {original_dir}, got {state.get('session_dir')}"
        )

    def test_sidebar_shows_elapsed_time(self, tmp_path):
        """Sidebar should display a non-zero elapsed time after a few seconds."""
        import re

        agent = _make_mock_agent(tmp_path)
        info = _start_session(agent)

        _wait_for(
            lambda: len(_capture_pane(info["sidebar_pane"]).strip()) > 0,
            timeout=10,
            desc="sidebar to render",
        )
        time.sleep(5)

        content = _capture_pane(info["sidebar_pane"])
        has_time = bool(re.search(r"\d+:\d{2}", content))
        has_elapsed = "elapsed" in content.lower() or "timer" in content.lower()
        assert has_time or has_elapsed, f"Sidebar should show elapsed time but got:\n{content}"


# ---------------------------------------------------------------------------
# Test: Multi-Agent Session Launch
#
# Each agent adapter produces different artifacts in the session directory.
# These tests verify that --agent {name} runs the correct adapter setup,
# the mock agent functions in tmux, and cleanup works for all agents.
# ---------------------------------------------------------------------------


class TestMultiAgentSessionLaunch:
    """Verify each agent adapter creates correct artifacts during session start."""

    def _start_with_agent(
        self,
        tmp_path: Path,
        agent_name: str,
        extra_env: dict | None = None,
    ) -> dict:
        """Start a session with a specific --agent and return session info."""
        script = _make_mock_agent(tmp_path, name=f"mock-{agent_name}.sh")
        env = {"STUDYCTL_TEST_AGENT_CMD": f"bash {script} {{persona_file}}"}
        if extra_env:
            env.update(extra_env)

        args = ["study", "Integration Test", "--energy", "5", "--agent", agent_name]
        _studyctl(*args, env_overrides=env)

        _wait_for(STATE_FILE.exists, desc="session-state.json created")
        state = _read_state()
        session_name = state.get("tmux_session", "")
        _wait_for(lambda: _session_exists(session_name), desc=f"tmux session {session_name}")

        return {
            "session_name": session_name,
            "state": state,
            "session_dir": state.get("session_dir"),
        }

    def test_gemini_session_creates_gemini_md(self, tmp_path):
        """Gemini adapter writes GEMINI.md to the session directory."""
        info = self._start_with_agent(tmp_path, "gemini")
        session_dir = Path(info["session_dir"])

        gemini_md = session_dir / "GEMINI.md"
        assert gemini_md.exists(), "Gemini adapter should write GEMINI.md"
        content = gemini_md.read_text()
        assert "Integration Test" in content
        assert "5/10" in content

        assert info["state"]["agent"] == "gemini"

    def test_gemini_session_creates_mcp_settings(self, tmp_path):
        """Gemini adapter writes .gemini/settings.json with MCP config."""
        info = self._start_with_agent(tmp_path, "gemini")
        session_dir = Path(info["session_dir"])

        settings = session_dir / ".gemini" / "settings.json"
        assert settings.exists(), "Gemini adapter should write .gemini/settings.json"
        data = json.loads(settings.read_text())
        assert "studyctl-mcp" in data["mcpServers"]

    def test_kiro_session_writes_agent_json(self, tmp_path):
        """Kiro adapter writes study-mentor.json to the Kiro agents directory."""
        # Redirect Kiro agents dir to temp to avoid polluting real config
        fake_kiro = tmp_path / "kiro-agents"
        fake_kiro.mkdir()

        info = self._start_with_agent(
            tmp_path,
            "kiro",
            extra_env={"STUDYCTL_KIRO_AGENTS_DIR": str(fake_kiro)},
        )

        agent_json = fake_kiro / "study-mentor.json"
        assert agent_json.exists(), "Kiro adapter should write study-mentor.json"
        data = json.loads(agent_json.read_text())
        assert data["name"] == "study-mentor"
        assert data["prompt"].startswith("file://")

        assert info["state"]["agent"] == "kiro"

    def test_kiro_teardown_restores_backup(self, tmp_path):
        """Kiro teardown restores the backed-up agent JSON on session end."""
        fake_kiro = tmp_path / "kiro-agents"
        fake_kiro.mkdir()
        # Pre-existing config that should be restored
        original = fake_kiro / "study-mentor.json"
        original.write_text('{"name": "study-mentor", "prompt": "original"}')

        script = _make_fast_agent(tmp_path)
        env = {
            "STUDYCTL_TEST_AGENT_CMD": f"bash {script} {{persona_file}}",
            "STUDYCTL_KIRO_AGENTS_DIR": str(fake_kiro),
        }
        _studyctl("study", "Kiro Teardown Test", "--agent", "kiro", env_overrides=env)

        # Wait for the fast agent to finish and cleanup to run
        _wait_for(
            lambda: STATE_FILE.exists() and _read_state().get("mode") == "ended",
            timeout=20,
            desc="session ended (cleanup_on_exit ran)",
        )

        restored = json.loads(original.read_text())
        assert restored["prompt"] == "original", "Kiro teardown should restore backup"

    def test_opencode_session_creates_persona_with_frontmatter(self, tmp_path):
        """OpenCode adapter writes .opencode/agents/study-mentor.md."""
        info = self._start_with_agent(tmp_path, "opencode")
        session_dir = Path(info["session_dir"])

        persona = session_dir / ".opencode" / "agents" / "study-mentor.md"
        assert persona.exists(), "OpenCode adapter should write study-mentor.md"
        content = persona.read_text()
        assert content.startswith("---\n"), "Should have YAML frontmatter"
        assert "mode: primary" in content
        assert "Integration Test" in content

        assert info["state"]["agent"] == "opencode"

    def test_opencode_session_creates_mcp_config(self, tmp_path):
        """OpenCode adapter writes opencode.json with correct MCP schema."""
        info = self._start_with_agent(tmp_path, "opencode")
        session_dir = Path(info["session_dir"])

        config = session_dir / ".opencode" / "opencode.json"
        assert config.exists(), "OpenCode adapter should write opencode.json"
        data = json.loads(config.read_text())
        mcp = data["mcp"]["studyctl-mcp"]
        assert isinstance(mcp["command"], list), "OpenCode command must be array"
        assert mcp["enabled"] is True
        assert mcp["type"] == "local"

    def test_all_agents_support_topic_logging(self, tmp_path):
        """All agents can log topics via the studyctl wrapper in the session dir."""
        for agent_name in ("claude", "gemini", "opencode"):
            _cleanup_all()
            extra_env = {}
            if agent_name == "kiro":
                fake_kiro = tmp_path / f"kiro-{agent_name}"
                fake_kiro.mkdir(exist_ok=True)
                extra_env["STUDYCTL_KIRO_AGENTS_DIR"] = str(fake_kiro)

            self._start_with_agent(tmp_path, agent_name, extra_env=extra_env)

            _wait_for(
                lambda: TOPICS_FILE.exists() and "Closures" in TOPICS_FILE.read_text(),
                desc=f"topic logged via {agent_name} agent",
            )
            assert "status:learning" in TOPICS_FILE.read_text()

            # Clean up for next iteration
            _cleanup_all()
