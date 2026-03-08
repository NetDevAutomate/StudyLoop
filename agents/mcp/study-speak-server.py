#!/usr/bin/env python3
"""Standalone MCP server for study-speak TTS.

No dependency on agent_session_tools — just calls ~/.local/bin/study-speak.
Install: uv tool install mcp[cli]
Run: python mcp_speak_server.py
"""

import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("study-speak")

_SPEAK_BIN = Path.home() / ".local" / "bin" / "study-speak"


@mcp.tool()
def speak(text: str) -> str:
    """Speak text aloud using TTS. Use for Socratic questions when voice is enabled (@speak-start)."""
    try:
        subprocess.run([str(_SPEAK_BIN), text], check=True, timeout=30, capture_output=True)
        return f"🔊 Spoke: {text}"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"TTS failed (continuing without voice): {e}"


if __name__ == "__main__":
    mcp.run()
