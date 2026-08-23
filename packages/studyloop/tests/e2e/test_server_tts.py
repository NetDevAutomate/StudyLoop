"""Server-side speech, exercised against a running server.

Written because ``tests/test_e2e_coverage_gate.py`` flagged the three /api/tts
endpoints as dark. They are worth a real walk rather than a waiver: this path
exists specifically so a device that CANNOT run the browser engine still gets a
voice, and the only honest way to show that is to prove the browser reaches the
tier and plays audio without ever touching WebGPU.

These tests are tolerant of a host with no OpenVox. That is a completely normal
configuration -- most people running StudyLoop will not have it -- so an absent
OpenVox must skip, never fail. What is asserted unconditionally is the CONTRACT:
health answers honestly, speak refuses a non-English voice, and an unavailable
engine returns 503 (meaning "fall back") rather than 500 ("this app is broken").

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_server_tts.py -m e2e
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("requests")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import ConsoleWatch, launch_env, shutdown  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Browser

pytestmark = [pytest.mark.e2e]

PORT = 18613


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("server-tts")
    e = launch_env(root, PORT)
    try:
        yield e
    finally:
        shutdown(e)


def _health(env) -> dict:
    import requests

    response = requests.get(f"{env.base_url}/api/tts/health", timeout=20)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Contract — asserted whether or not OpenVox is installed
# ---------------------------------------------------------------------------


def test_health_answers_honestly_either_way(env) -> None:
    """Health must state availability AND, when unavailable, why.

    A client that learns only ``false`` cannot tell the learner what to fix, and
    "no voice, no reason" is the exact failure this whole path exists to remove.
    """
    body = _health(env)
    assert isinstance(body["available"], bool)
    assert body["model"]
    if body["available"]:
        assert body["voice_count"] > 0
        assert body["voices"], "available but offering no voices is incoherent"
    else:
        assert body["detail"], "unavailable without a reason is the bug being fixed"
        assert body["voices"] == []


def test_only_english_voices_are_ever_offered(env) -> None:
    """The catalogue must never include a voice that speaks another language.

    Kokoro ships Mandarin, Japanese, Spanish, French, Hindi and Italian voices in
    the same model, reachable with a perfectly valid request -- so offering one is
    not a 404 waiting to happen, it is confident wrong-language audio.
    """
    body = _health(env)
    if not body["available"]:
        pytest.skip("no OpenVox on this host")
    for entry in body["voices"]:
        assert entry["id"].startswith(("af_", "am_", "bf_", "bm_")), entry["id"]


def test_a_non_english_voice_is_refused_not_spoken(env) -> None:
    import requests

    response = requests.post(
        f"{env.base_url}/api/tts/speak",
        json={"text": "This must not be spoken.", "voice": "zf_xiaobei"},
        timeout=30,
    )
    assert response.status_code == 503, response.text
    assert "zf_xiaobei" in response.json()["detail"]


def test_an_unsupported_format_is_a_client_error(env) -> None:
    import requests

    response = requests.post(
        f"{env.base_url}/api/tts/speak",
        json={"text": "hello", "response_format": "aiff"},
        timeout=30,
    )
    assert response.status_code == 400, response.text


# ---------------------------------------------------------------------------
# Synthesis — needs OpenVox, so skips without it
# ---------------------------------------------------------------------------


def test_speak_returns_playable_audio(env) -> None:
    """The response must be real audio with an audio MIME type.

    Both halves matter: an <audio> element refuses to play without the MIME type,
    and a 200 carrying an error page would otherwise look like success.
    """
    import requests

    body = _health(env)
    if not body["available"]:
        pytest.skip("no OpenVox on this host")

    requests.post(f"{env.base_url}/api/tts/warm", timeout=120)
    response = requests.post(
        f"{env.base_url}/api/tts/speak",
        json={"text": "Server side speech is working.", "voice": "bf_emma"},
        timeout=180,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF", "not a WAV payload"
    # 24kHz 16-bit mono: anything under a few thousand bytes is not speech.
    assert len(response.content) > 8000, f"suspiciously small: {len(response.content)} bytes"


def test_warm_is_idempotent(env) -> None:
    """Warming twice must not error -- it is called opportunistically."""
    import requests

    if not _health(env)["available"]:
        pytest.skip("no OpenVox on this host")
    for _ in range(2):
        response = requests.post(f"{env.base_url}/api/tts/warm", timeout=120)
        assert response.status_code == 200, response.text
        assert response.json()["warmed"] is True


# ---------------------------------------------------------------------------
# Browser leg — the reason this path exists
# ---------------------------------------------------------------------------


def test_browser_uses_the_server_tier_without_touching_webgpu(browser: Browser, env) -> None:
    """The whole point: audio on a device that cannot run the browser engine.

    Asserting AudioContext was never created is what proves it. The neural tier
    plays through an AudioContext and needs WebGPU plus a secure context plus a
    multi-hundred-MB model download; the server tier plays an <audio> element and
    needs none of them. A tablet on `--lan` is served over plain HTTP, so it is
    not a secure context and cannot have the first path -- if this assertion ever
    fails, the tablet has silently lost its voice.
    """
    if not _health(env)["available"]:
        pytest.skip("no OpenVox on this host")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    watch = ConsoleWatch(page)
    try:
        page.goto(f"{env.base_url}/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        page.evaluate(
            """() => {
                window.__played = 0;
                const orig = Audio.prototype.play;
                Audio.prototype.play = function () { window.__played++; return orig.call(this); };
            }"""
        )
        page.evaluate("async () => { await window.ttsEngine.init(); }")

        assert page.evaluate("() => window.ttsEngine.tier") == "server-openvox"
        assert page.evaluate("() => window.ttsEngine.listVoices().length") > 0

        page.evaluate("async () => { await window.ttsEngine.speak('Hello from the host.'); }")
        assert page.evaluate("() => window.__played") >= 1, "no audio element ever played"
        assert page.evaluate("() => window.ttsEngine._audioCtx ? 'created' : 'never'") == "never", (
            "the server tier should never build an AudioContext"
        )
        watch.assert_clean("speaking through the server tier")
    finally:
        ctx.close()


def test_the_voice_picker_never_offers_a_foreign_language_voice(browser: Browser, env) -> None:
    """A voice id outside the offered set must be refused, not adopted.

    Reachable in ordinary use: on the Web Speech tier setVoice() is handed a
    SYSTEM voice name, which would otherwise persist into another tier as a bogus
    id -- and a bogus id on this model is a working request in another language.
    """
    if not _health(env)["available"]:
        pytest.skip("no OpenVox on this host")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        page.goto(f"{env.base_url}/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)
        page.evaluate("async () => { await window.ttsEngine.init(); }")
        result = page.evaluate(
            """async () => {
                const first = window.ttsEngine.listVoices()[0].id;
                await window.ttsEngine.setVoice(first);
                await window.ttsEngine.setVoice('zf_xiaobei');
                await window.ttsEngine.setVoice('Ting-Ting');
                return { expected: first, actual: window.ttsEngine.voiceId };
            }"""
        )
        assert result["actual"] == result["expected"], (
            f"a rejected voice became active: {result['actual']}"
        )
    finally:
        ctx.close()
