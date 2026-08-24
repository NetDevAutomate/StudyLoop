/**
 * components.js — Alpine review engine + settings store + Pomodoro
 *
 * Provides reviewApp() which drives the flashcard and quiz review UI.
 * Used by both the Flashcards and Quizzes tabs (x-data="reviewApp('flashcards')")
 * and (x-data="reviewApp('quiz')").
 */

/* eslint-disable no-unused-vars */

/* ====================================================================
 * Shared markdown renderer — used by liveAgentConsole AND courseExplorer.
 *
 * _escapeHtml(s)     — HTML-escape a plain string (no deps).
 * renderMarkdown(s)  — marked → DOMPurify → anchor-harden → hljs → html.
 *                      Mermaid code blocks are replaced with placeholder
 *                      <div class="mermaid-diagram" data-src="…"> so the
 *                      caller can run a two-pass mermaid.render() after
 *                      the DOM is updated.
 * ==================================================================== */

/**
 * HTML-escape a plain string.
 * @param {string} s
 * @returns {string}
 */
function _escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

/**
 * Render markdown to sanitised HTML.
 *
 * Special handling: ```mermaid fences are intercepted BEFORE hljs runs.
 * marked emits them as <pre><code class="language-mermaid">…</code></pre>.
 * We replace each such block with <div class="mermaid-diagram" data-src="…">
 * so the caller can invoke mermaid.render() in a second pass after DOM update.
 *
 * @param {string} text — raw markdown
 * @returns {string} — sanitised HTML ready for x-html / innerHTML
 */
function renderMarkdown(text) {
  if (!text) return '';
  let html;
  try {
    html = window.marked.parse(text, { gfm: true, breaks: false });
  } catch {
    return _escapeHtml(text);
  }

  /* DOMPurify — defence-in-depth on top of marked's own escaping. */
  const policy = window.StudyLoopRichTextPolicy;
  if (!policy) return _escapeHtml(text);
  const sanitised = window.DOMPurify.sanitize(
    html,
    window.StudyLoopRichTextPolicy.domPurifyOptions
  );

  const tmp = document.createElement('div');
  tmp.innerHTML = sanitised;
  window.StudyLoopRichTextPolicy.hardenRichTextTree(tmp);

  /* Intercept mermaid blocks BEFORE hljs so hljs doesn't corrupt the source.
     marked emits: <pre><code class="language-mermaid">…RAW DIAGRAM…</code></pre>
     We replace the whole <pre> with a placeholder div carrying data-src. */
  tmp.querySelectorAll('pre code.language-mermaid').forEach((code) => {
    const pre = code.parentElement;
    if (!pre) return;
    /* code.textContent is the raw diagram source (marked already un-escapes it). */
    const diagramSrc = code.textContent;
    const placeholder = document.createElement('div');
    placeholder.className = 'mermaid-diagram';
    placeholder.dataset.src = diagramSrc;
    pre.replaceWith(placeholder);
  });

  /* highlight.js — subtree-only, skip mermaid blocks (already replaced). */
  if (window.hljs) {
    tmp.querySelectorAll('pre code').forEach((block) => {
      try { window.hljs.highlightElement(block); } catch { /* ignore */ }
    });
  }

  return tmp.innerHTML;
}

/** Sanitize generated Mermaid SVG through the same no-egress policy. */
function _sanitizeMermaidSvg(svg) {
  const policy = window.StudyLoopRichTextPolicy;
  if (!policy) throw new Error('rich-text policy is unavailable');
  const sanitised = window.DOMPurify.sanitize(
    svg,
    window.StudyLoopRichTextPolicy.mermaidDomPurifyOptions
  );
  const tmp = document.createElement('div');
  tmp.innerHTML = sanitised;
  window.StudyLoopRichTextPolicy.hardenRichTextTree(tmp, { allowSvgStyle: true });
  const output = tmp.innerHTML;
  if (!output.includes('<svg')) throw new Error('Mermaid produced no safe SVG');
  return output;
}

/**
 * Strip a YAML frontmatter block from a markdown string.
 * Real lesson files start with `---\nkey: value\n...\n---\n`.
 * If passed raw, marked renders the `---` lines as <hr> tags and dumps
 * the YAML keys as paragraph text.  Strip the entire opening block.
 *
 * @param {string} text
 * @returns {string}
 */
function _stripFrontmatter(text) {
  /* Accept both LF (`---\n`) and CRLF (`---\r\n`) openers. */
  if (!text.startsWith('---\n') && !text.startsWith('---\r\n')) return text;
  /* Match the full frontmatter block: opening ---, YAML body, closing ---.
     \r? before each \n makes this CRLF-safe while keeping the LF path fast. */
  const match = text.match(/^---\r?\n[\s\S]*?\r?\n---\r?\n/);
  if (!match) return text;                 /* malformed/unclosed — leave as-is */
  return text.slice(match[0].length);      /* skip past the matched block */
}

/**
 * _mdToPlainText(md) — strip markdown to clean prose for TTS.
 *
 * window.ttsEngine.speak() takes PLAIN TEXT; it normalises + sentence-splits
 * internally. Markdown punctuation (`#`, `*`, backticks, `>`) would otherwise be
 * read aloud as noise, and code/diagram blocks are not worth speaking. This drops
 * structural syntax while preserving readable sentences and paragraph breaks (\n,
 * which the engine's sentence splitter uses).
 *
 * Pure + deterministic → unit-testable without a DOM or the TTS engine.
 * Pass frontmatter-stripped markdown (the `stripped` value from openLesson).
 */
function _mdToPlainText(md) {
  if (!md) return '';
  let t = md;
  /* Remove fenced code blocks AND mermaid diagrams entirely (don't speak code). */
  t = t.replace(/```[\s\S]*?```/g, ' ');
  t = t.replace(/~~~[\s\S]*?~~~/g, ' ');
  /* Images: drop entirely (alt text is rarely useful spoken). */
  t = t.replace(/!\[[^\]]*\]\([^)]*\)/g, ' ');
  /* Links [text](url) -> text. */
  t = t.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1');
  /* Inline code `x` -> x. */
  t = t.replace(/`([^`]*)`/g, '$1');
  /* Headings: strip leading #'s but keep the heading text (worth speaking). */
  t = t.replace(/^#{1,6}[ \t]+/gm, '');
  /* Blockquote / callout markers and list bullets at line start. */
  t = t.replace(/^[ \t]*>[ \t]?/gm, '');
  t = t.replace(/^[ \t]*([-*+]|\d+\.)[ \t]+/gm, '');
  /* Emphasis / strong / strikethrough / Obsidian ==highlight==. */
  t = t.replace(/(\*\*|__)(.*?)\1/g, '$2');
  t = t.replace(/(\*|_)(.*?)\1/g, '$2');
  t = t.replace(/~~(.*?)~~/g, '$1');
  t = t.replace(/==(.*?)==/g, '$1');
  /* Horizontal rules / table pipes. */
  t = t.replace(/^[ \t]*([-*_]){3,}[ \t]*$/gm, ' ');
  t = t.replace(/\|/g, ' ');
  /* Collapse 3+ newlines to a paragraph break; trim trailing spaces per line. */
  t = t.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n');
  return t.trim();
}

/**
 * Render one mermaid diagram without leaking DOM on failure.
 *
 * The two-argument form `mermaid.render(id, src)` appends its measurement node
 * to document.body, and on a parse failure it leaves an error SVG ("Syntax
 * error in text") attached there — pinned to the bottom of every page, since
 * nothing ever removes it. Three defences, applied at every call site:
 *
 *  1. `parse()` first. It validates without injecting DOM, so a source that is
 *     not a diagram is rejected before anything can be appended.
 *  2. The three-argument `render(id, src, containerEl)` form, so mermaid
 *     measures inside the caller's container instead of document.body.
 *  3. A `finally` that removes anything still keyed on the id — `#<id>` and
 *     `#d<id>`, the prefix mermaid uses for its measurement wrapper. Absence is
 *     the normal case, hence the optional chaining.
 *
 * Rejects on invalid source so callers keep their own fallback behaviour.
 *
 * @param {string} id — unique element id for this render
 * @param {string} src — mermaid diagram source
 * @param {Element} containerEl — element mermaid may measure inside
 * @returns {Promise<string>} the rendered SVG markup
 */
async function _renderMermaidScoped(id, src, containerEl) {
  try {
    await window.mermaid.parse(src);
    const { svg } = await window.mermaid.render(id, src, containerEl);
    return svg;
  } finally {
    document.getElementById(id)?.remove();
    document.getElementById('d' + id)?.remove();
  }
}

/**
 * Second-pass mermaid rendering.
 * renderMarkdown() leaves <div class="mermaid-diagram" data-src="…"> placeholders.
 * This function finds them inside `rootEl`, calls mermaid.render() for each,
 * injects the returned SVG, and removes `data-src` to prevent double-render.
 *
 * Guards:
 *  - window.mermaid missing → silently falls back (shows raw diagram text in pre)
 *  - Individual render failures → falls back to a <pre> with the raw source
 *
 * @param {Element} rootEl — the Alpine component root ($el)
 */
async function _renderMermaidPlaceholders(rootEl) {
  if (!window.mermaid) return;
  const placeholders = rootEl.querySelectorAll('.mermaid-diagram[data-src]');
  if (!placeholders.length) return;

  let counter = 0;
  for (const el of placeholders) {
    const src = el.dataset.src;
    /* Remove immediately to prevent double-render on re-entry. */
    delete el.dataset.src;
    const id = 'mermaid-render-' + Date.now() + '-' + (counter++);
    try {
      el.innerHTML = _sanitizeMermaidSvg(await _renderMermaidScoped(id, src, el));
    } catch (err) {
      console.warn('[CourseExplorer] mermaid.render failed:', err);
      /* Fallback: show the raw diagram source in a <pre> block. */
      const pre = document.createElement('pre');
      pre.className = 'mermaid-fallback';
      pre.textContent = src;
      el.replaceWith(pre);
    }
  }
}

/* ====================================================================
 * Pomodoro helpers
 * ==================================================================== */

const POMO_CIRCUMFERENCE = 2 * Math.PI * 18;

function _pomoNotify(title, body) {
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification(title, { body, icon: "/icons/studyloop-180.png" });
  }
  try {
    const ctx = new AudioContext();
    [0, 200, 400].forEach((delay) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      gain.gain.value = 0.15;
      osc.start(ctx.currentTime + delay / 1000);
      osc.stop(ctx.currentTime + delay / 1000 + 0.12);
    });
  } catch {
    /* audio not available */
  }
}

/* ====================================================================
 * Alpine stores — settings + pomodoro (registered in alpine:init)
 * ==================================================================== */

