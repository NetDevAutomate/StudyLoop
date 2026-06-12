"""Small wrapper around the external ``study-speak`` command."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _study_speak_path() -> str | None:
    """Return an executable study-speak path, preferring PATH then user bin."""
    if found := shutil.which("study-speak"):
        return found
    candidate = Path.home() / ".local" / "bin" / "study-speak"
    if candidate.exists():
        return str(candidate)
    return None


def speak_text(text: str, *, timeout: int = 60) -> bool:
    """Speak *text* with the configured terminal/MCP TTS backend.

    Voice output is optional support, never a learning blocker.  The caller gets
    a boolean for user feedback and tests, but exceptions are intentionally
    contained here.
    """
    command = _study_speak_path()
    if not command or not text.strip():
        return False
    try:
        result = subprocess.run(
            [command, text.strip()],
            check=False,
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 0
