/**
 * tts-engine.js — StudyLoop speech engine
 *
 * Three-tier architecture (resolved at init time, best first):
 *   Tier 1: server-side Kokoro on the host, reached over same-origin HTTP
 *           ('server-openvox' — any OpenAI-compatible speech server: OpenVox,
 *           VoiceMode's Kokoro, or a container). Synthesis happens on the host,
 *           so the device needs nothing but an <audio> element.
 *   Tier 2: Web Speech API (the device's own system voices)
 *   Tier 3: Silent no-op (no audio available at all)
 *
 * There is deliberately NO in-browser synthesis tier. Speech is either the
 * host's job or the operating system's.
 *
 * Public API (assigned to window.ttsEngine after init):
 *   await ttsEngine.init()         — probe the host, adopt the best tier
 *   await ttsEngine.speak(text)    — synthesise + play; resolves when playback ends
 *   ttsEngine.stop()               — stop in-flight speech
 *   ttsEngine.listVoices()         — array of { id, name, lang, tier }
 *   ttsEngine.isReady              — true after init() completes without error
 *   ttsEngine.isSpeaking           — true while audio is playing
 *   ttsEngine.tier                 — 'server-openvox' | 'web-speech' | 'silent'
 *   ttsEngine.voiceId              — the voice that will actually speak
 *
 * Events (fired on window):
 *   'tts:state-change'      — detail: { state, tier }  (state: idle|warming|downloading|ready|speaking)
 *   'tts:download-progress' — detail: { pct, file, done }
 *   'tts:tier-change'       — detail: { tier, reason, detail, degraded }
 *       reason/detail explain WHY the tier landed where it did (e.g. reason:
 *       'no-server-speech'); degraded is derived from an explicit healthy-tier
 *       list, never from "is not X and not Y" — a negative derivation once
 *       reported the fastest tier as broken.
 *
 * Design notes:
 *   - Nothing is downloaded to the device and no synthesis runs in the page: the
 *     browser only plays audio it is handed. That is what lets this work on a
 *     tablet over `studyloop web --lan`, where the origin is not secure and the
 *     browser therefore withholds the APIs an in-page engine would need.
 *   - Endpoints are same-origin, so the browser replays the --lan Basic
 *     credentials it already holds for the page; there is no second token.
 *   - The server tier plays through an Audio element rather than an
 *     AudioContext, which is why it needs no secure context.
 */

// ─── Constants ────────────────────────────────────────────────────────────────

// ─── Server-side speech (preferred tier) ──────────────────────────────────────
// The host can synthesise far faster than the browser and reaches devices no
// in-browser tier could serve. Endpoints are same-origin so the --lan Basic
// credentials the browser already holds are replayed automatically.
const SERVER_TTS_HEALTH = '/api/tts/health';
const SERVER_TTS_SPEAK = '/api/tts/speak';
const SERVER_TTS_WARM = '/api/tts/warm';
// A host that is not answering must not hold the voice system in 'warming'.
const SERVER_PROBE_TIMEOUT_MS = 2500;
/* The voice used until the learner picks one, and until the host's catalogue is
 * known.
 *
 * British female, chosen deliberately over the previous 'am_michael': this is a
 * study companion for a British learner, and an accent that matches the user
 * reduces the low-grade friction of listening to it for an hour. _initServer()
 * replaces this with a host voice as soon as it has one, so a host that does not
 * offer 'bf_emma' is not a problem.
 */
const DEFAULT_VOICE = 'bf_emma';
const DEFAULT_SPEED = 1.0;

// ─── Voice labels ─────────────────────────────────────────────────────────────

/* Derive a display name from a voice id ('bf_emma' → 'Emma'). The host reports
 * ids, not labels, so the picker builds its own. */
function _voiceLabel(voiceId) {
  const bare = String(voiceId || '').split('_').slice(1).join(' ');
  return bare ? bare.charAt(0).toUpperCase() + bare.slice(1) : String(voiceId || '');
}

// ─── Engine class ─────────────────────────────────────────────────────────────

