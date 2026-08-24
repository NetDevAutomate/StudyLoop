"""Server-side text-to-speech, so a tablet on the LAN can hear a voice.

WHY THIS EXISTS. In-browser Kokoro was the only voice path, and it cannot serve
the devices this tool is meant to be used from. Measured on the developer's Mac,
WebGPU tier, warmed, model cached: one sentence took 22.7 seconds to synthesise
3.45 seconds of audio -- 6.6x real time. The engine's own guard downgrades itself
past 3x and the bottom of that ladder is a silent no-op, which is exactly the
"I hear nothing" report. On a tablet it is worse: `--lan` serves plain HTTP, so
the origin is not a secure context and the browser hides both WebGPU and Cache
Storage -- forcing single-threaded WASM and a full model re-download every visit.

Doing synthesis here inverts all of that. OpenVox runs natively on the host with
real hardware access (measured 2.5s warm for a sentence, versus 22.7s in the
browser), and the device just plays an audio response. No WebGPU, no secure
context, no model download, no per-device capability question.

It also adds no new failure mode: this server is ALREADY a hard dependency for a
remote device, because the app itself is served from here. And OpenVox stays bound
to loopback -- the device authenticates to StudyLoop, and StudyLoop talks to
OpenVox privately, so an unauthenticated local API is never put on the network.

WHY NOT STREAMING. OpenVox does support `stream: true`, but it returns
`text/event-stream` with base64 audio chunks, and every chunk carries its OWN
RIFF header. Concatenating them yields a file players truncate to the first chunk
(measured: 1,164,132 bytes of PCM -- 24 seconds -- reported by ffprobe as 10.75s).
Streaming would therefore need per-chunk header surgery AND a browser willing to
play an unknown-length WAV: two new failure modes on precisely the devices this
route exists to fix, to save a couple of seconds. The non-streaming response is
already a single valid WAV. The latency that actually mattered was the cold start,
and warm-up solves that -- 51s to 2.5s.
"""

from __future__ import annotations

from threading import Lock
from time import monotonic

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from studyloop.learning.voice import (
    openvox_health,
    openvox_is_english_voice,
    openvox_server_configs,
    openvox_voices,
    openvox_warm,
    synthesise_openvox_bytes,
)

router = APIRouter()

#: Browsers need a real audio MIME type or an <audio> element will refuse to play.
_MEDIA_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}

#: Bound so a runaway caller cannot ask the host to synthesise a novel.
_MAX_CHARS = 4000

# Reuse a successful routing decision across the health -> warm -> speak burst.
# Kokoro servers commonly serialize model work, so an immediate second health
# probe can say "unavailable" solely because the first request just started a
# warm-up. App state keeps the cache scoped to one StudyLoop server/test app.
_SELECTION_CACHE_ATTR = "_studyloop_tts_selection"
_SELECTION_TTL_SECONDS = 30.0
_BACKEND_LOCK_ATTR = "_studyloop_tts_backend_lock"
_BACKEND_LOCK_INIT = Lock()


class SpeakRequest(BaseModel):
    """A request to speak some text."""

    text: str = Field(min_length=1, max_length=_MAX_CHARS)
    voice: str | None = None
    response_format: str | None = None


def _candidate_key(candidate: dict) -> str:
    return str(candidate.get("base_url") or candidate.get("openvox_base_url") or "").rstrip("/")


def _backend_lock(request: Request) -> Lock:
    lock = getattr(request.app.state, _BACKEND_LOCK_ATTR, None)
    if lock is not None:
        return lock
    # Warm and speak can be the first two requests and arrive concurrently, so
    # lazy creation itself must be serialised or each worker could get its own
    # lock and the protection would be imaginary.
    with _BACKEND_LOCK_INIT:
        lock = getattr(request.app.state, _BACKEND_LOCK_ATTR, None)
        if lock is None:
            lock = Lock()
            setattr(request.app.state, _BACKEND_LOCK_ATTR, lock)
    return lock


def _cached_selection(request: Request, candidates: list[dict]) -> tuple[dict | None, dict | None]:
    cached = getattr(request.app.state, _SELECTION_CACHE_ATTR, None)
    if not isinstance(cached, dict) or monotonic() - cached.get("at", 0.0) > _SELECTION_TTL_SECONDS:
        return None, None
    selected = next(
        (candidate for candidate in candidates if _candidate_key(candidate) == cached.get("key")),
        None,
    )
    if selected is None:
        return None, None
    body = cached.get("body")
    return selected, dict(body) if isinstance(body, dict) else None


def _remember_selection(request: Request, candidate: dict, body: dict | None = None) -> None:
    key = _candidate_key(candidate)
    existing = getattr(request.app.state, _SELECTION_CACHE_ATTR, None)
    if (
        body is None
        and isinstance(existing, dict)
        and existing.get("key") == key
        and isinstance(existing.get("body"), dict)
    ):
        body = existing["body"]
    setattr(
        request.app.state,
        _SELECTION_CACHE_ATTR,
        {"at": monotonic(), "key": key, "body": body},
    )


def _forget_selection(request: Request) -> None:
    setattr(request.app.state, _SELECTION_CACHE_ATTR, None)


