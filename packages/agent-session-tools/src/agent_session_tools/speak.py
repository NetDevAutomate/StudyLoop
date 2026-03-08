#!/usr/bin/env python3
"""Text-to-speech for the Socratic Study Mentor.

Backends (in priority order):
  1. kokoro-onnx — 82M params, ~1.5s TTFA, am_michael voice
  2. ltts/Qwen3-TTS — high quality but slow on Apple Silicon
  3. macOS say — last resort fallback
"""

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from agent_session_tools.config_loader import load_config

app = typer.Typer(add_completion=False)

# kokoro-onnx model paths (downloaded via wget from GitHub releases)
_KOKORO_DIR = Path.home() / ".cache" / "kokoro-onnx"
_KOKORO_MODEL = _KOKORO_DIR / "kokoro-v1.0.onnx"
_KOKORO_VOICES = _KOKORO_DIR / "voices-v1.0.bin"


def _get_tts_config() -> dict:
    """Load TTS config from studyctl config.yaml."""
    config = load_config()
    return config.get("tts", {})


def _ensure_kokoro_models() -> bool:
    """Download kokoro-onnx models if missing. Returns True if available."""
    if _KOKORO_MODEL.exists() and _KOKORO_VOICES.exists():
        return True
    _KOKORO_DIR.mkdir(parents=True, exist_ok=True)
    base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        if not (_KOKORO_DIR / name).exists():
            typer.echo(f"Downloading {name}...", err=True)
            try:
                subprocess.run(
                    ["wget", "-q", f"{base}/{name}", "-O", str(_KOKORO_DIR / name)],
                    check=True,
                    timeout=300,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                return False
    return _KOKORO_MODEL.exists() and _KOKORO_VOICES.exists()


def _speak_kokoro(text: str, *, voice: str, speed: float) -> bool:
    """Speak via kokoro-onnx (fast, high quality)."""
    try:
        import sounddevice as sd  # noqa: PLC0415
        from kokoro_onnx import Kokoro  # noqa: PLC0415
    except ImportError:
        return False
    if not _ensure_kokoro_models():
        return False
    try:
        import numpy as np  # noqa: PLC0415

        kokoro = Kokoro(str(_KOKORO_MODEL), str(_KOKORO_VOICES))
        samples, sr = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        # Resample to 48kHz — kokoro outputs 24kHz which causes crackling on some devices
        target_sr = 48000
        if sr != target_sr:
            samples = np.interp(
                np.linspace(0, len(samples), int(len(samples) * target_sr / sr), endpoint=False),
                np.arange(len(samples)),
                samples,
            ).astype(np.float32)
            sr = target_sr
        sd.play(samples, sr)
        sd.wait()
        return True
    except Exception:  # noqa: BLE001
        return False


def _speak_ltts(text: str, *, voice: str, lang: str, device: str, instruct: str | None) -> bool:
    """Speak via ltts (Qwen3-TTS). Slow on Apple Silicon but highest quality."""
    import shutil  # noqa: PLC0415

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
    speed: Annotated[float | None, typer.Option("-s", "--speed", help="Speech speed (0.5-2.0)")] = None,
    instruct: Annotated[
        str | None, typer.Option("--instruct", help="Emotion/style instruction (Qwen3 only)")
    ] = None,
    backend: Annotated[
        str | None, typer.Option("-b", "--backend", help="Backend: kokoro, qwen3, macos")
    ] = None,
) -> None:
    """Speak text aloud using configured TTS backend."""
    if text is None or text == "-":
        if sys.stdin.isatty():
            typer.echo("Usage: study-speak 'text' or echo 'text' | study-speak -", err=True)
            raise typer.Exit(1)
        text = sys.stdin.read().strip()

    if not text:
        return

    cfg = _get_tts_config()
    backend = backend or cfg.get("backend", "kokoro")
    voice = voice or cfg.get("voice", "am_michael")
    speed = speed or cfg.get("speed", 1.0)
    macos_voice = cfg.get("macos_voice", "Samantha")

    if backend == "kokoro":
        if _speak_kokoro(text, voice=voice, speed=speed):
            return
    elif backend == "qwen3":
        lang = cfg.get("lang", "en")
        device = cfg.get("device", "mps")
        if _speak_ltts(text, voice=voice, lang=lang, device=device, instruct=instruct):
            return
    elif backend == "macos":
        _speak_macos(text, voice=macos_voice)
        return

    # Fallback chain: kokoro → macos
    if backend != "kokoro" and _speak_kokoro(text, voice=voice, speed=speed):
        return
    _speak_macos(text, voice=macos_voice)


def main():
    app()


if __name__ == "__main__":
    main()
