#!/usr/bin/env python3
"""Standalone MCP server for study-speak TTS.

Reads config from ~/.config/studyctl/config.yaml:
  tts:
    voice: am_michael      # kokoro voice name
    speed: 1.0             # 0.5 (slow) to 2.0 (fast)
"""

import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("study-speak")

_SPEAK_BIN = Path.home() / ".local" / "bin" / "study-speak"


@mcp.tool()
def speak(text: str) -> str:
    """Speak text aloud using TTS.

    When voice is enabled, call this with your full response text (excluding code blocks).
    """
    try:
        subprocess.run([str(_SPEAK_BIN), text], check=True, timeout=120, capture_output=True)
        return f"🔊 Spoke: {text[:80]}..."
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"TTS failed (continuing without voice): {e}"


if __name__ == "__main__":
    mcp.run()