document.addEventListener("alpine:init", () => {
  /* Which renderer will actually PAINT the terminal — the renderer axis, not
     the transport axis. Conflating the two is the confusion that made `--dev`
     look like it "still showed xterm.js, ACP and Legacy (ttyd)": those are
     transports. Hydrated from /api/session/options.

     The defaults deliberately mirror describe_terminal_engine()'s stock output
     (dev_engines.py), so a slow or failed fetch still renders the CORRECT
     stock labels rather than a blank or a guess — an empty engine badge that
     silently means "xterm.js" is how a learner ends up believing an
     experimental renderer is live when it is not. */
  Alpine.store("terminalEngine", {
    dev_mode: false,
    engine: null,
    renderer: "xterm.js",
    label: "xterm.js",
    experimental: false,
    caveats: [],
    hydrate(d) {
      Object.assign(this, d || {});
    },
  });

  // Minimal shared toast — $store.toast.show('Parked ✓'). Auto-dismisses.
  Alpine.store("toast", {
    visible: false,
    message: "",
    _timer: null,
    show(msg, ms = 2000) {
      this.message = msg;
      this.visible = true;
      if (this._timer) clearTimeout(this._timer);
      this._timer = setTimeout(() => { this.visible = false; }, ms);
    },
  });

  // Quick-park brain-dump — capture a tangent WITHOUT leaving the current
  // view (AuDHD flow protection). Opened by the floating button or the 'p'
  // key (outside inputs); posts to /api/backlog/park.
  Alpine.store("quickPark", {
    open: false,
    text: "",
    saving: false,
    show() { this.open = true; this.text = ""; },
    hide() { this.open = false; },
    async save() {
      const q = this.text.trim();
      if (!q || this.saving) return;
      this.saving = true;
      try {
        const res = await fetch("/api/backlog/park", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q }),
        });
        if (res.ok) {
          Alpine.store("toast").show("Parked ✓");
          this.open = false;
        } else {
          Alpine.store("toast").show("Could not park — try again");
        }
      } catch {
        Alpine.store("toast").show("Could not park — offline?");
      } finally {
        this.saving = false;
      }
    },
  });

  Alpine.store("settings", {
    voiceOn: localStorage.getItem("voice") === "true",
    light: localStorage.getItem("theme") === "light",
    /* Palette selector: tokyo-night (default), dracula, catppuccin-mocha,
       catppuccin-latte. The legacy `light` toggle stays for backward
       compatibility but the palette is the canonical readability lever. */
    palette: localStorage.getItem("palette") || "tokyo-night",
    /* Reading font: inter (default), lexend, atkinson, system, serif,
       opendyslexic. ONE mechanism — body[data-font] feeding the --font custom
       property. OpenDyslexic used to be a separate body.dyslexic class that set
       font-family and line-height directly, which overrode the variable system
       and produced overlapping text when the two were toggled independently.
       Do not reintroduce a second mechanism. */
    font: localStorage.getItem("font") || "inter",
    /* Reading size: sm, md (default), lg, xl. Applied through the same
       attribute mechanism as `font` — see _applyFont(). */
    fontScale: localStorage.getItem("fontScale") || "md",
    // isSpeaking: driven by 'tts:state-change' events from tts-engine.js.
    // true while any tier (host-side or Web Speech API) is producing audio.
    isSpeaking: false,
    // ttsDownloadPct: 0-100 during first-run model download, -1 when idle.
    ttsDownloadPct: -1,
    ttsDownloadFile: '',
    /* TTS engine tier, as reported by tts-engine.js via 'tts:tier-change'.
       null means UNRESOLVED — not "no engine". The distinction matters: until
       the tier is known we must not offer the device's system voices, because a
       learner who installed a Kokoro app and silently got Apple voices has no
       way to tell. loadVoices() shows a disabled placeholder instead. */
    ttsTier: null,
    ttsTierReason: '',
    ttsTierDetail: '',
    ttsDegraded: false,
    ttsNotice: '',
    _preferredVoice: null,
    _voicesLoaded: false,

    /* Engine badge. Three states: pending (tier unknown), ok (the server tier is
       live), degraded (something else is speaking). "Degraded" is deliberately
       loud — a silent downgrade is indistinguishable from working software. */
    get ttsEngineLabel() {
      if (!this.ttsTier) return 'Detecting…';
      // 'server-openvox' is an internal tier id, kept stable because the
      // healthy-tier lists and their tests key off it -- but it must NOT reach the
      // user, who may well be running VoiceMode's Kokoro or a container rather
      // than OpenVox. With no case here it fell through to String(tier) and the
      // picker named a product that was not installed, which is how it was
      // reported: "OpenVox is down but it still says server-openvox".
      if (this.ttsTier === 'server-openvox') return 'Kokoro (server)';
      if (this.ttsTier === 'web-speech') return 'System voices';
      if (this.ttsTier === 'silent') return 'No audio';
      return String(this.ttsTier);
    },

    get ttsEngineClass() {
      if (!this.ttsTier) return 'tts-engine-badge pending';
      return this.ttsDegraded ? 'tts-engine-badge degraded' : 'tts-engine-badge ok';
    },

    get ttsEngineTitle() {
      if (!this.ttsTier) {
        return 'Detecting which speech engine this device can run…';
      }
      if (!this.ttsDegraded) {
        return `Kokoro is speaking from the host (${this.ttsTier}).`;
      }
      const why = this.ttsTierDetail || this.ttsTierReason || 'reason unknown';
      return (
        `Kokoro is NOT active — using ${this.ttsEngineLabel} instead. ` +
        `Reason: ${this.ttsTierReason || 'unknown'} — ${why}`
      );
    },

    init() {
      this._migrateDyslexicSetting();
      if (this.light) document.body.classList.add("light");
      this._applyPalette();
      this._applyFont();

      // Wire tts:state-change → isSpeaking reactive flag.
      // tts-engine.js also patches this directly (see _createEngine bridge),
      // but this listener is the canonical Alpine-side binding.
      window.addEventListener('tts:state-change', (e) => {
        this.isSpeaking = (e.detail.state === 'speaking');
      });

      // Wire tts:download-progress → ttsDownloadPct for the progress indicator.
      window.addEventListener('tts:download-progress', (e) => {
        this.ttsDownloadPct = e.detail.done ? -1 : e.detail.pct;
        this.ttsDownloadFile = e.detail.done ? '' : (e.detail.file || '');
      });

      // Wire tts:tier-change → record the tier and rebuild the voice selector.
      window.addEventListener('tts:tier-change', (e) => {
        const d = (e && e.detail) || {};
        this.ttsTier = d.tier || (window.ttsEngine && window.ttsEngine.tier) || null;
        this.ttsTierReason = d.reason || '';
        this.ttsTierDetail = d.detail || '';
        this.ttsDegraded = !!d.degraded;
        this.loadVoices();
      });

      /* Wire tts:engine-notice → surface it. A failure inside the speech engine
         (a voice that would not download, WebGPU vanishing mid-session) is
         otherwise completely invisible: audio just stops happening, and the
         learner concludes the feature is broken rather than that one voice
         failed to fetch. */
      window.addEventListener('tts:engine-notice', (e) => {
        const d = (e && e.detail) || {};
        this.ttsNotice = d.message || '';
        if (this.ttsNotice) Alpine.store('toast').show(this.ttsNotice);
      });

      // Adopt whatever the engine already resolved before this store mounted —
      // tts-engine.js is a module and may win the race.
      if (window.ttsEngine && window.ttsEngine.tier) {
        this.ttsTier = window.ttsEngine.tier;
        this.ttsTierReason = window.ttsEngine.tierReason || '';
        this.ttsTierDetail = window.ttsEngine.tierDetail || '';
        // Mirrors _setTier's derivation in tts-engine.js: an EXPLICIT
        // healthy-tier list, never "is not web-speech and not silent". A
        // negative derivation here would report the fastest tier as broken --
        // 'server-openvox' is the best path, not a degraded one.
        this.ttsDegraded = !(this.ttsTier === 'server-openvox');
      }

      /* Start the engine when voice is already on. tts-engine.js deliberately
         does NOT init() at load (it is a multi-hundred-MB model download), so
         without this the tier never resolves for a returning learner who left
         voice enabled — the badge sits on "Detecting…" forever and the voice
         list never leaves its placeholder. */
      if (this.voiceOn && window.ttsEngine && window.ttsEngine.init) {
        try {
          window.ttsEngine.init();
        } catch (err) {
          console.warn('[settings] ttsEngine.init() failed:', err);
        }
      }

      // Web Speech API fallback: load WSA voices if ttsEngine is not yet
      // initialised (or falls back to web-speech tier).
      this.loadVoices();
      if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = () => this.loadVoices();
      }
    },

    /* One-time migration off the removed body.dyslexic mechanism.
       A learner who had the old `Aa` toggle on must land on the equivalent
       dropdown option rather than silently losing their reading font. The stale
       key is cleared unconditionally: leaving it behind would let a later reader
       resurrect the second mechanism this migration exists to remove. */
    _migrateDyslexicSetting() {
      const legacy = localStorage.getItem("dyslexic");
      if (legacy === null) return;
      localStorage.removeItem("dyslexic");
      if (legacy !== "true") return;
      this.font = "opendyslexic";
      localStorage.setItem("font", "opendyslexic");
    },

    toggleTheme() {
      this.light = !this.light;
      document.body.classList.toggle("light", this.light);
      localStorage.setItem("theme", this.light ? "light" : "dark");
    },

    setPalette(name) {
      const allowed = [
        "tokyo-night",
        "dracula",
        "catppuccin-mocha",
        "catppuccin-latte",
        "nord",
        "gruvbox-dark",
        "gruvbox-light",
        "solarized-dark",
        "solarized-light",
        "one-dark",
        "rose-pine",
        "everforest",
      ];
      if (!allowed.includes(name)) return;
      this.palette = name;
      localStorage.setItem("palette", name);
      this._applyPalette();
    },

    _applyPalette() {
      /* `tokyo-night` is the bare :root state — drop the data attribute. */
      if (this.palette === "tokyo-night") {
        document.body.removeAttribute("data-palette");
      } else {
        document.body.setAttribute("data-palette", this.palette);
      }
      /* Notify palette-aware surfaces (e.g. the parking-lot Markdown preview
         and its mermaid diagrams) so they re-render against the new tokens.
         A hardcoded mermaid theme is exactly what this lets callers avoid. */
      window.dispatchEvent(
        new CustomEvent("studyloop:theme-change", { detail: { palette: this.palette } })
      );
    },

    setFont(name) {
      const allowed = [
        "inter",
        "lexend",
        "atkinson",
        "system",
        "serif",
        "opendyslexic",
      ];
      if (!allowed.includes(name)) return;
      this.font = name;
      localStorage.setItem("font", name);
      this._applyFont();
    },

    setFontScale(step) {
      const allowed = ["sm", "md", "lg", "xl"];
      if (!allowed.includes(step)) return;
      this.fontScale = step;
      localStorage.setItem("fontScale", step);
      this._applyFont();
    },

    /* The single font mechanism: both family and size are body attributes that
       style.css turns into custom properties. Family and size travel together
       here deliberately — the overlapping-text bug came from a second mechanism
       setting font metrics behind this one's back. */
    _applyFont() {
      /* `inter` is the bare :root state — drop the data attribute. */
      if (this.font === "inter") {
        document.body.removeAttribute("data-font");
      } else {
        document.body.setAttribute("data-font", this.font);
      }
      /* `md` is likewise the bare :root state. */
      if (this.fontScale === "md") {
        document.body.removeAttribute("data-font-scale");
      } else {
        document.body.setAttribute("data-font-scale", this.fontScale);
      }
    },

    toggleVoice() {
      this.voiceOn = !this.voiceOn;
      localStorage.setItem("voice", this.voiceOn);
      if (this.voiceOn) {
        this.speak("Voice enabled");
      } else {
        this.stopSpeaking();
      }
    },

    // speak() — gate on voiceOn, then route through ttsEngine.
    // Falls back to Web Speech API only if ttsEngine is absent (shouldn't
    // happen once tts-engine.js loads, but defensive guard kept).
    // Returns the underlying ttsEngine.speak() promise so callers MAY await
    // playback completion; existing fire-and-forget callers ignore it.
    speak(text) {
      if (!this.voiceOn || !text) return;
      return this.speakNow(text);
    },

    // speakNow() — bypass voiceOn gate (used for confirmations like
    // "Voice enabled"). Routes through ttsEngine for all tiers.
    // Returns ttsEngine.speak()'s promise (resolves when playback ends);
    // the WSA fallback path returns undefined (fire-and-forget).
    speakNow(text) {
      if (!text) return;
      if (window.ttsEngine) {
        return window.ttsEngine.speak(text);
      }
      // Legacy WSA fallback (tts-engine.js not yet loaded)
      if (!window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 0.95;
      u.pitch = 1.0;
      if (this._preferredVoice) u.voice = this._preferredVoice;
      window.speechSynthesis.speak(u);
    },

    // stopSpeaking() — delegates to the unified engine stop().
    stopSpeaking() {
      if (window.ttsEngine) {
        window.ttsEngine.stop();
        return;
      }
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    },

    // loadVoices() — populates the #voice-select dropdown.
    // Server tier: uses ttsEngine.listVoices() (the host's catalogue).
    // web-speech tier / no engine: uses speechSynthesis.getVoices().
    loadVoices() {
      const select = document.getElementById("voice-select");

      /* UNRESOLVED tier: show a disabled placeholder, never the device's system
         voices. This is the whole bug the e2e test names — a learner who
         installed a Kokoro-speaking app and silently got Apple voices has no
         way to tell the difference, so offering them is worse than offering
         nothing. Falling through to the Web Speech path here is what did that.
         `null` tier means "not known yet", which is NOT the same as
         'web-speech' (a real, deliberate decision by the engine). */
      if (!(window.ttsEngine && window.ttsEngine.tier)) {
        if (select) {
          select.innerHTML = "";
          const opt = document.createElement("option");
          // Three different situations shared one misleading message. Voice is
          // OFF by default and the engine is only started once it is on, so
          // "Detecting…" was usually describing work that was never going to
          // happen — a placeholder that looks like progress is worse than none.
          opt.textContent = this.voiceOn
            ? "Starting voice engine…"
            : "Turn on voice to load the engine";
          opt.value = "";
          opt.disabled = true;
          select.appendChild(opt);
          select.disabled = true;
        }
        this._voicesLoaded = false;
        return;
      }

      /* A resolved-but-mute engine must explain itself. The 'silent' tier makes
         speak() an explicit no-op, so without this the learner gets an empty
         picker and no audio — indistinguishable from a broken install. The
         engine already reports WHY in the tier-change detail; surface it. */
      if (window.ttsEngine.tier === 'silent') {
        if (select) {
          select.innerHTML = "";
          const opt = document.createElement("option");
          opt.textContent = this.ttsTierDetail
            ? `No voice available — ${this.ttsTierDetail}`
            : "No voice available on this device";
          opt.value = "";
          opt.disabled = true;
          select.appendChild(opt);
          select.disabled = true;
        }
        this._voicesLoaded = false;
        return;
      }
      if (select) select.disabled = false;

      /* Server tier: the host reports its own catalogue, so ask the engine.
         Matched EXPLICITLY rather than as "any tier that is not web-speech or
         silent" — a negative derivation here is what previously let an
         unexpected tier fall into the wrong branch. */
      if (window.ttsEngine.tier === 'server-openvox') {
        const voices = window.ttsEngine.listVoices();
        if (select) {
          select.innerHTML = "";
          voices.forEach((v) => {
            const opt = document.createElement("option");
            opt.value = v.id;
            opt.textContent = v.grade ? `${v.name} [${v.grade}]` : v.name;
            select.appendChild(opt);
          });
          // Select the voice that will ACTUALLY speak, not merely the saved one.
          // With no saved preference the <select> fell to option index 0 while
          // the engine stayed on its own DEFAULT_VOICE — so the dropdown named
          // one voice and a different one was heard, with nothing in the UI
          // admitting the disagreement. The engine has already reconciled the
          // saved 'serverVoiceId' against what the host offers, so its live
          // voice is the authority here.
          const engineVoice = window.ttsEngine && window.ttsEngine.voiceId;
          if (engineVoice && voices.find((v) => v.id === engineVoice)) {
            select.value = engineVoice;
          }
        }
        this._voicesLoaded = true;
        return;
      }

      // Web Speech API / fallback path (unchanged behaviour)
      if (!window.speechSynthesis) return;
      const voices = window.speechSynthesis.getVoices();
      if (!voices.length) return;
      this._voicesLoaded = true;

      const english = voices.filter((v) => v.lang.startsWith("en"));
      if (select) {
        select.innerHTML = "";
        english.forEach((v) => {
          const opt = document.createElement("option");
          opt.value = v.name;
          const label = v.name.replace(/Microsoft |Google |Apple /i, "");
          opt.textContent = v.localService ? label : `${label} (online)`;
          select.appendChild(opt);
        });
      }

      const saved = localStorage.getItem("voiceName");
      const savedVoice = saved && english.find((v) => v.name === saved);
      if (savedVoice) {
        this._preferredVoice = savedVoice;
        if (select) select.value = savedVoice.name;
      } else {
        this._preferredVoice =
          english.find((v) => /premium|enhanced|natural/i.test(v.name)) ||
          english.find((v) => /samantha|daniel|karen|moira|tessa|fiona/i.test(v.name)) ||
          english.find((v) => v.lang.startsWith("en-") && !v.name.includes("Google")) ||
          english[0] ||
          null;
        if (this._preferredVoice && select) select.value = this._preferredVoice.name;
        // PERSIST the computed preference. Without this the dropdown displayed a
        // chosen voice while the engine read nothing from 'voiceName' and let the
        // browser pick its own default -- the label and the audio disagreed on
        // first load, which is the same defect already fixed on the server tier.
        // Only the engine's stored key is read at speak time, so choosing a
        // voice here and not writing it is indistinguishable from choosing none.
        if (this._preferredVoice) {
          localStorage.setItem("voiceName", this._preferredVoice.name);
        }
      }
    },

    onVoiceChange(name) {
      const tier = (window.ttsEngine && window.ttsEngine.tier) || null;

      // Server tier: the id belongs to the HOST's catalogue, and setVoice()
      // validates it against that catalogue and stores it under 'serverVoiceId'.
      // Matched EXPLICITLY rather than as "any tier that is not web-speech or
      // silent": that negative form silently swallowed the server tier when it
      // was added, writing a host voice id into a key meant for another engine.
      if (tier === 'server-openvox') {
        window.ttsEngine.setVoice(name);
        if (this.voiceOn) this.speakNow("Voice changed");
        return;
      }

      // WSA fallback
      const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
      this._preferredVoice = voices.find((v) => v.name === name) || null;
      localStorage.setItem("voiceName", name);
      if (this.voiceOn) this.speakNow("Voice changed");
    },
  });

  Alpine.store("pomodoro", {
    STUDY: 25 * 60, BREAK: 5 * 60, LONG_BREAK: 15 * 60, CYCLES: 4,
    focusMin: 25, shortBreakMin: 5, longBreakMin: 15, cycles: 4,
    running: false, paused: false, visible: false, isBreak: false,
    remaining: 25 * 60, total: 25 * 60, sessions: 0, _interval: null, _loaded: false,

    get display() {
      const m = Math.floor(this.remaining / 60);
      const s = this.remaining % 60;
      return `${m}:${s.toString().padStart(2, "0")}`;
    },
    get label() {
      if (!this.running) return "Study";
      return this.isBreak
        ? (this.sessions > 0 && this.sessions % this.CYCLES === 0 ? "Long Break" : "Break")
        : "Study";
    },
    get arcOffset() { return POMO_CIRCUMFERENCE * (1 - (1 - this.remaining / this.total)); },
    get pauseIcon() { return this.paused ? "\u25b6" : "\u23f8\ufe0e"; },

    async loadConfig() {
      if (this._loaded) return;
      this._loaded = true;
      let defaults = { focus: 25, short_break: 5, long_break: 15, cycles: 4 };
      try { const res = await fetch("/api/settings/pomodoro"); if (res.ok) defaults = await res.json(); } catch {}
      this.focusMin = parseInt(localStorage.getItem("pomoFocus")) || defaults.focus;
      this.shortBreakMin = parseInt(localStorage.getItem("pomoShortBreak")) || defaults.short_break;
      this.longBreakMin = parseInt(localStorage.getItem("pomoLongBreak")) || defaults.long_break;
      this.cycles = parseInt(localStorage.getItem("pomoCycles")) || defaults.cycles;
      this._applyDurations();
    },
    _applyDurations() {
      this.STUDY = this.focusMin * 60; this.BREAK = this.shortBreakMin * 60;
      this.LONG_BREAK = this.longBreakMin * 60; this.CYCLES = this.cycles;
      if (!this.running) { this.remaining = this.STUDY; this.total = this.STUDY; }
    },
    saveDurations() {
      localStorage.setItem("pomoFocus", this.focusMin);
      localStorage.setItem("pomoShortBreak", this.shortBreakMin);
      localStorage.setItem("pomoLongBreak", this.longBreakMin);
      localStorage.setItem("pomoCycles", this.cycles);
      this._applyDurations();
    },
    toggle() { this.visible = !this.visible; },
    start() {
      this._applyDurations(); this.isBreak = false;
      this.remaining = this.STUDY; this.total = this.STUDY;
      this.running = true; this.paused = false; this.visible = true;
      this._startInterval();
      Alpine.store("settings").speak(`Pomodoro started. ${this.focusMin} minutes of focused study.`);
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    },
    togglePause() {
      if (this.paused) { this.paused = false; this._startInterval(); }
      else { this.paused = true; clearInterval(this._interval); }
    },
    stop() { this.running = false; this.paused = false; this.visible = false; clearInterval(this._interval); },
    _startInterval() { clearInterval(this._interval); this._tick(); this._interval = setInterval(() => this._tick(), 1000); },
    _tick() {
      if (this.paused) return;
      this.remaining--;
      if (this.remaining <= 0) {
        clearInterval(this._interval);
        if (this.isBreak) {
          Alpine.store("settings").speak("Break over! Time to study.");
          _pomoNotify("Break over!", "Time for another study session.");
          this.isBreak = false; this.remaining = this.STUDY; this.total = this.STUDY;
        } else {
          this.sessions++;
          const isLong = this.sessions % this.CYCLES === 0;
          const breakTime = isLong ? this.LONG_BREAK : this.BREAK;
          const breakMins = Math.round(breakTime / 60);
          Alpine.store("settings").speak(isLong ? `Great work! Take a ${breakMins} minute break.` : `Good session! Take a ${breakMins} minute break.`);
          _pomoNotify("Study session complete!", `Take a ${breakMins} minute break.`);
          this.isBreak = true; this.remaining = breakTime; this.total = breakTime;
        }
        this._interval = setInterval(() => this._tick(), 1000);
      }
    },
  });

  Alpine.store("pomodoro").loadConfig();
});

