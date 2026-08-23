"""Voice helpers for optional spoken and saved learning recaps."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
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
        return VoiceResult(
            ok=False, backend="", requested=requested, detail="study-speak not found"
        )
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
        return VoiceResult(
            ok=False, backend="", requested=requested, detail="study-speak exited non-zero"
        )
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
        return VoiceResult(
            ok=False, backend="", requested=requested, detail="no text to synthesize"
        )
    cfg = _tts_config()
    resolved = output_path.expanduser().resolve()
    if requested == "openvox" and _write_openvox_audio(text.strip(), resolved, cfg):
        return VoiceResult(ok=True, backend="openvox", requested=requested, detail="")
    if _write_macos_audio(text.strip(), resolved, cfg):
        return VoiceResult(ok=True, backend="macos", requested=requested, detail="")
    return VoiceResult(
        ok=False, backend="", requested=requested, detail="no export backend produced audio"
    )


def synthesize_text_to_file(text: str, output_path: Path, *, backend: str | None = None) -> bool:
    """Save *text* as an audio file when a local export backend is available.

    Export is deliberately optional. OpenVox is preferred when configured
    because it returns file bytes directly; macOS ``say`` is a local fallback.
    """
    return synthesize_text_to_file_result(text, output_path, backend=backend).ok


# ─────────────────────────────────────────────────────────────────────────────
# Web-facing OpenVox client
#
# The functions above serve the CLI and write to a FILE. The web app needs the
# same synthesis as BYTES, because it streams audio back over HTTP rather than
# leaving a file on the server's disk.
#
# Three behaviours are added here that the file-writing path never needed, each
# verified against a live OpenVox rather than taken from the docs:
#
#   * WARM-UP. A cold model costs 51s for the first utterance and 5s once warm
#     (measured). Fifty seconds of silence after pressing "speak" reads as
#     broken software, so the model is warmed explicitly.
#   * 429 RETRY. OpenVox serialises strictly: three concurrent requests returned
#     two immediate 429s and one 200. Two browser tabs, or a double-click on
#     speak, hit this instantly -- so it is a normal condition to wait through,
#     not an error to surface.
#   * VOICE VALIDATION. The `language` field in the request is DECORATIVE:
#     "en", "English", "US English" and "British English" all returned
#     byte-identical audio, so the VOICE alone selects the language. That makes
#     the voice the only thing worth validating -- a `zf_*` or `jf_*` id is a
#     working request that speaks Mandarin or Japanese.
# ─────────────────────────────────────────────────────────────────────────────

#: OpenVox rejects a concurrent request immediately rather than queueing it, so
#: retries are cheap and a short wait is the correct response.
_OPENVOX_BUSY_STATUS = 429
_OPENVOX_BUSY_RETRIES = 6
_OPENVOX_BUSY_BACKOFF = 0.75

#: Voice id prefixes that are English. Kokoro encodes language in the prefix:
#: `a` American, `b` British; `z` Mandarin, `j` Japanese, `e` Spanish,
#: `f` French, `h` Hindi, `i` Italian, `p` Portuguese all exist in the same
#: model and are reachable with a valid request.
_ENGLISH_VOICE_PREFIXES = ("af_", "am_", "bf_", "bm_")


@dataclass(frozen=True, slots=True)
class OpenVoxHealth:
    """Whether server-side speech is usable right now, and why not if it isn't.

    ``detail`` is written to be shown to a learner, not logged: an unreachable
    voice engine must say what happened, because silence that looks like
    working software is the failure this whole path exists to remove.
    """

    reachable: bool
    model: str
    voice_count: int
    detail: str = ""


def _openvox_settings(cfg: dict | None = None) -> dict:
    """Resolve the OpenVox connection settings, with the documented defaults."""
    resolved = cfg if cfg is not None else _tts_config()
    return {
        "base_url": str(resolved.get("openvox_base_url", _OPENVOX_DEFAULT_BASE_URL)),
        "model": str(resolved.get("openvox_model", _OPENVOX_DEFAULT_MODEL)),
        "voice": str(resolved.get("openvox_voice", _OPENVOX_DEFAULT_VOICE)),
        "response_format": str(
            resolved.get("openvox_response_format", _OPENVOX_DEFAULT_RESPONSE_FORMAT)
        ),
        "timeout": _coerce_timeout(resolved.get("openvox_timeout")),
    }


def _openvox_get_json(base_url: str, path: str, timeout: float) -> dict | None:
    request = urllib.request.Request(
        _openvox_url(base_url, path),
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if int(getattr(response, "status", 200) or 200) >= 400:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
    ):
        return None


def openvox_voices(cfg: dict | None = None) -> dict[str, str]:
    """Return ``{voice_id: language}`` for the configured model.

    Empty when OpenVox is unreachable -- callers must treat an empty mapping as
    "cannot validate" rather than "no voices exist", because refusing every
    voice on a transient network blip would be worse than not checking.
    """
    settings = _openvox_settings(cfg)
    payload = _openvox_get_json(
        settings["base_url"], f"/models/{settings['model']}/voices", settings["timeout"]
    )
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("data")
    if not isinstance(entries, list):
        return {}
    voices: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            voices[entry["id"]] = str(entry.get("language", ""))
    return voices


def openvox_is_english_voice(voice_id: object) -> bool:
    """True when ``voice_id`` is one of Kokoro's English voices.

    Checked by prefix rather than against the live catalogue so it still works
    when OpenVox is unreachable, and so a network failure can never widen what
    counts as English.
    """
    return isinstance(voice_id, str) and voice_id.startswith(_ENGLISH_VOICE_PREFIXES)


def openvox_health(cfg: dict | None = None) -> OpenVoxHealth:
    """Probe OpenVox: reachable, serving the configured model, offering voices."""
    settings = _openvox_settings(cfg)
    model = settings["model"]
    payload = _openvox_get_json(settings["base_url"], "/models", settings["timeout"])
    if not isinstance(payload, dict):
        return OpenVoxHealth(
            reachable=False,
            model=model,
            voice_count=0,
            detail=f"OpenVox is not answering at {settings['base_url']}",
        )
    models = payload.get("data")
    ids = (
        {m.get("id") for m in models if isinstance(m, dict)} if isinstance(models, list) else set()
    )
    if model not in ids:
        return OpenVoxHealth(
            reachable=False,
            model=model,
            voice_count=0,
            detail=f"OpenVox is running but does not serve the model {model!r}",
        )
    return OpenVoxHealth(reachable=True, model=model, voice_count=len(openvox_voices(cfg)))


def openvox_warm(cfg: dict | None = None) -> bool:
    """Ask OpenVox to load the model so the next request is not a cold start.

    Measured difference: 51s cold vs 5s warm for one sentence. Returns False
    rather than raising, because failing to warm is not a reason to refuse to
    try synthesising.
    """
    settings = _openvox_settings(cfg)
    request = urllib.request.Request(
        _openvox_url(settings["base_url"], f"/models/{settings['model']}/load"),
        data=b"",
        headers={"Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            return int(getattr(response, "status", 200) or 200) < 400
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
    ):
        return False


def synthesise_openvox_bytes(
    text: str,
    *,
    voice: str | None = None,
    response_format: str | None = None,
    cfg: dict | None = None,
    sleep: object = None,
) -> tuple[bytes | None, str]:
    """Synthesise ``text`` and return ``(audio_bytes, detail)``.

    ``detail`` is empty on success and carries a learner-facing reason on
    failure. Audio is returned rather than written, so the caller can stream it
    to a browser -- a tablet on the LAN needs no WebGPU and no model download to
    play it, which is the entire point of doing this server-side.

    ``sleep`` is injectable so the 429 retry path is testable without waiting.
    """
    body = text.strip()
    if not body:
        return None, "nothing to speak"

    settings = _openvox_settings(cfg)
    chosen = voice or settings["voice"]
    if not openvox_is_english_voice(chosen):
        # Refused rather than passed through: the request would SUCCEED and
        # speak another language, which is indistinguishable from a bug to the
        # learner and is the reported "why is it speaking Mandarin" symptom.
        return None, f"refusing non-English voice {chosen!r}"

    waiter = sleep if callable(sleep) else time.sleep
    payload = {
        "model": settings["model"],
        "input": body,
        "voice": chosen,
        "response_format": response_format or settings["response_format"],
    }
    data = json.dumps(payload).encode("utf-8")
    url = _openvox_url(settings["base_url"], "/audio/speech")

    for attempt in range(_OPENVOX_BUSY_RETRIES):
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "audio/*"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
                audio = response.read()
                if audio:
                    return audio, ""
                return None, "OpenVox returned no audio"
        except urllib.error.HTTPError as exc:
            if exc.code != _OPENVOX_BUSY_STATUS:
                return None, f"OpenVox rejected the request (HTTP {exc.code})"
            # Busy: OpenVox generates one clip at a time and rejects the rest
            # instantly. Waiting is the correct behaviour, not an error.
            if attempt == _OPENVOX_BUSY_RETRIES - 1:
                return None, "OpenVox stayed busy — another clip is still generating"
            waiter(_OPENVOX_BUSY_BACKOFF * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return None, f"could not reach OpenVox: {exc}"

    return None, "OpenVox stayed busy"
