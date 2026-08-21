"""The voice picker and the engine badge must tell the truth about the engine.

WHY THIS FILE EXISTS
--------------------
A user reported "voices have reverted to Apple voices rather than Kokoro
browser voices". Nothing was broken at synthesis time — the *picker* was wrong
by construction:

* nothing ever called ``window.ttsEngine.init()`` at page load, so
  ``ttsEngine.tier`` stayed ``null``;
* ``loadVoices()`` treated ``null`` as "not neural" and fell through to
  ``speechSynthesis.getVoices()``, filling the dropdown with macOS voices;
* ``speechSynthesis.onvoiceschanged`` could re-run that same path at any time.

The existing browser coverage could not catch this: ``test_web_smoke_browser``
*stubs* ``window.ttsEngine`` outright, and ``test_web_tts`` only asserts static
files exist. These tests drive the real ``components.js`` state machine and the
real ``tts-engine.js`` module in a real browser.

Determinism note: the neural tier cannot be reached in CI (it needs a ~92 MB
Hugging Face download), so tier resolution is driven by dispatching the real
``tts:tier-change`` event and by installing a tier-bearing engine stub. What is
under test is the app's reaction to a tier, not the ONNX runtime.

Run:  uv run pytest packages/studyloop/tests/e2e/test_web_tts_engine.py -m e2e
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import (  # noqa: E402
    auth_context_fixture_factory,
    web_page_fixture_factory,
    web_server_fixture_factory,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18614  # unique port; sister e2e suites use 18568-18613

web_server = web_server_fixture_factory(WEB_PORT)
auth_context = auth_context_fixture_factory()
web_page = web_page_fixture_factory("web_server", "auth_context")


# Headless Chromium ships no system voices at all, so the "Apple voices leak
# into the picker" defect is invisible unless we supply some. This stubs
# speechSynthesis with a macOS-shaped voice list BEFORE any app script runs.
_APPLE_VOICES = """
window.__appleVoiceNames = ['Samantha', 'Daniel', 'Karen'];
const __voices = window.__appleVoiceNames.map((name) => ({
  name, lang: 'en-US', localService: true, default: name === 'Samantha',
}));
window.speechSynthesis = {
  getVoices: () => __voices,
  speak() {},
  cancel() {},
  onvoiceschanged: null,
};
window.SpeechSynthesisUtterance = function (text) { this.text = text; };
"""

# A ttsEngine whose tier we control. Defined as an accessor so the real
# /tts-engine.js module's later `window.ttsEngine = ...` assignment cannot
# replace it mid-test (the module resolves asynchronously).
_ENGINE_STUB = """
window.__ttsInitCalls = 0;
const __engine = {
  _tier: null,
  get tier() { return this._tier; },
  tierReason: '',
  tierDetail: '',
  listVoices() {
    if (this._tier !== 'neural-webgpu' && this._tier !== 'neural-wasm') return [];
    return [
      { id: 'af_heart',   name: 'Heart (Female)',   lang: 'en-us', grade: 'A'  },
      { id: 'am_michael', name: 'Michael (Male)',   lang: 'en-us', grade: 'C+' },
      { id: 'bf_emma',    name: 'Emma (Female)',    lang: 'en-gb', grade: 'B-' },
    ];
  },
  setVoice(id) { this.lastVoice = id; return Promise.resolve(); },
  speak() { return Promise.resolve(); },
  stop() {},
  init() { window.__ttsInitCalls += 1; return Promise.resolve(); },
};
Object.defineProperty(window, 'ttsEngine', {
  get: () => __engine,
  set: () => {},
  configurable: false,
});
window.__resolveTier = (tier, reason, detail) => {
  __engine._tier = tier;
  __engine.tierReason = reason || 'ok';
  __engine.tierDetail = detail || '';
  window.dispatchEvent(new CustomEvent('tts:tier-change', {
    detail: {
      tier, reason: reason || 'ok', detail: detail || '',
      degraded: tier !== 'neural-webgpu' && tier !== 'neural-wasm',
      environment: null,
    },
  }));
};
"""


def _goto(page: Page) -> None:
    page.goto(f"http://127.0.0.1:{WEB_PORT}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.wait_for_function(
        "() => !!(window.Alpine.store && window.Alpine.store('settings'))", timeout=5000
    )


def _picker_options(page: Page) -> list[str]:
    return page.evaluate(
        """() => {
            const el = document.getElementById('voice-select');
            return el ? [...el.options].map((o) => o.textContent.trim()) : [];
        }"""
    )


# ---------------------------------------------------------------------------
# The reported defect
# ---------------------------------------------------------------------------


class TestPickerNeverGuessesTheEngine:
    def test_unresolved_tier_shows_a_placeholder_not_apple_voices(self, web_page: Page) -> None:
        """The whole bug in one assertion.

        With the tier unresolved, the picker used to list Samantha/Daniel/Karen
        on every single page load of a Kokoro app.
        """
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)
        web_page.evaluate("() => window.Alpine.store('settings').loadVoices()")

        options = _picker_options(web_page)

        assert options == ["Detecting voice engine…"], (
            f"picker must not name an engine before the tier resolves: {options}"
        )
        for apple in web_page.evaluate("() => window.__appleVoiceNames"):
            assert not any(apple in o for o in options)

    def test_onvoiceschanged_cannot_refill_with_apple_voices(self, web_page: Page) -> None:
        """The OS fires onvoiceschanged asynchronously; before the fix that
        handler re-ran the Web Speech branch regardless of tier."""
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)

        web_page.evaluate(
            "() => window.speechSynthesis.onvoiceschanged "
            "&& window.speechSynthesis.onvoiceschanged()"
        )

        assert _picker_options(web_page) == ["Detecting voice engine…"]

    def test_placeholder_option_is_disabled_so_it_cannot_be_chosen(self, web_page: Page) -> None:
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)
        web_page.evaluate("() => window.Alpine.store('settings').loadVoices()")

        state = web_page.evaluate(
            """() => {
                const el = document.getElementById('voice-select');
                return { disabled: el.disabled, optDisabled: el.options[0].disabled };
            }"""
        )
        assert state == {"disabled": True, "optDisabled": True}

    def test_neural_tier_lists_kokoro_voices(self, web_page: Page) -> None:
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)

        web_page.evaluate("() => window.__resolveTier('neural-webgpu')")

        options = _picker_options(web_page)
        assert any("Michael" in o for o in options)
        assert any("Emma" in o for o in options)
        assert not any("Samantha" in o for o in options)
        assert web_page.evaluate("() => document.getElementById('voice-select').disabled") is False

    def test_neural_tier_restores_the_saved_kokoro_voice(self, web_page: Page) -> None:
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        web_page.add_init_script("localStorage.setItem('neuralVoiceId', 'bf_emma');")
        _goto(web_page)

        web_page.evaluate("() => window.__resolveTier('neural-wasm')")

        assert web_page.evaluate("() => document.getElementById('voice-select').value") == "bf_emma"

    def test_web_speech_tier_is_the_only_state_that_lists_os_voices(self, web_page: Page) -> None:
        """The fallback is still allowed — it just has to be a resolved,
        labelled decision rather than a default."""
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)

        web_page.evaluate("() => window.__resolveTier('web-speech', 'device-too-slow', 'too slow')")

        options = _picker_options(web_page)
        assert any("Samantha" in o for o in options)


# ---------------------------------------------------------------------------
# The engine badge — a degradation the learner can SEE
# ---------------------------------------------------------------------------


class TestEngineBadge:
    def _enable_voice(self, page: Page) -> None:
        page.evaluate(
            """() => {
                const s = window.Alpine.store('settings');
                s.voiceOn = true;
            }"""
        )

    def test_badge_reports_kokoro_when_neural_resolves(self, web_page: Page) -> None:
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)
        self._enable_voice(web_page)

        web_page.evaluate("() => window.__resolveTier('neural-webgpu')")
        web_page.wait_for_timeout(150)

        badge = web_page.locator("#tts-engine-badge")
        assert "Kokoro" in badge.inner_text()
        assert badge.is_visible()
        assert "degraded" not in (badge.get_attribute("class") or "")

    def test_badge_names_the_fallback_and_its_reason(self, web_page: Page) -> None:
        """A user running a Kokoro app must never silently get Apple voices."""
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)
        self._enable_voice(web_page)

        web_page.evaluate(
            """() => window.__resolveTier(
                 'web-speech', 'device-too-slow',
                 'this device needed 900ms to synthesise 200ms of audio')"""
        )
        web_page.wait_for_timeout(150)

        badge = web_page.locator("#tts-engine-badge")
        assert badge.is_visible()
        assert "degraded" in (badge.get_attribute("class") or "")
        title = badge.get_attribute("title") or ""
        assert "Kokoro is NOT active" in title
        assert "900ms" in title

    def test_badge_is_pending_before_the_tier_resolves(self, web_page: Page) -> None:
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)
        self._enable_voice(web_page)
        web_page.wait_for_timeout(150)

        badge = web_page.locator("#tts-engine-badge")
        assert "pending" in (badge.get_attribute("class") or "")
        assert "Detecting" in badge.inner_text()

    def test_engine_notice_reaches_the_user_as_a_toast(self, web_page: Page) -> None:
        """`tts:engine-notice` replaces the console.warn nobody reads."""
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)
        self._enable_voice(web_page)

        web_page.evaluate(
            """() => window.dispatchEvent(new CustomEvent('tts:engine-notice', {
                 detail: { code: 'voice-fetch-failed', level: 'error',
                           message: 'Could not download the "am_michael" voice' } }))"""
        )
        web_page.wait_for_timeout(150)

        state = web_page.evaluate(
            """() => ({
                notice: window.Alpine.store('settings').ttsNotice,
                toast: window.Alpine.store('toast').message,
                visible: window.Alpine.store('toast').visible,
            })"""
        )
        assert "am_michael" in state["notice"]
        assert "am_michael" in state["toast"]
        assert state["visible"] is True


# ---------------------------------------------------------------------------
# Engine initialisation is actually triggered
# ---------------------------------------------------------------------------


class TestTierResolutionIsTriggered:
    def test_init_is_called_at_load_when_voice_is_enabled(self, web_page: Page) -> None:
        """Nothing called init() at page load, which is why the tier never
        resolved and the picker never saw Kokoro."""
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        web_page.add_init_script("localStorage.setItem('voice', 'true');")
        _goto(web_page)

        web_page.wait_for_function("() => window.__ttsInitCalls > 0", timeout=5000)

    def test_init_is_not_forced_when_voice_is_off_and_model_uncached(self, web_page: Page) -> None:
        """Guardrail: don't spend 92 MB of someone's connection on a feature
        they have not switched on."""
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        web_page.add_init_script("localStorage.setItem('voice', 'false');")
        _goto(web_page)
        web_page.wait_for_timeout(400)

        assert web_page.evaluate("() => window.__ttsInitCalls") == 0


# ---------------------------------------------------------------------------
# tts-engine.js internals, exercised as real module code
# ---------------------------------------------------------------------------


class TestEngineModule:
    def test_speed_probe_excludes_the_warmup_inference(self, web_page: Page) -> None:
        """The probe used to time the FIRST inference, which pays ONNX graph
        build + kernel compilation. A capable machine measured >3x real time,
        was declared "too slow", and was demoted to Apple voices permanently.
        """
        _goto(web_page)
        result = web_page.evaluate(
            """async () => {
                const { TTSEngine } = await import('/tts-engine.js');
                const engine = new TTSEngine();
                let call = 0;
                const started = [];
                engine._synthesiseChunk = async () => {
                    call += 1;
                    started.push(call);
                    if (call === 1) {
                        // Expensive one-off warmup: 300ms of wall clock.
                        const until = performance.now() + 300;
                        while (performance.now() < until) { /* busy wait */ }
                    }
                    return 0.05;  // 50ms of audio
                };
                const probe = await engine._probeSpeed();
                return { calls: call, passed: probe.passed, ratio: probe.ratio,
                         reason: probe.reason };
            }"""
        )
        assert result["calls"] == 2, "probe must warm up first, then measure"
        assert result["passed"] is True, (
            "300ms of warmup against 50ms of audio must not count as a slow device"
        )
        assert result["ratio"] < 3.0
        assert result["reason"] == "ok"

    def test_speed_probe_still_rejects_a_genuinely_slow_device(self, web_page: Page) -> None:
        _goto(web_page)
        result = web_page.evaluate(
            """async () => {
                const { TTSEngine } = await import('/tts-engine.js');
                const engine = new TTSEngine();
                engine._synthesiseChunk = async () => {
                    const until = performance.now() + 250;
                    while (performance.now() < until) { /* busy wait */ }
                    return 0.05;
                };
                const probe = await engine._probeSpeed();
                return { passed: probe.passed, reason: probe.reason,
                         detail: probe.detail };
            }"""
        )
        assert result["passed"] is False
        assert result["reason"] == "device-too-slow"
        # The outcome must be explainable, not a bare boolean.
        assert "real time" in result["detail"]

    def test_probe_reports_a_failed_warmup_distinctly(self, web_page: Page) -> None:
        _goto(web_page)
        result = web_page.evaluate(
            """async () => {
                const { TTSEngine } = await import('/tts-engine.js');
                const engine = new TTSEngine();
                engine._synthesiseChunk = async () => {
                    throw new Error('voice bin 503');
                };
                const probe = await engine._probeSpeed();
                return { passed: probe.passed, reason: probe.reason,
                         detail: probe.detail };
            }"""
        )
        assert result["passed"] is False
        assert result["reason"] == "warmup-failed"
        assert "503" in result["detail"]

    def test_insecure_context_is_detected_and_explained(self, web_page: Page) -> None:
        """`studyloop web --lan` opened at http://<ip>:8567 is NOT a secure
        context: the browser hides navigator.gpu AND caches, which pushes the
        engine onto WASM, defeats model caching, and makes the speed probe far
        more likely to trip. This cannot be reproduced from a localhost test
        page, so the detector takes its inputs as arguments."""
        _goto(web_page)
        warnings = web_page.evaluate(
            """async () => {
                const mod = await import('/tts-engine.js');
                const env = mod.describeEnvironment({
                    secureContext: false, hasGpu: false, hasCaches: false,
                    origin: 'http://192.168.1.20:8567',
                });
                return env.warnings;
            }"""
        )
        codes = [w["code"] for w in warnings]
        assert "insecure-context" in codes
        message = next(w["message"] for w in warnings if w["code"] == "insecure-context")
        assert "192.168.1.20:8567" in message
        assert "localhost" in message

    def test_secure_context_without_webgpu_is_reported_as_a_lesser_warning(
        self, web_page: Page
    ) -> None:
        _goto(web_page)
        codes = web_page.evaluate(
            """async () => {
                const mod = await import('/tts-engine.js');
                return mod.describeEnvironment({
                    secureContext: true, hasGpu: false, hasCaches: true,
                }).warnings.map((w) => w.code);
            }"""
        )
        assert codes == ["no-webgpu"]

    def test_a_healthy_environment_produces_no_warnings(self, web_page: Page) -> None:
        _goto(web_page)
        warnings = web_page.evaluate(
            """async () => {
                const mod = await import('/tts-engine.js');
                return mod.describeEnvironment({
                    secureContext: true, hasGpu: true, hasCaches: true,
                }).warnings;
            }"""
        )
        assert warnings == []

    def test_set_tier_broadcasts_the_reason_not_just_the_tier(self, web_page: Page) -> None:
        _goto(web_page)
        detail = web_page.evaluate(
            """async () => {
                const { TTSEngine } = await import('/tts-engine.js');
                const engine = new TTSEngine();
                let seen = null;
                window.addEventListener('tts:tier-change',
                    (e) => { seen = e.detail; }, { once: true });
                engine._setTier('web-speech', 'device-too-slow', 'measured 7.4x');
                return seen;
            }"""
        )
        assert detail["tier"] == "web-speech"
        assert detail["reason"] == "device-too-slow"
        assert detail["detail"] == "measured 7.4x"
        assert detail["degraded"] is True