/**
 * Review application Alpine component.
 * @param {string} defaultMode - 'flashcards' or 'quiz'
 */
function reviewApp(defaultMode) {
  return {
    // Navigation state
    view: 'courses',       // 'courses' | 'config' | 'study' | 'summary'
    mode: defaultMode,

    // Course listing
    courses: [],
    coursesLoading: true,
    liveSession: null,
    // Monotonic guard against a stale _loadLiveSession() response overwriting a
    // newer stop. Must be initialised: without it the first bump is
    // `undefined + 1` === NaN, and the guard would then only work because
    // NaN !== NaN — correct by accident, and silently broken by anyone who
    // "tidies" the comparison.
    _liveSessionEpoch: 0,
    // True once init() has finished ALL of its async work. Exposed for tests:
    // there is no other honest "ready" signal, because coursesLoading goes false
    // in _loadCourses()'s finally — measured at ~250ms BEFORE liveSession is
    // populated — so waiting on it returns while the session fetch is still in
    // flight. That gap is what made the banner tests intermittent.
    _initDone: false,
    heatmapDays: [],
    history: [],

    // Course-list scaling: search box + collapsible publisher groups.
    searchQuery: '',
    collapsedGroups: new Set(),  // publisher names the user has collapsed

    // Config / session setup
    course: '',
    sources: [],
    selectedSource: 'all',
    cardLimit: 20,

    // Study state
    cards: [],
    index: 0,
    revealed: false,
    correct: 0,
    incorrect: 0,
    skipped: 0,
    sessionStartTime: null,
    isRetry: false,

    // Quiz state
    quizAnswered: false,
    quizSelectedIdx: -1,

    // Wrong-answer tracking for retry
    wrongHashes: [],

    get currentCard() {
      return this.cards[this.index] || null;
    },

    get progressPct() {
      return this.cards.length ? Math.round((this.index / this.cards.length) * 100) : 0;
    },

    get scoreText() {
      const answered = this.correct + this.incorrect;
      if (!answered) return '';
      return Math.round((this.correct / answered) * 100) + '%';
    },

    get retryTag() {
      return this.isRetry ? ' (retry)' : '';
    },

    get wrongCount() {
      return this.wrongHashes.length;
    },

    get summaryPct() {
      const answered = this.correct + this.incorrect;
      return answered ? Math.round((this.correct / answered) * 100) : 0;
    },

    get summaryCircumference() {
      return 2 * Math.PI * 58;  // r=58 from SVG
    },

    get summaryRingOffset() {
      const pct = this.summaryPct / 100;
      return this.summaryCircumference * (1 - pct);
    },

    get summaryGrade() {
      const pct = this.summaryPct;
      if (pct >= 90) return { text: 'Excellent!', cls: 'grade-a' };
      if (pct >= 70) return { text: 'Good work', cls: 'grade-b' };
      if (pct >= 50) return { text: 'Keep going', cls: 'grade-c' };
      return { text: 'Review again', cls: 'grade-d' };
    },

    // --- Course-list filtering + grouping (drives both panels) -------------
    // Mode-split lives HERE: each panel instantiates reviewApp('flashcards')
    // or reviewApp('quiz'), so this.mode picks which count gates the list.
    // The Flashcards panel shows only decks with flashcards; Quizzes only
    // decks with quiz questions. Then the search box filters by course name.
    get filteredCourses() {
      const countKey = this.mode === 'quiz' ? 'quiz_count' : 'flashcard_count';
      const q = this.searchQuery.trim().toLowerCase();
      return this.courses
        .filter((c) => (c[countKey] || 0) > 0)
        .filter((c) => !q || (c.name || '').toLowerCase().includes(q));
    },

    // Group the filtered courses by publisher, sorted alphabetically. Only
    // publishers with ≥1 matching course appear (derived from filteredCourses),
    // so a group whose courses are all filtered out simply vanishes.
    get groupedCourses() {
      const groups = {};
      for (const c of this.filteredCourses) {
        const pub = c.publisher || 'Other';
        (groups[pub] = groups[pub] || []).push(c);
      }
      return Object.entries(groups)
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([publisher, courses]) => ({ publisher, courses }));
    },

    // Collapse/expand a publisher group. Reassign the Set (Alpine doesn't
    // observe in-place Set mutation).
    toggleGroup(publisher) {
      const next = new Set(this.collapsedGroups);
      next.has(publisher) ? next.delete(publisher) : next.add(publisher);
      this.collapsedGroups = next;
    },

    get summaryDuration() {
      if (!this.sessionStartTime) return '';
      const secs = Math.floor((Date.now() - this.sessionStartTime) / 1000);
      const m = Math.floor(secs / 60);
      const s = secs % 60;
      return m + 'm ' + s + 's';
    },

    get correctQuizIdx() {
      if (!this.currentCard || this.currentCard.type !== 'quiz') return -1;
      return this.currentCard.options.findIndex(o => o.is_correct);
    },

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    async init() {
      // Register the stop listener BEFORE any await. The reviewApp factory is
      // mounted with x-data and stays alive while hidden by x-show — it is never
      // re-init()'d on tab nav — so when the user stops a session from the Study
      // Session view, _loadLiveSession() doesn't get called again and a stale
      // banner would stick. Hence the global listener.
      //
      // Ordering is load-bearing, not style: this used to sit AFTER
      // `await this._loadCourses()`, which sets this.courses and then keeps
      // awaiting a stats fetch per course. Any stop dispatched in that window
      // hit no listener at all and was lost permanently, leaving the banner up
      // for a session that had ended. An event handler must exist before the
      // work that can emit the event, so nothing is registered behind an await.
      window.addEventListener('study-session-stop', () => {
        // Bump the epoch BEFORE clearing: a _loadLiveSession() fetch already in
        // flight captured the old epoch and must not write its now-stale
        // "session is active" response over this clear.
        this._liveSessionEpoch += 1;
        this.liveSession = null;
      });
      await this._loadCourses();
      await this._loadLiveSession();
      // Last line of init() on purpose — this is the only signal that every
      // await above has settled.
      this._initDone = true;
    },

    async _loadCourses() {
      // Tri-state: while loading, the UI shows "Checking your content…"
      // instead of flashing the "No courses found" empty state (which used
      // to render instantly on pane switch, then get replaced seconds later).
      this.coursesLoading = true;
      try {
        const res = await fetch('/api/courses');
        if (res.ok) {
          this.courses = await res.json();
          await this._loadHistory();
          this._buildHeatmap();
        }
      } catch { /* courses unavailable */ }
      finally { this.coursesLoading = false; }
    },

    async _loadLiveSession() {
      const epoch = this._liveSessionEpoch;
      try {
        const res = await fetch('/api/session/state');
        if (res.ok) {
          const state = await res.json();
          // Drop the response if a stop happened while it was in flight: the
          // user's stop is newer information than a fetch that started before
          // it, so honouring the fetch would show a banner for a session that
          // is already over.
          if (epoch !== this._liveSessionEpoch) return;
          if (state.study_session_id && state.mode !== 'ended') {
            this.liveSession = state;
          }
        }
      } catch { /* no live session */ }
    },

    async _loadHistory() {
      // Build history from course stats — review_sessions table
      const items = [];
      for (const c of this.courses) {
        try {
          const res = await fetch('/api/stats/' + encodeURIComponent(c.name));
          if (res.ok) {
            const stats = await res.json();
            if (stats.total_reviews > 0) {
              items.push({
                course: c.name,
                mode: this.mode,
                correct: stats.mastered || 0,
                total: stats.unique_cards || 0,
                date: '',
              });
            }
          }
        } catch { /* skip */ }
      }
      this.history = items;
    },

    _buildHeatmap() {
      // Simple 90-day heatmap placeholder — real implementation would
      // query per-day review counts from the API
      const days = [];
      const now = new Date();
      for (let i = 89; i >= 0; i--) {
        const d = new Date(now);
        d.setDate(d.getDate() - i);
        days.push({
          date: d.toISOString().slice(0, 10),
          count: 0,
          level: 'level-0',
        });
      }
      this.heatmapDays = days;
    },

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------

    goHome() {
      this.view = 'courses';
      this.cards = [];
      this.index = 0;
      this.revealed = false;
      this.correct = 0;
      this.incorrect = 0;
      this.skipped = 0;
      this.isRetry = false;
      this.wrongHashes = [];
      this.searchQuery = '';  // clear the filter when returning to the list
      this._loadCourses();
    },

    async openConfig(course, mode) {
      this.course = course;
      this.mode = mode;
      this.selectedSource = 'all';
      this.view = 'config';

      try {
        const res = await fetch(
          '/api/sources/' + encodeURIComponent(course) + '?mode=' + mode
        );
        if (res.ok) this.sources = await res.json();
      } catch {
        this.sources = [];
      }
    },

    // ------------------------------------------------------------------
    // Session lifecycle
    // ------------------------------------------------------------------

    async startSession(source, limit) {
      try {
        const res = await fetch(
          '/api/cards/' + encodeURIComponent(this.course) + '?mode=' + this.mode
        );
        if (!res.ok) return;
        let cards = await res.json();
        const { dueHashes, wrongHashes } = await this._loadPriorityHashes();

        // Filter by source
        if (source && source !== 'all') {
          cards = cards.filter(c => c.source === source);
        }

        cards = this._prioritizeSessionCards(cards, dueHashes, wrongHashes, limit);

        if (!cards.length) return;

        this.cards = cards;
        this.index = 0;
        this.revealed = false;
        this.correct = 0;
        this.incorrect = 0;
        this.skipped = 0;
        this.wrongHashes = [];
        this.isRetry = false;
        this.sessionStartTime = Date.now();
        this.view = 'study';
      } catch { /* load failed */ }
    },

    async _loadPriorityHashes() {
      const course = encodeURIComponent(this.course);
      const fetchJson = async (url) => {
        try {
          const res = await fetch(url);
          return res.ok ? await res.json() : [];
        } catch {
          return [];
        }
      };

      const [dueCards, wrongCards] = await Promise.all([
        fetchJson('/api/due/' + course),
        fetchJson('/api/wrong/' + course),
      ]);

      return {
        dueHashes: this._uniqueHashes(
          Array.isArray(dueCards)
            ? dueCards.map(c => typeof c === 'string' ? c : c?.card_hash)
            : []
        ),
        wrongHashes: this._uniqueHashes(Array.isArray(wrongCards) ? wrongCards : []),
      };
    },

    _prioritizeSessionCards(cards, dueHashes, wrongHashes, limit) {
      const byHash = new Map();
      for (const card of cards) {
        if (card.hash && !byHash.has(card.hash)) byHash.set(card.hash, card);
      }

      const picked = new Set();
      const ordered = [];
      const addByHash = (hash) => {
        const card = byHash.get(hash);
        if (!card || picked.has(card.hash)) return;
        picked.add(card.hash);
        ordered.push(card);
      };

      dueHashes.forEach(addByHash);
      wrongHashes.forEach(addByHash);

      const remaining = cards.filter(c => !c.hash || !picked.has(c.hash));
      ordered.push(...this._shuffleCards(remaining));

      return limit && limit > 0 ? ordered.slice(0, limit) : ordered;
    },

    _uniqueHashes(hashes) {
      const seen = new Set();
      const unique = [];
      for (const hash of hashes) {
        if (!hash || seen.has(hash)) continue;
        seen.add(hash);
        unique.push(hash);
      }
      return unique;
    },

    _shuffleCards(cards) {
      for (let i = cards.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [cards[i], cards[j]] = [cards[j], cards[i]];
      }
      return cards;
    },

    restartSession() {
      this.startSession(this.selectedSource, this.cardLimit);
    },

    retryWrong() {
      if (!this.wrongHashes.length) return;
      const wrongSet = new Set(this.wrongHashes);
      const retryCards = this.cards.filter(c => wrongSet.has(c.hash));
      if (!retryCards.length) return;

      this.cards = retryCards;
      this.index = 0;
      this.revealed = false;
      this.correct = 0;
      this.incorrect = 0;
      this.skipped = 0;
      this.wrongHashes = [];
      this.isRetry = true;
      this.sessionStartTime = Date.now();
      this.view = 'study';
    },

    // ------------------------------------------------------------------
    // Card interaction
    // ------------------------------------------------------------------

    flipCard() {
      if (this.currentCard?.type === 'flashcard') {
        this.revealed = !this.revealed;
      }
    },

    async answerFlashcard(correct) {
      if (!this.currentCard) return;

      if (correct) {
        this.correct++;
      } else {
        this.incorrect++;
        this.wrongHashes.push(this.currentCard.hash);
      }

      // Record review to server
      this._recordReview(this.currentCard.hash, correct, 'flashcard');
      this._advance();
    },

    answerQuiz(idx) {
      if (this.quizAnswered || !this.currentCard) return;

      this.quizAnswered = true;
      this.quizSelectedIdx = idx;
      const isCorrect = this.currentCard.options[idx]?.is_correct || false;

      if (isCorrect) {
        this.correct++;
      } else {
        this.incorrect++;
        this.wrongHashes.push(this.currentCard.hash);
      }

      this._recordReview(this.currentCard.hash, isCorrect, 'quiz');

      // Auto-advance after delay
      setTimeout(() => this._advance(), 1500);
    },

    quizOptionClass(idx) {
      if (!this.quizAnswered) return '';
      const opt = this.currentCard?.options[idx];
      if (!opt) return '';
      if (opt.is_correct) return 'correct';
      if (idx === this.quizSelectedIdx && !opt.is_correct) return 'incorrect';
      return 'dimmed';
    },

    skipCard() {
      this.skipped++;
      this._advance();
    },

    _advance() {
      this.revealed = false;
      this.quizAnswered = false;
      this.quizSelectedIdx = -1;

      if (this.index + 1 < this.cards.length) {
        this.index++;
      } else {
        this.view = 'summary';
      }
    },

    async _recordReview(cardHash, correct, cardType) {
      try {
        await fetch('/api/review', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            course: this.course,
            card_hash: cardHash,
            correct: correct,
            card_type: cardType,
          }),
        });
      } catch { /* best effort */ }
    },

    // ------------------------------------------------------------------
    // TTS
    // ------------------------------------------------------------------

    speakCurrentCard() {
      if (!this.currentCard) return;
      const text = this.currentCard.type === 'flashcard'
        ? (this.revealed ? this.currentCard.back : this.currentCard.front)
        : this.currentCard.question;
      // Route through the unified tts-engine (all three tiers: server-openvox,
      // web-speech, silent). ttsEngine.speak() handles stop + restart
      // internally so calling it mid-utterance is safe.
      if (window.ttsEngine) {
        window.ttsEngine.speak(text);
        return;
      }
      // Legacy WSA fallback (tts-engine.js not yet loaded)
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
      }
    },

    // ------------------------------------------------------------------
    // Keyboard shortcuts
    // ------------------------------------------------------------------

    handleKey(event) {
      const key = event.key.toLowerCase();

      if (this.view === 'study') {
        if (this.currentCard?.type === 'flashcard') {
          if (key === ' ' || key === 'spacebar') { event.preventDefault(); this.flipCard(); }
          else if (key === 'y' && this.revealed) this.answerFlashcard(true);
          else if (key === 'n' && this.revealed) this.answerFlashcard(false);
          else if (key === 's') this.skipCard();
          else if (key === 't') this.speakCurrentCard();
          else if (key === 'escape') this.goHome();
        } else if (this.currentCard?.type === 'quiz') {
          if (['1', '2', '3', '4'].includes(key) && !this.quizAnswered) {
            this.answerQuiz(parseInt(key) - 1);
          }
          else if (key === 't') this.speakCurrentCard();
          else if (key === 'escape') this.goHome();
        }
      } else if (this.view === 'summary') {
        if (key === 'r' && this.wrongCount) this.retryWrong();
        else if (key === 'escape') this.goHome();
      } else if (this.view === 'courses') {
        // No global shortcuts on courses view
      }
    },
  };
}

