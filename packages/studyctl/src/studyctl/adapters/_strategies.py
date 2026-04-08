"""Reusable persona injection strategies and MCP config writers.

These are the building blocks for constructing AgentAdapter instances.
Each strategy handles one specific mechanism (temp file, CWD file, MCP
config) so adapter definitions remain declarative and DRY.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from pathlib import Path


def cli_flag_setup(canonical_content: str, _session_dir: Path) -> Path:
    """Write persona to a secure temp file for agents that accept --flag /path.

    Creates a file with 0o600 permissions (owner read/write only) so the
    persona content is not world-readable on multi-user systems.

    Args:
        canonical_content: The rendered persona markdown content.
        _session_dir: Unused; accepted to satisfy the setup callable signature.

    Returns:
        Path to the temporary file. Caller is responsible for cleanup.
    """
    fd, tmp = tempfile.mkstemp(suffix=".md", prefix="studyctl-persona-")
    try:
        os.write(fd, canonical_content.encode())
    finally:
        os.close(fd)

    # Set secure permissions: owner read+write only
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)

    return Path(tmp)


def cwd_file_setup(
    canonical_content: str,
    session_dir: Path,
    *,
    filename: str = "PERSONA.md",
) -> Path:
    """Write persona as a named file inside the session directory.

    Used by agents (e.g. Kiro) that pick up context files from the CWD
    rather than accepting an explicit flag.

    Args:
        canonical_content: The rendered persona markdown content.
        session_dir: Directory where the persona file will be written.
        filename: Name for the persona file. Defaults to ``PERSONA.md``.

    Returns:
        Path to the written file.
    """
    dest = session_dir / filename
    dest.write_text(canonical_content, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# MCP config writer
# ---------------------------------------------------------------------------


def _mcp_command() -> list[str]:
    """Return the command list for launching studyctl-mcp.

    Checks PATH first so installed tool users get the fast path. Falls
    back to ``uv run`` against the workspace package so development
    checkouts work without a separate install step.

    Returns:
        A list suitable for use as ``command + args`` in an MCP config.
    """
    if shutil.which("studyctl-mcp"):
        return ["studyctl-mcp"]

    # Repo root is six levels up from this file:
    # packages/studyctl/src/studyctl/adapters/_strategies.py
    #                                          ^adapters
    #                                 ^studyctl
    #                        ^src
    #               ^studyctl  (package)
    #      ^packages
    # ^repo_root
    repo_root = Path(__file__).parent.parent.parent.parent.parent.parent
    return [
        "uv",
        "run",
        "--project",
        str(repo_root / "packages" / "studyctl"),
        "studyctl-mcp",
    ]


def write_mcp_config(
    session_dir: Path,
    *,
    fmt: str = "generic",
    path: str | None = None,
) -> None:
    """Write the MCP server configuration JSON for the given agent format.

    Supported formats:

    * ``"generic"`` — Claude Code / generic MCP schema at ``.mcp.json``
    * ``"gemini"`` — Gemini CLI schema at ``.gemini/settings.json``
    * ``"opencode"`` — OpenCode schema at ``.opencode/opencode.json``

    Args:
        session_dir: Root of the session workspace; config paths are
            resolved relative to this directory.
        fmt: Target config format. Must be one of the supported strings.
        path: Override the default config file path (relative to
            ``session_dir``). If omitted the format-specific default is used.

    Raises:
        ValueError: If ``fmt`` is not a recognised format string.
    """
    cmd = _mcp_command()

    if fmt == "generic":
        default_path = ".mcp.json"
        config = {
            "mcpServers": {
                "studyctl-mcp": {
                    "command": cmd[0],
                    "args": cmd[1:],
                }
            }
        }
    elif fmt == "gemini":
        default_path = ".gemini/settings.json"
        config = {
            "mcpServers": {
                "studyctl-mcp": {
                    "command": cmd[0],
                    "args": cmd[1:],
                }
            }
        }
    elif fmt == "opencode":
        default_path = ".opencode/opencode.json"
        config = {
            "mcp": {
                "studyctl-mcp": {
                    "command": cmd,
                    "enabled": True,
                    "type": "local",
                }
            }
        }
    else:
        raise ValueError(f"Unknown MCP config format: {fmt!r}")

    target = session_dir / (path or default_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2), encoding="utf-8")
