"""Autoresearch-style E2E test matrix for all agent adapters.

Parametrized over all 6 agents.  Each test uses a mock agent script
injected via ``STUDYCTL_TEST_AGENT_CMD``.

Run::

    uv run pytest tests/test_harness_matrix.py -v
    uv run pytest tests/test_harness_matrix.py -v -k claude      # single agent
    uv run pytest tests/test_harness_matrix.py -v -k "gemini or kiro"
    uv run pytest tests/test_harness_matrix.py -v -k claude      # single agent
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

# Path bootstrapping — no conftest.py (see MEMORY.md: pluggy conflict)
sys.path.insert(0, str(Path(__file__).parent))

from harness.agents import matrix_agent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENTS = ["claude", "gemini", "kiro", "opencode", "ollama", "lmstudio"]

TOPIC = "Harness Matrix"
ENERGY = 5
POLL_TIMEOUT = 20
POLL_INTERVAL = 0.5

CONFIG_DIR = Path.home() / ".config" / "studyctl"
STATE_FILE = CONFIG_DIR / "session-state.json"
TOPICS_FILE = CONFIG_DIR / "session-topics.md"
PARKING_FILE = CONFIG_DIR / "session-parking.md"
ONELINE_FILE = CONFIG_DIR / "session-oneline.txt"

pytestmark = [
    pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
    pytest.mark.e2e,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for(
    predicate,
    *,
    timeout: float = POLL_TIMEOUT,
    interval: float = POLL_INTERVAL,
    desc: str = "condition",
) -> bool:
    """Poll *predicate* until truthy or *timeout* seconds elapse."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {desc} after {timeout}s")


def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _session_exists(name: str) -> bool:
    if not name:
        return False
    r = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
        check=False,
    )
    return r.returncode == 0


def _make_test_config(tmp_path: Path) -> Path:
    """Write a minimal config with test topic and content path."""
    content_base = tmp_path / "study-materials"
    content_base.mkdir(exist_ok=True)
    config = tmp_path / "studyctl-matrix-config.yaml"
    config.write_text(
        f"topics:\n"
        f"  - name: {TOPIC}\n"
        f"    slug: harness-matrix\n"
        f"    obsidian_path: test/harness-matrix\n"
        f"    tags: [test, harness]\n"
        f"content:\n"
        f"  base_path: {content_base}\n"
    )
    return config


def _agent_extra_env(agent_name: str, tmp_path: Path) -> dict[str, str]:
    """Return agent-specific env vars needed for the adapter."""
    if agent_name == "kiro":
        kiro_dir = tmp_path / "kiro-agents"
        kiro_dir.mkdir(exist_ok=True)
        return {"STUDYCTL_KIRO_AGENTS_DIR": str(kiro_dir)}
    return {}


def _build_env(
    agent_name: str,
    agent_cmd: str,
    config_path: Path,
    tmp_path: Path,
) -> dict[str, str]:
    """Build the full subprocess environment."""
    env = {
        **os.environ,
        "STUDYCTL_TEST_AGENT_CMD": agent_cmd,
        "STUDYCTL_CONFIG": str(config_path),
        **_agent_extra_env(agent_name, tmp_path),
    }
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    return env


def _cleanup_all() -> None:
    """Kill stale sessions, processes, and IPC files."""
    for f in (STATE_FILE, TOPICS_FILE, PARKING_FILE, ONELINE_FILE):
        with contextlib.suppress(OSError):
            f.unlink(missing_ok=True)

    # Kill any study-* tmux sessions
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        for name in result.stdout.strip().splitlines():
            if name.startswith("study-"):
                subprocess.run(
                    ["tmux", "kill-session", "-t", name],
                    capture_output=True,
                    check=False,
                )

    # Kill orphaned mock agents and sidebar processes
    for pattern in ("mock-agent-matrix", "studyctl.tui.sidebar"):
        subprocess.run(["pkill", "-f", pattern], capture_output=True, check=False)


# ---------------------------------------------------------------------------
# Session metadata
# ---------------------------------------------------------------------------


