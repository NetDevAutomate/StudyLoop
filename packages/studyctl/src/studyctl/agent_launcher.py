"""Agent launcher — backwards-compatible facade.

All adapter logic has moved to studyctl.adapters/.  This module re-exports
the public API and provides thin local wrappers where tests patch
``studyctl.agent_launcher.shutil.which`` or
``studyctl.agent_launcher.KIRO_AGENTS_DIR``.

Functions that tests call *after* patching ``agent_launcher.shutil.which``
must live here so the patch reaches their ``shutil.which`` call.  Everything
else is imported directly from the adapter modules.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

import studyctl.adapters.kiro as _kiro_module
from studyctl.adapters._local_llm import _get_local_llm_config, _local_llm_env_prefix
from studyctl.adapters._protocol import AgentAdapter
from studyctl.adapters._strategies import cli_flag_setup as _claude_setup
from studyctl.adapters.claude import _claude_launch
from studyctl.adapters.gemini import _gemini_launch, _gemini_setup
from studyctl.adapters.kiro import _KIRO_BACKUP_SUFFIX, KIRO_AGENT_NAME
from studyctl.adapters.lmstudio import _lmstudio_launch
from studyctl.adapters.opencode import _opencode_launch, _opencode_setup
from studyctl.adapters.registry import (
    get_all_adapters,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AGENTS",
    "KIRO_AGENTS_DIR",
    "KIRO_AGENT_NAME",
    "PERSONA_DIR",
    "AgentAdapter",
    "_claude_launch",
    "_claude_setup",
    "_gemini_launch",
    "_gemini_mcp",
    "_gemini_setup",
    "_get_local_llm_config",
    "_kiro_launch",
    "_kiro_setup",
    "_kiro_teardown",
    "_lmstudio_launch",
    "_local_llm_env_prefix",
    "_mcp_command",
    "_ollama_launch",
    "_opencode_launch",
    "_opencode_mcp",
    "_opencode_setup",
    "build_canonical_persona",
    "build_persona_file",
    "detect_agents",
    "get_adapter",
    "get_default_agent",
    "get_launch_command",
]

# ---------------------------------------------------------------------------
# Registry and constants
# ---------------------------------------------------------------------------

# Dynamically built registry — callers use ``from agent_launcher import AGENTS``.
AGENTS = get_all_adapters()

# Kiro constants re-exported so tests can monkeypatch them in this namespace.
KIRO_AGENTS_DIR = _kiro_module.KIRO_AGENTS_DIR

# Persona files live in the repo at agents/shared/personas/.
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
PERSONA_DIR = _REPO_ROOT / "agents" / "shared" / "personas"


# ---------------------------------------------------------------------------
# MCP command helper — local so patches on agent_launcher.shutil.which work.
# ---------------------------------------------------------------------------


def _mcp_command() -> list[str]:
    """Build the studyctl-mcp server command.

    Prefers the installed console script (pip/uv tool install).
    Falls back to uv run --project for development.
    """
    binary = shutil.which("studyctl-mcp")
    if binary:
        return [binary]
    project_path = str(_REPO_ROOT / "packages" / "studyctl")
    return ["uv", "run", "--project", project_path, "studyctl-mcp"]


# ---------------------------------------------------------------------------
# Gemini MCP — local so patch on agent_launcher.shutil.which reaches _mcp_command.
# ---------------------------------------------------------------------------


def _gemini_mcp(session_dir: Path) -> None:
    """Write .gemini/settings.json with studyctl-mcp server config."""
    gemini_dir = session_dir / ".gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)

    cmd = _mcp_command()
    settings = {
        "mcpServers": {
            "studyctl-mcp": {
                "command": cmd[0],
                "args": cmd[1:],
            },
        },
    }
    (gemini_dir / "settings.json").write_text(json.dumps(settings, indent=2))


# ---------------------------------------------------------------------------
# OpenCode MCP — local so patch on agent_launcher.shutil.which reaches _mcp_command.
# ---------------------------------------------------------------------------


def _opencode_mcp(session_dir: Path) -> None:
    """Write opencode.json with studyctl-mcp in OpenCode's MCP schema."""
    oc_dir = session_dir / ".opencode"
    oc_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "mcp": {
            "studyctl-mcp": {
                "command": _mcp_command(),
                "enabled": True,
                "type": "local",
            },
        },
    }
    (oc_dir / "opencode.json").write_text(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# Ollama launch — local so patch on agent_launcher.shutil.which reaches shutil.which("claude").
# ---------------------------------------------------------------------------


def _ollama_launch(persona_path: Path, resume: bool) -> str:
    """Build Claude launch command with Ollama backend env vars."""
    claude_bin = shutil.which("claude") or "claude"
    base_url, model = _get_local_llm_config("ollama")
    env = _local_llm_env_prefix(base_url, "ollama", model)
    if resume:
        return f"{env}{claude_bin} -r --append-system-prompt-file {persona_path}"
    return f"{env}{claude_bin} --append-system-prompt-file {persona_path}"


# ---------------------------------------------------------------------------
# Kiro wrappers — local so monkeypatch on KIRO_AGENTS_DIR in this namespace works.
# The adapter module (adapters/kiro.py) holds its own KIRO_AGENTS_DIR; these
# wrappers read from *this* module's attribute instead.
# ---------------------------------------------------------------------------


def _kiro_setup(canonical_content: str, _session_dir: Path) -> Path:  # type: ignore[misc]
    """Write persona temp file and update Kiro agent JSON atomically."""
    import studyctl.agent_launcher as _self

    kiro_agents_dir = _self.KIRO_AGENTS_DIR

    fd, persona_path = tempfile.mkstemp(
        prefix="studyctl-kiro-persona-",
        suffix=".md",
        dir=tempfile.gettempdir(),
    )
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(canonical_content)

    kiro_template = _kiro_module._KIRO_TEMPLATE
    if kiro_template.exists():
        agent_def = json.loads(kiro_template.read_text())
    else:
        agent_def = {
            "name": KIRO_AGENT_NAME,
            "description": "Socratic study mentor",
        }

    agent_def["prompt"] = f"file://{persona_path}"

    kiro_agents_dir.mkdir(parents=True, exist_ok=True)
    target = kiro_agents_dir / f"{KIRO_AGENT_NAME}.json"
    backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)

    if backup.exists():
        logger.warning(
            "Stale Kiro backup detected (previous session crashed?) — restoring %s",
            backup,
        )
        os.replace(backup, target)

    if target.exists():
        shutil.copy2(target, backup)

    fd2, tmp_json = tempfile.mkstemp(
        prefix=f"{KIRO_AGENT_NAME}-",
        suffix=".json",
        dir=str(kiro_agents_dir),
    )
    with os.fdopen(fd2, "w") as f:
        json.dump(agent_def, f, indent=2)
    os.replace(tmp_json, target)

    return Path(persona_path)


