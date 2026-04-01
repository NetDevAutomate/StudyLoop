"""Agent launcher — detect installed AI agents and build launch commands.

Currently Claude-only. The dict structure makes adding Gemini/Kiro/OpenCode
a one-entry change when we can test against the actual binaries.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Persona files live in the repo at agents/shared/personas/.
# Traverse up from src/studyctl/agent_launcher.py → repo root.
# Falls back to inline defaults if not found (e.g. pip install).
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
PERSONA_DIR = _REPO_ROOT / "agents" / "shared" / "personas"

AGENT_REGISTRY: dict[str, dict[str, str]] = {
    "claude": {
        "binary": "claude",
        "check": "claude --version",
        "launch": "claude --append-system-prompt-file {persona_file}",
        "resume": "claude -r --append-system-prompt-file {persona_file}",
    },
    # gemini, kiro, opencode: add when testing against actual binaries.
    # Each requires pre-created config files in their agent directories.
    # Resume flags: kiro-cli chat --resume, etc.
}


def detect_agents() -> list[str]:
    """Return names of installed agents, in priority order."""
    found: list[str] = []
    for name, info in AGENT_REGISTRY.items():
        if shutil.which(info["binary"]):
            found.append(name)
    return found


def get_default_agent() -> str | None:
    """Return the first available agent, or None."""
    agents = detect_agents()
    return agents[0] if agents else None


def build_persona_file(
    mode: str,
    topic: str,
    energy: int,
    *,
    previous_notes: str | None = None,
) -> Path:
    """Create a temporary persona file with session-specific instructions.

    Args:
        mode: Session mode (study, co-study).
        topic: Study topic.
        energy: Energy level 1-10.
        previous_notes: If resuming, notes from the previous session
            (topics covered, wins, struggles, parked questions).

    Uses ``mkstemp`` with 0600 permissions (security review N-04).
    Returns the path to the temp file. Caller should clean up on session end.
    """
    # Load the mode-specific persona template
    persona_path = PERSONA_DIR / f"{mode}.md"
    template = persona_path.read_text() if persona_path.exists() else _default_persona(mode)

    # Build resume context if available
    resume_section = ""
    if previous_notes:
        resume_section = f"""
## Resuming Previous Session

This is a RESUMED session. Here's what was covered last time:

{previous_notes}

Pick up where we left off. Don't re-introduce the topic from scratch —
reference specific items from the previous session and ask where the
student wants to continue.

---

"""

    # Inject session context
    content = f"""# Study Session Context

**Topic:** {topic}
**Energy:** {energy}/10
**Mode:** {mode}

---
{resume_section}
{template}
"""
    fd, path = tempfile.mkstemp(
        prefix="studyctl-persona-",
        suffix=".md",
        dir=tempfile.gettempdir(),
    )
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return Path(path)


def get_launch_command(
    agent: str,
    persona_file: Path,
    *,
    resume: bool = False,
) -> str:
    """Build the shell command to launch an agent with a persona.

    Args:
        agent: Agent name (e.g. "claude").
        persona_file: Path to the persona file.
        resume: If True, use the agent's resume command (e.g. ``claude -r``)
            to continue the previous conversation in the session directory.

    Raises:
        KeyError: If the agent is not in the registry.
    """
    info = AGENT_REGISTRY[agent]
    template = info["resume"] if resume and "resume" in info else info["launch"]
    return template.format(persona_file=persona_file)


def _default_persona(mode: str) -> str:
    """Fallback persona when no persona file exists for the mode."""
    if mode == "co-study":
        return (
            "You are a study companion. The user is driving — watching videos, "
            "reading docs, or doing exercises. Stay available but don't interrupt. "
            "When asked questions, use the Socratic method. Keep answers concise.\n\n"
            "Check the session IPC files for context:\n"
            "- ~/.config/studyctl/session-state.json\n"
            "- ~/.config/studyctl/session-topics.md\n"
            "- ~/.config/studyctl/session-parking.md\n"
        )
    # Default: study mode
    return (
        "You are a Socratic study mentor. Drive the session — ask questions, "
        "probe understanding, use the 70/30 balance (70% questions, 30% strategic "
        "information). Adapt to the student's energy level.\n\n"
        "Check the session IPC files for context:\n"
        "- ~/.config/studyctl/session-state.json\n"
        "- ~/.config/studyctl/session-topics.md\n"
        "- ~/.config/studyctl/session-parking.md\n"
    )