class TTSEngine {
  constructor() {
    this._state = 'idle';
    this._tier = null;
    this._serverVoices = [];
    this._serverAudio = null;
    this._stopped = false;
    // Monotonic speak-generation counter. Each speak() claims a new
    // generation; older speech loops see the mismatch and exit. The shared
    // _stopped boolean alone can't do this: speak() B resets it to false
    // while speak() A is suspended in an await, so A's next check passes and
    // BOTH continue (the "two voices talking over each other" bug).
    this._generation = 0;
    this._initPromise = null;
    this._voiceId = DEFAULT_VOICE;
    this._speed = DEFAULT_SPEED;

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
   * degraded is derived, not passed in, so listeners can't drift out of sync
   * with the tier list.
   */
  _setTier(tier, reason = 'ok', detail = '') {
    this._tier = tier;
    // Derived from an EXPLICIT healthy-tier list, never from "is not web-speech
    // and not silent". 'server-openvox' is the best tier, not a degraded one:
    // synthesis runs natively on the host (~2.5s per sentence warm) and it works
    // on devices that can do no synthesis of their own. A negative derivation
    // here previously labelled the fastest path as broken.
    const healthy = tier === 'server-openvox';
    window.dispatchEvent(new CustomEvent('tts:tier-change', {
      detail: { tier, reason, detail, degraded: !healthy },
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
   */
  async init() {
    if (this._initPromise) return this._initPromise;
    this._initPromise = this._doInit();
    return this._initPromise;
  }

  async warmup() { return this.init(); }

  async _doInit() {
    this._setState('warming');

    // ── Tier 1: server-side Kokoro ────────────────────────────────────────────
    // The only tier that synthesises anything. In-page synthesis was removed
    // after measuring 6.6x real time on the fastest browser path available
    // (22.7s of work for 3.45s of audio), and it could not run at all on a
    // tablet over `--lan`, where a non-secure origin makes the browser withhold
    // the APIs it needed. The host has none of those constraints and asks
    // nothing of the device but an audio player.
    if (await this._initServer()) {
      this._setState('ready');
      return;
    }

    // ── Tier 2/3: the device's own voices, or nothing ─────────────────────────
    this._initWebSpeech(
      'no-server-speech',
      'the host is not offering server-side speech',
    );

    // WSA restores its voice per-utterance from localStorage 'voiceName' in
    // _speakWSA, so there is nothing to restore here.

    this._setState('ready');
  }

  /**
   * _initServer() — adopt server-side speech when the host offers it.
   *
   * Returns true when the server tier is now live. Deliberately quiet on
   * failure: a host without a speech server is a completely normal
   * configuration, not an error, and the ladder continues to the system voices.
   *
   * The probe is bounded by a timeout because an unreachable host must not hold
   * the whole voice system in 'warming' -- an init that never resolves is
   * indistinguishable from broken software, which is the failure mode this
   * entire path exists to remove.
   */
  async _initServer() {
    let health;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), SERVER_PROBE_TIMEOUT_MS);
      const response = await fetch(SERVER_TTS_HEALTH, {
        signal: controller.signal,
        // Same-origin so the browser replays the --lan Basic credentials it
        // already holds for the page; no second token to manage.
        credentials: 'same-origin',
      });
      clearTimeout(timer);
      if (!response.ok) return false;
      health = await response.json();
    } catch (_) {
      return false;
    }

    if (!health || !health.available) {
      if (health && health.detail) {
        console.info('[tts-engine] server speech unavailable:', health.detail);
      }
      return false;
    }

    this._serverVoices = Array.isArray(health.voices) ? health.voices : [];
    if (!this._serverVoices.length) return false;

    // Prefer a British voice, then whatever the saved preference was, then the
    // first offered. A saved id is only honoured when the server still offers it.
    const saved = localStorage.getItem('serverVoiceId');
    const ids = this._serverVoices.map(v => v.id);
    const british = this._serverVoices.find(v => v.british);
    this._voiceId =
      (saved && ids.includes(saved) && saved) ||
      (british && british.id) ||
      ids[0];

    // Fire and forget: a cold model costs ~51s on the first utterance versus
    // ~2.5s warm, so warming now is the difference between "slow" and "broken".
    fetch(SERVER_TTS_WARM, { method: 'POST', credentials: 'same-origin' }).catch(() => {});

    this._setTier('server-openvox', 'ok', `${this._serverVoices.length} voices on the host`);
    return true;
  }

  /**
   * _speakServer(text, gen) — synthesise on the host and play the response.
   *
   * Plays through an Audio element, which needs no secure context and no model
   * download — precisely why this tier reaches a tablet at all.
   *
   * Resolves when playback ends so the caller's state machine stays truthful --
   * returning early would report 'idle' while audio was still playing.
   */
  async _speakServer(text, gen) {
    let blob;
    try {
      const response = await fetch(SERVER_TTS_SPEAK, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: this._voiceId }),
      });
      if (!response.ok) {
        // 503 means "ask someone else", so drop to the local ladder for the rest
        // of this session rather than failing every future utterance the same way.
        let detail = `HTTP ${response.status}`;
        try {
          const body = await response.json();
          if (body && body.detail) detail = body.detail;
        } catch (_) { /* non-JSON error body */ }
        console.warn('[tts-engine] server speech failed, falling back:', detail);
        this._serverVoices = [];
        this._tier = null;
        await this.init();
        if (gen !== this._generation) return;
        if (this._tier === 'web-speech') {
          this._setState('speaking');
          this._speakWSA(text);
        }
        return;
      }
      blob = await response.blob();
    } catch (err) {
      console.warn('[tts-engine] server speech unreachable:', err && err.message);
      return;
    }

