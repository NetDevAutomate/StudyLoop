"""Tests for the in-browser neural TTS engine — vendored assets and wiring.

These guard the static-asset contract that makes Kokoro-via-transformers.js work
in a no-build offline PWA. They are intentionally static-file assertions (no live
browser): the runtime synthesis path is verified manually via Playwright, but the
brittle, regression-prone parts are the importmap ↔ vendored-file ↔ engine-import
agreement, which a string/existence check catches cheaply.

Background: the ORT WASM must be a version-matched pair served locally; if the
filenames drift, transformers.js silently falls back to its jsdelivr CDN copies,
which breaks offline use AND triggers `_OrtGetInputName is not a function`.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "studyloop" / "web" / "static"
VENDOR_JS = STATIC_DIR / "vendor" / "js"
ENGINE = STATIC_DIR / "tts-engine.js"

# The exact ORT WASM filenames transformers.js 3.5.2 requests when
# env.backends.onnx.wasm.wasmPaths points at /vendor/js/. The JSEP build serves
# both the webgpu and wasm execution providers, so this single pair covers both
# neural tiers. If these names drift, ORT 404s and falls back to the CDN.
ORT_WASM_FILES = (
    "ort-wasm-simd-threaded.jsep.wasm",
    "ort-wasm-simd-threaded.jsep.mjs",
)
TRANSFORMERS_LIB = "transformers-3.5.2.web.js"


class TestNeuralTtsVendorFiles:
    def test_tts_engine_module_exists(self):
        assert ENGINE.exists(), "tts-engine.js missing"

    def test_transformers_lib_vendored(self):
        assert (VENDOR_JS / TRANSFORMERS_LIB).exists()

    def test_ort_wasm_pair_vendored(self):
        for name in ORT_WASM_FILES:
            assert (VENDOR_JS / name).exists(), f"vendored ORT file missing: {name}"

    def test_ort_wasm_binary_is_substantial(self):
        # The real ORT WASM binary is ~20+ MB; a tiny file means a failed download
        # or an HTML error page got saved instead.
        wasm = VENDOR_JS / "ort-wasm-simd-threaded.jsep.wasm"
        assert wasm.stat().st_size > 1_000_000, "ORT WASM binary suspiciously small"


class TestImportmapConsistency:
    """The importmap, the vendored files, and the engine's bare-specifier imports
    must all name the same files — the #1 regression risk for this feature."""

    def test_importmap_present_before_module_script(self):
        html = (STATIC_DIR / "index.html").read_text()
        imap = html.find('type="importmap"')
        mod = html.find('src="/tts-engine.js"')
        assert imap != -1, "importmap missing from index.html"
        assert mod != -1, "tts-engine.js module script missing"
        assert imap < mod, "importmap must precede the tts-engine.js module script"

    def test_importmap_targets_exist_on_disk(self):
        """Every /vendor/js/* target in the importmap must be a real file."""
        html = (STATIC_DIR / "index.html").read_text()
        # Pull the importmap block and assert each vendored path resolves.
        for name in (TRANSFORMERS_LIB, "ort.all.bundle.min.mjs", "phonemizer-1.2.1.js"):
            ref = f"/vendor/js/{name}"
            if ref in html:
                assert (VENDOR_JS / name).exists(), f"importmap references missing file: {ref}"

    def test_engine_pins_wasm_paths_to_vendor(self):
        """The wasmPaths pin is what keeps ORT off the CDN — must point at /vendor/js/."""
        src = ENGINE.read_text()
        assert "wasmPaths" in src
        assert "/vendor/js/" in src

    def test_engine_uses_quantised_dtype_not_fp32(self):
        """fp32 is the 326 MB variant — wrong for browser. Must be q8."""
        src = ENGINE.read_text()
        assert "'q8'" in src or '"q8"' in src
        assert "KOKORO_DTYPE = 'fp32'" not in src

    def test_engine_selects_device_via_from_pretrained(self):
        """device must be passed to from_pretrained, NOT assigned to the no-op
        env.backends.onnx.preferredBackend (which is not a real transformers.js v3
        field). A mention in comments is fine; an assignment is the regression."""
        src = ENGINE.read_text()
        assert "preferredBackend =" not in src, "preferredBackend is not a real v3 field"
        assert "device" in src


