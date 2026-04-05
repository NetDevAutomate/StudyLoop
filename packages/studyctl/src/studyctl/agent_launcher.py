"""Agent launcher — detect installed AI agents and build launch commands.

Adapters handle the per-agent differences in persona injection, MCP config,
and launch commands. The canonical persona content is shared; each adapter's
setup() callable transforms it for that agent's specific mechanism.

Agent mechanisms (verified 2026-04-03):
  Claude:   --append-system-prompt-file {temp_file}
  Gemini:   GEMINI.md written to session cwd (auto-loaded)
  Kiro:     ~/.kiro/agents/study-mentor.json updated with file:// prompt ref
  OpenCode: ~/.config/opencode/agents/study-mentor.md with YAML frontmatter
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Persona files live in the repo at agents/shared/personas/.
# Traverse up from src/studyctl/agent_launcher.py → repo root.
# Falls back to inline defaults if not found (e.g. pip install).
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
PERSONA_DIR = _REPO_ROOT / "agents" / "shared" / "personas"


# ---------------------------------------------------------------------------
# Adapter dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentAdapter:
    """Configuration and behaviour for one AI coding agent.

    Each field is either static data or a callable that handles
    the agent-specific mechanism for persona injection and launch.
    """

    name: str
    binary: str
    setup: Callable[[str, Path], Path]
    """(canonical_content, session_dir) → persona_path"""
    launch_cmd: Callable[[Path, bool], str]
    """(persona_path, resume) → shell command string"""
    teardown: Callable[[Path], None] | None = None
    """Optional cleanup for agents that write global state (e.g. Kiro)."""
    mcp_setup: Callable[[Path], None] | None = None
    """Optional MCP config writer for the session directory."""


# ---------------------------------------------------------------------------
# Claude adapter
# ---------------------------------------------------------------------------


def _claude_setup(canonical_content: str, _session_dir: Path) -> Path:
    """Write canonical content to a secure temp file for Claude's CLI flag."""
    fd, path = tempfile.mkstemp(
        prefix="studyctl-persona-",
        suffix=".md",
        dir=tempfile.gettempdir(),
    )
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(canonical_content)
    return Path(path)


def _claude_launch(persona_path: Path, resume: bool) -> str:
    """Build Claude launch command with absolute binary path.

    Resolves to absolute path because tmux panes run non-interactive
    shells which don't source .zshrc (~/.local/bin not in PATH).
    """
    binary = shutil.which("claude") or "claude"
    if resume:
        return f"{binary} -r --append-system-prompt-file {persona_path}"
    return f"{binary} --append-system-prompt-file {persona_path}"


# ---------------------------------------------------------------------------
# Kiro adapter
#
# Kiro loads agents natively from ~/.kiro/agents/.  The setup function
# writes canonical content to a temp persona file, then updates the
# agent JSON's "prompt" field to reference it via file:// URI.
# Teardown restores the original JSON from a backup.
# ---------------------------------------------------------------------------

KIRO_AGENTS_DIR = Path(os.environ.get("STUDYCTL_KIRO_AGENTS_DIR", Path.home() / ".kiro" / "agents"))
KIRO_AGENT_NAME = "study-mentor"
_KIRO_TEMPLATE = _REPO_ROOT / "agents" / "kiro" / "study-mentor.json"
_KIRO_BACKUP_SUFFIX = ".studyctl-backup"


def _kiro_setup(canonical_content: str, _session_dir: Path) -> Path:
    """Write persona temp file and update Kiro agent JSON atomically."""
    # 1. Write canonical content to a temp persona file
    fd, persona_path = tempfile.mkstemp(
        prefix="studyctl-kiro-persona-",
        suffix=".md",
        dir=tempfile.gettempdir(),
    )
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(canonical_content)

    # 2. Load the base agent template
    if _KIRO_TEMPLATE.exists():
        agent_def = json.loads(_KIRO_TEMPLATE.read_text())
    else:
        agent_def = {
            "name": KIRO_AGENT_NAME,
            "description": "Socratic study mentor",
        }

    # 3. Update prompt to reference the temp persona file
    agent_def["prompt"] = f"file://{persona_path}"

    # 4. Ensure target directory exists
    KIRO_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    target = KIRO_AGENTS_DIR / f"{KIRO_AGENT_NAME}.json"

    # 5. Backup existing agent JSON if present
    if target.exists():
        backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)
        shutil.copy2(target, backup)

    # 6. Atomic write: temp file in same dir → os.replace()
    fd2, tmp_json = tempfile.mkstemp(
        prefix=f"{KIRO_AGENT_NAME}-",
        suffix=".json",
        dir=str(KIRO_AGENTS_DIR),
    )
    with os.fdopen(fd2, "w") as f:
        json.dump(agent_def, f, indent=2)
    os.replace(tmp_json, target)

    return Path(persona_path)


