"""OpenCode adapter — persona via .opencode/agents/study-mentor.md.

OpenCode uses --agent <name> to select an agent defined in
~/.config/opencode/agents/ or project-local agents/. The setup
function writes the persona as a markdown file with YAML frontmatter
in the session directory. MCP uses a different schema from others:
"command" is a flat array, "enabled" (not "disabled"),
"type": "local" required.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from studyctl.adapters._protocol import AgentAdapter
from studyctl.adapters._strategies import write_mcp_config

if TYPE_CHECKING:
    from pathlib import Path

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
        "permission:\n"
        "  edit: allow\n"
        "  bash:\n"
        '    "studyctl *": allow\n'
        '    "session-* *": allow\n'
        '    "*": ask\n'
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
    """Write opencode.json with studyctl-mcp in OpenCode's MCP schema."""
    write_mcp_config(session_dir, fmt="opencode")


ADAPTER = AgentAdapter(
    name="opencode",
    binary="opencode",
    setup=_opencode_setup,
    launch_cmd=_opencode_launch,
    mcp_setup=_opencode_mcp,
)