def _kiro_launch(_persona_path: Path, resume: bool) -> str:  # type: ignore[misc]
    """Build Kiro launch command."""
    binary = shutil.which("kiro-cli") or shutil.which("kiro") or "kiro-cli"
    if resume:
        return f"{binary} chat --agent {KIRO_AGENT_NAME} --resume"
    return f"{binary} chat --agent {KIRO_AGENT_NAME}"


def _kiro_teardown(_session_dir: Path) -> None:  # type: ignore[misc]
    """Restore the backed-up Kiro agent JSON."""
    import studyctl.agent_launcher as _self

    kiro_agents_dir = _self.KIRO_AGENTS_DIR
    target = kiro_agents_dir / f"{KIRO_AGENT_NAME}.json"
    backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)
    if backup.exists():
        os.replace(backup, target)


# ---------------------------------------------------------------------------
# Agent detection — local so patches on agent_launcher.shutil.which work.
# ---------------------------------------------------------------------------


def detect_agents() -> list[str]:
    """Return names of installed agents, in configured priority order.

    Priority comes from (highest to lowest):
    1. ``STUDYCTL_AGENT`` env var (single agent, if installed)
    2. ``agents.priority`` in config.yaml
    3. Registry insertion order (fallback)
    """
    env_agent = os.environ.get("STUDYCTL_AGENT")
    if env_agent and env_agent in AGENTS:
        if shutil.which(AGENTS[env_agent].binary):
            return [env_agent]
        return []

    try:
        from studyctl.settings import load_settings

        priority = load_settings().agents.priority
    except Exception:
        priority = list(AGENTS.keys())

    ordered = [n for n in priority if n in AGENTS]
    ordered += [n for n in AGENTS if n not in ordered]

    found: list[str] = []
    for name in ordered:
        if shutil.which(AGENTS[name].binary):
            found.append(name)
    return found


def get_default_agent() -> str | None:
    """Return the first available agent, or None."""
    agents = detect_agents()
    return agents[0] if agents else None


def get_adapter(name: str) -> AgentAdapter:
    """Get an adapter by name.

    Raises:
        KeyError: If the agent is not in the registry.
    """
    return AGENTS[name]


# ---------------------------------------------------------------------------
# Persona builder — agent-agnostic, lives here permanently.
# ---------------------------------------------------------------------------


def build_canonical_persona(
    mode: str,
    topic: str,
    energy: int,
    *,
    previous_notes: str | None = None,
) -> str:
    """Build the canonical persona content as a markdown string.

    This is agent-agnostic. Each adapter's ``setup()`` callable
    transforms and writes it in the format that agent expects.
    """
    persona_path = PERSONA_DIR / f"{mode}.md"
    template = persona_path.read_text() if persona_path.exists() else _default_persona(mode)

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

    return f"""# Study Session Context

**Topic:** {topic}
**Energy:** {energy}/10
**Mode:** {mode}

---
{resume_section}
{template}
"""


# ---------------------------------------------------------------------------
# Backward-compatible wrappers
# ---------------------------------------------------------------------------


def build_persona_file(
    mode: str,
    topic: str,
    energy: int,
    *,
    previous_notes: str | None = None,
) -> Path:
    """Build persona file using Claude adapter (backward-compatible).

    New code should use::

        canonical = build_canonical_persona(mode, topic, energy, ...)
        path = adapter.setup(canonical, session_dir)

    Uses ``mkstemp`` with 0600 permissions (security review N-04).
    Returns the path to the temp file. Caller should clean up on session end.
    """
    canonical = build_canonical_persona(mode, topic, energy, previous_notes=previous_notes)
    return _claude_setup(canonical, Path(tempfile.gettempdir()))


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
        resume: If True, use the agent's resume command.

    Raises:
        KeyError: If the agent is not in the registry.
    """
    adapter = AGENTS[agent]
    return adapter.launch_cmd(persona_file, resume)


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
