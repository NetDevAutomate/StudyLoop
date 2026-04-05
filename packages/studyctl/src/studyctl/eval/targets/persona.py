"""Persona evaluation target — runs scenarios via Claude Code print mode.

Uses ``claude -p`` (headless print mode) instead of tmux sessions.
This avoids all TUI complexity: no pane capture, no trust dialogs,
no timing issues. The persona is loaded via --append-system-prompt-file
and the response comes back as structured JSON on stdout.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from studyctl.eval.models import Scenario

logger = logging.getLogger(__name__)

# Timeout for claude -p subprocess (seconds). Opus can take 60s+ to respond.
CLAUDE_TIMEOUT = 120


class PersonaTarget:
    """Eval target using Claude Code's print mode (``claude -p``).

    Each scenario is evaluated as a single-turn prompt with the full
    persona loaded as a system prompt. Setup prompts are prepended to
    provide conversational context.
    """

    name = "persona"

    def __init__(self, agent: str = "claude") -> None:
        self.agent = agent
        self.persona_hash: str = ""
        self._persona_file: Path | None = None

    def setup(self, scenario: Scenario) -> None:
        """Build the persona file for this scenario."""
        from studyctl.agent_launcher import (
            AGENTS,
            build_canonical_persona,
            detect_agents,
        )

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

        # Build persona — same canonical persona used in live sessions
        canonical = build_canonical_persona("focus", scenario.topic, scenario.energy)
        self.persona_hash = hashlib.sha256(canonical.encode()).hexdigest()[:16]

        # Write persona to a temp file for --append-system-prompt-file
        persona_dir = Path.home() / ".config" / "studyctl" / "eval-personas"
        persona_dir.mkdir(parents=True, exist_ok=True)
        persona_file = persona_dir / f"eval-{scenario.id}.md"
        persona_file.write_text(canonical)
        self._persona_file = persona_file

        logger.info(
            "Persona ready for %s (hash=%s, file=%s)",
            scenario.id,
            self.persona_hash,
            persona_file,
        )

    def run(self, scenario: Scenario) -> str:
        """Send the scenario prompt via claude -p, return the response.

        If the scenario has setup_prompts, they are prepended as
        conversational context in a single multi-turn prompt.
        """
        if not self._persona_file:
            logger.warning("No persona file — returning empty response")
            return ""

        # Build the full prompt with setup context
        prompt = self._build_prompt(scenario)

        cmd = [
            "claude",
            "-p",
            prompt,
            "--append-system-prompt-file",
            str(self._persona_file),
            "--output-format",
            "json",
        ]

        logger.info(
            "Running claude -p for %s (prompt=%d chars)",
            scenario.id,
            len(prompt),
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("claude -p timed out after %ds for %s", CLAUDE_TIMEOUT, scenario.id)
            return ""

        if result.returncode != 0:
            logger.warning(
                "claude -p failed for %s: rc=%d stderr=%s",
                scenario.id,
                result.returncode,
                result.stderr[:200],
            )
            return ""

        # Parse JSON response
        try:
            data = json.loads(result.stdout)
            response = data.get("result", "")
        except (json.JSONDecodeError, KeyError):
            # Fall back to raw stdout if not valid JSON
            response = result.stdout

        logger.info("Got %d chars response for %s", len(response), scenario.id)
        return response.strip()

    def teardown(self) -> None:
        """Clean up persona file."""
        if self._persona_file and self._persona_file.exists():
            self._persona_file.unlink(missing_ok=True)
        self._persona_file = None

    def _build_prompt(self, scenario: Scenario) -> str:
        """Build the full prompt including setup context.

        Setup prompts are included as conversational history so the
        model has context (e.g. "we've been discussing decorators").
        """
        parts: list[str] = []

        if scenario.setup_prompts:
            parts.append("Context from earlier in the study session:")
            for sp in scenario.setup_prompts:
                parts.append(f"Student: {sp}")
            parts.append("")
            parts.append(
                f"The session has been running for {scenario.elapsed_minutes} minutes. "
                f"Student energy is {scenario.energy}/10."
            )
            parts.append("")
            parts.append("Now the student says:")

        parts.append(scenario.prompt.strip())
        return "\n".join(parts)
