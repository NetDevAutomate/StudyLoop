#!/usr/bin/env python3
"""MCP server for study-speak TTS."""

import subprocess
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("study-speak")


@mcp.tool()
def speak(text: str) -> str:
    """Speak text aloud using TTS. Use for Socratic questions when voice is enabled (@speak-start)."""
    try:
        subprocess.run(
            [sys.executable, "-m", "agent_session_tools.speak", text],
            check=True,
            timeout=30,
            capture_output=True,
        )
        return f"🔊 Spoke: {text}"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return f"TTS failed (continuing without voice): {e}"


if __name__ == "__main__":
    mcp.run()
