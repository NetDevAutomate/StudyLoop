# TTS Engine Decision

## Chosen Engine

**Kokoro-ONNX via @huggingface/transformers v4 (transformers.web.js) with the kokoro-v1.0.onnx weights and am_michael voice**

## Rationale

The four lens verdicts split across engines, but one decision breaks the deadlock: COOP/COEP must not be added because it would kill the ttyd iframe (SecurityHeadersMiddleware sets X-Frame-Options: SAMEORIGIN specifically for that embed). Any engine requiring SharedArrayBuffer (multi-threaded WASM) is therefore disqualified unless explicitly configured otherwise.

Kokoro-ONNX via transformers.js is the only option that satisfies all four constraints simultaneously:

1. **Audio quality**: Kokoro weights (am_michael, StyleTTS2-derived 82M params) are the same weights the Python backend uses and that the user has already validated as acceptable. No other engine under 100 MB matches this quality.

2. **No-build ESM**: transformers.js v4 dist/transformers.web.js is a genuine ESM bundle with no Node.js built-ins. The only friction is two bare-specifier imports (onnxruntime-web/webgpu and onnxruntime-common) which map to a 2-entry importmap — 3 vendored files total, zero bundler.

3. **Offline + cache survivability**: transformers.js exposes env.useBrowserCache = false and env.cacheType — setting cacheType to 'indexeddb' routes model weight storage to IndexedDB, which the SW self-destruct does not touch (it only clears Cache Storage via caches.delete()). This is a deliberate one-liner that must be set before model load.

4. **Infra blast radius**: ort.env.wasm.numThreads = 1 forces the single-threaded ort-wasm-simd.wasm backend. The WebGPU backend path bypasses WASM threads entirely. Either path requires zero header changes to app.py. The ttyd iframe is unaffected.

The kokoro-js package (scores 2/10 on ESM lens) is disqualified because its dist/kokoro.js imports path and fs/promises — Node built-ins with no browser equivalent. The fix is to use transformers.js directly with the kokoro model ID, bypassing the kokoro-js wrapper entirely. The weights are the same; only the JS wrapper differs.

Piper (@mintplex-labs/piper-tts-web) wins the download/cache lens but scores 0 on no-build-ESM (requires bun build, ships no ESM exports) and has no WebGPU path. It cannot be adopted without a build step, which is a hard constraint violation.

Transformers.js with SpeechT5/MMS scores 3/10 on download size (170 MB first-run vs 91 MB for Kokoro) and 3/10 on infra blast radius because its default backend is threaded WASM. It would require COOP/COEP to use as documented. Kokoro weights via transformers.js avoid this because the integration is configured explicitly rather than using the library's TTS convenience API.

## Runner-Up

**Piper via @mintplex-labs/piper-tts-web** — wins on download size (68 MB vs 91 MB) and IndexedDB caching is native (not a config option). Disqualified only by the hard no-build-step constraint: the package ships no ESM exports and requires bun build to produce usable worker bundles. If the project ever relaxes the build constraint (e.g., adds a CI vendoring step), Piper becomes the better pick for the download-size lens.

## Architecture

Three-tier engine with a unified tts-engine.js abstraction module:

**Tier 1 (neural)**: transformers.js v4 loading kokoro-v1.0.onnx + voices-v1.0.bin via the Kokoro model ID on HuggingFace (hexgrad/Kokoro-82M). Backend preference: WebGPU first (ort.env.backends.onnx.executionProviders = ['webgpu', 'wasm']). Single-thread WASM fallback: ort.env.wasm.numThreads = 1 set unconditionally before model load to ensure no SharedArrayBuffer is ever requested. IndexedDB persistence: env.useBrowserCache = false on the transformers global, then point the ort cache to IndexedDB via a custom cache adapter so weights survive the SW nuke. Audio output: transformers.js Kokoro pipeline returns Float32Array PCM; decoded via AudioContext.decodeAudioData, played via AudioBufferSourceNode (stored as _currentSource for stop()).

**Tier 2 (fallback)**: Web Speech API. Wraps existing speak/stopSpeaking logic. Activated when navigator.gpu is absent AND single-thread WASM synthesis takes longer than 3x realtime on a warmup probe (i.e., device is too slow).

**Tier 3 (last resort)**: silent no-op with console.warn. Never throws; caller UI degrades gracefully.

