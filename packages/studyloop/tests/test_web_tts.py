"""Tests for the browser TTS engine's static contract.

StudyLoop speaks through a server-side Kokoro: the browser POSTs to
`/api/tts/speak` and plays the response. The in-browser neural engine that these
tests were originally written for -- Kokoro-82M via transformers.js, on WebGPU or
WASM -- has been removed, so the assertions here changed shape with it.

What they still guard: that no tier can reach the user as a raw internal id, that
the ~27MB neural runtime stays deleted, that stop() actually stops the transport
now in use, and that a voice id is validated before it becomes live.

Where the old English-only invariant went: it used to live in this file, against
the JS `KOKORO_VOICES` catalogue. It is now enforced SERVER-side, because the
browser no longer holds a catalogue -- `_ENGLISH_VOICE_PREFIXES` in
`learning/voice.py` plus the filter in `web/routes/tts.py`, covered by
`test_openvox_web_client.py` and `test_web_tts_routes.py`. That move matters: a
real Kokoro server offers 67 voices across seven languages, and a non-English id
is a VALID request that speaks that language rather than an error, so the guard
had to sit where the catalogue does.

These are intentionally static-file assertions rather than a live browser: the
runtime path is verified against real hardware, and what breaks silently is the
agreement between files.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "studyloop" / "web" / "static"
VENDOR_JS = STATIC_DIR / "vendor" / "js"
ENGINE = STATIC_DIR / "tts-engine.js"
COMPONENTS = STATIC_DIR / "components.js"

#: Every tier id the engine can report. The neural pair is deliberately absent.
ALL_TIERS = ("server-openvox", "web-speech", "silent")


class TestEngineLabelsCoverEveryTier:
    """Every tier the engine can report must have a human label.

    ttsEngineLabel ends in `return String(this.ttsTier)`, so a tier with no case
    does not fail -- it renders its internal id. That is how the primary path came
    to announce itself as "server-openvox" on a machine where OpenVox was not even
    running, reported from a tablet. The fallthrough is worth keeping as a
    last-resort guard, which is precisely why it needs a test above it.
    """

    def _label_block(self) -> str:
        source = COMPONENTS.read_text(encoding="utf-8")
        start = source.index("get ttsEngineLabel()")
        return source[start : start + 1400]

    def test_every_tier_id_has_an_explicit_label(self):
        block = self._label_block()
        # Match the CODE, not a mention of it. An earlier version of this test
        # looked for the bare quoted id and still passed after the label case was
        # deleted, because the explanatory comment above it also quotes
        # 'server-openvox' -- it was asserting on prose. Requiring the whole
        # `if (...) return` shape is what makes it a test of behaviour.
        for tier in ALL_TIERS:
            needle = f"if (this.ttsTier === '{tier}') return "
            assert needle in block, (
                f"tier {tier!r} has no label case, so the picker will show the raw id to the user"
            )

    def test_the_server_tier_label_does_not_name_a_specific_product(self):
        """The label must not say OpenVox -- the server is often something else.

        Verified against three interchangeable backends: OpenVox, VoiceMode's
        Kokoro and a container. Naming one of them in the UI is wrong for the
        other two, and reads as a bug to anyone running them.
        """
        block = self._label_block()
        marker = "if (this.ttsTier === 'server-openvox') return "
        assert marker in block, "server tier label case missing"
        label = block[block.index(marker) + len(marker) :].split(";")[0]
        assert "openvox" not in label.lower(), (
            f"the server tier label names OpenVox specifically: {label}"
        )
        assert label.strip() not in ("String(this.ttsTier)", ""), (
            "the server tier must not fall through to its raw id"
        )

    def test_no_neural_tier_survives_anywhere(self):
        """The neural tiers are gone; a stray reference means a dead branch.

        Written as a whole-file scan rather than a label check because the danger
        is not a missing label -- it is a conditional that can never be true
        silently shaping behaviour, e.g. a healthy-tier list that still admits a
        tier the engine can no longer report.
        """
        for path in (ENGINE, COMPONENTS):
            source = path.read_text(encoding="utf-8")
            for dead in ("neural-webgpu", "neural-wasm"):
                assert dead not in source, f"{path.name} still references the removed tier {dead!r}"


class TestTheNeuralRuntimeStaysDeleted:
    """~27MB of vendored model runtime was removed with the in-browser engine.

    This is a regression guard with a specific failure in mind: re-vendoring ORT
    or transformers.js "just to try something" puts a 23MB binary back into git
    history, where it cannot be removed without a rewrite. Cheap to assert, and
    the alternative is discovering it after the push.
    """

    #: Deleted with the neural tier. Sizes were 1.6MB, 815KB, 23MB, 52KB, 1.3MB.
    REMOVED_VENDOR_FILES = (
        "transformers-3.5.2.web.js",
        "ort.all.bundle.min.mjs",
        "ort-wasm-simd-threaded.jsep.wasm",
        "ort-wasm-simd-threaded.jsep.mjs",
        "phonemizer-1.2.1.js",
    )

    def test_tts_engine_module_exists(self):
        assert ENGINE.exists(), "tts-engine.js missing"

    def test_the_neural_runtime_is_not_vendored(self):
        present = [f for f in self.REMOVED_VENDOR_FILES if (VENDOR_JS / f).exists()]
        assert not present, (
            f"the neural runtime is back in vendor/js: {present}. The browser engine was "
            f"removed; nothing loads these, and the ORT wasm alone is 23MB of git history."
        )

    def test_the_engine_does_not_import_the_neural_runtime(self):
        source = ENGINE.read_text(encoding="utf-8")
        for spec in ("@huggingface/transformers", "onnxruntime", "phonemizer"):
            assert spec not in source, (
                f"tts-engine.js still references {spec!r}, which is no longer vendored -- "
                f"the import would fall through to a CDN or fail outright"
            )

    def test_the_importmap_no_longer_aliases_the_neural_runtime(self):
        """The importmap existed only for these bare specifiers.

        Its four entries are gone with them. Asserting the aliases are absent
        rather than that the block is absent, because a future feature may
        legitimately reintroduce an importmap for something else.
        """
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for alias in (
            '"@huggingface/transformers":',
            '"onnxruntime-web":',
            '"onnxruntime-common":',
            '"phonemizer":',
        ):
            assert alias not in html, f"index.html still aliases {alias} in an importmap"


class TestStopControl:
    """The stop button must halt the transport actually in use.

    It previously had to stop an AudioBufferSourceNode, because neural synthesis
    played through WebAudio. Server audio plays through an Audio element instead,
    so the assertion moved with the implementation -- the user-visible rule is
    unchanged: pressing stop stops the sound.
    """

    def test_stop_button_in_html(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert "stop-tts-btn" in html
        assert "stopSpeaking()" in html

    def test_stop_button_bound_to_is_speaking(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert 'x-show="$store.settings.isSpeaking"' in html

    def test_store_stop_delegates_to_engine(self):
        components = COMPONENTS.read_text()
        assert "isSpeaking" in components
        assert "ttsEngine" in components

    def test_engine_stop_pauses_server_audio_and_cancels_speech(self):
        """Both live transports must be stopped, not just one.

        Pausing the Audio element is what makes stop() audibly stop on the server
        tier -- without it the clip played to the end. speechSynthesis.cancel()
        covers the fallback tier. Missing either leaves a tier that ignores the
        button.
        """
        source = ENGINE.read_text(encoding="utf-8")
        start = source.index("stop() {")
        body = source[start : source.index("\n  }", start)]
        assert "_serverAudio" in body and ".pause()" in body, (
            "stop() does not pause the server audio element, so server-tier playback continues"
        )
        assert "speechSynthesis" in body and "cancel()" in body, (
            "stop() does not cancel speechSynthesis, so the fallback tier continues"
        )


class TestServerVoiceValidation:
    """A voice id must be validated before it becomes the live voice.

    This survived the deletion because the hazard did. The engine no longer holds
    a catalogue, but the host's catalogue is still a boundary: a real Kokoro
    server offers voices in seven languages, and an id it does not offer must
    never become live. The original bug was ordering -- setVoice() assigned
    this._voiceId first and validated afterwards.
    """

    def test_the_server_branch_validates_before_assigning(self) -> None:
        source = ENGINE.read_text(encoding="utf-8")
        start = source.index("async setVoice(voiceId)")
        body = source[start : source.index("\n  }", start)]
        assert "_serverVoices" in body, "server branch does not consult the host catalogue"
        guard = body.index("if (!known)")
        assign = body.index("this._voiceId = voiceId")
        assert guard < assign, "setVoice() assigns the voice before validating it"

    def test_the_default_voice_is_a_british_english_id(self) -> None:
        """The default must be an English voice, and is deliberately British.

        Checked as a prefix rather than against a catalogue, since the browser no
        longer has one -- `bf_`/`bm_` is British, `af_`/`am_` American, and
        anything else is another language entirely.
        """
        source = ENGINE.read_text(encoding="utf-8")
        match = re.search(r"const DEFAULT_VOICE = '([a-z]{2}_[a-z]+)'", source)
        assert match, "DEFAULT_VOICE not found or not a bare voice id"
        assert match.group(1).startswith(("bf_", "bm_")), (
            f"DEFAULT_VOICE is {match.group(1)!r}, which is not a British English voice"
        )

    def test_a_saved_voice_is_restored_but_only_if_the_host_still_offers_it(self) -> None:
        """The engine owns which voice is live, and must re-check a saved id.

        The picker deliberately no longer reads localStorage itself -- it asks the
        engine -- so this restoration is the only thing that makes a chosen voice
        survive a reload. It is guarded here because the browser test cannot prove
        it: that test installs an engine stub, so it verifies the picker DISPLAYS
        what the engine reports, not that the engine reports the right thing.

        The "still offers it" half matters because backends are interchangeable:
        a voice saved against one Kokoro server may be absent from the next, and
        a saved id that is silently kept would ask for a voice the host does not
        have.
        """
        source = ENGINE.read_text(encoding="utf-8")
        # Anchor on the DEFINITION. Anchoring on the bare name found a mention in
        # the file header instead and measured a window of prose -- the same
        # mistake this file's Web Speech test already documents. `async` is what
        # distinguishes the definition from both the comment and the call site.
        start = source.index("async _initServer()")
        body = source[start : source.index("\n  }", start)]
        assert "localStorage.getItem('serverVoiceId')" in body, (
            "_initServer does not restore the saved voice, so a chosen voice will not "
            "survive a reload"
        )
        assert "includes(saved)" in body, (
            "the saved voice is used without checking the host still offers it"
        )


class TestWebSpeechFallbackFoundOnRealDevices:
    """Guards for defects found by testing on an iPad and an Android tablet.

    They share one shape: the picker and the engine disagreed about which voice
    was live, so the UI named one voice and another spoke -- or none changed at
    all. None was visible on a desktop browser, which is why they survived until
    real hardware ran them.

    Web Speech is the permanent fallback rather than a last resort: a tablet
    loading the app over `--lan` gets a plain-HTTP origin, so `isSecureContext`
    is false. That is also why the neural tier could never work there, and why it
    is gone -- but the fallback's own bugs still matter, because it is what a user
    gets whenever no Kokoro server is reachable.
    """

    def test_utterance_language_is_set_alongside_the_voice(self) -> None:
        """Android exposes one voice per locale and ignores `voice` on its own.

        Selecting "English (Australia)" instead of "English (United Kingdom)"
        changed the dropdown label and nothing audible. Setting `lang` from the
        matched voice is what makes the selection take effect.
        """
        src = ENGINE.read_text()
        # Anchor on the DEFINITION, not a call site: `this._speakWSA(text);` also
        # appears inside the server tier's fallback path, and matching that
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
        better.
        """
        src = COMPONENTS.read_text()
        start = src.index("_preferredVoice =")
        window = src[start : start + 1400]
        assert 'localStorage.setItem("voiceName"' in window, (
            "the computed default voice is never persisted, so the engine cannot use it"
        )

    def test_no_voice_id_is_written_to_the_retired_neural_key(self) -> None:
        """'neuralVoiceId' must not be written or read anywhere.

        This replaces an ordering test. The original defect was that the server
        tier fell through a branch written as "any tier that is not web-speech or
        silent" and wrote a HOST voice id into 'neuralVoiceId', where it would
        later be handed to an engine with no such voice. With the neural tier
        deleted the ordering no longer exists to get wrong -- but a leftover
        read or write would now silently restore a voice from a namespace nothing
        maintains, so the key itself is what to assert on.
        """
        for path in (ENGINE, COMPONENTS):
            source = path.read_text(encoding="utf-8")
            assert "neuralVoiceId" not in source, (
                f"{path.name} still touches the retired 'neuralVoiceId' key"
            )
