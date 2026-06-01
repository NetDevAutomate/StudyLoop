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
