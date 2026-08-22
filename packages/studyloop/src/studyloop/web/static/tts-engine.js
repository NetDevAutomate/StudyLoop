/**
 * tts-engine.js — StudyLoop in-browser neural TTS engine
 *
 * Three-tier architecture (auto-detected at init time):
 *   Tier 1: Kokoro-82M via transformers.js v3 (WebGPU → single-thread WASM)
 *   Tier 2: Web Speech API (system voices, existing behaviour)
 *   Tier 3: Silent no-op (audio unavailable)
 *
 * Public API (assigned to window.ttsEngine after init):
 *   await ttsEngine.init()         — probe GPU, load ORT backend, warm up model
 *   await ttsEngine.speak(text)    — synthesise + play; resolves when playback starts
 *   ttsEngine.stop()               — stop in-flight synthesis AND in-flight WebAudio
 *   ttsEngine.listVoices()         — array of { id, name, lang, tier }
 *   ttsEngine.isReady              — true after init() completes without error
 *   ttsEngine.isSpeaking           — true while audio is playing
 *   ttsEngine.tier                 — 'neural-webgpu' | 'neural-wasm' | 'web-speech' | 'silent'
 *   ttsEngine.onProgress           — assign a function(pct, file, done) to receive download progress
 *
 * describeEnvironment(signals) — named export alongside TTSEngine (see below).
 *
 * Events (fired on window):
 *   'tts:state-change'   — detail: { state, tier }   (state: idle|warming|downloading|ready|speaking)
 *   'tts:download-progress' — detail: { pct, file, done }
 *   'tts:tier-change'    — detail: { tier, reason, detail, degraded }
 *       reason/detail explain WHY the tier landed where it did (e.g. reason:
 *       'device-too-slow', detail: 'measured 7.4x real time'); degraded is
 *       true whenever the tier is not one of the neural tiers.
 *
 * describeEnvironment({ secureContext, hasGpu, hasCaches, origin }) — pure
 * function, exported alongside TTSEngine. Explains, ahead of any actual
 * init() attempt, why the neural tier may be unavailable or degraded in the
 * caller's environment. Returns { warnings: [{ code, message }, ...] }:
 *   - 'insecure-context' when secureContext is false (navigator.gpu and the
 *     browser caches are hidden on non-secure origins); message names the
 *     origin and points at localhost/HTTPS as the fix.
 *   - 'no-webgpu' when secureContext is true but hasGpu is false — a lesser
 *     warning, since WASM Tier 1 still works, just slower.
 *   - No warnings at all when secureContext, hasGpu and hasCaches all hold.
 *
 * Vendor deps (loaded via importmap — see index.html):
 *   "onnxruntime-web"    → /vendor/js/ort.all.bundle.min.mjs
 *   "onnxruntime-common" → /vendor/js/ort.all.bundle.min.mjs  (same file)
 *   "@huggingface/transformers" → /vendor/js/transformers-3.5.2.web.js
 *
 * No COOP/COEP headers required. numThreads is forced to 1 before model load.
 * IndexedDB caching: ORT Web ≥1.18 stores compiled WASM modules in 'onnxruntime-web'
 * IndexedDB automatically, so the model survives reloads without any service worker.
 *
 * Voice file caching: per-voice .bin files are fetched from HuggingFace CDN and
 * stored in Cache Storage under 'kokoro-voices'. If that cache is ever cleared the
 * ~300KB voice bin re-downloads on next synthesis — cheap, and the main 82MB ONNX
 * model is safe in IndexedDB regardless. A future improvement would move voice bins
 * to IndexedDB too. (There is no PWA service worker — see docs/audit/2026-07-11 §0.1.)
 *
 * Design notes:
 *   - All synthesis runs in the main thread (single-thread WASM, or WebGPU shader dispatch).
 *   - The engine does NOT use a Worker because the importmap + ESM chain cannot be loaded
 *     in a Worker without a separate HTML shim.
 *   - Long texts are split on sentence boundaries (. ! ?) before synthesis to keep each
 *     ONNX forward pass inside the 510-token Kokoro context limit (truncation still on as
 *     a safety net). Each chunk is queued in _playQueue and played sequentially.
 *   - _stopped is checked between chunks so stop() halts the queue immediately.
 */

// ─── Constants ────────────────────────────────────────────────────────────────