/* ======================================================================
 * M2: Course Explorer Panel
 *
 * Fetches GET /api/explorer/tree on first open and renders one horizontal
 * CSS scroll-snap carousel row per provider. Clicking a course card
 * fetches GET /api/explorer/courses/{course_id:path}/lessons and shows a
 * lesson list below the carousels.
 *
 * M3 seam
 * -------
 * - view: 'browser' | 'reader'  (only 'browser' is implemented here)
 * - activeLesson: stashed lesson object
 * - openLesson(lesson): STUB — sets view='reader', stashes lesson.
 *   M3 will call GET /api/explorer/lesson/{lesson_id:path}/content and
 *   render markdown inside .explorer-reader-view.
 * - backToBrowser(): returns from reader to browser view.
 * ====================================================================== */

const COMPANION_MODE_INSTRUCTIONS = {
  recall: 'Start with one active-recall question. Keep the first turn answerable without rereading.',
  diagram: 'Ask for a tiny diagram repair: one missing edge, label, or direction to fix.',
  trace: 'Ask the learner to trace one concrete example through the note step by step.',
  teachback: 'Ask for a 90-second teach-back, then probe for one gap or assumption.',
  repair: 'Find the likely fragile point and ask a small repair question.',
};

const COMPANION_MODE_LABELS = {
  recall: 'Recall',
  diagram: 'Diagram',
  trace: 'Trace',
  teachback: 'Teach-back',
  repair: 'Repair',
};

function _commandSafe(value) {
  return String(value || 'study').replace(/["\\]/g, '').trim() || 'study';
}

function _lessonEvidenceCommand(lesson, title) {
  const concept = _commandSafe(String(title || 'lesson').toLowerCase());
  const topic = _commandSafe(lesson && lesson.course_id ? lesson.course_id : 'study');
  return `studyloop progress "${concept}" -t "${topic}" -c learning`;
}

function courseExplorer() {
  return {
    // ---- View state — 'browser' = carousels, 'reader' = M3 lesson view
    view: 'browser',

    // ---- Tree data  [{ id, name, courses: [{ id, name, provider }] }]
    providers: [],
    loading: false,
    loadError: '',
    _treeLoaded: false,

    // ---- Per-provider filter strings keyed by provider id
    filters: {},

    // ---- Active course and its lessons
    activeCourse: null,
    lessons: [],
    lessonsLoading: false,
    lessonsError: '',

    // ---- M3: reader view state
    activeLesson: null,
    readerHtml: '',
    readerText: '',        // frontmatter-stripped markdown source, for TTS (Phase 6)
    readerLoading: false,
    readerError: '',

    // ---- In-app note companion (browser-local context pack)
    companionOpen: false,
    companionMode: 'recall',
    companionPrompt: '',
    companionAnswer: '',
    companionFollowup: '',
    companionCopied: false,
    companionEvidenceCopied: false,

    // --- Phase 6: TTS read-aloud (gated on the browser-neural-tts worktree) ---
    // window.ttsEngine only exists once that worktree merges; all uses below
    // feature-detect it and no-op gracefully when absent.
    isReading: false,
    ttsAvailable: false,   // set in init() by probing window.ttsEngine
    // Generation counter: incremented each time a new openLesson() or
    // backToBrowser() is triggered.  Each async chain captures its own
    // generation at entry and bails if it has been superseded.
    _readerGen: 0,

    // ---- Phase 4: global search state
    searchQuery: '',
    searchResults: [],   // merged client + server hits
    searchLoading: false,
    _searchDebounce: null,
    _searchGen: 0,       // cancels stale async searches (same pattern as _readerGen)
    // Fuse.js index over {id, title, course, provider} items from the tree.
    // Rebuilt whenever the tree is loaded/refreshed.
    _fuseIndex: null,

    // ------------------------------------------------------------------
    // init: wire this component's toggle/close onto the store so the
    // sidebar button ($store.explorer.toggle()) gets the full behaviour
    // (lazy-fetch + layout class) rather than the boot-stub.
    // ------------------------------------------------------------------
    init() {
      const self = this;
      const store = Alpine.store('explorer');
      store.toggle = () => self.toggle();
      store.close  = () => self.close();

      // Phase 6: probe for the (optional) TTS engine and track speaking state.
      // window.ttsEngine is provided only by the browser-neural-tts worktree;
      // when absent, ttsAvailable stays false and the read-aloud button hides.
      this.ttsAvailable = !!(window.ttsEngine && typeof window.ttsEngine.speak === 'function');
      window.addEventListener('tts:state-change', (e) => {
        // Only reflect speaking state while the reader is the active surface.
        self.isReading = (e.detail && e.detail.state === 'speaking');
      });
    },

    // ------------------------------------------------------------------
    // Toggle the panel open/closed; lazy-fetch tree on first open.
    // Drives $store.explorer.open so the sidebar button :class reacts.
    // ------------------------------------------------------------------
    async toggle() {
      const store = Alpine.store('explorer');
      store.open = !store.open;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.toggle('explorer-open', store.open);
      if (store.open && !this._treeLoaded) {
        await this._fetchTree();
      }
    },

    close() {
      const store = Alpine.store('explorer');
      store.open = false;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.remove('explorer-open');
    },

    // ------------------------------------------------------------------
    // Fetch the study tree once.
    // ------------------------------------------------------------------
    async _fetchTree() {
      this.loading = true;
      this.loadError = '';
      try {
        const res = await fetch('/api/explorer/tree');
        if (res.ok) {
          const data = await res.json();
          this.providers = data;
          // Seed a filter entry for each provider so x-model is bound
          data.forEach((p) => {
            if (!(p.id in this.filters)) this.filters[p.id] = '';
          });
          this._treeLoaded = true;
          // Build Fuse index over provider+course names (title-level search).
          this._buildFuseIndex(data);
        } else {
          this.loadError = `Could not load course tree (${res.status})`;
        }
      } catch {
        this.loadError = 'Network error loading course tree';
      } finally {
        this.loading = false;
      }
    },

    // ------------------------------------------------------------------
    // Build (or rebuild) the Fuse.js index over provider+course names.
    // Called after the tree loads and can be extended with lesson titles
    // as courses are opened.
    // ------------------------------------------------------------------
    _buildFuseIndex(providers) {
      if (!window.Fuse) return;
      const items = [];
      (providers || []).forEach((p) => {
        (p.courses || []).forEach((c) => {
          items.push({
            lesson_id: null,  // course-level hit — no lesson_id yet
            course_id: c.id,
            provider: p.id,
            title: c.name,
            _kind: 'course',
          });
        });
      });
      this._fuseIndex = new window.Fuse(items, {
        keys: [
          { name: 'title',    weight: 5 },
          { name: 'course_id', weight: 2 },
          { name: 'provider',  weight: 1 },
        ],
        threshold: 0.35,
        ignoreLocation: true,
        includeMatches: true,
        minMatchCharLength: 2,
      });
    },

    // ------------------------------------------------------------------
    // Add lesson titles to the Fuse index after a course is opened.
    // Existing index items for this course are replaced (dedup by course_id).
    // ------------------------------------------------------------------
    _addLessonsToFuseIndex(lessons) {
      if (!window.Fuse || !this._fuseIndex) return;
      // Grab current items, drop existing lesson entries for this course.
      const existing = this._fuseIndex._docs || [];
      const courseId = lessons.length > 0 ? lessons[0].course_id : null;
      const kept = courseId
        ? existing.filter((item) => !(item._kind === 'lesson' && item.course_id === courseId))
        : existing;
      const newItems = lessons.map((l) => ({
        lesson_id: l.id,
        course_id: l.course_id,
        provider: l.course_id ? l.course_id.split('/')[0] : '',
        title: l.name,
        slug: l.slug,
        _kind: 'lesson',
      }));
      const all = [...kept, ...newItems];
      this._fuseIndex = new window.Fuse(all, {
        keys: [
          { name: 'title',    weight: 5 },
          { name: 'course_id', weight: 2 },
          { name: 'provider',  weight: 1 },
        ],
        threshold: 0.35,
        ignoreLocation: true,
        includeMatches: true,
        minMatchCharLength: 2,
      });
    },

    // ------------------------------------------------------------------
    // Debounced handler for the search input.
    // ------------------------------------------------------------------
    onSearchInput() {
      clearTimeout(this._searchDebounce);
      const q = this.searchQuery.trim();
      if (q.length < 2) {
        this.searchResults = [];
        this.searchLoading = false;
        return;
      }
      // Show client-side Fuse hits immediately (zero latency).
      this._applyFuseSearch(q);
      // Debounce the server FTS call by ~250 ms.
      this._searchDebounce = setTimeout(() => this._fetchServerSearch(q), 250);
    },

    clearSearch() {
      this.searchQuery = '';
      this.searchResults = [];
      this.searchLoading = false;
      clearTimeout(this._searchDebounce);
    },

    // ------------------------------------------------------------------
    // Run the Fuse.js index over the current query; fill searchResults
    // with client-side title hits immediately.
    // ------------------------------------------------------------------
    _applyFuseSearch(q) {
      if (!this._fuseIndex) {
        this.searchResults = [];
        return;
      }
      const hits = this._fuseIndex.search(q);
      this.searchResults = hits.map((h) => ({
        lesson_id: h.item.lesson_id || h.item.course_id,
        course_id: h.item.course_id,
        provider:  h.item.provider,
        title:     h.item.title,
        excerpt:   '',  // client hits have no body excerpt
        _kind:     h.item._kind,
        slug:      h.item.slug || null,
      }));
    },

    // ------------------------------------------------------------------
    // Fetch server FTS body hits and merge with the current results.
    // Uses a generation counter to ignore stale responses.
    // ------------------------------------------------------------------
    async _fetchServerSearch(q) {
      const myGen = ++this._searchGen;
      this.searchLoading = true;
      try {
        const url = `/api/explorer/search?q=${encodeURIComponent(q)}&limit=20`;
        const res = await fetch(url);
        if (this._searchGen !== myGen) return;  // superseded
        if (!res.ok) return;
        const data = await res.json();
        if (this._searchGen !== myGen) return;

        const serverHits = (data.results || []).map((r) => ({
          ...r,
          _kind: 'lesson',
          slug: null,
        }));

        // Merge: keep all client hits, add server hits not already present.
        const seen = new Set(this.searchResults.map((r) => r.lesson_id));
        const merged = [...this.searchResults];
        for (const hit of serverHits) {
          if (!seen.has(hit.lesson_id)) {
            merged.push(hit);
            seen.add(hit.lesson_id);
          } else {
            // Upgrade an existing client hit with the server excerpt.
            const idx = merged.findIndex((r) => r.lesson_id === hit.lesson_id);
            if (idx >= 0 && hit.excerpt) {
              merged[idx] = { ...merged[idx], excerpt: hit.excerpt };
            }
          }
        }
        this.searchResults = merged;
      } catch {
        /* silently ignore network errors — client hits remain shown */
      } finally {
        if (this._searchGen === myGen) this.searchLoading = false;
      }
    },

    // ------------------------------------------------------------------
    // Group search results by provider for display.
    // ------------------------------------------------------------------
    searchResultGroups() {
      const groups = {};
      for (const r of this.searchResults) {
        const prov = r.provider || r.course_id?.split('/')[0] || 'Unknown';
        if (!groups[prov]) groups[prov] = { provider: prov, results: [] };
        groups[prov].results.push(r);
      }
      return Object.values(groups);
    },

    // ------------------------------------------------------------------
    // Open a result from the search overlay.
    // Constructs the minimal lesson object openLesson() needs:
    //   { id, slug, name, course_id }
    // ------------------------------------------------------------------
    openSearchResult(result) {
      this.clearSearch();
      // lesson_id is the full path "provider/course/slug" — that's openLesson's `id`.
      // Derive slug from lesson_id by stripping course_id prefix.
      const lessonId = result.lesson_id;
      const courseId = result.course_id;
      const slug = courseId && lessonId.startsWith(courseId + '/')
        ? lessonId.slice(courseId.length + 1)
        : lessonId;
      const lesson = {
        id: lessonId,
        slug: slug,
        name: result.title,
        course_id: courseId,
      };
      this.openLesson(lesson);
    },

    // ------------------------------------------------------------------
    // Safe excerpt renderer: escape all HTML, then re-allow only
    // <mark> and </mark> tags (the only HTML SQLite's snippet() injects).
    // This prevents any lesson body content from being rendered as HTML.
    // ------------------------------------------------------------------
    safeExcerpt(excerpt) {
      if (!excerpt) return '';
      // 1. HTML-escape the whole string.
      const escaped = _escapeHtml(excerpt);
      // 2. Un-escape only our <mark> sentinel pairs.
      //    After _escapeHtml, <mark> becomes &lt;mark&gt; and </mark>
      //    becomes &lt;/mark&gt;. Replace those exact strings back.
      return escaped
        .replace(/&lt;mark&gt;/g, '<mark>')
        .replace(/&lt;\/mark&gt;/g, '</mark>');
    },

    // ------------------------------------------------------------------
    // Filtered course list for a provider row.
    // ------------------------------------------------------------------
    filteredCourses(provider) {
      const q = (this.filters[provider.id] || '').toLowerCase().trim();
      if (!q) return provider.courses;
      return provider.courses.filter((c) =>
        c.name.toLowerCase().includes(q)
      );
    },

    // ------------------------------------------------------------------
    // Scroll a carousel left or right.
    // Alpine 3 x-ref is static-only (no dynamic binding), so the carousel
    // divs use data-carousel-id and we find them with querySelector.
    // ------------------------------------------------------------------
    scrollCarousel(providerId, direction) {
      const el = this.$el.querySelector(
        `.explorer-carousel[data-carousel-id="${CSS.escape(providerId)}"]`
      );
      if (el) el.scrollBy({ left: direction * 158, behavior: 'smooth' });
    },

    // ------------------------------------------------------------------
    // A course card was clicked: fetch lessons.
    // Clicking the already-active course collapses the lesson list.
    // ------------------------------------------------------------------
    async selectCourse(course) {
      if (this.activeCourse && this.activeCourse.id === course.id) {
        this.activeCourse = null;
        this.lessons = [];
        this.lessonsError = '';
        return;
      }
      this.activeCourse = course;
      this.lessons = [];
      this.lessonsError = '';
      this.lessonsLoading = true;
      try {
        // CRITICAL: the :path segment must preserve real slashes.
        // Encode each segment of the id individually and rejoin with '/'.
        const enc = (id) => id.split('/').map(encodeURIComponent).join('/');
        const res = await fetch(`/api/explorer/courses/${enc(course.id)}/lessons`);
        if (res.ok) {
          this.lessons = await res.json();
          // Extend the Fuse index with lesson titles for this course so
          // subsequent searches can find individual lessons by title.
          this._addLessonsToFuseIndex(this.lessons);
        } else {
          this.lessonsError = `Could not load lessons (${res.status})`;
        }
      } catch {
        this.lessonsError = 'Network error loading lessons';
      } finally {
        this.lessonsLoading = false;
      }
    },

    // ------------------------------------------------------------------
    // Open a lesson: fetch raw markdown, strip frontmatter, render HTML.
    //
    // Race-safety: a generation counter (_readerGen) is incremented at the
    // top of every call.  After each await point the chain checks whether
    // its own captured generation is still current; if a newer call (or
    // backToBrowser) has run, this chain silently abandons its result so
    // stale content never overwrites fresher content.
    // ------------------------------------------------------------------
    async openLesson(lesson) {
      const myGen = ++this._readerGen;   // capture generation before any await

      this.activeLesson = lesson;
      this.readerHtml = '';
      this.readerText = '';
      this.readerError = '';
      this._resetCompanion();
      this.readerLoading = true;
      this.view = 'reader';
      this.stopReading();   // halt any TTS playback from a previous lesson

      try {
        // lesson.id is the full "provider/course/slug" path.
        // Encode each segment individually so the :path route param sees
        // real slashes, not %2F which Starlette would reject.
        const enc = (id) => id.split('/').map(encodeURIComponent).join('/');
        const res = await fetch('/api/explorer/lesson/' + enc(lesson.id) + '/content');

        // Guard 1: a newer openLesson or backToBrowser ran while we fetched.
        if (this._readerGen !== myGen) return;

        if (res.ok) {
          const data = await res.json();

          // Guard 2: a newer call ran while we parsed the JSON body.
          if (this._readerGen !== myGen) return;

          const raw = data.content || '';
          const stripped = _stripFrontmatter(raw);
          this.readerText = stripped;   // raw source for TTS (Phase 6)
          this.readerHtml = renderMarkdown(stripped);
          /* The prose is x-show hidden while readerLoading is true. Mermaid
             measures its container, so rendering before revealing it freezes
             the diagram at a meaningless 16x16 viewBox. */
          this.readerLoading = false;

          /* Two-pass mermaid: Alpine's x-html directive schedules its DOM
             write as a reactive effect.  The first $nextTick exhausts the
             current microtask queue and triggers the effect; the second
             $nextTick waits for the effect's DOM mutation to be flushed
             before _renderMermaidPlaceholders queries for placeholders.
             Without both ticks the querySelectorAll runs before x-html has
             written the content and finds nothing to render. */
          await this.$nextTick();
          await this.$nextTick();

          // Guard 3: a newer call ran during the DOM-flush ticks.
          if (this._readerGen !== myGen) return;

          /* $el, NOT $root. Verified by test: the parking panel needs $root
             because its call is reached from a @click expression on a button,
             but this call site is NOT, and switching it to $root breaks
             test_explorer_search_finds_and_opens_a_lesson. The two sites are
             genuinely different; assuming they were the same was wrong. */
          /* Guarded $root, not $el. $el is whatever element the invoking
             expression sits on - for a lesson opened by clicking a list
             item, that item, which does NOT contain the reader prose the
             placeholders live in. An earlier attempt at bare $root threw
             when it was undefined and broke the search test (aaad544); the
             guard is what makes $root safe here. */
          if (this.$root) await _renderMermaidPlaceholders(this.$root);
        } else {
          this.readerError = `Could not load lesson (${res.status})`;
        }
      } catch (err) {
        // Only surface the error if this generation is still current.
        if (this._readerGen === myGen) {
          this.readerError = 'Network error loading lesson';
          console.error('[CourseExplorer] openLesson error:', err);
        }
      } finally {
        // Only clear the loading spinner for the generation that set it.
        if (this._readerGen === myGen) {
          this.readerLoading = false;
        }
      }
    },

    // Back to carousel view from reader.
    // Bumps _readerGen to invalidate any in-flight openLesson() chain so
    // a late-arriving response cannot overwrite the browser view.
    // Also clears readerLoading so the spinner doesn't persist if Back is
    // pressed while a fetch is still running (F7).
    backToBrowser() {
      this._readerGen++;          // invalidate any in-flight openLesson chain
      this.stopReading();         // halt TTS playback when leaving the reader
      this.view = 'browser';
      this.activeLesson = null;
      this.readerHtml = '';
      this.readerText = '';
      this.readerError = '';
      this.readerLoading = false; // clear spinner even if fetch was in-flight
      this.struggleMarked = false;
      this.struggleError = '';
      this.discussionCopied = false;
      this.discussionError = '';
      this._resetCompanion();
    },

    // ---- Phase 6: TTS read-aloud (GATED on the browser-neural-tts worktree) ----
    // window.ttsEngine is provided ONLY by that worktree's tts-engine.js. Until
    // it merges, the engine is absent here — every method below feature-detects
    // it and no-ops, so the button can ship now and "lights up" once TTS lands.
    //
    // Contract (verified against the TTS worktree):
    //   window.ttsEngine.speak(plainText) — takes PLAIN TEXT (not markdown/HTML)
    //     and passes it to the host as given. Resolves when playback ends.
    //   window.ttsEngine.stop() — halts synthesis + audio.
    //   window 'tts:state-change' event, detail.state === 'speaking' | 'idle' | …
    // We must convert markdown -> plain text ourselves (_mdToPlainText) so the
    // engine doesn't read '#', '*', backticks, or code/diagram blocks aloud.
    readAloud() {
      if (!window.ttsEngine || typeof window.ttsEngine.speak !== 'function') {
        return;  // TTS not present on this build — gracefully do nothing
      }
      if (this.view !== 'reader' || !this.readerText) return;
      const plain = _mdToPlainText(this.readerText);
      if (!plain) return;
      try {
        // speak() handles stop-then-restart internally; isReading is driven by
        // the tts:state-change listener wired in init() (single source of truth).
        window.ttsEngine.speak(plain);
      } catch (err) {
        console.error('[CourseExplorer] readAloud error:', err);
      }
    },

    stopReading() {
      if (window.ttsEngine && typeof window.ttsEngine.stop === 'function') {
        try { window.ttsEngine.stop(); } catch { /* engine already idle */ }
      }
      // isReading is reset by the state-change listener; clear eagerly too in
      // case the engine is absent (no event will fire).
      this.isReading = false;
    },

    // ---- Phase 5: mark current lesson section as a struggle topic --------
    // State: struggleMarked (bool, transient confirmation) + struggleError (str).
    // Guard: only callable when view==='reader' && activeLesson is set.
    struggleMarked: false,
    struggleError: '',
    discussionCopied: false,
    discussionError: '',

    async markStruggle() {
      if (this.view !== 'reader' || !this.activeLesson) return;

      const lesson = this.activeLesson;
      // Derive publisher from the course_id prefix ("provider/course" → "provider").
      const publisher = lesson.course_id ? lesson.course_id.split('/')[0] : null;

      try {
        const resp = await fetch('/api/history/struggling-topics', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            course: lesson.course_id || lesson.id,
            section: lesson.slug || lesson.id,
            publisher: publisher,
            note: null,
          }),
        });
        let data = null;
        try {
          data = await resp.json();
        } catch {
          data = null;
        }
        if (resp.ok && data && data.ok === true) {
          this.struggleMarked = true;
          this.struggleError = '';
        } else {
          this.struggleError = `Failed to mark struggle (${resp.status})`;
        }
      } catch {
        this.struggleError = 'Network error — could not mark struggle';
      }
    },

    async discussLesson() {
      this.openCompanion();
      await this.copyCompanionPrompt();
    },

    _resetCompanion() {
      this.companionOpen = false;
      this.companionPrompt = '';
      this.companionAnswer = '';
      this.companionFollowup = '';
      this.companionCopied = false;
      this.companionEvidenceCopied = false;
    },

    openCompanion() {
      if (this.view !== 'reader' || !this.activeLesson || !this.readerText) return;
      this.companionOpen = true;
      this.companionPrompt = this.buildCompanionPrompt();
      this.companionFollowup = '';
      this.companionCopied = false;
      this.companionEvidenceCopied = false;
    },

    setCompanionMode(mode) {
      if (!Object.prototype.hasOwnProperty.call(COMPANION_MODE_INSTRUCTIONS, mode)) return;
      this.companionMode = mode;
      if (this.companionOpen) this.companionPrompt = this.buildCompanionPrompt();
    },

    companionModeLabel(mode) {
      return COMPANION_MODE_LABELS[mode] || mode;
    },

    buildCompanionPrompt() {
      if (!this.activeLesson || !this.readerText) return '';
      const lesson = this.activeLesson;
      const title = lesson.name || lesson.slug || 'this lesson';
      const excerpt = _mdToPlainText(this.readerText).slice(0, 3200);
      return [
        "You are StudyLoop's AuDHD-aware Socratic mentor.",
        `Lesson: ${title}`,
        `Mode: ${this.companionMode}`,
        '',
        COMPANION_MODE_INSTRUCTIONS[this.companionMode],
        'Use the lesson only as context. Ask one question at a time and keep the loop small.',
        '',
        excerpt,
        '',
        `End by suggesting: ${_lessonEvidenceCommand(lesson, title)}`,
      ].join('\n');
    },

    buildCompanionFollowup() {
      const answer = this.companionAnswer.trim();
      if (!answer) {
        this.companionFollowup = 'Try one rough answer first. A messy retrieval attempt is enough to create a useful next question.';
        return;
      }
      const title = this.activeLesson ? (this.activeLesson.name || this.activeLesson.slug) : 'this lesson';
      const opener = {
        recall: 'Now compare your answer against the note and name one missing detail.',
        diagram: 'Now identify one node or edge in your diagram that carries the most meaning.',
        trace: 'Now point to the exact step where state, data, or control changed.',
        teachback: 'Now rate the teach-back from 1-5 and repair the weakest sentence.',
        repair: 'Now rewrite the fragile part as one test, rule, or example.',
      }[this.companionMode] || 'Now make one small repair.';
      this.companionFollowup = [
        opener,
        '',
        `Lesson: ${title}`,
        'Your answer:',
        answer.slice(0, 1200),
        '',
        `Evidence command: ${this.companionEvidenceCommand()}`,
      ].join('\n');
    },

    companionEvidenceCommand() {
      if (!this.activeLesson) return 'studyloop progress "study" -t "study" -c learning';
      const title = this.activeLesson.name || this.activeLesson.slug || 'lesson';
      return _lessonEvidenceCommand(this.activeLesson, title);
    },

    async _copyText(text, onOk) {
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        onOk();
        this.discussionError = '';
      } catch {
        this.discussionError = 'Could not copy discussion prompt';
      }
    },

    async copyCompanionPrompt() {
      if (!this.companionPrompt) this.companionPrompt = this.buildCompanionPrompt();
      await this._copyText(this.companionPrompt, () => {
        this.discussionCopied = true;
        this.companionCopied = true;
      });
    },

    async copyCompanionEvidence() {
      await this._copyText(this.companionEvidenceCommand(), () => {
        this.companionEvidenceCopied = true;
      });
    },

  };
}

