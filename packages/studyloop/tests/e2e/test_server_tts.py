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

import io
import sys
import time
import wave
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("requests")
pytest.importorskip("playwright")

from playwright.sync_api import Error as PlaywrightError

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import ConsoleWatch, launch_env, shutdown  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]

PORT = 18589


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
# Playback probes — did the learner HEAR it, not just did the engine ask?
# ---------------------------------------------------------------------------

#: Installed before any app script: records how every media element's play()
#: ended and every CSP violation, so a test can tell "the engine asked for audio"
#: apart from "the audio played".
_PLAYBACK_PROBE = """
window.__plays = [];
window.__cspViolations = [];
document.addEventListener('securitypolicyviolation', (e) => {
  window.__cspViolations.push(`${e.effectiveDirective} ${e.blockedURI}`);
});
const __play = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  const record = { outcome: 'pending', playing: false };
  window.__plays.push(record);
  this.addEventListener('playing', () => { record.playing = true; });
  const promise = __play.call(this);
  promise.then(
    () => { record.outcome = 'resolved'; },
    (err) => { record.outcome = `${err.name}: ${err.message}`; },
  );
  return promise;
};
"""

_PLAYS_SETTLED = (
    "() => window.__plays.length > 0 && window.__plays.every((p) => p.outcome !== 'pending')"
)


def _enable_voice(page: Page, base_url: str, *, timeout_ms: int) -> dict:
    """Click the header voice toggle, as the learner does, and report how its
    "Voice enabled" utterance ended.

    A real click rather than page.evaluate: it is the learner's path, and it
    gives the page the user activation a browser requires before audio plays.
    """
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_function(
        "() => !!window.Alpine && !!window.Alpine.store('settings')", timeout=15000
    )
    page.click("button[title^='Toggle voice']")
    page.wait_for_function(
        "() => !!window.ttsEngine && window.ttsEngine.tier !== null", timeout=timeout_ms
    )
    # Only the server tier plays through a media element; on any other tier
    # there is nothing to wait for, and the caller's tier assertion says why.
    if page.evaluate("() => window.ttsEngine.tier") == "server-openvox":
        page.wait_for_function(_PLAYS_SETTLED, timeout=timeout_ms)
    return page.evaluate(
        "() => ({ plays: window.__plays, csp: window.__cspViolations,"
        " tier: window.ttsEngine.tier })"
    )


#: The host's answers, faked at the network edge so the next two tests need no
#: OpenVox and therefore run in CI. Only /api/tts/* is faked: the page, its real
#: Content-Security-Policy header and the real tts-engine.js come from the server.
_FAKE_HEALTH = {
    "available": True,
    "model": "kokoro",
    "voice_count": 1,
    "detail": "",
    "voices": [{"id": "bf_emma", "language": "en-gb", "british": True}],
}