class TestStopControl:
    """The user-requested stop button must call a unified engine stop() that halts
    neural WebAudio playback, not merely speechSynthesis.cancel()."""

    def test_stop_button_in_html(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert "stop-tts-btn" in html
        assert "stopSpeaking()" in html

    def test_stop_button_bound_to_is_speaking(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert 'x-show="$store.settings.isSpeaking"' in html

    def test_store_stop_delegates_to_engine(self):
        components = (STATIC_DIR / "components.js").read_text()
        assert "isSpeaking" in components
        # stopSpeaking should route through the unified engine, not only speechSynthesis
        assert "ttsEngine" in components

    def test_engine_stop_halts_webaudio_source(self):
        """stop() must stop the AudioBufferSourceNode, not just cancel speechSynthesis."""
        src = ENGINE.read_text()
        assert "_currentSource" in src
        assert ".stop()" in src
        assert "_pendingPlayResolve" in src, "stop() must settle the in-flight playback promise"


class TestVoiceCatalogueIsEnglishOnly:
    """The catalogue is a security boundary, not just a menu.

    Voice embeddings are fetched at runtime from the model repo's voices/
    directory, which ships 54 files — including jf_* (Japanese), zf_* (Mandarin),
    ef_* (Spanish), ff_* (French), hf_* (Hindi) and if_* (Italian) — and
    Kokoro-82M-v1.0 can speak every one of them. So an id outside the catalogue
    does NOT 404: it loads successfully and speaks another language. That is the
    mechanism behind the reported "the voice suddenly sounds Mandarin" symptom,
    and the catalogue plus the setVoice() guard are the only things preventing it.
    """

    #: Only American (a) and British (b) English prefixes may appear.
    ALLOWED_PREFIXES = ("af_", "am_", "bf_", "bm_")

    def _catalogue_ids(self) -> list[str]:
        src = ENGINE.read_text()
        start = src.index("const KOKORO_VOICES")
        end = src.index("});", start)
        body = src[start:end]
        return re.findall(r"^\s{2}([a-z]{2}_[a-z]+):", body, re.MULTILINE)

    def test_catalogue_is_not_empty(self) -> None:
        """A vacuous pass here would make every assertion below meaningless."""
        assert len(self._catalogue_ids()) >= 9

    def test_every_voice_is_english(self) -> None:
        offenders = [v for v in self._catalogue_ids() if not v.startswith(self.ALLOWED_PREFIXES)]
        assert not offenders, (
            f"non-English voices in the catalogue: {offenders}. These load fine from "
            "the CDN and will speak that language — remove them."
        )

    def test_default_voice_is_in_the_catalogue(self) -> None:
        """A default outside the catalogue leaves the engine with no voice
        metadata, so the phonemiser language falls back silently."""
        src = ENGINE.read_text()
        match = re.search(r"const DEFAULT_VOICE = '([a-z]{2}_[a-z]+)'", src)
        assert match, "DEFAULT_VOICE not found or not a bare voice id"
        assert match.group(1) in self._catalogue_ids()

    def test_set_voice_validates_before_assigning(self) -> None:
        """Regression guard: setVoice() used to assign this._voiceId FIRST and
        only check the catalogue when deciding whether to pre-warm, so an
        unknown id still became the live voice.

        Scoped to the NEURAL branch deliberately. An earlier version of this test
        took a fixed 1200-character window from the top of setVoice(), which broke
        the moment a server-tier branch was added ahead of it -- the behaviour was
        still correct, but the test was measuring position in a string rather than
        the ordering it cared about. Anchoring on `const isNeural` pins the branch
        this rule is actually about.
        """
        src = ENGINE.read_text()
        start = src.index("async setVoice(voiceId)")
        neural = src.index("const isNeural", start)
        body = src[neural : src.index("\n  }", neural)]
        guard = body.index("!KOKORO_VOICES[voiceId]")
        assign = body.index("this._voiceId = voiceId")
        assert guard < assign, (
            "setVoice() assigns the voice before validating it against the catalogue"
        )

    def test_the_server_branch_also_validates_before_assigning(self) -> None:
        """The server tier has its own catalogue and needs the same ordering.

        Its voices come from the host rather than KOKORO_VOICES, so the neural
        guard above does not cover it -- and the same hazard applies: an id the
        host does not offer must never become the live voice.
        """
        src = ENGINE.read_text()
        start = src.index("async setVoice(voiceId)")
        branch = src[start : src.index("const isNeural", start)]
        assert "_serverVoices" in branch, "server branch does not consult the host catalogue"
        guard = branch.index("if (!known)")
        assign = branch.index("this._voiceId = voiceId")
        assert guard < assign, "server branch assigns before validating"


COMPONENTS = STATIC_DIR / "components.js"


class TestWebSpeechFallbackFoundOnRealDevices:
    """Guards for three defects found by testing on an iPad and an Android tablet.

    All three share one shape: the picker and the engine disagreed about which
    voice was live, so the UI named one voice and another spoke -- or none
    changed at all. None was visible on a desktop browser, which is why they
    survived until real hardware ran them.

    Context that makes these load-bearing rather than cosmetic: a tablet loading
    the app over `--lan` gets a plain-HTTP origin, so `isSecureContext` is false
    and the browser hides BOTH navigator.gpu and Cache Storage (verified against
    the real LAN address). In-browser Kokoro therefore cannot run there at all,
    which makes Web Speech the permanent tablet fallback rather than a last
    resort -- so its bugs matter as much as the neural tier's.
    """

    def test_utterance_language_is_set_alongside_the_voice(self) -> None:
        """Android exposes one voice per locale and ignores `voice` on its own.

        Selecting "English (Australia)" instead of "English (United Kingdom)"
        changed the dropdown label and nothing audible. Setting `lang` from the
        matched voice is what makes the selection take effect.
        """
        src = ENGINE.read_text()
        # Anchor on the DEFINITION, not a call site: `this._speakWSA(text);` now
        # appears earlier inside the server tier's fallback path, and matching it
        # sliced the wrong function.
        start = src.index("_speakWSA(text) {")
        body = src[start : src.index("\n  }", start)]
        assert "utter.voice = match" in body
        assert "utter.lang = match.lang" in body, (
            "utter.lang is not set from the matched voice — Android will ignore the selection"
        )

    def test_the_computed_default_voice_is_persisted(self) -> None:
        """The picker chose a preferred voice, displayed it, and never stored it.

        Only the stored key is read at speak time, so a displayed-but-unstored
        choice let the browser's own default speak while the UI named something
        better. Same defect already fixed once on the neural tier.
        """
        src = COMPONENTS.read_text()
        start = src.index("_preferredVoice =")
        window = src[start : start + 1400]
        assert 'localStorage.setItem("voiceName"' in window, (
            "the computed default voice is never persisted, so the engine cannot use it"
        )

    def test_the_server_tier_does_not_write_the_neural_voice_key(self) -> None:
        """onVoiceChange's neural test is "any tier that isn't web-speech or
        silent", which swallowed the server tier when it was added and wrote a
        HOST voice id into 'neuralVoiceId' — where it would later be offered to
        an engine with no such voice. The server branch must come first.
        """
        src = COMPONENTS.read_text()
        start = src.index("onVoiceChange(name)")
        body = src[start : src.index("\n    },", start)]
        server = body.index("'server-openvox'")
        neural = body.index('localStorage.setItem("neuralVoiceId"')
        assert server < neural, (
            "the server tier is handled after the neural branch, so it writes the wrong key"
        )