/* ======================================================================
 * Mastery graph panel
 * ====================================================================== */
function _masteryMermaidId(name, used) {
  let ident = String(name || 'concept').replace(/[^A-Za-z0-9_]/g, '_').replace(/^_+|_+$/g, '') || 'concept';
  if (/^\d/.test(ident)) ident = `concept_${ident}`;
  let unique = ident;
  let suffix = 2;
  while (used.has(unique)) {
    unique = `${ident}_${suffix}`;
    suffix += 1;
  }
  used.add(unique);
  return unique;
}

function _masteryMermaidLabel(name) {
  return String(name || '')
    .replace(/"/g, "'")
    .replace(/`/g, "'")
    .replace(/\[/g, '(')
    .replace(/\]/g, ')')
    .replace(/\n/g, ' ');
}

function _masteryMermaidFromGraph(graph) {
  const topic = graph && graph.topic ? graph.topic : 'topic';
  const edges = graph && Array.isArray(graph.edges) ? graph.edges : [];
  if (!edges.length) return `flowchart LR\n  empty["No mastery edges found for ${_masteryMermaidLabel(topic)} yet"]`;

  const nodes = graph && Array.isArray(graph.nodes) ? graph.nodes : [];
  const used = new Set();
  const ids = {};
  const lines = ['flowchart LR'];

  /* Colour comes from the API, not from CSS on the rendered SVG.
   *
   * `mastery.py` also builds a coloured diagram server-side, but the browser has
   * never used it: this function assembles the source from the JSON graph, so
   * the server's classDef lines were unreachable from the UI. Rather than switch
   * the panel to `format=mermaid` — which would discard the node/edge data the
   * counters and weak-link list read — emit the same directives here from
   * `node_categories` and `legend`, which the JSON response already carries.
   * One source of colour, one legend, and they cannot disagree. */
  const legend = graph && Array.isArray(graph.legend) ? graph.legend : [];
  const nodeCats = (graph && graph.node_categories) || {};
  const nodeLegend = legend.filter((c) => c.kind === 'node');
  const edgeLegend = legend.filter((c) => c.kind !== 'node');
  const byKey = {};
  legend.forEach((c) => {
    byKey[c.key] = c;
  });

  nodes.forEach((node) => {
    const id = _masteryMermaidId(node, used);
    ids[node] = id;
    lines.push(`  ${id}["${_masteryMermaidLabel(node)}"]`);
  });

  // One classDef per node category actually present, then the assignments.
  const grouped = {};
  nodes.forEach((node) => {
    const key = nodeCats[node];
    if (!key || !byKey[key] || !ids[node]) return;
    (grouped[key] = grouped[key] || []).push(ids[node]);
  });
  nodeLegend.forEach((cat) => {
    if (!grouped[cat.key]) return;
    const styles = [`fill:${cat.colour}`, `stroke:${cat.border_colour || cat.colour}`, 'color:#fff'];
    if (cat.dashed) styles.push('stroke-dasharray:4 3');
    lines.push(`  classDef sl_${cat.key} ${styles.join(',')};`);
    lines.push(`  class ${grouped[cat.key].join(',')} sl_${cat.key};`);
  });

  // Edge styling is positional in mermaid, so track the emitted index.
  const edgeIndexByKey = {};
  let edgeIndex = 0;
  edges.forEach((edge) => {
    if (!ids[edge.source_concept] || !ids[edge.target_concept]) return;
    lines.push(
      `  ${ids[edge.source_concept]} -->|"${_masteryMermaidLabel(edge.relation_type)}"| ${ids[edge.target_concept]}`
    );
    const match = edgeLegend.find((c) => c.key === edge.relation_type) ||
      edgeLegend.find((c) => c.key === 'other');
    if (match) (edgeIndexByKey[match.key] = edgeIndexByKey[match.key] || []).push(edgeIndex);
    edgeIndex += 1;
  });
  Object.keys(edgeIndexByKey).forEach((key) => {
    const cat = byKey[key];
    if (!cat) return;
    lines.push(
      `  linkStyle ${edgeIndexByKey[key].join(',')} stroke:${cat.colour},stroke-width:2px;`
    );
  });

  return lines.join('\n');
}

function masteryPanel() {
  return {
    topic: localStorage.getItem('masteryTopic') || 'python',
    loading: false,
    error: '',
    graph: null,
    weakLinks: [],
    /* Legend categories as DATA from /api/mastery/graph — [{label, colour,
       meaning}]. Never hardcode the categories here or in the markup: the
       colours come from the server-side generator, so a local copy becomes a
       lie the moment the palette changes. Empty until the API supplies them,
       which keeps the panel usable against an older response. */
    legend: [],
    mermaidSource: '',
    copyStatus: '',
    graphLimit: 80,
    weakLinkTotal: 0,
    hasLoaded: false,

    maybeLoad() {
      if (this.hasLoaded || this.loading) return;
      this.load();
    },

    async load() {
      const topic = this.topic.trim();
      if (!topic) return;
      this.hasLoaded = true;
      localStorage.setItem('masteryTopic', topic);
      this.loading = true;
      this.error = '';
      this.graph = null;
      this.weakLinks = [];
      this.legend = [];
      this.mermaidSource = '';
      this.copyStatus = '';
      this.weakLinkTotal = 0;
      try {
        const qs = new URLSearchParams({ topic, limit: String(this.graphLimit) });
        const graphResp = await fetch('/api/mastery/graph?' + qs.toString());
        if (!graphResp.ok) {
          this.error = 'Could not load mastery graph';
          return;
        }
        this.graph = await graphResp.json();
        /* `legend` is the field name coded against; `legend_categories` is
           accepted as an alias so a naming difference in the generator degrades
           to an absent legend rather than a broken panel. */
        this.legend = this.graph.legend || this.graph.legend_categories || [];
        this.mermaidSource = _masteryMermaidFromGraph(this.graph);
        this.loading = false;
        await this.$nextTick();
        await this.renderGraph();
        this.loadWeakLinks(topic);
      } catch (err) {
        this.error = 'Network error loading mastery graph';
        console.error('[Mastery] load error:', err);
      } finally {
        this.loading = false;
      }
    },

    async loadWeakLinks(topic) {
      try {
        const weakQs = new URLSearchParams({ topic, limit: '12' });
        const weakResp = await fetch('/api/mastery/weak-links?' + weakQs.toString());
        if (!weakResp.ok) return;
        const weak = await weakResp.json();
        this.weakLinks = weak.weak_links || [];
        this.weakLinkTotal = weak.weak_link_count_total || this.weakLinks.length;
      } catch {
        // Keep the graph usable; weak links are advisory and can be refreshed.
      }
    },

    async renderGraph() {
      const el = this.$refs.graphCanvas;
      if (!el || !this.mermaidSource) return;
      if (!window.mermaid) {
        el.textContent = this.mermaidSource;
        return;
      }
      try {
        const id = 'mastery-graph-' + Date.now();
        el.innerHTML = await _renderMermaidScoped(id, this.mermaidSource, el);
      } catch (err) {
        console.warn('[Mastery] mermaid.render failed:', err);
        el.textContent = this.mermaidSource;
      }
    },

    get nodeCount() {
      return this.graph && this.graph.nodes ? this.graph.nodes.length : 0;
    },

    get edgeCount() {
      return this.graph && this.graph.edges ? this.graph.edges.length : 0;
    },

    get edgeCountTotal() {
      return this.graph && this.graph.edge_count_total ? this.graph.edge_count_total : this.edgeCount;
    },

    get graphLimited() {
      return Boolean(this.graph && this.graph.limited);
    },

    get weakLinksLimited() {
      return this.weakLinkTotal > this.weakLinks.length;
    },

    async copyMermaid() {
      if (!this.mermaidSource) return;
      try {
        await navigator.clipboard.writeText(this.mermaidSource);
        this.copyStatus = 'Copied';
      } catch {
        this.copyStatus = 'Copy unavailable';
      }
    },
  };
}

/* ------------------------------------------------------------------
 * Today panel — "one next action" landing view (AuDHD-first).
 *
 * Fetches all four sources in parallel and renders exactly ONE primary
 * recommendation (from the shared decision engine via /api/now), a
 * context-aware resume shortcut, and parked-topic pickup chips.
 * Resume precedence: live session (rejoin) > last study session
 * (start-again-same-topic) > last review deck.
 * ------------------------------------------------------------------ */
function todayPanel() {
  return {
    loading: true,
    plan: null,          // /api/now NowPlan
    parked: [],          // /api/backlog parking_lot
    resumeKind: null,    // 'rejoin' | 'session' | 'deck' | null
    resumeLabel: '',
    _resumePayload: null,
    showAlternates: false,

    async init() {
      const get = (url) => fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      const [plan, backlog, state, last, history] = await Promise.all([
        get('/api/now'),
        get('/api/backlog'),
        get('/api/session/state'),
        get('/api/session/last'),
        get('/api/history'),
      ]);

      this.plan = plan;
      this.parked = (backlog && backlog.parking_lot) || [];

      if (state && state.study_session_id && state.mode !== 'ended') {
        this.resumeKind = 'rejoin';
        this.resumeLabel = state.topic_config_name || state.topic || 'active session';
      } else if (last && last.topic) {
        this.resumeKind = 'session';
        this.resumeLabel = last.topic;
        this._resumePayload = last;
      } else if (Array.isArray(history) && history.length > 0) {
        this.resumeKind = 'deck';
        this.resumeLabel = history[0].course;
      }

      this.loading = false;
    },

    resumeAction() {
      if (this.resumeKind === 'rejoin') {
        Alpine.store('nav').go('study-session');
      } else if (this.resumeKind === 'session') {
        // Hand the topic to the study-session picker (start-again-same-topic).
        // sessionTimer.init() already ran at page load, so this is an event.
        window.dispatchEvent(new CustomEvent('today-resume', {
          detail: {
            topic: this._resumePayload.topic,
            energy: this._resumePayload.energy_level || null,
          },
        }));
        Alpine.store('nav').go('study-session');
      } else if (this.resumeKind === 'deck') {
        Alpine.store('nav').go('flashcards');
      }
    },

    // Map the decision engine's action_type to the view that hosts it.
    _viewFor(actionType) {
      const map = {
        review: 'flashcards',
        recall: 'flashcards',
        quiz: 'quizzes',
        conversation: 'study-session',
        teach_back: 'study-session',
        generate: 'generate',
        'hands-on': 'study-session',
      };
      return map[actionType] || 'flashcards';
    },

    startPrimary() {
      if (this.plan && this.plan.primary) this.startAction(this.plan.primary);
    },

    startAction(rec) {
      Alpine.store('nav').go(this._viewFor(rec.action_type));
    },

    pickUpParked(p) {
      window.dispatchEvent(new CustomEvent('today-resume', {
        detail: { topic: p.question, energy: null },
      }));
      Alpine.store('nav').go('study-session');
    },

    async dismissParked(p) {
      const idx = this.parked.indexOf(p);
      if (idx !== -1) this.parked.splice(idx, 1);
      try {
        const res = await fetch('/api/backlog/dismiss', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: p.id }),
        });
        if (!res.ok) {
          this.parked.splice(idx, 0, p);
          Alpine.store('toast').show('Could not dismiss — try again');
        }
      } catch {
        this.parked.splice(idx, 0, p);
        Alpine.store('toast').show('Could not dismiss — offline?');
      }
    },
  };
}

/* ====================================================================
 * Parking Lot + Notes panels (3rd-column side panels).
 *
 * Both mirror the courseExplorer() pattern: a boot-stub store
 * (Alpine.store('parking') / 'notes') drives the sidebar toggle button,
 * and the component wires its real toggle()/close() onto the store in
 * init() (lazy-fetch + layout class). Only one 3rd-column panel is open
 * at a time — opening one closes the siblings.
 * ==================================================================== */

/**
 * Re-initialise mermaid so diagrams follow the ACTIVE palette rather than a
 * hardcoded theme. Reads the live CSS custom properties off <body> and feeds
 * them to mermaid's `base` theme, so a light palette produces a light diagram.
 * Called immediately before each mermaid render pass in the parking preview.
 */
function _mermaidInitForPalette() {
  if (!window.mermaid) return;
  const cs = getComputedStyle(document.body);
  const v = (name, fallback) => (cs.getPropertyValue(name).trim() || fallback);
  const bg = v('--bg', '#1a1b26');
  const surface = v('--bg-card', '#24283b');
  const surfaceAlt = v('--bg-hover', surface);
  const text = v('--text', '#c0caf5');
  const accent = v('--accent', '#7aa2f7');
  const border = v('--border', '#3b4261');
  const muted = v('--text-muted', '#565f89');
  try {
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      /* Rich-text hardening deliberately removes foreignObject because it can
         embed an HTML subtree. Native SVG labels survive that boundary and
         keep every flowchart readable after sanitisation. */
      htmlLabels: false,
      flowchart: { htmlLabels: false },
      theme: 'base',
      themeVariables: {
        darkMode: false,
        background: bg,
        primaryColor: surface,
        mainBkg: surface,
        secondaryColor: surfaceAlt,
        tertiaryColor: surfaceAlt,
        primaryBorderColor: accent,
        nodeBorder: accent,
        clusterBkg: surfaceAlt,
        clusterBorder: border,
        primaryTextColor: text,
        nodeTextColor: text,
        textColor: text,
        lineColor: muted,
        edgeLabelBackground: bg,
      },
    });
  } catch (err) {
    console.warn('[parking] mermaid re-init failed:', err);
  }
}

/* Fallback diagram source if the server template is unavailable. Guarantees
   the one-click "Insert diagram" always drops a real ```mermaid fence. */
const _PARKING_FALLBACK_DIAGRAM =
  '```mermaid\ngraph TD\n    A[Start] --> B[Next step]\n```\n';

function parkingPanel() {
  return {
    columns: [],
    diagramTemplate: '',
    loadError: '',

    // editor state (single open editor — #parking-note-input is a unique id)
    editingId: null,
    titleText: '',
    noteText: '',
    areaText: '',
    priorityVal: '',
    showPreview: false,
    previewHtml: '',
    saveState: 'Save',

    // selection + bulk state
    selectMode: false,
    selectedIds: [],
    undoBuffer: [],

    // column admin
    manageColumns: false,
    newColumnName: '',

    // drag state
    dragOverColumn: null,
    _justDragged: false,

    init() {
      const self = this;
      const store = Alpine.store('parking');
      store.toggle = () => self.toggle();
      store.close = () => self.close();
      window.addEventListener('parking:changed', () => {
        if (Alpine.store('parking').open) self.refresh();
      });
      window.addEventListener('studyloop:theme-change', () => {
        if (self.showPreview && self.editingId != null) self.renderPreview();
      });
    },

    async toggle() {
      const store = Alpine.store('parking');
      store.open = !store.open;
      const layout = document.querySelector('.app-layout');
      if (store.open) {
        try { Alpine.store('explorer').close(); } catch { /* stub */ }
        try { Alpine.store('notes').close(); } catch { /* stub */ }
        if (layout) layout.classList.add('parking-open');
        await this.refresh();
      } else if (layout) {
        layout.classList.remove('parking-open');
      }
    },

    close() {
      const store = Alpine.store('parking');
      store.open = false;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.remove('parking-open');
    },

    async refresh() {
      try {
        const res = await fetch('/api/parking/board');
        if (res.ok) {
          const data = await res.json();
          this.columns = data.columns || [];
          this.diagramTemplate = data.diagram_template || '';
          this.loadError = '';
        } else {
          this.loadError = `Could not load parking lot (${res.status})`;
        }
      } catch {
        this.loadError = 'Network error loading parking lot';
      }
    },

    // ---- derived ----
    allItems() {
      return this.columns.flatMap((c) => c.items || []);
    },
    totalCount() {
      return this.allItems().length;
    },
    totalLabel() {
      const n = this.totalCount();
      return `${n} item${n === 1 ? '' : 's'}`;
    },
    selectedCountLabel() {
      const n = this.selectedIds.length;
      return n === 0 ? 'None selected' : `${n} selected`;
    },

    // ---- selection ----
    isSelected(id) {
      return this.selectedIds.includes(id);
    },
    toggleSelect(id) {
      if (this.selectedIds.includes(id)) {
        this.selectedIds = this.selectedIds.filter((x) => x !== id);
      } else {
        this.selectedIds = [...this.selectedIds, id];
      }
    },
    selectAll() {
      this.selectedIds = this.allItems().map((i) => i.id);
    },
    selectNone() {
      this.selectedIds = [];
    },
    selectColumn(colKey) {
      const col = this.columns.find((c) => c.key === colKey);
      if (!col) return;
      const set = new Set(this.selectedIds);
      (col.items || []).forEach((i) => set.add(i.id));
      this.selectedIds = [...set];
    },

    // ---- editor ----
    openEditor(item) {
      this.editingId = item.id;
      this.titleText = item.question || '';
      this.noteText = item.notes || '';
      this.areaText = item.tech_area || '';
      this.priorityVal = item.priority ? String(item.priority) : '';
      this.showPreview = false;
      this.previewHtml = '';
      this.saveState = 'Save';
    },
    closeEditor() {
      const wasEditing = this.editingId;
      this.editingId = null;
      this.showPreview = false;
      this.previewHtml = '';
      /* Put focus back on the card. Closing the editor makes Alpine rebuild the
         card's contents, and the browser drops focus to <body> when the focused
         node goes away — so a keyboard user who pressed Escape loses their place
         entirely and the next arrow key does nothing. Restoring it keeps the
         board navigable without a pointer, which for this audience is the
         difference between usable and not. */
      if (wasEditing == null) return;
      requestAnimationFrame(() => {
        /* $root can be undefined by the time this frame runs — the component may
           have been torn down (a reload, or the panel closing). Reading through
           it unguarded throws an uncaught pageerror, which the journey's
           clean-console assertion catches. */
        const root = this.$root || document;
        const el = root.querySelector(`.parking-card[data-id="${wasEditing}"]`);
        if (el && typeof el.focus === 'function') el.focus();
      });
    },
    onTitleClick(item) {
      if (this._justDragged) { this._justDragged = false; return; }
      if (this.selectMode) { this.toggleSelect(item.id); return; }
      this.openEditor(item);
    },
    onCardKey(item, ev) {
      if (ev.key === 'ArrowRight') { ev.preventDefault(); this.moveByOffset(item, 1); }
      else if (ev.key === 'ArrowLeft') { ev.preventDefault(); this.moveByOffset(item, -1); }
      else if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
        ev.preventDefault();
        if (this.selectMode) this.toggleSelect(item.id);
        else this.openEditor(item);
      } else if (ev.key === 'Escape') {
        /* The panel also listens for Escape on window. Without stopping this
           event, one keypress closes the editor and then the whole panel. */
        ev.stopPropagation();
        this.closeEditor();
      }
    },

    insertDiagram() {
      let tpl = this.diagramTemplate || '';
      if (!tpl.includes('```mermaid')) tpl = _PARKING_FALLBACK_DIAGRAM;
      this.noteText = this.noteText
        ? this.noteText.replace(/\s*$/, '') + '\n\n' + tpl
        : tpl;
    },

    togglePreview() {
      this.showPreview = !this.showPreview;
      if (this.showPreview) this.renderPreview();
    },

    async renderPreview() {
      /* Clear first, and let the effect flush, before writing the same HTML
         again. Without this a re-render is a no-op: renderMarkdown() is pure, so
         a palette switch reassigns previewHtml to a byte-identical string,
         Alpine's x-html effect sees no change and never rewrites the DOM, the
         already-rendered placeholder keeps its old SVG and no longer carries
         data-src — so _renderMermaidPlaceholders finds nothing to do and the
         diagram silently keeps the previous palette's colours. The e2e test
         catches this precisely: identical SVG, same mermaid-render-<ts> id. */
      if (this.previewHtml) {
        this.previewHtml = '';
        await this.$nextTick();
      }
      this.previewHtml = renderMarkdown(this.noteText || '');
      /* Two ticks so Alpine's x-html effect writes the DOM before we query the
         mermaid placeholders (same pattern as courseExplorer's reader). */
      await this.$nextTick();
      await this.$nextTick();
      _mermaidInitForPalette();
      /* $root, NOT $el. Alpine resolves $el against the EVALUATION SCOPE, and
         this method is reached synchronously from @click="togglePreview()" on
         the Preview button — so $el here is that button, whose subtree contains
         no preview and therefore no placeholders. The pass found nothing,
         returned, and left the diagram unrendered with its data-src intact: no
         throw, no console output, nothing to see. $root is the component root
         and is scope-stable. */
      await _renderMermaidPlaceholders(this.$root || document);
    },

    _replaceItem(item) {
      for (const c of this.columns) {
        const idx = (c.items || []).findIndex((i) => i.id === item.id);
        if (idx !== -1) { c.items.splice(idx, 1, { ...c.items[idx], ...item }); return; }
      }
    },

    async save() {
      if (this.editingId == null) return;
      this.saveState = 'Saving';
      const body = { question: this.titleText, notes: this.noteText };
      if (this.areaText) body.tech_area = this.areaText;
      if (this.priorityVal) body.priority = parseInt(this.priorityVal, 10);
      try {
        const res = await fetch(`/api/parking/item/${this.editingId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (res.ok) {
          const data = await res.json();
          const item = data.item || {};
          this._replaceItem(item);
          if (typeof item.notes === 'string') this.noteText = item.notes;
          this.saveState = 'Saved';
          this.showPreview = true;
          await this.renderPreview();
        } else {
          this.saveState = 'Save';
          Alpine.store('toast').show('Could not save — try again');
        }
      } catch {
        this.saveState = 'Save';
        Alpine.store('toast').show('Could not save — offline?');
      }
    },

    // ---- clearing ----
    async _clear(ids) {
      if (!ids.length) return;
      try {
        const res = await fetch('/api/parking/clear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids }),
        });
        if (res.ok) {
          this.undoBuffer = ids.slice();
          this.selectedIds = [];
          if (this.editingId != null && ids.includes(this.editingId)) this.closeEditor();
          await this.refresh();
        } else {
          Alpine.store('toast').show('Could not clear — try again');
        }
      } catch {
        Alpine.store('toast').show('Could not clear — offline?');
      }
    },
    clearOne(id) { return this._clear([id]); },
    clearSelected() { return this._clear(this.selectedIds.slice()); },
    clearAll() { return this._clear(this.allItems().map((i) => i.id)); },

    async undoClear() {
      if (!this.undoBuffer.length) return;
      try {
        const res = await fetch('/api/parking/restore', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: this.undoBuffer }),
        });
        if (res.ok) { this.undoBuffer = []; await this.refresh(); }
      } catch {
        Alpine.store('toast').show('Could not undo — offline?');
      }
    },

    // ---- kanban move (keyboard + drag) ----
    moveByOffset(item, delta) {
      const idx = this.columns.findIndex((c) => (c.items || []).some((i) => i.id === item.id));
      if (idx === -1) return;
      const target = this.columns[idx + delta];
      if (!target) return;
      this.moveItem(item.id, target.key);
    },
    async moveItem(id, colKey) {
      let moved = null;
      for (const c of this.columns) {
        const idx = (c.items || []).findIndex((i) => i.id === id);
        if (idx !== -1) { moved = c.items.splice(idx, 1)[0]; break; }
      }
      if (!moved) return;
      moved.board_column = colKey;
      const target = this.columns.find((c) => c.key === colKey);
      if (target) (target.items = target.items || []).push(moved);
      try {
        await fetch(`/api/parking/item/${id}/move`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ board_column: colKey }),
        });
      } catch {
        await this.refresh();
      }
    },

    startDrag(item, ev) {
      /* Ignore presses that begin on an interactive control or inside the
         editor — only the card body/title initiates a drag. */
      if (ev.target.closest(
        '.parking-card-check-label, .parking-card-clear, .parking-card-editor, ' +
        'button, input, textarea, select, a'
      )) return;
      if (ev.button && ev.button !== 0) return;

      const startX = ev.clientX;
      const startY = ev.clientY;
      const startCol = this._columnKeyForItem(item.id);
      const self = this;
      let dragging = false;
      let maxTravel = 0;

      const onMove = (e) => {
        const dist = Math.hypot(e.clientX - startX, e.clientY - startY);
        if (dist > maxTravel) maxTravel = dist;
        if (!dragging && dist > 6) dragging = true;   // 6px drag threshold
        if (dragging) {
          const el = document.elementFromPoint(e.clientX, e.clientY);
          const col = el && el.closest ? el.closest('.parking-column') : null;
          self.dragOverColumn = col ? col.dataset.column : null;
        }
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        const dropCol = self.dragOverColumn;
        self.dragOverColumn = null;
        if (dragging && dropCol && dropCol !== startCol) {
          /* A committed move to a different column: perform it and swallow the
             trailing click so the editor does not pop open. */
          self._justDragged = true;
          self.moveItem(item.id, dropCol);
        } else if (dragging && maxTravel >= 24) {
          /* An unambiguous drag that was reconsidered (dropped back in place):
             still swallow the click. A small drift (< 24px) is treated as a
             plain click so near-unselectable cards open on tap. */
          self._justDragged = true;
        }
        /* Safety net: clear the swallow flag shortly after, in case no click
           follows (e.g. the drop landed on a column gutter, not a title). */
        if (self._justDragged) {
          setTimeout(() => { self._justDragged = false; }, 120);
        }
      };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
    },

    _columnKeyForItem(id) {
      const col = this.columns.find((c) => (c.items || []).some((i) => i.id === id));
      return col ? col.key : null;
    },

    // ---- column admin ----
    async addColumn() {
      const name = (this.newColumnName || '').trim();
      if (!name) return;
      try {
        const res = await fetch('/api/parking/columns', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
        if (res.ok) { this.newColumnName = ''; await this.refresh(); }
        else Alpine.store('toast').show('Could not add column');
      } catch {
        Alpine.store('toast').show('Could not add column — offline?');
      }
    },
    async renameColumn(key, name) {
      const clean = (name || '').trim();
      if (!clean) return;
      try {
        const res = await fetch(`/api/parking/columns/${encodeURIComponent(key)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: clean }),
        });
        if (res.ok) await this.refresh();
      } catch {
        Alpine.store('toast').show('Could not rename column — offline?');
      }
    },
    async removeColumn(key) {
      try {
        const res = await fetch(`/api/parking/columns/${encodeURIComponent(key)}`, {
          method: 'DELETE',
        });
        if (res.ok) await this.refresh();
        else Alpine.store('toast').show('Could not remove column');
      } catch {
        Alpine.store('toast').show('Could not remove column — offline?');
      }
    },
  };
}

