"""Voice helpers for optional spoken and saved learning recaps."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from studyloop.settings import load_raw_config

_OPENVOX_DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
_OPENVOX_DEFAULT_MODEL = "kokoro"
_OPENVOX_DEFAULT_VOICE = "af_bella"
_OPENVOX_DEFAULT_LANGUAGE = "en"
_OPENVOX_DEFAULT_RESPONSE_FORMAT = "wav"
_OPENVOX_DEFAULT_TIMEOUT = 30.0


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


def _tts_config() -> dict:
    raw = load_raw_config()
    config = raw.get("tts", {})
    return config if isinstance(config, dict) else {}


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


def _format_for_path(path: Path, configured: object) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"wav", "mp3", "ogg", "flac"}:
        return suffix
    if isinstance(configured, str) and configured.strip():
        return configured.strip().lower()
    return _OPENVOX_DEFAULT_RESPONSE_FORMAT


def _write_openvox_audio(text: str, output_path: Path, cfg: dict) -> bool:
    response_format = _format_for_path(
        output_path,
        cfg.get("openvox_response_format", _OPENVOX_DEFAULT_RESPONSE_FORMAT),
    )
    payload = {
        "model": cfg.get("openvox_model", _OPENVOX_DEFAULT_MODEL),
        "input": text,
        "language": cfg.get("openvox_language", _OPENVOX_DEFAULT_LANGUAGE),
        "voice": cfg.get("openvox_voice", _OPENVOX_DEFAULT_VOICE),
        "response_format": response_format,
    }
    request = urllib.request.Request(
        _openvox_url(str(cfg.get("openvox_base_url", _OPENVOX_DEFAULT_BASE_URL)), "/audio/speech"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "audio/*"},
        method="POST",
    )
    timeout = _coerce_timeout(cfg.get("openvox_timeout"))
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        tmp_path.write_bytes(audio)
        tmp_path.replace(output_path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        return False
    return True


def _write_macos_audio(text: str, output_path: Path, cfg: dict) -> bool:
    say = shutil.which("say")
    if not say:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    voice = str(cfg.get("macos_voice", "Samantha"))
    try:
        subprocess.run(
            [say, "-v", voice, "-o", str(output_path), text],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
        OSError,
    ):
        return False
    return output_path.exists()


def synthesize_text_to_file(text: str, output_path: Path, *, backend: str | None = None) -> bool:
    """Save *text* as an audio file when a local export backend is available.

    Export is deliberately optional. OpenVox is preferred when configured
    because it returns file bytes directly; macOS ``say`` is a local fallback.
    """
    if not text.strip():
        return False
    cfg = _tts_config()
    selected = (backend or cfg.get("backend") or "openvox").strip().lower()
    resolved = output_path.expanduser().resolve()
    if selected == "openvox" and _write_openvox_audio(text.strip(), resolved, cfg):
        return True
    if selected in {"openvox", "macos", "kokoro", "qwen3"}:
        return _write_macos_audio(text.strip(), resolved, cfg)
    return False
