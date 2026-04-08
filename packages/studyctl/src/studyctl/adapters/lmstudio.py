"""LM Studio adapter — Claude Code frontend with LM Studio backend.

Uses Claude Code as the UI/session management layer but routes API
calls to a local LM Studio instance (default port 1234). Env vars
tier-pin all model slots to the same local model.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from studyctl.adapters._local_llm import _get_local_llm_config, _local_llm_env_prefix
from studyctl.adapters._protocol import AgentAdapter
from studyctl.adapters._strategies import cli_flag_setup

if TYPE_CHECKING:
    from pathlib import Path


def _lmstudio_launch(persona_path: Path, resume: bool) -> str:
    """Build Claude launch command with LM Studio backend env vars."""
    claude_bin = shutil.which("claude") or "claude"
    base_url, model = _get_local_llm_config("lmstudio")
    env = _local_llm_env_prefix(base_url, "lm-studio", model)
    if resume:
        return f"{env}{claude_bin} -r --append-system-prompt-file {persona_path}"
    return f"{env}{claude_bin} --append-system-prompt-file {persona_path}"


ADAPTER = AgentAdapter(
    name="lmstudio",
    binary="lms",
    setup=cli_flag_setup,
    launch_cmd=_lmstudio_launch,
)