const KOKORO_MODEL_ID = 'onnx-community/Kokoro-82M-v1.0-ONNX';
/* q8 (~92 MB) is the kokoro-js default and the right browser tradeoff — the
   model card notes Kokoro is "resilient to quantization". fp32 is 326 MB and
   needlessly large for in-browser use. */
const KOKORO_DTYPE = 'q8';
/* Directory holding the version-matched ORT WASM (ort-wasm-simd-threaded.jsep.{wasm,mjs}
   vendored from @huggingface/transformers@3.5.2/dist). Pinning wasmPaths here is
   what keeps ORT off the jsdelivr CDN (offline-PWA invariant) AND fixes the
   `_OrtGetInputName is not a function` error, which is a JS-glue/WASM version mismatch
   that occurs when transformers.js silently pulls its own CDN copies. Trailing slash
   is required — ORT treats it as a directory prefix. */
const ORT_WASM_PATH = '/vendor/js/';
const KOKORO_SAMPLE_RATE = 24000;
const DEFAULT_VOICE = 'am_michael';
const DEFAULT_SPEED = 1.0;
const WARMUP_TEXT = 'Hello world.';
const SLOW_DEVICE_RATIO = 3.0; // synthesis_wall / audio_duration threshold
const SENTENCE_SPLIT_RE = /(?<=[.!?…])\s+(?=[A-Z"'])|(?<=\n)/g;
const MAX_TOKENS_PER_CHUNK = 500; // leave headroom under Kokoro's 510 limit

// ─── Environment diagnostics ───────────────────────────────────────────────────

/**
 * describeEnvironment({ secureContext, hasGpu, hasCaches, origin })
 * Pure function: explains ahead of any init() attempt why the neural tier
 * may be unavailable or degraded in the caller's environment. The caller
 * supplies the browser signals (navigator.gpu, window.caches, etc.) rather
 * than this function reading them directly, because the insecure-context
 * case specifically HIDES those APIs — there is no way to probe them from
 * a page that is itself served over a secure origin (e.g. this test page).
 *
 * Returns { warnings: [{ code, message }, ...] }, ordered most→least severe:
 *   'insecure-context' — non-secure origins (e.g. `studyloop web --lan` opened
 *     at http://<lan-ip>:8567) hide navigator.gpu AND the Cache/IndexedDB
 *     APIs, forcing WASM and defeating model caching. Named as the root
 *     cause rather than reported as 'no-webgpu' + 'no-caches' separately.
 *   'no-webgpu' — secure context, but no WebGPU adapter: Tier 1 still runs
 *     on WASM, just slower. A lesser warning than insecure-context.
 * No warnings at all when the context is secure, WebGPU is present, and
 * Cache Storage is available.
 */
function describeEnvironment({ secureContext, hasGpu, hasCaches, origin = '' } = {}) {
  const warnings = [];

  if (!secureContext) {
    const host = origin.replace(/^https?:\/\//, '');
    warnings.push({
      code: 'insecure-context',
      message:
        `${host || 'this page'} is not a secure context, so the browser hides WebGPU ` +
        `and its caches — Kokoro falls back to slower WASM and re-downloads its model ` +
        `every visit. Open StudyLoop over localhost or HTTPS instead.`,
    });
  }

  if (!hasGpu) {
    warnings.push({
      code: 'no-webgpu',
      message: 'No WebGPU adapter available — Kokoro will run on WASM, which is slower.',
    });
  }

  return { warnings };
}

// ─── Voice catalogue (mirrors kokoro-js) ──────────────────────────────────────

const KOKORO_VOICES = Object.freeze({
  af_heart:   { name: 'Heart',    lang: 'en-us', gender: 'Female', grade: 'A'  },
  af_bella:   { name: 'Bella',    lang: 'en-us', gender: 'Female', grade: 'A-' },
  af_nicole:  { name: 'Nicole',   lang: 'en-us', gender: 'Female', grade: 'B-' },
  af_sarah:   { name: 'Sarah',    lang: 'en-us', gender: 'Female', grade: 'C+' },
  am_michael: { name: 'Michael',  lang: 'en-us', gender: 'Male',   grade: 'C+' },
  am_fenrir:  { name: 'Fenrir',   lang: 'en-us', gender: 'Male',   grade: 'C+' },
  am_puck:    { name: 'Puck',     lang: 'en-us', gender: 'Male',   grade: 'C+' },
  bf_emma:    { name: 'Emma',     lang: 'en-gb', gender: 'Female', grade: 'B-' },
  bm_george:  { name: 'George',   lang: 'en-gb', gender: 'Male',   grade: 'B-' },
});

// ─── Text normalisation (ported from kokoro-js m() function) ──────────────────

function _normaliseText(text) {
  return text
    .replace(/['']/g, "'")
    .replace(/[""]/g, '"')
    .replace(/、/g, ', ').replace(/。/g, '. ').replace(/！/g, '! ')
    .replace(/，/g, ', ').replace(/：/g, ': ').replace(/；/g, '; ').replace(/？/g, '? ')
    .replace(/[^\S \n]/g, ' ').replace(/  +/g, ' ')
    .replace(/\bD[Rr]\.(?= [A-Z])/g, 'Doctor')
    .replace(/\b(?:Mr\.|MR\.(?= [A-Z]))/g, 'Mister')
    .replace(/\b(?:Ms\.|MS\.(?= [A-Z]))/g, 'Miss')
    .replace(/\b(?:Mrs\.|MRS\.(?= [A-Z]))/g, 'Mrs')
    .replace(/\betc\.(?! [A-Z])/gi, 'etc')
    .trim();
}

// ─── Sentence splitter ────────────────────────────────────────────────────────

function _splitSentences(text) {
  // Split on sentence boundaries, keep each part non-empty
  const raw = text.split(SENTENCE_SPLIT_RE).map(s => s.trim()).filter(s => s.length > 0);
  if (raw.length === 0) return [text];
  // Further split very long sentences by comma if needed (rough token estimate: 1 word ≈ 1.3 tokens)
  const result = [];
  for (const sentence of raw) {
    const wordCount = sentence.split(/\s+/).length;
    if (wordCount * 1.3 > MAX_TOKENS_PER_CHUNK) {
      // Split on commas as secondary boundary
      const parts = sentence.split(/,\s+/).map(s => s.trim()).filter(s => s.length > 0);
      result.push(...parts);
    } else {
      result.push(sentence);
    }
  }
  return result;
}

// ─── Voice style loading (mirrors kokoro-js k() function, browser path) ───────

const _voiceCache = new Map();
const VOICE_BIN_BASE = 'https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/voices/';
const VOICE_CACHE_NAME = 'kokoro-voices';

async function _loadVoiceStyle(voiceId) {
  if (_voiceCache.has(voiceId)) return _voiceCache.get(voiceId);

  const url = `${VOICE_BIN_BASE}${voiceId}.bin`;
  let cacheStorage = null;

  // Try Cache Storage for voice bins (separate from SW nuke target)
  try {
    cacheStorage = await caches.open(VOICE_CACHE_NAME);
    const cached = await cacheStorage.match(url);
    if (cached) {
      const buf = await cached.arrayBuffer();
      const style = new Float32Array(buf);
      _voiceCache.set(voiceId, style);
      return style;
    }
  } catch (e) {
    console.warn('[tts-engine] Voice cache open failed:', e.message);
  }

  // Fetch from HF CDN
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Voice fetch failed: ${resp.status} ${url}`);
  const buf = await resp.arrayBuffer();

  // Cache for future loads
  if (cacheStorage) {
    try {
      await cacheStorage.put(url, new Response(buf, { headers: resp.headers }));
    } catch (e) {
      console.warn('[tts-engine] Voice cache put failed:', e.message);
    }
  }

  const style = new Float32Array(buf);
  _voiceCache.set(voiceId, style);
  return style;
}

// ─── Engine class ─────────────────────────────────────────────────────────────

class TTSEngine {
  constructor() {
    this._state = 'idle';
    this._tier = null;
    this._kokoroModel = null;
    this._tokenizer = null;
    this._Tensor = null;      // cached Tensor constructor from transformers.js
    this._audioCtx = null;
    this._currentSource = null;
    this._stopped = false;
    // Monotonic speak-generation counter. Each speak() claims a new
    // generation; older chunk loops see the mismatch and exit. The shared
    // _stopped boolean alone can't do this: speak() B resets it to false
    // while speak() A's loop is suspended in an await, so A's next
    // between-chunk check passes and BOTH loops feed the AudioContext
    // (the "two voices talking over each other" bug).
    this._generation = 0;
    this._initPromise = null;
    this._voiceId = DEFAULT_VOICE;
    this._speed = DEFAULT_SPEED;
    this._playQueue = [];

    /** Assign a function(pct: number, file: string, done: boolean) to receive progress */
    this.onProgress = null;
  }

  // ── Getters ──────────────────────────────────────────────────────────────────

  get isReady() { return this._state === 'ready' || this._state === 'speaking'; }
  get isSpeaking() { return this._state === 'speaking'; }
  get tier() { return this._tier; }

  /* The voice the engine will actually speak with.
   *
   * Exposed because the Settings dropdown previously derived its selection only
   * from localStorage: with no saved preference the <select> fell to option
   * index 0 while the engine was still on DEFAULT_VOICE, so the UI named one
   * voice and a different one spoke. The label and the audio have to agree, and
   * only the engine knows which voice is live. */
  get voiceId() { return this._voiceId; }

  // ── State machine ────────────────────────────────────────────────────────────

  _setState(state) {
    if (this._state === state) return;
    this._state = state;
    const detail = { state, tier: this._tier };
    window.dispatchEvent(new CustomEvent('tts:state-change', { detail }));
  }

  /**
   * _setTier(tier, reason, detail) — resolves the active tier and broadcasts
   * WHY it landed there. reason/detail default to the healthy case ('ok', '')
   * so existing call sites that only pass tier keep working unchanged.
   * degraded is derived, not passed in: true for anything but the two
   * neural tiers, so listeners can't drift out of sync with the tier list.
   */
  _setTier(tier, reason = 'ok', detail = '') {
    this._tier = tier;
    const degraded = tier !== 'neural-webgpu' && tier !== 'neural-wasm';
    window.dispatchEvent(new CustomEvent('tts:tier-change', {
      detail: { tier, reason, detail, degraded },
    }));
  }

  // ── Progress reporting ───────────────────────────────────────────────────────

  _emitProgress(pct, file, done) {
    const detail = { pct: Math.round(pct), file, done: !!done };
    window.dispatchEvent(new CustomEvent('tts:download-progress', { detail }));
    if (typeof this.onProgress === 'function') {
      this.onProgress(detail.pct, detail.file, detail.done);
    }
  }

  // ── Initialisation ───────────────────────────────────────────────────────────

  /**
   * init() / warmup() — both names work (warmup is an alias).
   * Idempotent: subsequent calls return the cached promise.
   * Downloads/loads model on first call; subsequent calls are instant cache hits.
   */
  async init() {
    if (this._initPromise) return this._initPromise;
    this._initPromise = this._doInit();
    return this._initPromise;
  }

  async warmup() { return this.init(); }

  async _doInit() {
    this._setState('warming');

    try {
      await this._initNeural();
    } catch (err) {
      console.warn('[tts-engine] Neural init failed, falling back to Web Speech API:', err.message);
      // err.message carries the reason code ('device-too-slow',
      // 'warmup-failed', or a generic failure); err.detail (set by
      // _initNeural's slow-device throw) carries the human-readable why.
      this._initWebSpeech(err.message, err.detail || err.message);
    }

    // Restore the persisted voice into the ENGINE, not just the settings
    // dropdown. Without this every page load spoke with DEFAULT_VOICE
    // (am_michael) regardless of the saved preference — the dropdown showed
    // the right voice while the engine used the wrong one.
    if (this._tier === 'neural-webgpu' || this._tier === 'neural-wasm') {
      const saved = localStorage.getItem('neuralVoiceId');
      if (saved && KOKORO_VOICES[saved]) this._voiceId = saved;
    }
    // WSA restores per-utterance from localStorage 'voiceName' in _speakWSA.

    this._setState('ready');
  }

  async _initNeural() {
    // ── Step 1: probe WebGPU ──────────────────────────────────────────────────
    let useWebGPU = false;
    if ('gpu' in navigator) {
      try {
        const adapter = await navigator.gpu.requestAdapter();
        useWebGPU = (adapter !== null);
      } catch (_) {
        useWebGPU = false;
      }
    }

    // ── Step 2: import transformers.js via the importmap alias ────────────────
    // The importmap in index.html maps "@huggingface/transformers" to the vendored file.
    let transformers;
    try {
      transformers = await import('@huggingface/transformers');
    } catch (err) {
      throw new Error(`transformers.js import failed: ${err.message}`);
    }

    const { env, AutoTokenizer, StyleTextToSpeech2Model, Tensor } = transformers;
    this._Tensor = Tensor;

    // ── Step 3: configure ORT backend BEFORE any model load ──────────────────
    // CRITICAL: numThreads=1 prevents SharedArrayBuffer usage (no COOP/COEP needed).
    env.backends.onnx.wasm.numThreads = 1;

    // Pin ORT WASM to the vendored, version-matched binaries. transformers.js
    // 3.5.2 otherwise defaults wasmPaths to its jsdelivr CDN, which both breaks
    // offline use AND triggers `_OrtGetInputName is not a function` (glue/binary
    // version skew). Must be set before any from_pretrained call.
    env.backends.onnx.wasm.wasmPaths = ORT_WASM_PATH;

    // Persist the ~92 MB model in Cache Storage ('transformers-cache') so it
    // downloads ONCE and survives reloads / works offline. This is the library
    // default (useBrowserCache = IS_WEB_CACHE_AVAILABLE); we set it explicitly
    // to document intent. The earlier `= false` here was a bug: it disabled the
    // ONLY store that holds the weights (ORT's IndexedDB caches compiled WASM
    // kernels, NOT model weights), so every page load re-fetched 92 MB from HF.
    env.useBrowserCache = true;

    // Device is selected per-call via from_pretrained({ device }) below — NOT via
    // env.backends.onnx.preferredBackend, which is not a real transformers.js v3
    // field (it silently did nothing). The JSEP WASM build serves both webgpu and
    // wasm execution providers, so the same vendored binaries cover both tiers.
    const device = useWebGPU ? 'webgpu' : 'wasm';
    console.info(`[tts-engine] Loading Kokoro with device=${device}, dtype=${KOKORO_DTYPE}`);

    // ── Step 4: build progress aggregator ────────────────────────────────────
    const fileProgress = {};
    const progressCallback = ({ status, file, progress }) => {
      if (status === 'progress' && file != null) {
        fileProgress[file] = progress || 0;
        this._setState('downloading');
      } else if (status === 'done' && file != null) {
        fileProgress[file] = 100;
      }

      const values = Object.values(fileProgress);
      const pct = values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : 0;
      const isDone = (status === 'ready') || (values.length > 0 && values.every(v => v >= 100));
      this._emitProgress(pct, file || '', isDone);
    };

    // ── Step 5: load model + tokenizer ───────────────────────────────────────
    // Both load in parallel. StyleTextToSpeech2Model is the Kokoro ONNX model class.
    const [model, tokenizer] = await Promise.all([
      StyleTextToSpeech2Model.from_pretrained(KOKORO_MODEL_ID, {
        dtype: KOKORO_DTYPE,
        device,
        progress_callback: progressCallback,
      }),
      AutoTokenizer.from_pretrained(KOKORO_MODEL_ID, {
        progress_callback: progressCallback,
      }),
    ]);

    this._kokoroModel = model;
    this._tokenizer = tokenizer;

    // ── Step 6: warm up + slow-device probe (WASM only) ──────────────────────
    if (!useWebGPU) {
      const probe = await this._probeSpeed();
      if (!probe.passed) {
        // Device too slow (or warmup failed) for real-time neural synthesis — fall back
        console.warn(`[tts-engine] Falling back to Web Speech API (${probe.reason}): ${probe.detail}`);
        this._kokoroModel = null;
        this._tokenizer = null;
        this._Tensor = null;
        const err = new Error(probe.reason);
        err.detail = probe.detail;
        throw err;
      }
    }

    this._setTier(useWebGPU ? 'neural-webgpu' : 'neural-wasm');
    console.info(`[tts-engine] Neural TTS ready (${this._tier})`);
  }

  /**
   * _probeSpeed() — warm up once (discarded from timing; pays ONNX graph
   * build + kernel compilation), then measure a second, timed inference.
   * The first version of this probe timed the warmup itself, so a capable
   * machine's one-off compilation cost got misread as "too slow" and the
   * device was permanently demoted to Web Speech. Returns a structured
   * result instead of a bare boolean so callers can explain the outcome:
   *   { passed, ratio, reason, detail }
   *   reason: 'ok' | 'device-too-slow' | 'warmup-failed'
   */
  async _probeSpeed() {
    try {
      await this._synthesiseChunk(WARMUP_TEXT, /* play= */ false);
    } catch (e) {
      console.warn('[tts-engine] Warmup probe failed:', e.message);
      return { passed: false, ratio: null, reason: 'warmup-failed', detail: e.message };
    }

    const t0 = performance.now();
    let audioDuration;
    try {
      audioDuration = await this._synthesiseChunk(WARMUP_TEXT, /* play= */ false);
    } catch (e) {
      console.warn('[tts-engine] Speed measurement failed:', e.message);
      return { passed: false, ratio: null, reason: 'warmup-failed', detail: e.message };
    }
    const wallMs = performance.now() - t0;
    const audioMs = audioDuration * 1000;
    const ratio = wallMs / (audioMs || 1);
    console.info(`[tts-engine] Speed probe: ${wallMs.toFixed(0)}ms wall / ${audioMs.toFixed(0)}ms audio = ${ratio.toFixed(2)}x`);

    if (ratio >= SLOW_DEVICE_RATIO) {
      return {
        passed: false,
        ratio,
        reason: 'device-too-slow',
        detail: `measured ${ratio.toFixed(1)}x real time (threshold ${SLOW_DEVICE_RATIO}x)`,
      };
    }
    return { passed: true, ratio, reason: 'ok', detail: '' };
  }

  _initWebSpeech(reason = 'no-neural-support', detail = '') {
    if (!('speechSynthesis' in window)) {
      console.warn('[tts-engine] Web Speech API not available, using silent mode');
      this._setTier('silent', reason, detail);
      return;
    }
    this._setTier('web-speech', reason, detail);
    console.info('[tts-engine] Web Speech API ready');
  }

  // ── AudioContext lazy init ────────────────────────────────────────────────────

  _getAudioContext() {
    if (!this._audioCtx || this._audioCtx.state === 'closed') {
      this._audioCtx = new AudioContext({ sampleRate: KOKORO_SAMPLE_RATE });
    }
    if (this._audioCtx.state === 'suspended') {
      this._audioCtx.resume().catch(() => {});
    }
    return this._audioCtx;
  }

  // ── Neural synthesis ─────────────────────────────────────────────────────────

  /**
   * Synthesise one text chunk using Kokoro.
   * @param {string} text
   * @param {boolean} play — if true, play and return; if false, return duration only
   * @returns {Promise<number>} audio duration in seconds
   */
  async _synthesiseChunk(text, play = true, gen = null) {
    if (!this._kokoroModel || !this._tokenizer || !this._Tensor) {
      throw new Error('Neural model not loaded');
    }

    const Tensor = this._Tensor;

    // Phonemise: for en-us voices the first char of the voice id is 'a',
    // for en-gb it's 'b'. Kokoro voice lang prefix drives phonemizer lang.
    const voiceMeta = KOKORO_VOICES[this._voiceId];
    const lang = (voiceMeta && voiceMeta.lang === 'en-gb') ? 'en' : 'en-us';
    const phonemes = await _phonemise(text, this._voiceId[0], lang);

    // Tokenise
    const { input_ids } = this._tokenizer(phonemes, { truncation: true });

    // Load voice style vector
    const voiceStyle = await _loadVoiceStyle(this._voiceId);
    // Style slice: 256 floats starting at offset based on input length
    const offset = 256 * Math.min(Math.max(input_ids.dims.at(-1) - 2, 0), 509);
    const styleSlice = voiceStyle.slice(offset, offset + 256);

    // Build ORT inputs
    const inputs = {
      input_ids,
      style: new Tensor('float32', styleSlice, [1, 256]),
      speed: new Tensor('float32', [this._speed], [1]),
    };

    // Forward pass
    const { waveform } = await this._kokoroModel(inputs);
    const pcm = waveform.data; // Float32Array

    const duration = pcm.length / KOKORO_SAMPLE_RATE;

    if (!play) return duration;

    // Create AudioBuffer
    const ctx = this._getAudioContext();
    const buffer = ctx.createBuffer(1, pcm.length, KOKORO_SAMPLE_RATE);
    buffer.copyToChannel(pcm, 0);

    return new Promise((resolve, reject) => {
      // Playback gate. The between-chunk generation check can't catch a chunk
      // that was already awaiting the (seconds-long) forward pass when a newer
      // speak() arrived — by then _stopped is false again. Re-check the
      // generation HERE, at the moment audio would actually start.
      if (this._stopped || (gen !== null && gen !== this._generation)) {
        resolve(duration);
        return;
      }

      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      this._currentSource = source;

      // Settle this playback promise exactly once, whether playback ends
      // naturally (onended) or is cut short by stop(). We hold the resolver on
      // the instance so stop() can settle it directly — onended does NOT fire
      // reliably once stop() suspends the AudioContext (the clock freezes), so
      // depending on it alone leaks a pending promise per interrupted chunk.
      this._pendingPlayResolve = () => {
        this._pendingPlayResolve = null;
        this._currentSource = null;
        resolve(duration);
      };

      source.onended = () => {
        if (this._pendingPlayResolve) this._pendingPlayResolve();
      };
      source.start();
    });
  }

  // ── Public speak / stop ───────────────────────────────────────────────────────

  /**
   * Speak text. Resolves when playback starts (or immediately for WSA).
   * Concurrent calls: stops current speech and starts the new one.
   */
  async speak(text) {
    if (!text || typeof text !== 'string') return;
    const trimmed = text.trim();
    if (!trimmed) return;

    // Stop current speech before starting new, and claim a new generation.
    // The generation is this call's identity: any older _speakNeural loop
    // still in flight sees this._generation move past its own and exits,
    // even though the _stopped flag below is reset for the new call.
    this.stop();
    this._stopped = false;
    const gen = ++this._generation;

    // Ensure engine is initialised
    if (!this._tier) await this.init();
    if (gen !== this._generation) return; // superseded while initialising

    this._setState('speaking');

    if (this._tier === 'neural-webgpu' || this._tier === 'neural-wasm') {
      await this._speakNeural(trimmed, gen);
    } else if (this._tier === 'web-speech') {
      this._speakWSA(trimmed);
    }
    // 'silent' tier: no-op

    if (!this._stopped && gen === this._generation) this._setState('idle');
  }

  async _speakNeural(text, gen) {
    const normalized = _normaliseText(text);
    const chunks = _splitSentences(normalized);

    for (const chunk of chunks) {
      if (this._stopped || gen !== this._generation) break;
      if (!chunk.trim()) continue;
      try {
        await this._synthesiseChunk(chunk, /* play= */ true, gen);
      } catch (err) {
        console.error('[tts-engine] Synthesis chunk failed:', err.message, '— chunk:', chunk);
        // Don't break on a single chunk failure; continue with next chunk
      }
    }
  }

  _speakWSA(text) {
    const utter = new SpeechSynthesisUtterance(text);
    // Restore voice preference from localStorage if available
    const savedVoice = localStorage.getItem('voiceName');
    if (savedVoice && window.speechSynthesis) {
      const voices = window.speechSynthesis.getVoices();
      const match = voices.find(v => v.name === savedVoice);
      if (match) utter.voice = match;
    }
    utter.onend = () => {
      if (!this._stopped) this._setState('idle');
    };
    utter.onerror = () => this._setState('idle');
    window.speechSynthesis.speak(utter);
  }

  /**
   * stop() — immediately halts all in-flight synthesis and playback.
   * Safe to call at any time, including before init().
   */
  stop() {
    this._stopped = true;

    // Stop WebAudio playback
    if (this._currentSource) {
      try { this._currentSource.stop(); } catch (_) {}
      try { this._currentSource.disconnect(); } catch (_) {}
      this._currentSource = null;
    }
    // Settle any in-flight playback promise NOW. Must happen before suspend():
    // a suspended context freezes the clock so source.onended never fires, which
    // would otherwise leave the _speakNeural await (and the caller's speak()
    // promise) hanging until the next resume.
    if (this._pendingPlayResolve) this._pendingPlayResolve();
    // Suspend AudioContext to release hardware
    if (this._audioCtx && this._audioCtx.state === 'running') {
      this._audioCtx.suspend().catch(() => {});
    }
    // Stop Web Speech API
    if ('speechSynthesis' in window) {
      try { window.speechSynthesis.cancel(); } catch (_) {}
    }

    this._setState('idle');
  }

  // ── Voice management ─────────────────────────────────────────────────────────

  /**
   * listVoices() — returns voices appropriate for the active tier.
   * Neural tiers return Kokoro voice list.
   * web-speech tier delegates to speechSynthesis.getVoices().
   */
  listVoices() {
    if (this._tier === 'neural-webgpu' || this._tier === 'neural-wasm') {
      return Object.entries(KOKORO_VOICES).map(([id, meta]) => ({
        id,
        name: `${meta.name} (${meta.gender})`,
        lang: meta.lang,
        tier: this._tier,
        grade: meta.grade,
      }));
    }
    if (this._tier === 'web-speech' && 'speechSynthesis' in window) {
      return window.speechSynthesis.getVoices().map(v => ({
        id: v.name,
        name: v.name,
        lang: v.lang,
        tier: 'web-speech',
      }));
    }
    return [];
  }

  /**
   * setVoice(voiceId) — change the active voice.
   * For neural tiers: voiceId is a Kokoro voice key (e.g. 'am_michael').
   * For web-speech: voiceId is the SpeechSynthesisVoice.name string.
   * Pre-fetches the voice .bin file so the next speak() is instant.
   */
  async setVoice(voiceId) {
    this._voiceId = voiceId;
    if ((this._tier === 'neural-webgpu' || this._tier === 'neural-wasm') && KOKORO_VOICES[voiceId]) {
      // Pre-warm the voice style cache
      try { await _loadVoiceStyle(voiceId); } catch (_) {}
    }
  }

  setSpeed(speed) {
    this._speed = Math.max(0.5, Math.min(2.0, speed));
  }
}

// ─── Phonemisation (browser-compatible, mirrors kokoro-js m() logic) ──────────
// phonemizer@1.2.1 is an ESM + eSpeak NG WASM bundle (WASM is inline base64).
// No Node requires, no external fetch. Imported via the importmap alias "phonemizer".
//
// API: phonemize(text: string, lang: string) → Promise<string[]>
// Each element is one line of IPA. We join with space for Kokoro input.

let _phonemizeImport = null;

async function _ensurePhonemizerLoaded() {
  if (_phonemizeImport) return _phonemizeImport;
  try {
    const mod = await import('phonemizer');
    _phonemizeImport = mod.phonemize;
    return _phonemizeImport;
  } catch (e) {
    throw new Error(`phonemizer import failed: ${e.message}`);
  }
}

/**
 * _phonemise(text, voiceLangPrefix, lang)
 * voiceLangPrefix: first char of voice id ('a' = en-us, 'b' = en-gb)
 * Returns IPA phoneme string ready for Kokoro tokenizer.
 *
 * Mirrors the m() function from kokoro-js, browser path.
 * If phonemizer fails, falls back to direct text pass-through (tokenizer handles it
 * with reduced but still acceptable quality).
 */
async function _phonemise(text, voiceLangPrefix, lang) {
  // For simplicity we phonemise the whole normalised text.
  // The tokenizer has truncation=true as a safety net.
  try {
    const phonemizeFn = await _ensurePhonemizerLoaded();

    // phonemize(text, language) returns string[] — one IPA string per input line.
    // eSpeak-NG language tag: 'en-us' for US English, 'en' for British.
    const espeakLang = (lang === 'en') ? 'en' : 'en-us';
    const result = await phonemizeFn(text, espeakLang);
    let phonemes = Array.isArray(result) ? result.join(' ') : String(result);

    // Post-processing corrections from kokoro-js
    phonemes = phonemes
      .replace(/kəkˈoːɹoʊ/g, 'kˈoʊkəɹoʊ')
      .replace(/kəkˈɔːɹəʊ/g, 'kˈəʊkəɹəʊ')
      .replace(/ʲ/g, 'j')
      .replace(/r/g, 'ɹ')
      .replace(/x/g, 'k')
      .replace(/ɬ/g, 'l')
      .replace(/(?<=[a-zɹː])(?=hˈʌndɹɪd)/g, ' ')
      .replace(/ z(?=[;:,.!?¡¿—…"«»"" ]|$)/g, 'z');

    if (voiceLangPrefix === 'a') {
      phonemes = phonemes.replace(/(?<=nˈaɪn)ti(?!ː)/g, 'di');
    }
    return phonemes.trim();
  } catch (e) {
    console.warn('[tts-engine] Phonemizer failed, passing text directly to tokenizer:', e.message);
    // Fallback: pass text directly — Kokoro can handle plain English with degraded quality
    return text;
  }
}

// ─── Singleton instantiation ──────────────────────────────────────────────────

/**
 * Create and assign the singleton engine to window.ttsEngine.
 * Called automatically when this module is imported.
 * Does NOT call init() — init() is lazy (triggered on first speak() or explicit call).
 */
function _createEngine() {
  const engine = new TTSEngine();
  window.ttsEngine = engine;

  // Bridge: forward 'tts:state-change' to Alpine $store.settings.isSpeaking
  // The Alpine store listens to this event independently, but we also patch a direct
  // Alpine bridge here in case the store isn't loaded yet.
  window.addEventListener('tts:state-change', (e) => {
    if (window.Alpine && Alpine.store && Alpine.store('settings')) {
      Alpine.store('settings').isSpeaking = (e.detail.state === 'speaking');
    }
  });

  return engine;
}

_createEngine();

export { TTSEngine, describeEnvironment };
