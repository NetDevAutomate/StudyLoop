"""Ollama adapter — Claude Code frontend with Ollama LLM backend.

Uses Claude Code as the UI/session management layer but routes API
calls to a local Ollama instance (typically via LiteLLM proxy on
port 4000). Env vars tier-pin all model slots to the same local model.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from studyctl.adapters._local_llm import _get_local_llm_config, _local_llm_env_prefix
from studyctl.adapters._protocol import AgentAdapter
from studyctl.adapters._strategies import cli_flag_setup

if TYPE_CHECKING:
    from pathlib import Path


def _ollama_launch(persona_path: Path, resume: bool) -> str:
    """Build Claude launch command with Ollama backend env vars."""
    claude_bin = shutil.which("claude") or "claude"
    base_url, model = _get_local_llm_config("ollama")
    env = _local_llm_env_prefix(base_url, "ollama", model)
    if resume:
        return f"{env}{claude_bin} -r --append-system-prompt-file {persona_path}"
    return f"{env}{claude_bin} --append-system-prompt-file {persona_path}"


ADAPTER = AgentAdapter(
    name="ollama",
    binary="ollama",
    setup=cli_flag_setup,
    launch_cmd=_ollama_launch,
)
