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

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from studyloop.learning.voice import (
    openvox_health,
    openvox_is_english_voice,
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


class SpeakRequest(BaseModel):
    """A request to speak some text."""

    text: str = Field(min_length=1, max_length=_MAX_CHARS)
    voice: str | None = None
    response_format: str | None = None


@router.get("/tts/health")
def tts_health() -> dict:
    """Report whether server-side speech is usable, and why not if it isn't.

    The browser uses this to decide whether to route speech here or fall back,
    so it must distinguish "not reachable" from "reachable but wrong model" --
    a client that only sees a boolean cannot tell the learner what to fix.
    """
    health = openvox_health()
    voices = openvox_voices() if health.reachable else {}
    english = sorted(v for v in voices if openvox_is_english_voice(v))
    return {
        "available": health.reachable,
        "model": health.model,
        "voice_count": health.voice_count,
        "detail": health.detail,
        # Only English voices are offered. The catalogue also holds Mandarin,
        # Japanese, Spanish, French, Hindi and Italian voices for this same
        # model, and they are valid requests that speak those languages.
        "voices": [
            {"id": v, "language": voices.get(v, ""), "british": v.startswith(("bf_", "bm_"))}
            for v in english
        ],
    }


@router.post("/tts/warm")
def tts_warm() -> dict:
    """Load the model so the next utterance is not a cold start.

    Cheap and idempotent (0.6s when already warm), and worth calling as soon as a
    learner shows any intent to use voice: the first utterance otherwise costs
    51 seconds, which reads as broken rather than slow.
    """
    return {"warmed": openvox_warm()}


@router.post("/tts/speak")
def tts_speak(request: SpeakRequest) -> Response:
    """Synthesise ``text`` and return playable audio bytes.

    Returns 503 rather than 500 when OpenVox is unreachable or busy: the client's
    correct response is to fall back to a local voice, and 503 says "try
    elsewhere" where 500 says "this is broken".
    """
    fmt = (request.response_format or "wav").lower()
    if fmt not in _MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported audio format {fmt!r}")

    audio, detail = synthesise_openvox_bytes(request.text, voice=request.voice, response_format=fmt)
    if audio is None:
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
