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

Determinism note: the server tier cannot be reached in CI (it needs a running
Kokoro server on the host), so tier resolution is driven by dispatching the real
``tts:tier-change`` event and by installing a tier-bearing engine stub. What is
under test is the app's reaction to a tier, not the synthesis behind it. The
tiers are now ``server-openvox``, ``web-speech`` and ``silent``: the in-browser
neural tiers this file was written against have been removed, because they could
not run over ``--lan`` at all and were 6.6x real time where they could.

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
  // Mirrors the real engine: it restores 'serverVoiceId' inside _initServer and
  // exposes it here. The picker deliberately no longer reads localStorage itself
  // -- the engine owns which voice is live, so a stub without this getter makes
  // the picker look broken when it is behaving correctly.
  get voiceId() {
    if (this._tier !== 'server-openvox') return null;
    const saved = localStorage.getItem('serverVoiceId');
    const ids = this.listVoices().map((v) => v.id);
    return (saved && ids.includes(saved)) ? saved : (ids[0] || null);
  },
  tierReason: '',
  tierDetail: '',
  listVoices() {
    if (this._tier !== 'server-openvox') return [];
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
      // Derived from the explicit healthy tier, never as "not web-speech and
      // not silent" -- that negative form is what previously reported the
      // fastest tier as broken when a new tier was added.
      degraded: tier !== 'server-openvox',
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

        assert options == ["Turn on voice to load the engine"], (
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

        assert _picker_options(web_page) == ["Turn on voice to load the engine"]

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

    def test_server_tier_lists_the_hosts_voices(self, web_page: Page) -> None:
        """A resolved server tier must show the HOST's catalogue, not the OS's."""
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)

        web_page.evaluate("() => window.__resolveTier('server-openvox')")

        options = _picker_options(web_page)
        assert any("Michael" in o for o in options)
        assert any("Emma" in o for o in options)
        assert not any("Samantha" in o for o in options)
        assert web_page.evaluate("() => document.getElementById('voice-select').disabled") is False

    def test_server_tier_restores_the_saved_voice(self, web_page: Page) -> None:
        """Restored from 'serverVoiceId'.

        Host voice ids and system voice NAMES are different namespaces, so they
        get separate keys -- reusing one applied a host-only voice where no such
        voice existed. The retired 'neuralVoiceId' key is deliberately not read.
        """
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        web_page.add_init_script("localStorage.setItem('serverVoiceId', 'bf_emma');")
        _goto(web_page)

        web_page.evaluate("() => window.__resolveTier('server-openvox')")

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

    def test_badge_reports_kokoro_when_the_server_tier_resolves(self, web_page: Page) -> None:
        """The badge must name the engine, and must NOT read as degraded.

        It also must not leak the internal tier id: the label case for
        'server-openvox' is what stops the badge announcing that string to a user
        who is running VoiceMode or a container rather than OpenVox.
        """
        web_page.add_init_script(_APPLE_VOICES)
        web_page.add_init_script(_ENGINE_STUB)
        _goto(web_page)
        self._enable_voice(web_page)

        web_page.evaluate("() => window.__resolveTier('server-openvox')")
        web_page.wait_for_timeout(150)

        badge = web_page.locator("#tts-engine-badge")
        text = badge.inner_text()
        assert "Kokoro" in text
        assert "server-openvox" not in text, "the badge leaked the internal tier id"
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

    def test_init_is_not_forced_when_voice_is_off(self, web_page: Page) -> None:
        """Voice is off by default and init must respect that.

        The original reason was bandwidth -- init downloaded a ~92 MB model. That
        model is gone with the in-browser engine, but the rule survives on
        different grounds: init probes the host for a TTS server, and a user who
        has not switched voice on should not have requests made on their behalf.
        """
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
    """The engine's own module surface.

    Six tests were removed here with the in-browser neural engine: three covered
    _probeSpeed (the slow-device guard that decided whether WebGPU/WASM synthesis
    was fast enough) and three covered describeEnvironment (which explained why a
    non-secure origin degraded that engine). Both functions are deleted -- the
    server does the synthesis now, so neither a speed verdict nor a WebGPU
    warning has anything to act on. They are not replaced: the equivalent
    question, "is the host's TTS reachable", is answered by _initServer's probe
    and covered in test_web_tts_routes.py and tests/e2e/test_server_tts.py.
    """

    def test_failed_server_synthesis_retries_with_web_speech(
        self, web_page: Page
    ) -> None:
        """A health check is only a snapshot; the server may die before speak()."""
        web_page.route(
            "**/api/tts/health",
            lambda route: route.fulfill(
                json={
                    "available": True,
                    "voices": [{"id": "bf_emma", "british": True}],
                }
            ),
        )
        web_page.route(
            "**/api/tts/warm", lambda route: route.fulfill(json={"warmed": True})
        )
        web_page.route(
            "**/api/tts/speak",
            lambda route: route.fulfill(status=503, json={"detail": "all servers stopped"}),
        )
        web_page.add_init_script(
            """(() => {
                window.__spokenFallback = [];
                window.SpeechSynthesisUtterance = class {
                    constructor(text) { this.text = text; }
                };
                Object.defineProperty(window, 'speechSynthesis', {
                    configurable: true,
                    value: {
                        getVoices: () => [],
                        cancel: () => {},
                        speak: (utterance) => window.__spokenFallback.push(utterance.text),
                    },
                });
            })()"""
        )
        _goto(web_page)

        result = web_page.evaluate(
            """async () => {
                const { TTSEngine } = await import('/tts-engine.js');
                const engine = new TTSEngine();
                await engine.init();
                const before = engine.tier;
                await engine.speak('Continue with a system voice.');
                return {
                    before,
                    after: engine.tier,
                    spoken: window.__spokenFallback,
                };
            }"""
        )

        assert result == {
            "before": "server-openvox",
            "after": "web-speech",
            "spoken": ["Continue with a system voice."],
        }

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