function notesPanel() {
  return {
    notes: [],
    loadError: '',

    editingId: null,
    titleText: '',
    bodyText: '',
    saveState: 'Save',

    selectMode: false,
    selectedIds: [],
    undoBuffer: [],

    /* Kind filter. #notes-total-count tracks the SELECTION, not the library:
       "1 note" under a `plan` filter is the honest answer to "how many of these
       am I looking at", and a count that ignores the filter makes the filter
       look broken. */
    kindFilter: '',
    exportOpen: false,
    exportText: '',
    /* Which face of an open note is showing. 'rendered' is the default because a
       saved note is read far more often than rewritten, and opening straight
       into a raw textarea hides the diagrams it was written for. */
    expandedTab: 'rendered',
    renderedHtml: '',

    init() {
      const self = this;
      const store = Alpine.store('notes');
      store.toggle = () => self.toggle();
      store.close = () => self.close();
      window.addEventListener('notes:changed', () => {
        if (Alpine.store('notes').open) self.refresh();
      });
    },

    async toggle() {
      const store = Alpine.store('notes');
      store.open = !store.open;
      const layout = document.querySelector('.app-layout');
      if (store.open) {
        try { Alpine.store('explorer').close(); } catch { /* stub */ }
        try { Alpine.store('parking').close(); } catch { /* stub */ }
        if (layout) layout.classList.add('notes-open');
        await this.refresh();
      } else if (layout) {
        layout.classList.remove('notes-open');
      }
    },

    close() {
      const store = Alpine.store('notes');
      store.open = false;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.remove('notes-open');
    },

    async refresh() {
      try {
        const res = await fetch('/api/notes');
        if (res.ok) {
          const data = await res.json();
          this.notes = data.notes || [];
          this.loadError = '';
        } else {
          this.loadError = `Could not load notes (${res.status})`;
        }
      } catch {
        this.loadError = 'Network error loading notes';
      }
    },

    filteredNotes() {
      if (!this.kindFilter) return this.notes;
      return this.notes.filter((n) => n.kind === this.kindFilter);
    },
    totalLabel() {
      const n = this.filteredNotes().length;
      return `${n} note${n === 1 ? '' : 's'}`;
    },
    async toggleExport() {
      this.exportOpen = !this.exportOpen;
      if (!this.exportOpen) return;
      try {
        const res = await fetch('/api/notes/markdown');
        this.exportText = res.ok ? await res.text() : 'Could not load the export.';
      } catch {
        this.exportText = 'Could not load the export — offline?';
      }
    },
    selectedCountLabel() {
      const n = this.selectedIds.length;
      return n === 0 ? 'None selected' : `${n} selected`;
    },

    isSelected(id) { return this.selectedIds.includes(id); },
    toggleSelect(id) {
      if (this.selectedIds.includes(id)) {
        this.selectedIds = this.selectedIds.filter((x) => x !== id);
      } else {
        this.selectedIds = [...this.selectedIds, id];
      }
    },
    selectAll() { this.selectedIds = this.notes.map((n) => n.id); },
    selectNone() { this.selectedIds = []; },

    openEditor(note) {
      this.editingId = note.id;
      this.titleText = note.title || '';
      this.bodyText = note.body || '';
      this.saveState = 'Save';
      this.expandedTab = 'rendered';
      this.renderCard(note);
    },
    closeEditor() { this.editingId = null; },

    async showRendered(note) {
      this.expandedTab = 'rendered';
      await this.renderCard(note);
    },

    async renderCard(note) {
      /* Render from the CURRENT buffer when this note is the one open, so the
         reading tab shows what is about to be saved rather than a stale copy. */
      const src = (this.editingId === note.id ? this.bodyText : note.body) || '';
      this.renderedHtml = '';
      await this.$nextTick();
      this.renderedHtml = renderMarkdown(src);
      await this.$nextTick();
      await this.$nextTick();
      _mermaidInitForPalette();
      /* $root, not $el — $el resolves to the element the calling expression sits
         on (a tab button), whose subtree holds no placeholders. See 11f7862. */
      await _renderMermaidPlaceholders(this.$root || document);
    },

    insertNoteDiagram() {
      const tpl = '```mermaid\nflowchart TD\n  A[Start] --> B[Next]\n```';
      this.bodyText = (this.bodyText || '').replace(/\s+$/, '') + '\n\n' + tpl;
    },
    onTitleClick(note) {
      if (this.selectMode) { this.toggleSelect(note.id); return; }
      this.openEditor(note);
    },
    onCardKey(note, ev) {
      if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
        ev.preventDefault();
        if (this.selectMode) this.toggleSelect(note.id);
        else this.openEditor(note);
      } else if (ev.key === 'Escape') {
        this.closeEditor();
      }
    },

    async save() {
      if (this.editingId == null) return;
      this.saveState = 'Saving';
      try {
        const res = await fetch(`/api/notes/${this.editingId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: this.titleText, body: this.bodyText }),
        });
        if (res.ok) {
          const data = await res.json();
          const note = data.note || {};
          const idx = this.notes.findIndex((n) => n.id === note.id);
          if (idx !== -1) this.notes.splice(idx, 1, { ...this.notes[idx], ...note });
          /* Adopt the SERVER's body. normalise_markdown is the single hygiene
             gate, so what was typed and what was stored can differ (fences,
             trailing whitespace). Leaving the textarea showing the typed version
             makes the next edit silently re-submit unnormalised text. */
          if (note.body !== undefined) this.bodyText = note.body;
          this.saveState = 'Saved';
        } else {
          this.saveState = 'Save';
          Alpine.store('toast').show('Could not save — try again');
        }
      } catch {
        this.saveState = 'Save';
        Alpine.store('toast').show('Could not save — offline?');
      }
    },

    async _clear(ids) {
      if (!ids.length) return;
      try {
        const res = await fetch('/api/notes/clear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids }),
        });
        if (res.ok) {
          this.undoBuffer = ids.slice();
          this.selectedIds = [];
          if (this.editingId != null && ids.includes(this.editingId)) this.closeEditor();
          await this.refresh();
        } else {
          Alpine.store('toast').show('Could not delete — try again');
        }
      } catch {
        Alpine.store('toast').show('Could not delete — offline?');
      }
    },
    clearOne(id) { return this._clear([id]); },
    clearSelected() { return this._clear(this.selectedIds.slice()); },
    clearAll() { return this._clear(this.notes.map((n) => n.id)); },

    async undoClear() {
      if (!this.undoBuffer.length) return;
      try {
        const res = await fetch('/api/notes/restore', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: this.undoBuffer }),
        });
        if (res.ok) { this.undoBuffer = []; await this.refresh(); }
      } catch {
        Alpine.store('toast').show('Could not undo — offline?');
      }
    },
  };
}

/* ====================================================================
 * bodyDoubleSession() — the Body Double workspace.
 *
 * Owns its own session lifecycle (origin 'body-double', ADR-0002) so the
 * Study Session picker and this view can each run a session without the
 * other's console reacting. Capture (note/park) lives here rather than in a
 * separate view on purpose: the whole point is to record a tangent WITHOUT
 * leaving the session, because leaving is what loses the thread.
 *
 * Named bodyDoubleSession() rather than bodyDoubleView() because the session
 * recovery spec addresses this component by its x-data attribute string
 * (`[x-data="bodyDoubleSession()"]`). bodyDoubleView() survives below as a
 * delegating alias, so the rename cannot half-land while the markup catches up.
 * ==================================================================== */
function bodyDoubleSession() {
  return {
    slots: [], slotsUsed: 0, maxActive: 3, atCapacity: false, parkingLotCount: 0,
    focus: { topics: [], is_set: false, is_stale: false },
    focusCollapsed: false, captureCollapsed: false, captureTab: 'note',
    activity: '', agent: '', transport: 'pty', energy: 5, agents: [],
    sessionActive: false, liveActivity: '', confirmingEnd: false,
    starting: false, startError: '',
    /* ---- origin-aware session recovery --------------------------------
     * There is ONE session slot. When the Study Session view holds it, this
     * view will not adopt the session (ADR-0002's origin guard exists so two
     * consoles never attach to one PTY) — so it rendered its picker, and that
     * picker's Start could only ever 409. conflictSession is the live session
     * that blocks us, normalised by _conflictShape(); conflictOwnerLabel and
     * conflictIsOwn are DERIVED from it (getters, below) so clearing it can
     * never leave a stale owner label or a stale "reattach is safe" flag.
     * ------------------------------------------------------------------ */
    studySessionId: null,
    conflictSession: null,
    /* Monotonic staleness guard, mirroring reviewApp's _liveSessionEpoch:
       bumped on every end/reattach so a conflict probe still in flight cannot
       write its now-stale "someone else is live" answer over fresher state.
       Initialised on purpose — `undefined + 1` is NaN, and a NaN !== NaN
       comparison would then work only by accident. */
    _conflictEpoch: 0,
    /* True once init() has finished ALL its async work. The only honest ready
       signal for tests: the conflict probe settles after the focus and options
       loads, so nothing else marks the end of init(). */
    _initDone: false,
    noteKind: 'note', noteTopic: '', noteTitle: '', noteBody: '',
    noteConfidence: '', showPreview: false, previewHtml: '', noteSaved: false,
    templates: {}, diagramTemplate: '',
    parkQuestion: '', parkNotes: '', parkSaved: false,
    _savedTimer: null, _parkTimer: null,

    /* 'Study Session' | 'Body Double' — the surface that OWNS the live session.
       An absent origin means 'study' (the server's documented default, applied
       with setdefault), so absent and 'study' must read identically here. */
    get conflictOwnerLabel() {
      const origin = (this.conflictSession && this.conflictSession.origin) || 'study';
      return origin === 'body-double' ? 'Body Double' : 'Study Session';
    },
    /* True only when the blocking session is THIS view's own. Reattach is gated
       on it: adopting a foreign-origin session here is exactly what the origin
       guard exists to prevent. */
    get conflictIsOwn() {
      const origin = (this.conflictSession && this.conflictSession.origin) || 'study';
      return origin === 'body-double';
    },

    async init() {
      /* Registered BEFORE any await, deliberately. A stop dispatched while the
         awaits below are in flight would otherwise hit no listener at all and
         be lost permanently, leaving a recovery banner up for a session that
         has already ended — the same ordering bug fixed in reviewApp.init(). */
      window.addEventListener('study-session-stop', (event) => {
        const origin = (event.detail && event.detail.origin) || 'study';
        /* Bump BEFORE clearing: a probe already in flight captured the old
           epoch and must not restore the banner it saw a moment ago. */
        this._conflictEpoch += 1;
        const conflict = this.conflictSession;
        if (conflict && (conflict.origin || 'study') === origin) {
          this.conflictSession = null;
          this.startError = '';
        }
      });
      this.focusCollapsed = localStorage.getItem('bd.focus.collapsed') === 'true';
      this.captureCollapsed = localStorage.getItem('bd.capture.collapsed') === 'true';
      await this.refreshFocus();
      try {
        const res = await fetch('/api/session/options');
        if (res.ok) {
          const data = await res.json();
          this.agents = data.agents || [];
          /* Hydrate the renderer store from here too, so the transport labels
             are right even if the learner never opens the Study picker. */
          Alpine.store('terminalEngine').hydrate(data.terminal_engine);
        }
      } catch { /* labels fall back to the store's stock defaults */ }
      try {
        const res = await fetch('/api/notes?limit=1');
        if (res.ok) {
          const data = await res.json();
          this.templates = data.templates || {};
          this.diagramTemplate = data.diagram_template || '';
        }
      } catch { /* template button simply does nothing */ }
      /* A session already holding the slot must be announced BEFORE the learner
         presses Start, because Start can do nothing but 409 while it is held. */
      await this._checkLiveSessionConflict();
      /* Last line of init() on purpose — the only signal that every await
         above, the conflict probe included, has settled. */
      this._initDone = true;
    },

    async refreshFocus() {
      try {
        const res = await fetch('/api/body-double/focus');
        if (!res.ok) return;
        const d = await res.json();
        this.slots = d.slots || [];
        this.slotsUsed = d.slots_used ?? this.slots.length;
        this.maxActive = d.max_active ?? 3;
        this.atCapacity = !!d.at_capacity;
        this.parkingLotCount = d.parking_lot_count || 0;
        this.focus = d.focus || { topics: [], is_set: false, is_stale: false };
        /* Default the note topic to what the learner is actually doing. A note
           filed against the wrong topic is worse than an untagged one. */
        if (!this.noteTopic) {
          this.noteTopic = this.liveActivity || (this.slots[0] && this.slots[0].topic) || '';
        }
      } catch {
        Alpine.store('toast').show('Could not load focus — offline?');
      }
    },

    toggleFocus() {
      this.focusCollapsed = !this.focusCollapsed;
      localStorage.setItem('bd.focus.collapsed', String(this.focusCollapsed));
    },
    toggleCapture() {
      this.captureCollapsed = !this.captureCollapsed;
      localStorage.setItem('bd.capture.collapsed', String(this.captureCollapsed));
    },

    pickTopic(slot) { this.activity = slot.topic; },

    async dropTopic(topic) { await this._setFocus(this.focus.topics.filter((t) => t !== topic)); },
    async clearFocus() { await this._setFocus([]); },
    async _setFocus(topics) {
      try {
        const res = await fetch('/api/body-double/focus', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ topics }),
        });
        if (res.ok) await this.refreshFocus();
        else Alpine.store('toast').show('Could not update focus — try again');
      } catch {
        Alpine.store('toast').show('Could not update focus — offline?');
      }
    },

    applyTemplate() { this.noteBody = this.templates[this.noteKind] || ''; },

    insertDiagram() {
      const tpl = this.diagramTemplate || '```mermaid\nflowchart TD\n  A[Start] --> B[Next]\n```';
      this.noteBody = (this.noteBody || '').replace(/\s+$/, '') + '\n\n' + tpl;
      this.showPreview = true;
      this.renderPreview();
    },
    togglePreview() {
      this.showPreview = !this.showPreview;
      if (this.showPreview) this.renderPreview();
    },
    async renderPreview() {
      if (this.previewHtml) { this.previewHtml = ''; await this.$nextTick(); }
      this.previewHtml = renderMarkdown(this.noteBody || '');
      await this.$nextTick();
      await this.$nextTick();
      _mermaidInitForPalette();
      /* $root, NOT $el — $el resolves to whatever element the calling
         expression sits on (here the Preview button), whose subtree holds no
         placeholders. Same bug as the parking panel's, fixed in 11f7862. */
      await _renderMermaidPlaceholders(this.$root || document);
    },

    async saveNote() {
      const payload = {
        title: this.noteTitle, body: this.noteBody, kind: this.noteKind,
        topic: this.noteTopic, origin: 'body-double',
      };
      if (this.noteConfidence) payload.confidence = parseInt(this.noteConfidence, 10);
      try {
        const res = await fetch('/api/notes', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) { Alpine.store('toast').show('Could not save note — try again'); return; }
        this.noteSaved = true;
        if (this._savedTimer) clearTimeout(this._savedTimer);
        this._savedTimer = setTimeout(() => { this.noteSaved = false; }, 1500);
        window.dispatchEvent(new CustomEvent('notes:changed'));
      } catch {
        Alpine.store('toast').show('Could not save note — offline?');
      }
    },

    async submitPark() {
      try {
        const res = await fetch('/api/parking/item', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: this.parkQuestion, notes: this.parkNotes }),
        });
        if (!res.ok) { Alpine.store('toast').show('Could not park — try again'); return; }
        this.parkSaved = true;
        if (this._parkTimer) clearTimeout(this._parkTimer);
        this._parkTimer = setTimeout(() => { this.parkSaved = false; }, 1500);
        this.parkQuestion = '';
        this.parkNotes = '';
        await this.refreshFocus();
        window.dispatchEvent(new CustomEvent('parking:changed'));
      } catch {
        Alpine.store('toast').show('Could not park — offline?');
      }
    },

    async startSession() {
      this.starting = true;
      this.startError = '';
      try {
        const res = await fetch('/api/session/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            topic: this.activity, energy: this.energy, agent: this.agent,
            transport: this.transport, origin: 'body-double',
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (res.status === 409) {
            /* Not merely an error: another session holds the only slot. Turn the
               refusal into the levers that get the learner out of it — open the
               owning surface, end it, or (own origin only) reattach. */
            await this._raiseStartConflict(data);
            return;
          }
          this.startError = data.error || data.detail || `Could not start (${res.status})`;
          return;
        }
        this.sessionActive = true;
        this.studySessionId = data.study_session_id || null;
        /* A start that succeeded proves nothing is blocking us any more. */
        this.conflictSession = null;
        this.liveActivity = this.activity;
        /* Live work changes the visual hierarchy: keep the disclosure itself
           available, but fold the duplicate focus topic so the agent terminal
           gets the first screen. Do not persist this automatic fold — ending
           the session restores the learner's explicit localStorage choice. */
        this.focusCollapsed = true;
        /* Re-point the note composer at the live activity. refreshFocus() ran at
           init(), before any session existed, so its default fell back to the
           first focus slot - filing notes against the wrong topic for the whole
           session. A misfiled note is worse than an untagged one. */
        this.noteTopic = this.activity;
        window.dispatchEvent(new CustomEvent('study-session-start', {
          detail: {
            topic: this.activity, origin: 'body-double', energy: this.energy,
            agent: this.agent || null,
            resolvedAgent: data.agent || this.agent || null,
            studySessionId: data.study_session_id || null,
            transport: data.transport || this.transport,
            wsUrl: data.ws_url || null,
            personaText: data.persona_text || null,
          },
        }));
      } catch {
        this.startError = 'Could not reach the server.';
      } finally {
        this.starting = false;
      }
    },

    /* ================================================================
     * Origin-aware recovery from a session we cannot start over.
     * ================================================================ */

    /* Normalise GET /api/session/state — or a 409 start body — into the one
       shape the recovery block reads. camelCase is the JS-side convention (it
       matches the study-session-start detail); the snake_case aliases are kept
       alongside because the server payload speaks that dialect and a template
       binding to the wrong spelling fails SILENTLY rather than loudly. */
    _conflictShape(source) {
      const id = source.study_session_id || null;
      const origin = source.origin === 'body-double' ? 'body-double' : 'study';
      const reattachUrl = source.reattach_url
        || (id ? `/api/session/ws?study_session_id=${encodeURIComponent(id)}` : '');
      return {
        studySessionId: id,
        study_session_id: id,
        topic: source.topic || '',
        agent: source.agent || '',
        origin,
        transport: source.transport || 'pty',
        detached: !!source.detached,
        reattachUrl,
        reattach_url: reattachUrl,
      };
    },

    /* Publish the conflict and the sentence that explains it. Split from the
       probe/409 callers so both paths word it identically. */
    _applyConflict(conflict, serverMessage) {
      this.conflictSession = conflict;
      if (conflict.origin === 'body-double') {
        /* Our own session: the server's text already names the topic and both
           verbs, so keep it rather than paraphrasing it worse. */
        this.startError = serverMessage
          || 'A Body Double session is already active — reattach to it, or end it first.';
        return;
      }
      /* Foreign origin: NAME the surface that owns it. "A session is already
         active" without saying which is the dead end this work removes, and the
         way out is over there, not here. */
      const on = conflict.topic ? ` on "${conflict.topic}"` : '';
      this.startError = `${this.conflictOwnerLabel} already has a session active${on}`
        + ' — open it there to carry on, or end it to free the slot.';
    },

    /* Put this component into the same live state as a fresh start, using the
       server's existing Body Double session. The nested console performs its
       own guarded socket adoption; this method restores the surrounding UI so
       that successfully reattached terminal is not hidden by x-show. */
    _adoptOwnSession(conflict) {
      const topic = conflict.topic || this.activity || '';
      this.sessionActive = true;
      this.studySessionId = conflict.studySessionId;
      this.liveActivity = topic;
      this.focusCollapsed = true;
      if (topic) {
        this.activity = topic;
        this.noteTopic = topic;
      }
      this.conflictSession = null;
      this.startError = '';
      this.starting = false;
      return {
        topic,
        origin: 'body-double',
        energy: this.energy,
        agent: conflict.agent || this.agent || null,
        resolvedAgent: conflict.agent || this.agent || null,
        studySessionId: conflict.studySessionId,
        transport: conflict.transport || 'pty',
        wsUrl: conflict.reattachUrl || null,
        personaText: null,
        reattached: true,
      };
    },

    /* Proactive probe at init(). Parent and console each restore only the part
       of the session they own: this component restores live chrome/state,
       while liveAgentConsole independently mounts the PTY. Do NOT dispatch a
       second start event here — that races the console's own GET and can open,
       close, then reopen the same WebSocket during a refresh. */
    async _checkLiveSessionConflict() {
      if (this.sessionActive) return;
      const epoch = this._conflictEpoch;
      try {
        const res = await fetch('/api/session/state');
        if (!res.ok) return;
        const state = await res.json();
        /* Drop the answer if a stop or a reattach landed while it was in
           flight — that is newer information than this fetch. */
        if (epoch !== this._conflictEpoch || this.sessionActive) return;
        if (!state.study_session_id || state.mode === 'ended') return;
        const conflict = this._conflictShape(state);
        if (conflict.origin === 'body-double') {
          this._adoptOwnSession(conflict);
          return;
        }
        this._applyConflict(conflict, '');
      } catch { /* offline — Start will surface the 409 instead */ }
    },

    /* The 409 carries study_session_id / topic / agent / detached /
       reattach_url but NOT origin, so ownership cannot be decided from it
       alone. Resolve origin from /api/session/state, which echoes it for
       exactly this purpose, and trust that answer only when it describes the
       SAME session the 409 named — otherwise a race would let one session's
       origin decide another's fate. */
    async _raiseStartConflict(body) {
      const conflict = this._conflictShape(body || {});
      const message = (body && (body.error || body.detail)) || '';
      const epoch = this._conflictEpoch;
      try {
        const res = await fetch('/api/session/state');
        if (res.ok) {
          const state = await res.json();
          if (epoch !== this._conflictEpoch) return;
          const sameSession = state.study_session_id
            && (!conflict.studySessionId || state.study_session_id === conflict.studySessionId);
          if (sameSession) {
            const live = this._conflictShape(state);
            /* The overlay branch of /session/state rebuilds its dict from the
               slot and drops topic/transport, so prefer the 409's copy when the
               state's is blank. */
            live.topic = live.topic || conflict.topic;
            live.agent = live.agent || conflict.agent;
            live.detached = live.detached || conflict.detached;
            this._applyConflict(live, message);
            return;
          }
        }
      } catch { /* fall through to the 409's own, origin-less answer */ }
      if (epoch !== this._conflictEpoch) return;
      this._applyConflict(conflict, message);
    },

    /* Route to the surface that OWNS the live session. 'study' maps to the
       'study-session' route — the origin id and the route id differ, and
       sending the learner to the wrong one lands them in a picker that cannot
       adopt the session: the closed loop this work exists to break. */
    openConflictOwner() {
      const origin = (this.conflictSession && this.conflictSession.origin) || 'study';
      const route = origin === 'body-double' ? 'body-double' : 'study-session';
      const nav = window.Alpine && window.Alpine.store('nav');
      if (nav) nav.go(route);
    },

    /* Release the slot outright. No confirmation step on purpose: this button
       only exists while a session is BLOCKING the learner, and a second click
       to confirm is one more wall in the dead end. The stop event carries the
       ENDED session's origin so the console that owns it tears down — the
       origin filter means our own console correctly ignores a foreign stop. */
    async endConflictSession() {
      const origin = (this.conflictSession && this.conflictSession.origin) || 'study';
      /* Bump BEFORE the await: a probe in flight must not restore the banner. */
      this._conflictEpoch += 1;
      try {
        await fetch('/api/session/end', { method: 'POST' });
      } catch { /* tear the UI down regardless — a stuck banner is worse */ }
      window.dispatchEvent(new CustomEvent('study-session-stop', { detail: { origin } }));
      const pomodoro = Alpine.store('pomodoro');
      if (pomodoro) pomodoro.stop();
      if (origin === 'body-double') {
        this.sessionActive = false;
        this.studySessionId = null;
      }
      this.conflictSession = null;
      this.startError = '';
      this.confirmingEnd = false;
    },

    /* Adopt the live session instead of starting a new one. Gated on own
       origin: reattaching to a foreign session would attach a second console to
       one PTY, which is what the guard forbids. The console mounts off the
       study-session-start event, so reattached:true and the server's
       reattach_url are the load-bearing fields here. */
    reattachConflictSession() {
      const conflict = this.conflictSession;
      if (!conflict || conflict.origin !== 'body-double') return;
      /* Newer than any probe in flight — that probe would re-raise the banner
         for the very session we just adopted. */
      this._conflictEpoch += 1;
      const detail = this._adoptOwnSession(conflict);
      window.dispatchEvent(new CustomEvent('study-session-start', {
        detail,
      }));
    },

    endSession() { this.confirmingEnd = true; },
    cancelEnd() { this.confirmingEnd = false; },
    async confirmEnd() {
      /* Bumped before the await for the same reason as endConflictSession():
         a conflict probe in flight must not raise a banner for the session we
         are in the middle of ending. */
      this._conflictEpoch += 1;
      try {
        await fetch('/api/session/end', { method: 'POST' });
      } catch { /* tear the UI down regardless — a stuck "live" strip is worse */ }
      window.dispatchEvent(new CustomEvent('study-session-stop', {
        detail: { origin: 'body-double' },
      }));
      Alpine.store('pomodoro').stop();
      this.sessionActive = false;
      this.studySessionId = null;
      this.conflictSession = null;
      this.startError = '';
      this.activity = '';
      /* Restore the learner's explicit idle-layout preference. The automatic
         live collapse above intentionally never wrote localStorage. */
      this.focusCollapsed = localStorage.getItem('bd.focus.collapsed') === 'true';
      this.confirmingEnd = false;
      /* Deliberately NOT clearing the note draft: losing a half-written note
         because the session ended is exactly the kind of loss this view exists
         to prevent. */
    },
  };
}

/* Delegating alias for the pre-rename attribute string `bodyDoubleView()`.
 * NOT a second implementation — it returns the one factory above — so a markup
 * file still carrying the old x-data cannot silently get a component without
 * the recovery block, and the rename cannot half-land. */
function bodyDoubleView() { return bodyDoubleSession(); }