def _silent_wav(seconds: float = 0.2, rate: int = 24000) -> bytes:
    """A real, decodable WAV in the shape OpenVox returns: 24 kHz, 16-bit, mono."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


def _fake_host(page: Page, *, audio: bytes, health_delay_s: float = 0.0) -> None:
    def health(route) -> None:
        if health_delay_s:
            time.sleep(health_delay_s)  # the page's fetch waits; nothing else runs meanwhile
        # The page may have given up and aborted the fetch while we slept.
        with suppress(PlaywrightError):
            route.fulfill(json=_FAKE_HEALTH)

    page.route("**/api/tts/health", health)
    page.route("**/api/tts/warm", lambda route: route.fulfill(json={"warmed": True}))
    page.route(
        "**/api/tts/speak",
        lambda route: route.fulfill(status=200, content_type="audio/wav", body=audio),
    )


def test_host_audio_plays_under_the_pages_own_policy(browser: Browser, env) -> None:
    """The host's audio must PLAY in the page, not merely be fetched.

    Regression: `default-src 'self'` (2 Sep) with no media-src refused the blob:
    URL every server-tier utterance plays through. /api/tts/speak answered 200
    audio/wav, play() rejected, and the learner heard nothing while the badge
    said "Kokoro (server)". The real-engine test below caught that only while
    OpenVox was running, and so never in CI, which has none. This one fakes the
    host's answers instead, so CI runs it.
    """
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.add_init_script(_PLAYBACK_PROBE)
    _fake_host(page, audio=_silent_wav())
    watch = ConsoleWatch(page)
    try:
        state = _enable_voice(page, env.base_url, timeout_ms=20000)

        assert state["tier"] == "server-openvox"
        assert state["csp"] == [], f"the page's own policy refused: {state['csp']}"
        assert [p["outcome"] for p in state["plays"]] == ["resolved"], state["plays"]
        assert state["plays"][0]["playing"], "play() resolved but playback never started"
        watch.assert_clean("playing the host's audio")
    finally:
        ctx.close()


def test_audio_the_page_cannot_play_is_reported_not_silent(browser: Browser, env) -> None:
    """When the host answers but the browser will not play it, the learner is told.

    The engine resolved a refused play() silently, which is why the regression
    above looked like a dead speech server: the badge stayed green, OpenVox had
    answered every request, and the only trace was one console line. Bytes no
    browser can decode stand in for any refusal: a policy, a codec, a corrupt
    response.
    """
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.add_init_script(_PLAYBACK_PROBE)
    _fake_host(page, audio=b"this is not audio " * 64)
    try:
        state = _enable_voice(page, env.base_url, timeout_ms=20000)
        assert state["plays"][0]["outcome"] != "resolved", "undecodable bytes played?"

        toast = _toast_text(page, timeout_ms=5000)
        assert "would not play" in toast, f"the refusal was silent (toast: {toast!r})"
        # A failure notice has to last long enough to read; the store's 2s
        # default is gone before a sentence is finished.
        page.wait_for_timeout(3000)
        assert page.evaluate("() => window.Alpine.store('toast').visible"), (
            "the failure notice vanished before it could be read"
        )
    finally:
        ctx.close()


def test_a_slow_but_alive_host_still_gets_the_server_tier(browser: Browser, env) -> None:
    """A host that answers in a few seconds is present, not absent.

    Measured on the developer's Mac (29 Sep): OpenVox's own /v1/models takes 1.2
    to 2.7s, so /api/tts/health does too, and the page gave it 2.5s. Five of eight
    health calls ran over, and one page load in five fell back to system voices
    with a healthy host -- a badge that flips between loads for no visible reason.
    Four seconds is over the old budget and well inside a sane one.
    """
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.add_init_script(_PLAYBACK_PROBE)
    _fake_host(page, audio=_silent_wav(), health_delay_s=4.0)
    try:
        state = _enable_voice(page, env.base_url, timeout_ms=20000)
        assert state["tier"] == "server-openvox", (
            f"a host answering in 4s was treated as absent (tier {state['tier']!r})"
        )
    finally:
        ctx.close()


def _toast_text(page: Page, *, timeout_ms: int) -> str:
    """The toast's message once one appears, or '' if none does in time."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    with suppress(PlaywrightTimeoutError):
        page.wait_for_function("() => !!window.Alpine.store('toast').message", timeout=timeout_ms)
    return page.evaluate("() => window.Alpine.store('toast').message || ''")


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

    It asserts that the audio PLAYED. It used to count play() calls, which kept
    passing while the page's own policy refused every one (see
    test_host_audio_plays_under_the_pages_own_policy below).
    """
    if not _health(env)["available"]:
        pytest.skip("no OpenVox on this host")

    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.add_init_script(_PLAYBACK_PROBE)
    watch = ConsoleWatch(page)
    try:
        # A cold model costs ~51s on its first utterance, so allow for one.
        state = _enable_voice(page, env.base_url, timeout_ms=120000)

        assert state["tier"] == "server-openvox"
        assert page.evaluate("() => window.ttsEngine.listVoices().length") > 0
        assert state["csp"] == [], f"the page's own policy refused: {state['csp']}"
        assert [p["outcome"] for p in state["plays"]] == ["resolved"], (
            f"the host's audio never played: {state['plays']}"
        )
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
