#!/usr/bin/env python3
"""Standalone MCP server for study-speak TTS.

Reads config from ~/.config/studyctl/config.yaml:
  tts:
    voice: am_michael      # kokoro voice name
    speed: 1.0             # 0.5 (slow) to 2.0 (fast)
    pause: 0.3             # seconds between sentences
"""

import re
import subprocess
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("study-speak")

_SPEAK_BIN = Path.home() / ".local" / "bin" / "study-speak"
_CONFIG_PATH = Path.home() / ".config" / "studyctl" / "config.yaml"


def _load_tts_config() -> dict:
    """Load TTS config section."""
    try:
        import yaml  # noqa: PLC0415

        return yaml.safe_load(_CONFIG_PATH.read_text()).get("tts", {})
    except Exception:  # noqa: BLE001
        return {}


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for chunked playback."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


@mcp.tool()
def speak(text: str) -> str:
    """Speak text aloud using TTS. When voice is enabled, call this with your full response text (excluding code blocks)."""
    cfg = _load_tts_config()
    pause = cfg.get("pause", 0.3)

    sentences = _split_sentences(text)
    spoken = 0
    for i, sentence in enumerate(sentences):
        try:
            subprocess.run(
                [str(_SPEAK_BIN), sentence], check=True, timeout=30, capture_output=True
            )
            spoken += 1
            if i < len(sentences) - 1 and pause > 0:
                time.sleep(pause)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            break
    return f"🔊 Spoke {spoken}/{len(sentences)} sentences"


if __name__ == "__main__":
    mcp.run()
