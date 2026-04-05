"""Persona evaluation target — runs scenarios against a live study session."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from studyctl.eval.capture import capture_response
from studyctl.session_state import (
    PARKING_FILE,
    SESSION_DIR,
    TOPICS_FILE,
    _ensure_session_dir,
    is_session_active,
    read_session_state,
    write_session_state,
)

if TYPE_CHECKING:
    from studyctl.eval.models import Scenario

logger = logging.getLogger(__name__)


class PersonaTarget:
    """Eval target that starts a headless study session per scenario.

    Uses the same internal functions as ``POST /api/session/start`` —
    creates the tmux session detached without trying to attach (which
    would block when run non-interactively).
    """

    name = "persona"

    def __init__(self, agent: str = "claude") -> None:
        self.agent = agent
        self._session_name: str = ""
        self._tmux_main_pane: str = ""
        self.persona_hash: str = ""

    def setup(self, scenario: Scenario) -> None:
        """Start a fresh headless study session for this scenario."""
        from studyctl.agent_launcher import (
            AGENTS,
            build_canonical_persona,
            detect_agents,
        )
        from studyctl.history import start_study_session
        from studyctl.history.sessions import update_persona_hash
        from studyctl.output import energy_to_label
        from studyctl.session.orchestrator import (
            build_wrapped_agent_cmd,
            create_tmux_environment,
            setup_session_dir,
        )
        from studyctl.tmux import is_tmux_available, kill_session, session_exists

        if not is_tmux_available():
            logger.error("tmux not available — cannot start eval session")
            return

        if is_session_active():
            logger.warning("Session already active — cleaning up before eval")
            self._force_teardown()

        # Resolve agent
        agent_name = self.agent
        if agent_name not in AGENTS:
            available = detect_agents()
            if not available:
                logger.error("No AI agent found")
                return
            agent_name = available[0]

        adapter = AGENTS[agent_name]
        if not shutil.which(adapter.binary):
            logger.error("Agent binary not found: %s", adapter.binary)
            return

        # Create DB record
        energy_label = energy_to_label(scenario.energy)
        study_id = start_study_session(scenario.topic, energy_label)
        if not study_id:
            logger.error("Failed to create session record")
            return

        # Write session state
        _ensure_session_dir()
        now = datetime.now(UTC).isoformat()
        write_session_state(
            {
                "study_session_id": study_id,
                "topic": scenario.topic,
                "energy": scenario.energy,
                "energy_label": energy_label,
                "mode": "focus",
                "timer_mode": "energy",
                "started_at": now,
                "start_time": now,
                "paused_at": None,
                "total_paused_seconds": 0,
            }
        )
        TOPICS_FILE.touch(mode=0o600, exist_ok=True)
        PARKING_FILE.touch(mode=0o600, exist_ok=True)

        # Session directory + tmux
        slug = scenario.topic.lower().replace(" ", "-")[:20]
        short_id = study_id[:8]
        session_name = f"study-{slug}-{short_id}"
        session_dir = SESSION_DIR / "sessions" / session_name

        if session_exists(session_name):
            kill_session(session_name)

        setup_session_dir(session_dir, scenario.topic)

        # Build persona
        canonical = build_canonical_persona("focus", scenario.topic, scenario.energy)
        self.persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        update_persona_hash(study_id, self.persona_hash)

        persona_file = adapter.setup(canonical, session_dir)
        if adapter.mcp_setup:
            adapter.mcp_setup(session_dir)

        # Build agent command
        test_agent_cmd = os.environ.get("STUDYCTL_TEST_AGENT_CMD")
        if test_agent_cmd:
            agent_cmd = test_agent_cmd.format(persona_file=persona_file)
        else:
            claude_project_key = str(session_dir).replace("/", "-").lstrip("-")
            claude_project_dir = Path.home() / ".claude" / "projects" / claude_project_key
            is_resuming = claude_project_dir.exists()
            agent_cmd = adapter.launch_cmd(persona_file, is_resuming)

        wrapped_cmd = build_wrapped_agent_cmd(session_dir, agent_cmd)

        result = create_tmux_environment(
            session_name=session_name,
            session_dir=session_dir,
            wrapped_agent_cmd=wrapped_cmd,
            session_state_dir=SESSION_DIR,
        )

        # Persist tmux metadata
        write_session_state(
            {
                "tmux_session": session_name,
                "tmux_main_pane": result["tmux_main_pane"],
                "tmux_sidebar_pane": result["tmux_sidebar_pane"],
                "persona_file": str(persona_file),
                "session_dir": str(session_dir),
                "agent": agent_name,
                "persona_hash": self.persona_hash,
            }
        )

        self._session_name = session_name
        self._tmux_main_pane = result["tmux_main_pane"]

        # Wait for agent to be ready (poll for child process in tmux pane)
        for _ in range(30):
            if is_session_active():
                break
            time.sleep(1)

        # Accept Claude Code's trust dialog if present — send Enter to select
        # "Yes, I trust this folder" (option 1, already highlighted).
        # This is needed because Claude Code may not respect hasTrustDialogAccepted
        # in settings.json for dynamically-created session directories.
        from studyctl.eval.capture import capture_pane_plain, send_keys

        time.sleep(3)  # Give Claude time to render the trust prompt
        pane_content = capture_pane_plain(self._tmux_main_pane)
        if "trust" in pane_content.lower() and "Yes, I trust" in pane_content:
            logger.info("Trust dialog detected — accepting automatically")
            send_keys(self._tmux_main_pane, "")  # Enter accepts default option 1
            time.sleep(5)  # Wait for Claude to initialize after trust acceptance

        # Inject elapsed time for the scenario
        fake_start = datetime.now(UTC) - timedelta(minutes=scenario.elapsed_minutes)
        write_session_state(
            {
                "started_at": fake_start.isoformat(),
                "start_time": fake_start.isoformat(),
            }
        )

        logger.info("Session %s started for scenario %s", session_name, scenario.id)

    def run(self, scenario: Scenario) -> str:
        """Send setup prompts + test prompt, capture response.

        Uses the explicit tmux pane ID (``%N``) rather than the session name
        to ensure we capture the agent pane, not the sidebar.
        """
        if not self._tmux_main_pane:
            logger.warning("No main pane ID — returning empty response")
            return ""

        target = self._tmux_main_pane
        logger.info("Capturing from pane %s (session %s)", target, self._session_name)

        # Send setup prompts with stable-wait between each
        for prompt in scenario.setup_prompts:
            capture_response(target, prompt, timeout=60, stable_seconds=3)

        # Send test prompt and capture
        response = capture_response(target, scenario.prompt, timeout=90, stable_seconds=5)
        logger.info("Captured %d chars for %s", len(response), scenario.id)
        return response

    def teardown(self) -> None:
        """End the session and clean up."""
        self._force_teardown()

    def _force_teardown(self) -> None:
        """Force-kill any active session."""
        from studyctl.session.cleanup import end_session_common

        state = read_session_state()
        if state.get("study_session_id"):
            try:
                end_session_common(state)
            except Exception:
                logger.exception("end_session_common failed")

        # Belt and suspenders: kill tmux session directly
        if self._session_name:
            from studyctl.tmux import kill_session, session_exists

            if session_exists(self._session_name):
                kill_session(self._session_name)
            self._session_name = ""
