"""Voice helpers for optional spoken and saved learning recaps."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from studyloop.settings import load_raw_config
from studyloop.tts_backends import DEFAULT_BACKEND, UnknownBackendError, resolve_backend

_OPENVOX_DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
_OPENVOX_DEFAULT_MODEL = "kokoro"
_OPENVOX_DEFAULT_VOICE = "af_bella"
_OPENVOX_DEFAULT_LANGUAGE = "en"
_OPENVOX_DEFAULT_RESPONSE_FORMAT = "wav"
_OPENVOX_DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class VoiceResult:
    """Outcome of a voice call: what was asked for vs. what actually spoke.

    ``degraded`` is true only when the call succeeded but a *different*
    backend than the one requested produced the audio — the exact situation
    that used to fail silently (macOS ``say`` standing in for a configured
    OpenVox/Kokoro backend with no indication to the caller).
    """

    ok: bool
    backend: str
    requested: str
    detail: str = ""

    @property
    def degraded(self) -> bool:
        return self.ok and bool(self.backend) and self.backend != self.requested


def _study_speak_path() -> str | None:
    """Return an executable study-speak path, preferring PATH then user bin."""
    if found := shutil.which("study-speak"):
        return found
    candidate = Path.home() / ".local" / "bin" / "study-speak"
    if candidate.exists():
        return str(candidate)
    return None


def _requested_backend() -> str:
    """Resolve the configured backend, falling back to the default on a
    typo rather than raising — voice output must never block learning."""
    cfg = _tts_config()
    try:
        return resolve_backend(cfg.get("backend"))
    except UnknownBackendError:
        return DEFAULT_BACKEND


def _backend_marker_from_stderr(stderr: bytes | str) -> str:
    """Pull the ``study-speak: backend=<name>`` marker study-speak prints."""
    text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("study-speak: backend="):
            return line.split("=", 1)[1].strip()
    return ""


def speak_text_result(text: str, *, timeout: int = 60) -> VoiceResult:
    """Speak *text* and report which backend actually produced the audio."""
    requested = _requested_backend()
    command = _study_speak_path()
    if not command:
        return VoiceResult(ok=False, backend="", requested=requested, detail="study-speak not found")
    if not text.strip():
        return VoiceResult(ok=False, backend="", requested=requested, detail="no text to speak")
    try:
        result = subprocess.run(
            [command, text.strip()],
            check=False,
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return VoiceResult(ok=False, backend="", requested=requested, detail=str(exc))
    if result.returncode != 0:
        return VoiceResult(ok=False, backend="", requested=requested, detail="study-speak exited non-zero")
    backend = _backend_marker_from_stderr(result.stderr) or requested
    return VoiceResult(ok=True, backend=backend, requested=requested, detail="")


def speak_text(text: str, *, timeout: int = 60) -> bool:
    """Speak *text* with the configured terminal/MCP TTS backend.

    Voice output is optional support, never a learning blocker.  The caller gets
    a boolean for user feedback and tests, but exceptions are intentionally
    contained here.
    """
    return speak_text_result(text, timeout=timeout).ok


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


def synthesize_text_to_file_result(
    text: str, output_path: Path, *, backend: str | None = None
) -> VoiceResult:
    """Save *text* as an audio file and report which backend wrote it.

    OpenVox is the only backend that can produce non-macOS audio here; every
    other configured backend (``kokoro``, ``qwen3``, or an explicit
    ``macos``) currently renders through macOS ``say`` as a local fallback,
    so callers must be told when that happened instead of a bare success.
    """
    requested_raw = backend if backend is not None else _tts_config().get("backend")
    try:
        requested = resolve_backend(requested_raw)
    except UnknownBackendError as exc:
        return VoiceResult(ok=False, backend="", requested="", detail=str(exc))
    if not text.strip():
        return VoiceResult(ok=False, backend="", requested=requested, detail="no text to synthesize")
    cfg = _tts_config()
    resolved = output_path.expanduser().resolve()
    if requested == "openvox" and _write_openvox_audio(text.strip(), resolved, cfg):
        return VoiceResult(ok=True, backend="openvox", requested=requested, detail="")
    if _write_macos_audio(text.strip(), resolved, cfg):
        return VoiceResult(ok=True, backend="macos", requested=requested, detail="")
    return VoiceResult(ok=False, backend="", requested=requested, detail="no export backend produced audio")


def synthesize_text_to_file(text: str, output_path: Path, *, backend: str | None = None) -> bool:
    """Save *text* as an audio file when a local export backend is available.

    Export is deliberately optional. OpenVox is preferred when configured
    because it returns file bytes directly; macOS ``say`` is a local fallback.
    """
    return synthesize_text_to_file_result(text, output_path, backend=backend).ok
