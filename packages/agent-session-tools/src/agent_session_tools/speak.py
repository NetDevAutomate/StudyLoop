#!/usr/bin/env python3
"""Text-to-speech for the Socratic Study Mentor.

Wraps ltts (Qwen3-TTS / Kokoro) with fallback to macOS `say`.
Agents call this to speak responses aloud.
"""

import shutil
import subprocess
import sys
from typing import Annotated

import typer

from agent_session_tools.config_loader import load_config

app = typer.Typer(add_completion=False)


def _get_tts_config() -> dict:
    """Load TTS config from studyctl config.yaml."""
    config = load_config()
    return config.get("tts", {})


def _speak_ltts(text: str, *, voice: str, lang: str, device: str, instruct: str | None) -> bool:
    """Speak via ltts (Qwen3-TTS)."""
    if not shutil.which("uvx"):
        return False
    cmd = ["uvx", "ltts", text, "--say", "--device", device, "-v", voice, "-l", lang]
    if instruct:
        cmd.extend(["--instruct", instruct])
    try:
        subprocess.run(cmd, check=True, timeout=120)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _speak_macos(text: str, *, voice: str) -> bool:
    """Fallback: macOS say command."""
    try:
        subprocess.run(["say", "-v", voice, text], check=True, timeout=60)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


@app.command()
def speak(
    text: Annotated[str | None, typer.Argument(help="Text to speak (or - for stdin)")] = None,
    voice: Annotated[str | None, typer.Option("-v", "--voice", help="Voice name")] = None,
    instruct: Annotated[
        str | None, typer.Option("--instruct", help="Emotion/style instruction (Qwen3 only)")
    ] = None,
    backend: Annotated[
        str | None, typer.Option("-b", "--backend", help="Backend: qwen3, kokoro, macos")
    ] = None,
) -> None:
    """Speak text aloud using configured TTS backend."""
    # Read from stdin if text is "-" or None
    if text is None or text == "-":
        if sys.stdin.isatty():
            typer.echo("Usage: study-speak 'text' or echo 'text' | study-speak -", err=True)
            raise typer.Exit(1)
        text = sys.stdin.read().strip()

    if not text:
        return

    cfg = _get_tts_config()
    voice = voice or cfg.get("voice", "Ryan")
    lang = cfg.get("lang", "en")
    device = cfg.get("device", "mps")
    backend = backend or cfg.get("backend", "qwen3")
    macos_voice = cfg.get("macos_voice", "Samantha")

    if backend == "macos":
        _speak_macos(text, voice=macos_voice)
    elif _speak_ltts(text, voice=voice, lang=lang, device=device, instruct=instruct):
        pass  # success
    else:
        # Fallback to macOS
        _speak_macos(text, voice=macos_voice)


def main():
    app()


if __name__ == "__main__":
    main()
