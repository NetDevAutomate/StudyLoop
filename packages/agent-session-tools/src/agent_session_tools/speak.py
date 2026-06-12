#!/usr/bin/env python3
"""Text-to-speech for the StudyLoop.

Backends:
  1. openvox — local OpenVox API server, fast natural voices on macOS
  2. kokoro-onnx — 82M params, ~1.5s TTFA, am_michael voice
  3. ltts/Qwen3-TTS — high quality but slow on Apple Silicon
  4. macOS say — last resort fallback
"""

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated

import typer

from agent_session_tools.config_loader import load_config

app = typer.Typer(add_completion=False)

# kokoro-onnx model paths (downloaded via wget from GitHub releases)
_KOKORO_DIR = Path.home() / ".cache" / "kokoro-onnx"
_KOKORO_MODEL = _KOKORO_DIR / "kokoro-v1.0.onnx"
_KOKORO_VOICES = _KOKORO_DIR / "voices-v1.0.bin"

_OPENVOX_DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
_OPENVOX_DEFAULT_MODEL = "kokoro"
_OPENVOX_DEFAULT_VOICE = "af_bella"
_OPENVOX_DEFAULT_LANGUAGE = "en"
_OPENVOX_DEFAULT_RESPONSE_FORMAT = "wav"
_OPENVOX_DEFAULT_TIMEOUT = 30.0


def _get_tts_config() -> dict:
    """Load TTS config from studyloop config.yaml."""
    config = load_config()
    return config.get("tts", {})


def _ensure_kokoro_models() -> bool:
    """Download kokoro-onnx models if missing. Returns True if available."""
    if _KOKORO_MODEL.exists() and _KOKORO_VOICES.exists():
        return True
    _KOKORO_DIR.mkdir(parents=True, exist_ok=True)
    base = (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    )
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
        import sounddevice as sd  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
        from kokoro_onnx import Kokoro  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
    except ImportError:
        return False
    if not _ensure_kokoro_models():
        return False
    try:
        import numpy as np  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

        kokoro = Kokoro(str(_KOKORO_MODEL), str(_KOKORO_VOICES))
        samples, sr = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
        # Resample to 48kHz — kokoro outputs 24kHz which causes crackling on some devices
        target_sr = 48000
        if sr != target_sr:
            samples = np.interp(
                np.linspace(
                    0, len(samples), int(len(samples) * target_sr / sr), endpoint=False
                ),
                np.arange(len(samples)),
                samples,
            ).astype(np.float32)
            sr = target_sr
        sd.play(samples, sr)
        sd.wait()
        return True
    except Exception:  # noqa: BLE001
        return False


def _coerce_timeout(value: object, default: float = _OPENVOX_DEFAULT_TIMEOUT) -> float:
    if not isinstance(value, (str, int, float)):
        return default
    try:
        timeout = float(value)
    except ValueError:
        return default
    return timeout if timeout > 0 else default


def _openvox_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _speak_openvox(
    text: str,
    *,
    base_url: str,
    model: str,
    voice: str,
    language: str,
    response_format: str,
    timeout: float,
) -> bool:
    """Speak via a local OpenVox API server."""
    afplay = shutil.which("afplay")
    if not afplay:
        return False

    response_format = (
        (response_format or _OPENVOX_DEFAULT_RESPONSE_FORMAT).strip().lower()
    )
    payload = {
        "model": model,
        "input": text,
        "language": language,
        "voice": voice,
        "response_format": response_format,
    }
    request = urllib.request.Request(
        _openvox_url(base_url, "/audio/speech"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "audio/*"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if int(getattr(response, "status", 200) or 200) >= 400:
                return False
            audio = response.read()
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
    ):
        return False

    if not audio:
        return False

    audio_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="studyloop-openvox-",
            suffix=f".{response_format}",
            delete=False,
        ) as tmp:
            tmp.write(audio)
            audio_path = Path(tmp.name)
        subprocess.run([afplay, str(audio_path)], check=True, timeout=timeout + 60)
        return True
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ):
        return False
    finally:
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)


def _speak_ltts(
    text: str, *, voice: str, lang: str, device: str, instruct: str | None
) -> bool:
    """Speak via ltts (Qwen3-TTS). Slow on Apple Silicon but highest quality."""
    if not shutil.which("uvx"):
        return False
    cmd = ["uvx", "ltts", text, "--say", "--device", device, "-v", voice, "-l", lang]
    if instruct:
        cmd.extend(["--instruct", instruct])
    try:
        subprocess.run(cmd, check=True, timeout=120)
        return True
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return False


def _speak_macos(text: str, *, voice: str) -> bool:
    """Fallback: macOS say command."""
    try:
        subprocess.run(["say", "-v", voice, text], check=True, timeout=60)
        return True
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return False


@app.command()
def speak(
    text: Annotated[
        str | None, typer.Argument(help="Text to speak (or - for stdin)")
    ] = None,
    voice: Annotated[
        str | None, typer.Option("-v", "--voice", help="Voice name")
    ] = None,
    speed: Annotated[
        float | None, typer.Option("-s", "--speed", help="Speech speed (0.5-2.0)")
    ] = None,
    instruct: Annotated[
        str | None,
        typer.Option("--instruct", help="Emotion/style instruction (Qwen3 only)"),
    ] = None,
    backend: Annotated[
        str | None,
        typer.Option("-b", "--backend", help="Backend: openvox, kokoro, qwen3, macos"),
    ] = None,
) -> None:
    """Speak text aloud using configured TTS backend."""
    if text is None or text == "-":
        if sys.stdin.isatty():
            typer.echo(
                "Usage: study-speak 'text' or echo 'text' | study-speak -", err=True
            )
            raise typer.Exit(1)
        text = sys.stdin.read().strip()

    if not text:
        return

    cfg = _get_tts_config()
    backend = backend or cfg.get("backend", "kokoro")
    requested_voice = voice
    voice = requested_voice or cfg.get("voice", "am_michael")
    speed = speed or cfg.get("speed", 1.0)
    macos_voice = cfg.get("macos_voice", "Samantha")

    if backend == "openvox":
        openvox_timeout = _coerce_timeout(cfg.get("openvox_timeout"))
        if _speak_openvox(
            text,
            base_url=cfg.get("openvox_base_url", _OPENVOX_DEFAULT_BASE_URL),
            model=cfg.get("openvox_model", _OPENVOX_DEFAULT_MODEL),
            voice=requested_voice or cfg.get("openvox_voice", _OPENVOX_DEFAULT_VOICE),
            language=cfg.get("openvox_language", _OPENVOX_DEFAULT_LANGUAGE),
            response_format=cfg.get(
                "openvox_response_format", _OPENVOX_DEFAULT_RESPONSE_FORMAT
            ),
            timeout=openvox_timeout,
        ):
            return
    elif backend == "kokoro":
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
    if backend == "openvox":
        typer.echo(
            "OpenVox TTS not available — falling back to Kokoro/macOS. "
            "Start the OpenVox local server or set tts.backend: kokoro.",
            err=True,
        )
    if backend == "kokoro":
        typer.echo(
            "⚠ Kokoro TTS not available — falling back to macOS say. "
            "Install TTS deps: uv tool install './packages/agent-session-tools[tts]' --force",
            err=True,
        )
    if backend != "kokoro" and _speak_kokoro(text, voice=voice, speed=speed):
        return
    _speak_macos(text, voice=macos_voice)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