def _candidate_order(request: Request, candidates: list[dict]) -> tuple[list[dict], dict | None]:
    selected, _ = _cached_selection(request, candidates)
    if selected is None:
        return candidates, None
    return [selected, *(item for item in candidates if item is not selected)], selected


@router.get("/tts/health")
def tts_health(request: Request) -> dict:
    """Report whether server-side speech is usable, and why not if it isn't.

    The browser uses this to decide whether to route speech here or fall back,
    so it must distinguish "not reachable" from "reachable but wrong model" --
    a client that only sees a boolean cannot tell the learner what to fix.
    """
    candidates = list(openvox_server_configs())
    cached_candidate, cached_body = _cached_selection(request, candidates)
    if cached_candidate is not None and cached_body is not None:
        return cached_body

    selected = None
    health = None
    failures: list[str] = []
    for candidate in candidates:
        candidate_health = openvox_health(candidate)
        if candidate_health.reachable:
            selected = candidate
            health = candidate_health
            break
        if candidate_health.detail:
            failures.append(candidate_health.detail)
    if health is None:
        _forget_selection(request)
        model = str(candidates[0].get("openvox_model", "kokoro")) if candidates else "kokoro"
        detail = "; ".join(dict.fromkeys(failures)) or "no Kokoro server is configured"
        return {
            "available": False,
            "model": model,
            "voice_count": 0,
            "detail": detail,
            "server": None,
            "voices": [],
        }

    assert selected is not None
    voices = openvox_voices(selected)
    english = sorted(v for v in voices if openvox_is_english_voice(v))
    body = {
        "available": health.reachable,
        "model": health.model,
        # Count what this route actually offers, not the backend's multilingual
        # catalogue. These values must not contradict each other in the picker.
        "voice_count": len(english),
        "detail": health.detail,
        "server": selected.get("role"),
        # Only English voices are offered. The catalogue also holds Mandarin,
        # Japanese, Spanish, French, Hindi and Italian voices for this same
        # model, and they are valid requests that speak those languages.
        "voices": [
            {"id": v, "language": voices.get(v, ""), "british": v.startswith(("bf_", "bm_"))}
            for v in english
        ],
    }
    _remember_selection(request, selected, body)
    return body


@router.post("/tts/warm")
def tts_warm(request: Request) -> dict:
    """Load the model so the next utterance is not a cold start.

    Cheap and idempotent (0.6s when already warm), and worth calling as soon as a
    learner shows any intent to use voice: the first utterance otherwise costs
    51 seconds, which reads as broken rather than slow. A compatible server may
    not expose an explicit load endpoint (VoiceMode returns 404); in that case
    this returns ``warmed: false`` without marking otherwise-working speech as
    unavailable.
    """
    with _backend_lock(request):
        candidates, cached = _candidate_order(request, list(openvox_server_configs()))
        for candidate in candidates:
            # Do not spend the synthesis timeout warming a process that accepts a
            # connection but no longer answers. A short model probe is what lets the
            # VoiceMode fallback run promptly in that failure mode.
            if candidate is not cached and not openvox_health(candidate).reachable:
                continue
            if openvox_warm(candidate):
                _remember_selection(request, candidate)
                return {"warmed": True}
            if candidate is cached:
                _forget_selection(request)
    return {"warmed": False}


@router.post("/tts/speak")
def tts_speak(payload: SpeakRequest, request: Request) -> Response:
    """Synthesise ``text`` and return playable audio bytes.

    Returns 503 rather than 500 when OpenVox is unreachable or busy: the client's
    correct response is to fall back to a local voice, and 503 says "try
    elsewhere" where 500 says "this is broken".
    """
    fmt = (payload.response_format or "wav").lower()
    if fmt not in _MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported audio format {fmt!r}")
    if payload.voice is not None and not openvox_is_english_voice(payload.voice):
        raise HTTPException(
            status_code=503,
            detail=f"refusing non-English voice {payload.voice!r}",
        )

    with _backend_lock(request):
        audio = None
        failures: list[str] = []
        candidates, cached = _candidate_order(request, list(openvox_server_configs()))
        for candidate in candidates:
            health = None if candidate is cached else openvox_health(candidate)
            if health is not None and not health.reachable:
                if health.detail:
                    failures.append(health.detail)
                continue
            audio, detail = synthesise_openvox_bytes(
                payload.text,
                voice=payload.voice,
                response_format=fmt,
                cfg=candidate,
            )
            if audio is not None:
                _remember_selection(request, candidate)
                break
            if detail:
                failures.append(detail)
            if candidate is cached:
                _forget_selection(request)
        if audio is None:
            detail = "; ".join(dict.fromkeys(failures))
            raise HTTPException(status_code=503, detail=detail or "speech unavailable")

    return Response(
        content=audio,
        media_type=_MEDIA_TYPES[fmt],
        headers={
            # Audio is deterministic for a given text+voice, but caching it would
            # pin a voice the learner has since changed. Cheap to regenerate warm.
            "Cache-Control": "no-store",
            "Content-Length": str(len(audio)),
        },
    )
