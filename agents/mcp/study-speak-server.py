#!/usr/bin/env python3
"""Standalone MCP server for study-speak TTS.

No dependency on agent_session_tools — just calls ~/.local/bin/study-speak.
Install: uv tool install mcp[cli]
Run: python mcp_speak_server.py
"""

import re
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("study-speak")

_SPEAK_BIN = Path.home() / ".local" / "bin" / "study-speak"


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for chunked playback."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


@mcp.tool()
def speak(text: str) -> str:
    """Speak text aloud using TTS. When voice is enabled, call this with your full response text (excluding code blocks)."""
    sentences = _split_sentences(text)
    spoken = 0
    for sentence in sentences:
        try:
            subprocess.run(
                [str(_SPEAK_BIN), sentence], check=True, timeout=30, capture_output=True
            )
            spoken += 1
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            break
    return f"🔊 Spoke {spoken}/{len(sentences)} sentences"


if __name__ == "__main__":
    mcp.run()