**Download progress**: transformers.js pipeline() emits progress callbacks with {status: 'progress', file, progress: 0-100}. The module aggregates per-file progress into a single 0-1 value emitted via a custom event 'tts:download-progress' on window. The first call to init() triggers the download; subsequent calls are cache hits (IndexedDB).

**Stop control**: all three tiers expose the same stop() method. Neural tier: _currentSource.stop() + _currentSource.disconnect(). Web Speech API tier: speechSynthesis.cancel(). The unified stop() also sets a _stopped flag checked in the async synthesis loop so queued chunks do not play after stop() is called mid-stream.

**State machine**: idle -> warming -> downloading -> ready -> speaking -> idle. isSpeaking is a boolean derived from state === 'speaking'. The Alpine store observes window 'tts:state-change' events and updates its own isSpeaking reactive property.

## Files to Create

- `packages/studyloop/src/studyloop/web/static/tts-engine.js`
- `packages/studyloop/src/studyloop/web/static/vendor/js/transformers-4.x.web.js`
- `packages/studyloop/src/studyloop/web/static/vendor/js/ort-webgpu.bundle.min.mjs`
- `packages/studyloop/src/studyloop/web/static/vendor/js/ort-common.mjs`

## Files to Edit

- `packages/studyloop/src/studyloop/web/static/index.html`
- `packages/studyloop/src/studyloop/web/static/components.js`
- `packages/studyloop/src/studyloop/web/app.py`

## Header Changes

app.py SecurityHeadersMiddleware: **NO changes required**. This is the whole point of choosing the numThreads=1 / WebGPU path. The existing three headers (X-Content-Type-Options, X-Frame-Options: SAMEORIGIN, X-XSS-Protection) remain untouched. COOP and COEP are not added.

The ttyd iframe blast radius is therefore zero — the existing X-Frame-Options: SAMEORIGIN header already allows it, and no browsing-context-group isolation is introduced.