    if (this._stopped || gen !== this._generation) return;

    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    this._serverAudio = audio;
    try {
      await new Promise((resolve) => {
        audio.onended = resolve;
        audio.onerror = resolve;
        audio.play().catch(() => resolve());
      });
    } finally {
      URL.revokeObjectURL(url);
      if (this._serverAudio === audio) this._serverAudio = null;
    }
  }

  _initWebSpeech(reason = 'no-server-speech', detail = '') {
    if (!('speechSynthesis' in window)) {
      console.warn('[tts-engine] Web Speech API not available, using silent mode');
      this._setTier('silent', reason, detail);
      return;
    }
    this._setTier('web-speech', reason, detail);
    console.info('[tts-engine] Web Speech API ready');
  }

  // ── Public speak / stop ───────────────────────────────────────────────────────

  /**
   * Speak text. Resolves when playback ends (or immediately for WSA).
   * Concurrent calls: stops current speech and starts the new one.
   */
  async speak(text) {
    if (!text || typeof text !== 'string') return;
    const trimmed = text.trim();
    if (!trimmed) return;

    // Stop current speech before starting new, and claim a new generation.
    // The generation is this call's identity: any older speech still in flight
    // sees this._generation move past its own and exits, even though the
    // _stopped flag below is reset for the new call.
    this.stop();
    this._stopped = false;
    const gen = ++this._generation;

    // Ensure engine is initialised
    if (!this._tier) await this.init();
    if (gen !== this._generation) return; // superseded while initialising

    this._setState('speaking');

    if (this._tier === 'server-openvox') {
      await this._speakServer(trimmed, gen);
    } else if (this._tier === 'web-speech') {
      this._speakWSA(trimmed);
    }
    // 'silent' tier: no-op

    if (!this._stopped && gen === this._generation) this._setState('idle');
  }

  _speakWSA(text) {
    const utter = new SpeechSynthesisUtterance(text);
    // Restore voice preference from localStorage if available
    const savedVoice = localStorage.getItem('voiceName');
    if (savedVoice && window.speechSynthesis) {
      const voices = window.speechSynthesis.getVoices();
      const match = voices.find(v => v.name === savedVoice);
      if (match) {
        utter.voice = match;
        // `lang` must be set ALONGSIDE `voice`, not instead of it. Android's TTS
        // exposes one voice per locale ("English (Australia)", "English (United
        // Kingdom)"), and Chrome there ignores `voice` on its own -- picking a
        // different entry changed the label and nothing else, which is exactly
        // the "no actual change of voice" symptom reported on an Android tablet.
        // Harmless everywhere else: it restates the voice's own language.
        utter.lang = match.lang;
      }
    }
    utter.onend = () => {
      if (!this._stopped) this._setState('idle');
    };
    utter.onerror = () => this._setState('idle');
    window.speechSynthesis.speak(utter);
  }

  /**
   * stop() — immediately halts all in-flight speech.
   * Safe to call at any time, including before init().
   */
  stop() {
    this._stopped = true;
    // Server-tier audio plays through an Audio element; pausing it is what
    // actually makes stop() stop -- without this it kept playing.
    if (this._serverAudio) {
      try { this._serverAudio.pause(); } catch (_) { /* already gone */ }
      this._serverAudio = null;
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
   * server tier returns the host's catalogue; web-speech delegates to
   * speechSynthesis.getVoices().
   */
  listVoices() {
    if (this._tier === 'server-openvox') {
      // The host already filtered to English voices; it also holds Mandarin,
      // Japanese, Spanish, French, Hindi and Italian voices for the same model.
      return (this._serverVoices || []).map(v => ({
        id: v.id,
        name: v.british ? `${_voiceLabel(v.id)} (British)` : _voiceLabel(v.id),
        lang: v.british ? 'en-gb' : 'en-us',
        tier: this._tier,
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
   * For the server tier: voiceId is an id from the HOST's catalogue, validated
   * against it, and persisted under 'serverVoiceId'.
   * For web-speech: voiceId is the SpeechSynthesisVoice.name string, persisted
   * by the settings store under 'voiceName' and read back per utterance.
   */
  async setVoice(voiceId) {
    if (this._tier === 'server-openvox') {
      const known = (this._serverVoices || []).some(v => v.id === voiceId);
      if (!known) {
        console.warn(`[tts] host does not offer voice '${voiceId}' — keeping '${this._voiceId}'`);
        return;
      }
      this._voiceId = voiceId;
      // Persisted under its own key: a host voice id and a system voice NAME are
      // different namespaces, and reusing one key would apply a host-only voice
      // where it does not exist.
      localStorage.setItem('serverVoiceId', voiceId);
      return;
    }
    this._voiceId = voiceId;
  }

  setSpeed(speed) {
    this._speed = Math.max(0.5, Math.min(2.0, speed));
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

export { TTSEngine };
