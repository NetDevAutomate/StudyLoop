"""Config-driven factory for custom agent adapters.

Reads the ``agents.custom`` section from config.yaml and builds
``AgentAdapter`` instances at runtime. This allows users to add any
CLI-based AI agent without modifying source code.

Example config::

    agents:
      custom:
        aider:
          binary: aider
          strategy: cli-flag
          launch: "{binary} --read {persona}"
          resume: "{binary} --read {persona} --resume"
          env:
            OPENAI_API_KEY: sk-...
        my-agent:
          binary: my-agent
          strategy: cwd-file
          filename: .context.md
          launch: "{binary}"
          teardown: "pkill -f my-agent"
          mcp:
            format: generic
"""

from __future__ import annotations

import functools
import logging
import shutil
import subprocess
from typing import TYPE_CHECKING

from studyctl.adapters._protocol import AgentAdapter
from studyctl.adapters._strategies import cli_flag_setup, cwd_file_setup, write_mcp_config

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

# Supported strategy names → setup callables
_STRATEGIES = {
    "cli-flag": cli_flag_setup,
    "cwd-file": cwd_file_setup,
}


def build_custom_adapter(name: str, config: dict) -> AgentAdapter:
    """Build an ``AgentAdapter`` from a config dict.

    Args:
        name: The adapter name (key from ``agents.custom``).
        config: The raw config dict for this adapter.

    Returns:
        A fully-constructed ``AgentAdapter`` instance.

    Raises:
        ValueError: If ``strategy`` is not ``"cli-flag"`` or ``"cwd-file"``.
    """
    binary: str = config["binary"]
    strategy_name: str = config["strategy"]
    launch_template: str = config["launch"]
    resume_template: str = config.get("resume", launch_template)
    env_vars: dict[str, str] = config.get("env", {}) or {}
    teardown_cmd: str | None = config.get("teardown")
    mcp_config = config.get("mcp")

    # --- Strategy -----------------------------------------------------------
    if strategy_name not in _STRATEGIES:
        raise ValueError(
            f"Unknown strategy {strategy_name!r} for adapter {name!r}. "
            f"Must be one of: {sorted(_STRATEGIES)}"
        )

    if strategy_name == "cwd-file":
        filename = config.get("filename", "PERSONA.md")
        setup_fn = functools.partial(cwd_file_setup, filename=filename)
    else:
        setup_fn = _STRATEGIES[strategy_name]

    # --- Launch command builder ---------------------------------------------
    def _make_launch_cmd(persona_path: Path, resume: bool) -> str:
        template = resume_template if resume else launch_template
        resolved = shutil.which(binary) or binary
        cmd = template.format(
            binary=resolved,
            persona=str(persona_path),
            session_dir=str(persona_path.parent),
        )
        if env_vars:
            prefix = " ".join(f"{k}={v}" for k, v in env_vars.items())
            cmd = f"export {prefix}; {cmd}"
        return cmd

    # --- Teardown -----------------------------------------------------------
    teardown_fn = None
    if teardown_cmd:
        _cmd = teardown_cmd  # capture in closure

        def _teardown(_session_dir: Path) -> None:
            try:
                subprocess.run(_cmd, shell=True, timeout=10, check=False)
            except Exception as exc:
                log.warning("Teardown command %r failed: %s", _cmd, exc)

        teardown_fn = _teardown

    # --- MCP setup ----------------------------------------------------------
    mcp_fn = None
    if mcp_config is not None:
        if mcp_config is True:
            _fmt = "generic"
            _path = None
        else:
            _fmt = mcp_config.get("format", "generic")
            _path = mcp_config.get("path")

        def _mcp_setup(session_dir: Path) -> None:
            write_mcp_config(session_dir, fmt=_fmt, path=_path)

        mcp_fn = _mcp_setup

    return AgentAdapter(
        name=name,
        binary=binary,
        setup=setup_fn,
        launch_cmd=_make_launch_cmd,
        teardown=teardown_fn,
        mcp_setup=mcp_fn,
    )


def load_custom_adapters() -> dict[str, AgentAdapter]:
    """Load custom adapters from the ``agents.custom`` config section.

    Returns:
        Dict mapping adapter name → ``AgentAdapter``. Empty if no custom
        adapters are configured or the config cannot be loaded.
    """
    from studyctl.settings import load_settings

    customs = getattr(load_settings().agents, "custom", None)
    if not customs:
        return {}

    result: dict[str, AgentAdapter] = {}
    for adapter_name, adapter_config in customs.items():
        try:
            result[adapter_name] = build_custom_adapter(adapter_name, adapter_config)
        except Exception as exc:
            log.warning("Failed to build custom adapter %r: %s", adapter_name, exc)

    return result