def _kiro_launch(persona_path: Path, resume: bool) -> str:
    """Build Kiro launch command."""
    binary = shutil.which("kiro-cli") or shutil.which("kiro") or "kiro-cli"
    if resume:
        return f"{binary} chat --agent {KIRO_AGENT_NAME} --resume"
    return f"{binary} chat --agent {KIRO_AGENT_NAME}"


def _kiro_teardown(_session_dir: Path) -> None:
    """Restore the backed-up Kiro agent JSON."""
    target = KIRO_AGENTS_DIR / f"{KIRO_AGENT_NAME}.json"
    backup = target.with_suffix(target.suffix + _KIRO_BACKUP_SUFFIX)
    if backup.exists():
        os.replace(backup, target)


# ---------------------------------------------------------------------------
# Gemini adapter
#
# Gemini auto-loads GEMINI.md from the current working directory (3-tier
# hierarchy: global, workspace, JIT).  The setup function writes the
# canonical persona as GEMINI.md in the session directory.
# MCP config goes in .gemini/settings.json in the session directory.
# ---------------------------------------------------------------------------


def _gemini_setup(canonical_content: str, session_dir: Path) -> Path:
    """Write GEMINI.md to session dir (auto-loaded by Gemini CLI from cwd)."""
    persona_path = session_dir / "GEMINI.md"
    persona_path.write_text(canonical_content)
    return persona_path


def _gemini_launch(_persona_path: Path, resume: bool) -> str:
    """Build Gemini launch command.  Gemini picks up GEMINI.md from cwd."""
    binary = shutil.which("gemini") or "gemini"
    if resume:
        return f"{binary} -r"
    return binary


def _gemini_mcp(session_dir: Path) -> None:
    """Write .gemini/settings.json with studyctl-mcp server config."""
    gemini_dir = session_dir / ".gemini"
    gemini_dir.mkdir(parents=True, exist_ok=True)

    # Build MCP server command using the project path
    project_path = str(_REPO_ROOT / "packages" / "studyctl")
    settings = {
        "mcpServers": {
            "studyctl-mcp": {
                "command": "uv",
                "args": ["run", "--project", project_path, "studyctl-mcp"],
            },
        },
    }
    settings_path = gemini_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2))


# ---------------------------------------------------------------------------
# OpenCode adapter
#
# OpenCode uses --agent <name> to select an agent defined in
# ~/.config/opencode/agents/ or project-local agents/.  The setup
# function writes the persona as a markdown file with YAML frontmatter
# in the session directory.  MCP uses a different schema from others:
# "command" is a flat array, "enabled" (not "disabled"), "environment"
# (not "env").
# ---------------------------------------------------------------------------

_OPENCODE_AGENTS_DIR_NAME = ".opencode"


def _opencode_setup(canonical_content: str, session_dir: Path) -> Path:
    """Write study-mentor.md with YAML frontmatter for OpenCode."""
    agents_dir = session_dir / _OPENCODE_AGENTS_DIR_NAME / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    persona_path = agents_dir / "study-mentor.md"
    frontmatter = (
        "---\n"
        'description: "AuDHD-aware Socratic study mentor"\n'
        "mode: primary\n"
        "temperature: 0.3\n"
        "tools:\n"
        "  write: true\n"
        "  edit: true\n"
        "  bash: true\n"
        "---\n\n"
    )
    persona_path.write_text(frontmatter + canonical_content)
    return persona_path


def _opencode_launch(_persona_path: Path, resume: bool) -> str:
    """Build OpenCode launch command."""
    binary = shutil.which("opencode") or "opencode"
    if resume:
        return f"{binary} --agent study-mentor -c"
    return f"{binary} --agent study-mentor"


