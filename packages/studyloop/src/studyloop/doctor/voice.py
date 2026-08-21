"""Voice readiness checks for terminal/MCP TTS backends."""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from pathlib import Path

from studyloop.doctor.models import CheckResult
from studyloop.settings import load_raw_config
from studyloop.tts_backends import UnknownBackendError, resolve_backend

_KOKORO_MODEL = Path.home() / ".cache" / "kokoro-onnx" / "kokoro-v1.0.onnx"
_KOKORO_VOICES = Path.home() / ".cache" / "kokoro-onnx" / "voices-v1.0.bin"
_OPENVOX_DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"


def _tts_config() -> dict:
    raw = load_raw_config()
    tts = raw.get("tts", {})
    return tts if isinstance(tts, dict) else {}


def _openvox_reachable(base_url: str) -> bool:
    url = f"{base_url.rstrip('/')}/models"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return int(getattr(response, "status", 200) or 200) < 500
    except urllib.error.HTTPError as exc:
        # 404/405 still means the local server answered; 5xx means not healthy.
        return exc.code < 500
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def check_voice_readiness() -> list[CheckResult]:
    """Report local TTS readiness without making voice mandatory."""
    cfg = _tts_config()
    results: list[CheckResult] = []

    raw_backend = cfg.get("backend")
    try:
        backend = resolve_backend(raw_backend)
    except UnknownBackendError as exc:
        results.append(
            CheckResult(
                "voice",
                "backend",
                "fail",
                str(exc),
                f"Set tts.backend to one of the supported backends in config.yaml"
                f" (got {raw_backend!r})",
                False,
            )
        )
        return results
    results.append(
        CheckResult(
            "voice",
            "backend",
            "pass",
            f"tts.backend resolved to {backend!r}",
            "",
            False,
        )
    )

    if _KOKORO_MODEL.exists() and _KOKORO_VOICES.exists():
        results.append(
            CheckResult(
                "voice",
                "kokoro_models",
                "pass",
                "Kokoro model and voices are available",
                "",
                False,
            )
        )
    else:
        results.append(
            CheckResult(
                "voice",
                "kokoro_models",
                "info",
                "Kokoro model files are not pre-warmed",
                "See docs/voice-output.md for the model download command",
                False,
            )
        )

    afplay = shutil.which("afplay")
    results.append(
        CheckResult(
            "voice",
            "afplay",
            "pass" if afplay else "info",
            f"afplay available ({afplay})" if afplay else "afplay not found",
            "" if afplay else "Install/use macOS audio tools, or avoid OpenVox playback",
            False,
        )
    )

    if backend == "openvox":
        base_url = str(cfg.get("openvox_base_url", _OPENVOX_DEFAULT_BASE_URL))
        reachable = _openvox_reachable(base_url)
        results.append(
            CheckResult(
                "voice",
                "openvox_api",
                "pass" if reachable else "warn",
                f"OpenVox API reachable at {base_url}"
                if reachable
                else f"OpenVox API is not reachable at {base_url}",
                "Start OpenVox and enable its local API, or set backend: kokoro "
                "under the tts: section",
                False,
            )
        )
    else:
        results.append(
            CheckResult(
                "voice",
                "openvox_api",
                "info",
                f"OpenVox reachability skipped because tts.backend is {backend}",
                # Phrase the repair as nested YAML — the previous flat
                # "tts.backend: openvox" hint taught users to write a single
                # dotted top-level key, which YAML does NOT nest (the loader
                # now normalises that form too, but the nested one is canonical).
                "Set backend: openvox under the tts: section of config.yaml to enable this check",
                False,
            )
        )
    return results
