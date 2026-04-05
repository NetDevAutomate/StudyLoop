"""Persona evaluation target — runs scenarios against a live study session."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from studyctl.eval.capture import capture_response
from studyctl.session_state import is_session_active, write_session_state

if TYPE_CHECKING:
    from studyctl.eval.models import Scenario

logger = logging.getLogger(__name__)


class PersonaTarget:
    """Eval target that starts a study session per scenario and captures responses."""

    name = "persona"

    def __init__(self, agent: str = "claude") -> None:
        self.agent = agent
        self._session_name: str = ""

    def setup(self, scenario: Scenario) -> None:
        """Start a fresh study session for this scenario."""
        # Start study session via subprocess (non-blocking — detaches to tmux)
        cmd = [
            sys.executable,
            "-m",
            "studyctl.cli",
            "study",
            "start",
            scenario.topic,
            "--energy",
            str(scenario.energy),
            "--agent",
            self.agent,
        ]
        subprocess.run(cmd, capture_output=True, timeout=30, check=False)

        # Wait for session to become active (up to 30 seconds)
        for _ in range(30):
            if is_session_active():
                break
            time.sleep(1)

        # Read session name from state
        from studyctl.session_state import read_session_state

        state = read_session_state()
        self._session_name = state.get("tmux_session", "")

        # Inject elapsed time for the scenario
        fake_start = datetime.now(UTC) - timedelta(minutes=scenario.elapsed_minutes)
        write_session_state(
            {
                "started_at": fake_start.isoformat(),
                "start_time": fake_start.isoformat(),
            }
        )

    def run(self, scenario: Scenario) -> str:
        """Send setup prompts + test prompt, capture response."""
        if not self._session_name:
            return ""

        # Send setup prompts with stable-wait between each
        for prompt in scenario.setup_prompts:
            capture_response(self._session_name, prompt, timeout=60, stable_seconds=3)

        # Send test prompt and capture
        return capture_response(self._session_name, scenario.prompt, timeout=90, stable_seconds=5)

    def teardown(self) -> None:
        """End the session and clean up."""
        if self._session_name:
            subprocess.run(
                [sys.executable, "-m", "studyctl.cli", "study", "--end"],
                capture_output=True,
                timeout=15,
                check=False,
            )
            # Ensure tmux session is dead
            from studyctl.tmux import kill_session, session_exists

            if session_exists(self._session_name):
                kill_session(self._session_name)
            self._session_name = ""