def _opencode_mcp(session_dir: Path) -> None:
    """Write opencode.json with studyctl-mcp in OpenCode's MCP schema.

    OpenCode's schema differs from others:
    - ``command`` is a flat array (binary + args merged)
    - ``enabled`` instead of ``disabled``
    - ``environment`` instead of ``env``
    - ``type: "local"`` required
    """
    oc_dir = session_dir / _OPENCODE_AGENTS_DIR_NAME
    oc_dir.mkdir(parents=True, exist_ok=True)

    project_path = str(_REPO_ROOT / "packages" / "studyctl")
    config = {
        "mcp": {
            "studyctl-mcp": {
                "command": ["uv", "run", "--project", project_path, "studyctl-mcp"],
                "enabled": True,
                "type": "local",
                "environment": {},
            },
        },
    }
    config_path = oc_dir / "opencode.json"
    config_path.write_text(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# Local LLM adapters (Ollama, LM Studio)
#
# These use Claude Code as the frontend but point it at a local LLM backend
# via env vars. Tier-pinning sets all Claude model tiers to the same model
# since local LLMs only serve one model at a time.
# ---------------------------------------------------------------------------


def _get_local_llm_config(provider: str) -> tuple[str, str]:
    """Return (base_url, model) for a local LLM provider from config.

    Falls back to sensible defaults if config isn't available.
    """
    defaults = {
        "ollama": ("http://localhost:4000", "qwen3-coder"),  # LiteLLM proxy
        "lmstudio": ("http://localhost:1234", "qwen3-coder"),
    }
    try:
        from studyctl.settings import load_settings

        cfg = getattr(load_settings().agents, provider, None)
        if cfg and cfg.model:
            return cfg.base_url or defaults[provider][0], cfg.model
    except Exception:
        pass
    return defaults[provider]


def _local_llm_env_prefix(base_url: str, auth_token: str, model: str) -> str:
    """Build shell env var exports for a local LLM provider.

    Tier-pins all Claude Code model tiers to the same model, since
    local LLMs only serve one model at a time. Without this, Claude
    tries to use different models for sub-agents and fast tasks.
    """
    return (
        f"export ANTHROPIC_BASE_URL={base_url} "
        f"ANTHROPIC_AUTH_TOKEN={auth_token} "
        f"ANTHROPIC_MODEL={model} "
        f"ANTHROPIC_SMALL_FAST_MODEL={model} "
        f"ANTHROPIC_DEFAULT_HAIKU_MODEL={model} "
        f"ANTHROPIC_DEFAULT_SONNET_MODEL={model} "
        f"ANTHROPIC_DEFAULT_OPUS_MODEL={model}; "
    )


def _ollama_launch(persona_path: Path, resume: bool) -> str:
    """Build Claude launch command with Ollama backend env vars."""
    claude_bin = shutil.which("claude") or "claude"
    base_url, model = _get_local_llm_config("ollama")
    env = _local_llm_env_prefix(base_url, "ollama", model)
    if resume:
        return f"{env}{claude_bin} -r --append-system-prompt-file {persona_path}"
    return f"{env}{claude_bin} --append-system-prompt-file {persona_path}"


def _lmstudio_launch(persona_path: Path, resume: bool) -> str:
    """Build Claude launch command with LM Studio backend env vars."""
    claude_bin = shutil.which("claude") or "claude"
    base_url, model = _get_local_llm_config("lmstudio")
    env = _local_llm_env_prefix(base_url, "lm-studio", model)
    if resume:
        return f"{env}{claude_bin} -r --append-system-prompt-file {persona_path}"
    return f"{env}{claude_bin} --append-system-prompt-file {persona_path}"


# ---------------------------------------------------------------------------
# Agent registry — insertion order is the default detection priority.
# To customize priority, set agents.priority in config.yaml.
# ---------------------------------------------------------------------------

AGENTS: dict[str, AgentAdapter] = {
    "claude": AgentAdapter(
        name="claude",
        binary="claude",
        setup=_claude_setup,
        launch_cmd=_claude_launch,
    ),
    "gemini": AgentAdapter(
        name="gemini",
        binary="gemini",
        setup=_gemini_setup,
        launch_cmd=_gemini_launch,
        mcp_setup=_gemini_mcp,
    ),
    "kiro": AgentAdapter(
        name="kiro",
        binary="kiro-cli",
        setup=_kiro_setup,
        launch_cmd=_kiro_launch,
        teardown=_kiro_teardown,
    ),
    "opencode": AgentAdapter(
        name="opencode",
        binary="opencode",
        setup=_opencode_setup,
        launch_cmd=_opencode_launch,
        mcp_setup=_opencode_mcp,
    ),
    "ollama": AgentAdapter(
        name="ollama",
        binary="ollama",
        setup=_claude_setup,  # Same persona mechanism as Claude
        launch_cmd=_ollama_launch,
    ),
    "lmstudio": AgentAdapter(
        name="lmstudio",
        binary="lms",  # LM Studio CLI
        setup=_claude_setup,
        launch_cmd=_lmstudio_launch,
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_agents() -> list[str]:
    """Return names of installed agents, in configured priority order.

    Priority comes from (highest to lowest):
    1. ``STUDYCTL_AGENT`` env var (single agent, if installed)
    2. ``agents.priority`` in config.yaml
    3. Registry insertion order (fallback)
    """
    # Env var override — check single agent
    env_agent = os.environ.get("STUDYCTL_AGENT")
    if env_agent and env_agent in AGENTS:
        if shutil.which(AGENTS[env_agent].binary):
            return [env_agent]
        return []

    # Load configured priority order
    try:
        from studyctl.settings import load_settings

        priority = load_settings().agents.priority
    except Exception:
        priority = list(AGENTS.keys())

    # Check each agent in priority order, then any not in the list
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