@dataclass
class MatrixSession:
    """Metadata for an active matrix test session."""

    agent: str
    state: dict
    tmp_path: Path
    config_path: Path
    env: dict[str, str]
    content_base: Path
    session_name: str = ""
    ended: bool = False

    def read_state(self) -> dict:
        return _read_state()

    def end(self) -> None:
        """End the session via CLI."""
        if self.ended:
            return
        env = {**self.env}
        env.pop("STUDYCTL_TEST_AGENT_CMD", None)
        subprocess.run(
            [sys.executable, "-m", "studyctl.cli", "study", "--end"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.ended = True


# ---------------------------------------------------------------------------
# Parametrized fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class", params=AGENTS)
def matrix_session(request, tmp_path_factory):
    """Start a study session per agent, shared across all class tests."""
    agent_name = request.param
    tmp = tmp_path_factory.mktemp(f"matrix-{agent_name}")

    # Build config and environment
    config_path = _make_test_config(tmp)
    agent_cmd = matrix_agent(tmp)
    env = _build_env(agent_name, agent_cmd, config_path, tmp)

    # Clean prior state
    _cleanup_all()

    # Start the session
    subprocess.run(
        [
            sys.executable,
            "-m",
            "studyctl.cli",
            "study",
            TOPIC,
            "--energy",
            str(ENERGY),
            "--agent",
            agent_name,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    # Wait for state file
    _wait_for(STATE_FILE.exists, desc="session-state.json created")
    state = _read_state()
    session_name = state.get("tmux_session", "")

    # Wait for tmux session
    _wait_for(
        lambda: _session_exists(session_name),
        desc=f"tmux session {session_name}",
    )

    # Wait for BOTH topics to be logged (agent sleeps 2s, then logs with 1s gap)
    _wait_for(
        lambda: (
            TOPICS_FILE.exists()
            and "Decorator Pattern" in TOPICS_FILE.read_text()
            and "First-Class Functions" in TOPICS_FILE.read_text()
        ),
        timeout=25,
        desc="matrix agent topics logged",
    )

    content_base = tmp / "study-materials"
    session = MatrixSession(
        agent=agent_name,
        state=state,
        tmp_path=tmp,
        config_path=config_path,
        env=env,
        content_base=content_base,
        session_name=session_name,
    )

    yield session

    # Teardown — belt-and-suspenders cleanup
    _cleanup_all()


# ---------------------------------------------------------------------------
# Per-agent tests
# ---------------------------------------------------------------------------


class TestAgentMatrix:
    """Per-agent E2E tests covering the full session lifecycle.

    Tests are numbered to enforce execution order — 06 and 07 depend on
    the session being ended, which 06 triggers.
    """

    def test_01_session_start(self, matrix_session: MatrixSession) -> None:
        """tmux session exists with study-* name."""
        assert matrix_session.session_name.startswith("study-"), (
            f"Expected session starting with 'study-', got {matrix_session.session_name!r}"
        )
        assert _session_exists(matrix_session.session_name)

    def test_02_agent_launches(self, matrix_session: MatrixSession) -> None:
        """Agent process is running in the main pane."""
        state = matrix_session.read_state()
        main_pane = state.get("tmux_main_pane")
        assert main_pane, "No main pane in session state"

        # Get the pane PID and check for child processes (the agent)
        result = subprocess.run(
            ["tmux", "display-message", "-t", main_pane, "-p", "#{pane_pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"Failed to get pane PID: {result.stderr}"
        pid = result.stdout.strip()
        check = subprocess.run(["pgrep", "-P", pid], capture_output=True, check=False)
        assert check.returncode == 0, f"No child processes under pane PID {pid}"

    def test_03_topic_resolution(self, matrix_session: MatrixSession) -> None:
        """topic_slug and topic_config_name present in session state."""
        state = matrix_session.read_state()
        assert state.get("topic_slug") == "harness-matrix", (
            f"Expected topic_slug='harness-matrix', got {state.get('topic_slug')!r}"
        )
        assert state.get("topic_config_name") == TOPIC

    def test_04_briefing_injected(self, matrix_session: MatrixSession) -> None:
        """Persona file contains the study briefing header."""
        state = matrix_session.read_state()
        persona_file = state.get("persona_file")
        assert persona_file, "No persona_file in session state"

        persona = Path(persona_file)
        assert persona.exists(), f"Persona file {persona} does not exist"
        content = persona.read_text()

        # The briefing is always generated when topic_config resolves,
        # even with empty review/content data (graceful degradation).
        assert f"## Study Briefing: {TOPIC}" in content, (
            f"Briefing header not found in persona file ({persona})"
        )

    def test_05_topics_logged(self, matrix_session: MatrixSession) -> None:
        """session-topics.md has entries from the mock agent."""
        assert TOPICS_FILE.exists(), "Topics IPC file missing"
        content = TOPICS_FILE.read_text()
        assert "Decorator Pattern" in content, "Win topic not logged"
        assert "First-Class Functions" in content, "Learning topic not logged"

    def test_06_session_end(self, matrix_session: MatrixSession) -> None:
        """Session ends cleanly: tmux session gone, state mode is ended."""
        matrix_session.end()

        # Wait for tmux session to be destroyed
        _wait_for(
            lambda: not _session_exists(matrix_session.session_name),
            timeout=20,
            desc="tmux session destroyed after --end",
        )

        # State file should show mode=ended
        state = matrix_session.read_state()
        assert state.get("mode") == "ended", f"Expected mode='ended', got {state.get('mode')!r}"

    def test_07_flashcards_generated(self, matrix_session: MatrixSession) -> None:
        """JSON flashcard file exists after session with wins."""
        flashcard_dir = matrix_session.content_base / "harness-matrix" / "flashcards"
        if not flashcard_dir.exists():
            pytest.fail(
                f"Flashcard directory not created at {flashcard_dir} — "
                "cleanup_on_exit may not have seen topic_slug in state"
            )

        flashcard_files = list(flashcard_dir.glob("*flashcards.json"))
        assert flashcard_files, f"No flashcard files in {flashcard_dir}"

        # Verify the JSON structure and content
        data = json.loads(flashcard_files[0].read_text())
        assert "cards" in data, "Missing 'cards' key in flashcard JSON"
        assert len(data["cards"]) >= 1, "Expected at least 1 flashcard"

        # The win topic (Decorator Pattern) should have generated a card
        fronts = [c["front"] for c in data["cards"]]
        assert any("Decorator" in f for f in fronts), f"Expected a 'Decorator' card, got: {fronts}"