One optional addition that does NOT affect ttyd: if the team later wants to enable the multi-threaded WASM path (for performance on high-end devices), the correct approach is to add COOP/COEP only to the /api/tts/* namespace via a separate middleware that checks request.url.path.startswith('/api/tts') — not to the global SecurityHeadersMiddleware. This is documented as a future option in tts-engine.js comments but is not part of the current implementation.

## SW Changes

sw.js: The self-destruct block (lines 1-13) must NOT be reversed — it is intentional for development. The model weight caching strategy deliberately bypasses Cache Storage entirely.

The only required SW change: in the fetch handler (line 43 onwards, currently dead because the return on line 13 exits the worker), when the SW is eventually re-enabled, add a rule to never intercept requests to HuggingFace CDN or ONNX weight files. Specifically, skip caching for URLs matching `/\.onnx$/`, `/\.bin$/`, and hostname 'huggingface.co' or 'cdn-lfs.huggingface.co'.

The active caching path for model weights is IndexedDB, managed by ONNX Runtime Web's built-in cache layer. tts-engine.js sets this up with:

```js
import { env } from '/vendor/js/transformers-4.x.web.js';
env.useBrowserCache = false; // disable Cache Storage
env.localModelPath = null;   // no local file serving
// ort-specific: the ORT Web IndexedDB cache is enabled by default in ORT >=1.18
// No further configuration needed; ORT stores compiled WASM modules and downloaded
// weights in 'onnxruntime-web' IndexedDB store automatically.
```

This means: first run downloads ~91 MB (kokoro-v1.0.onnx ~82 MB + voices-v1.0.bin ~6 MB + ort WASM ~3 MB). On all subsequent page loads, ORT Web reads from IndexedDB — the SW nuke has no effect.

## Stop Button Design

The unified stop() method in tts-engine.js:

```js
stop() {
  this._stopped = true;
  if (this._currentSource) {
    try { this._currentSource.stop(); } catch (_) {}
    this._currentSource.disconnect();
    this._currentSource = null;
  }
  if (this._audioCtx) {
    this._audioCtx.suspend();
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel(); // covers WSA fallback
  this._setState('idle');
}
```

In components.js the settings store's stopSpeaking() is replaced with:

```js
stopSpeaking() { window.ttsEngine?.stop(); }
```

The Alpine isSpeaking reactive property is bound to a 'tts:state-change' event listener:

```js
window.addEventListener('tts:state-change', (e) => {
  this.isSpeaking = e.detail.state === 'speaking';
});
```

The stop button in index.html header-controls:

```html
<button class="toggle-btn stop-tts-btn"
        x-show="$store.settings.isSpeaking"
        x-cloak
        @click="$store.settings.stopSpeaking()"
        title="Stop reading aloud">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <rect x="6" y="6" width="12" height="12" rx="1"/>
  </svg>
</button>
```

Placement: immediately after the existing voice-toggle button (the speaker-wave SVG button at index.html line 79). The stop button is x-show-controlled by isSpeaking — it replaces the visual affordance while speaking and disappears when idle. It does NOT replace the voice-toggle button itself; both can coexist.

For the reviewApp.speakCurrentCard() call site (components.js line 687-696): replace the inline speechSynthesis calls with:

```js
speakCurrentCard() {
  if (!this.currentCard) return;
  const text = this.currentCard.type === 'flashcard'
    ? (this.revealed ? this.currentCard.back : this.currentCard.front)
    : this.currentCard.question;
  window.ttsEngine?.speak(text);
}
```

This routes through the unified engine for all three tiers including stop() support.

## Fallback Chain

The engine detects its tier at init() time and records the active tier in this._tier:

1. **Probe WebGPU**: 'gpu' in navigator AND (await navigator.gpu.requestAdapter()) !== null. If true, set ort executionProviders = ['webgpu']. Tier = 'neural-webgpu'.

2. If WebGPU unavailable, set ort executionProviders = ['wasm'], numThreads = 1. Run a warmup probe: synthesise a 5-word string and measure wall-clock time vs audio duration. If synthesis_time > 3 * audio_duration, the device is too slow for real-time WASM. Tier = 'neural-wasm' (fast enough) or fall through to tier 3.

3. If device too slow or any ONNX load error (network error, OOM, unsupported WASM): fall back to Web Speech API. Activate existing loadVoices() / onVoiceChange() logic. Tier = 'web-speech'.

4. If speechSynthesis absent (unusual but possible): silent no-op with console.warn. Tier = 'silent'.

The tier is exposed as window.ttsEngine.tier (read-only string) and emitted in every 'tts:state-change' event as e.detail.tier. The voice-select dropdown is shown only when tier === 'web-speech' (neural engine has no voice variety in v1). A future 'tts:tier-change' event fires once when the tier is resolved, allowing the settings panel to update the voice UI.

**Download-progress during tier 1 init**: transformers.js pipeline() accepts a progress_callback. The engine aggregates file-level progress (files: kokoro-v1.0.onnx, voices-v1.0.bin, tokenizer.json) into a single 0-100 integer emitted as 'tts:download-progress' with detail { pct: number, file: string, done: boolean }. The settings panel or a dedicated download-progress bar component listens to this event and renders a progress indicator. On done: true the indicator auto-hides.

## Test Plan

### 1. tts-engine.js unit tests (tests/web/test_tts_engine.py or a JS test file if the project adds one)

- init() resolves without throwing when WebGPU is mocked absent
- stop() sets _stopped = true and disconnects _currentSource without throwing when called before any speech
- 'tts:state-change' event fires with state='speaking' on speak() and state='idle' on stop()
- 'tts:download-progress' events fire with ascending pct values during model fetch (mock fetch with progress)
- Fallback to 'web-speech' tier when ONNX load throws (mock pipeline() to throw OOMError)

### 2. Integration smoke test (manual, documented in CONTRIBUTING.md)

a. Load app in Chrome with DevTools open, Network tab throttled to Slow 3G
b. Click voice toggle — 'tts:download-progress' events should appear in console with ascending pct
c. A progress indicator should appear in the header during download
d. After download: trigger speakCurrentCard() — audio should play from AudioBufferSourceNode (not speechSynthesis)
e. While audio is playing, the stop button (square icon) should be visible
f. Click stop button — audio stops immediately, stop button disappears, isSpeaking resets to false
g. Reload page — model loads from IndexedDB, no network requests for .onnx/.bin files (verify in Network tab: no HF CDN requests)

### 3. SW self-destruct regression

Verify that after sw.js activates (clears Cache Storage), the model is still loaded from IndexedDB on next synthesise call. This is the critical regression that would catch any accidental use of Cache Storage for weights.

### 4. ttyd iframe regression

Load the terminal panel while audio is playing, verify it renders and is interactive. Confirm no COOP/COEP headers in response headers (DevTools > Network > index.html response headers).

### 5. Slow-device fallback test

In tts-engine.js, add a test-only hook to force warmup_ratio > 3. Verify tier falls back to 'web-speech' and the voice-select dropdown becomes visible.
