/**
 * ghostty-adapter-0.4.0.js
 *
 * Bridges the StudyLoop liveAgentConsole() xterm.js API surface onto
 * ghostty-web 0.4.0 (Ghostty's VT100 parser — libghostty — compiled to WASM).
 *
 * Active only when the server injects:
 *   <meta name="studyloop-dev-mode" content="ghostty">
 *
 * ghostty-web is already broadly xterm.js API compatible, so this adapter
 * exists for four specific reasons the raw library cannot cover:
 *
 * 1. ASYNC WASM INIT
 *    ghostty-web requires `await init()` before the first `new Terminal()`,
 *    but liveAgentConsole() constructs, opens, fits and writes synchronously.
 *    This adapter is a queueing facade: calls made before WASM is ready are
 *    recorded and replayed once it resolves.
 *
 * 2. THEME PROPAGATION  (the headline fix)
 *    StudyLoop has 12 runtime-switchable palettes. ghostty-web 0.4.0 cannot
 *    change theme after open(): `options.theme = {...}` only logs
 *    "theme changes after open() are not yet fully supported".
 *    The reason is structural — the default fg/bg live in the *WASM* terminal
 *    config (baked in at construction, no setter on GhosttyTerminal), so
 *    `renderer.setTheme()` alone is not enough: renderer.resize() repaints the
 *    canvas in the new colour and the very next render() puts the old colour
 *    back from WASM cell attributes. Verified empirically.
 *    So a palette change REBUILDS the terminal with the new theme and replays
 *    the retained output. The PTY link is untouched — liveAgentConsole talks
 *    to this adapter, never to the underlying Terminal, so the swap is
 *    invisible to it.
 *
 * 3. FONT PROPAGATION
 *    Terminal font comes from the `--term-font-family` / `--term-font-size`
 *    CSS custom properties (see ghostty-0.4.0.css), so the reading-font picker
 *    and OpenDyslexic toggle reach the terminal too. Unlike theme, ghostty-web
 *    *does* support runtime font changes, so these use the supported
 *    `options.fontFamily` / `options.fontSize` proxy setters, followed by a
 *    re-fit because cell metrics changed.
 *
 * 4. RELIABLE RESIZE
 *    ghostty-web's FitAddon drops any fit() that lands inside its 50 ms
 *    `_isResizing` guard and never retries. See AdapterFitAddon.
 *
 * Propagation trigger: a MutationObserver on <body> watching `class`,
 * `data-palette` and `data-font`. Deliberately decoupled from components.js —
 * the Alpine settings store needs no changes, and every path that restyles the
 * page (palette picker, font picker, dyslexic toggle, light/dark toggle)
 * propagates for free.
 *
 * Source: ghostty-web@0.4.0 (MIT) — https://github.com/coder/ghostty-web
 * Evaluation: private-docs/ghostty-web-evaluation.md
 */

(function () {
  'use strict';

  const DEV_META = document.querySelector('meta[name="studyloop-dev-mode"]');
  if (!DEV_META || DEV_META.content !== 'ghostty') {
    // Not in ghostty dev mode — leave window.Terminal (xterm.js) untouched.
    return;
  }

  if (typeof window.GhosttyWeb === 'undefined') {
    console.warn('[ghostty-adapter] GhosttyWeb global not found — adapter inactive');
    return;
  }

  const GW = window.GhosttyWeb;

  const DEFAULT_MONO =
    'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';
  const DEFAULT_FONT_SIZE = 13;

  // Output retained for replay across a theme rebuild. Caps total retained
  // bytes; older chunks are dropped first, so a very long session loses
  // early scrollback on a palette change rather than growing without bound.
  const REPLAY_CAP_BYTES = 512 * 1024;

  // ------------------------------------------------------------------ //
  //  WASM init — one shared instance for every Terminal.
  // ------------------------------------------------------------------ //
  let wasmReady = false;
  let wasmError = null;

  const readyPromise = Promise.resolve()
    .then(() => GW.init())
    .then(() => {
      wasmReady = true;
      return true;
    })
    .catch((err) => {
      wasmError = err;
      console.error('[ghostty-adapter] WASM init failed:', err);
      return false;
    });

  // ------------------------------------------------------------------ //
  //  Theme + font derived from live CSS custom properties.
  // ------------------------------------------------------------------ //

  /**
   * Read a CSS custom property, falling back when unset/empty.
   *
   * Reads from <body>, NOT <html>. This matters: :root carries only the
   * tokyo-night defaults, while every palette override lands on
   * `body[data-palette="..."]` and every font override on
   * `body[data-font="..."]`. Custom properties inherit, so body resolves both
   * the defaults and the active override; documentElement only ever sees the
   * defaults.
   *
   * This is the second half of the xterm.js theme bug: index.html's
   * _computeTheme() reads getComputedStyle(document.documentElement), so even
   * if it were re-invoked on every palette change it would keep returning
   * tokyo-night colours.
   */
  function cssVar(name, fallback) {
    const target = document.body || document.documentElement;
    let raw = getComputedStyle(target).getPropertyValue(name).trim();
    if (!raw && target !== document.documentElement) {
      raw = getComputedStyle(document.documentElement)
        .getPropertyValue(name)
        .trim();
    }
    return raw || fallback;
  }

  /**
   * Map StudyLoop's 11 palette variables onto a full 16-colour ANSI theme.
   *
   * Every palette (tokyo-night, dracula, nord, gruvbox, solarized, ...)
   * defines the same variable set, so the terminal tracks whichever palette
   * the user picked instead of being frozen at construction time.
   */
  function computeTheme() {
    const bg = cssVar('--bg', '#1a1b26');
    const bgHover = cssVar('--bg-hover', '#292e42');
    const text = cssVar('--text', '#c0caf5');
    const muted = cssVar('--text-muted', '#565f89');
    const accent = cssVar('--accent', '#7aa2f7');
    const green = cssVar('--green', '#9ece6a');
    const red = cssVar('--red', '#f7768e');
    const yellow = cssVar('--yellow', '#e0af68');
    const orange = cssVar('--orange', '#ff9e64');

    return {
      background: bg,
      foreground: text,
      cursor: accent,
      cursorAccent: bg,
      selectionBackground: bgHover,
      selectionForeground: text,

      black: bg,
      red: red,
      green: green,
      yellow: yellow,
      blue: accent,
      magenta: orange,
      cyan: green,
      white: text,

      brightBlack: muted,
      brightRed: red,
      brightGreen: green,
      brightYellow: yellow,
      brightBlue: accent,
      brightMagenta: orange,
      brightCyan: accent,
      brightWhite: text,
    };
  }

  /**
   * Terminal font from CSS. `--term-font-family` / `--term-font-size` are
   * declared in ghostty-0.4.0.css and re-pointed per `body[data-font]` and
   * `body.dyslexic`, which is how a font change reaches the terminal.
   */
  function computeFont() {
    const family = cssVar('--term-font-family', DEFAULT_MONO);
    const rawSize = cssVar('--term-font-size', String(DEFAULT_FONT_SIZE));
    const size = parseFloat(rawSize);
    return {
      fontFamily: family,
      fontSize: Number.isFinite(size) && size > 0 ? size : DEFAULT_FONT_SIZE,
    };
  }

  /** Shallow compare two theme objects. */
  function sameTheme(a, b) {
    if (!a || !b) return false;
    const keys = Object.keys(a);
    if (keys.length !== Object.keys(b).length) return false;
    return keys.every((k) => a[k] === b[k]);
  }

  // ------------------------------------------------------------------ //
  //  Live instance registry — every open adapter restyles together.
  // ------------------------------------------------------------------ //
  const liveAdapters = new Set();

  /** Count of successful restyles, for tests and debugging. */
  let restyleCount = 0;
  /** Count of theme-driven terminal rebuilds. */
  let rebuildCount = 0;

  function restyleAll(reason) {
    for (const adapter of liveAdapters) {
      adapter._applyThemeAndFont(reason);
    }
  }

  // Watch every attribute that can change palette or font:
  //   data-palette → palette picker      data-font → reading-font picker
  //   class        → `light` + `dyslexic` toggles
  const bodyObserver = new MutationObserver((records) => {
    const relevant = records.some(
      (r) =>
        r.type === 'attributes' &&
        (r.attributeName === 'class' ||
          r.attributeName === 'data-palette' ||
          r.attributeName === 'data-font'),
    );
    if (!relevant) return;
    // Defer one frame: CSS custom properties resolve after the attribute
    // mutation is applied, so getComputedStyle sees the new values.
    requestAnimationFrame(() => restyleAll('mutation'));
  });

  function startObserving() {
    if (!document.body) return;
    bodyObserver.observe(document.body, {
      attributes: true,
      attributeFilter: ['class', 'data-palette', 'data-font'],
    });
  }

  if (document.body) {
    startObserving();
  } else {
    document.addEventListener('DOMContentLoaded', startObserving, { once: true });
  }

  // ------------------------------------------------------------------ //
  //  FitAddon facade.
  //
  //  Uses ghostty-web's FitAddon for its metrics maths (proposeDimensions()
  //  correctly accounts for cell size, element padding and scrollbar width)
  //  but drives term.resize() itself, because upstream fit() drops requests:
  //
  //      fit() {
  //        if (this._isResizing) return;        // <-- dropped, never retried
  //        ...
  //        this._isResizing = true;
  //        try { term.resize(cols, rows) }
  //        finally { setTimeout(() => this._isResizing = false, 50) }
  //      }
  //
  //  A ResizeObserver fire landing inside that 50 ms window is discarded with
  //  no queue and no retry. Since the observer only fires again on the *next*
  //  size change, one unlucky fire leaves the terminal permanently mis-sized —
  //  reproducible by shrinking the window shortly after the panel mounts.
  //  xterm.js's FitAddon has no such guard, so this restores parity.
  // ------------------------------------------------------------------ //
  class AdapterFitAddon {
    constructor() {
      this._real = null;
      this._adapter = null;
      this._verifyTimer = null;
    }

    /** Called by GhosttyAdapter.loadAddon(). */
    _bind(adapter) {
      this._adapter = adapter;
    }

    /** Called by GhosttyAdapter whenever a real Terminal is created. */
    _attach(term) {
      // Drop any addon bound to a previous terminal (theme rebuild).
      if (this._real) {
        try {
          this._real.dispose();
        } catch {
          /* already disposed */
        }
        this._real = null;
      }
      try {
        this._real = new GW.FitAddon();
        // loadAddon calls activate(), which stores the terminal reference.
        // We deliberately do NOT call observeResize() — liveAgentConsole owns
        // the ResizeObserver, and two observers would race.
        term.loadAddon(this._real);
      } catch (err) {
        console.warn('[ghostty-adapter] FitAddon attach failed:', err);
        this._real = null;
      }
    }

    /** Current best-fit dimensions, or undefined when the container is hidden. */
    proposeDimensions() {
      if (!this._real) return undefined;
      try {
        return this._real.proposeDimensions();
      } catch {
        return undefined;
      }
    }

    /**
     * Resize the terminal to fit its container.
     *
     * Idempotent and guard-free: safe to call from a ResizeObserver on every
     * frame. Schedules one verification pass because cell metrics can settle
     * a frame late (webfont load, font-size change).
     */
    fit() {
      this._fitNow();
      this._scheduleVerify();
    }

    _fitNow() {
      const term = this._adapter && this._adapter._term;
      if (!term || !this._real) return false;

      const dims = this.proposeDimensions();
      // undefined => container hidden or zero-size; the next observer fire
      // (or the verification pass) retries.
      if (!dims || !dims.cols || !dims.rows) return false;
      if (dims.cols === term.cols && dims.rows === term.rows) return false;

      try {
        term.resize(dims.cols, dims.rows);
      } catch (err) {
        console.warn('[ghostty-adapter] resize failed:', err);
        return false;
      }

      // Keep upstream's memo in step so its own fit() (if ever triggered)
      // agrees with reality instead of short-circuiting on a stale value.
      this._real._lastCols = dims.cols;
      this._real._lastRows = dims.rows;
      return true;
    }

    /**
     * Re-check shortly after a fit.
     *
     * Covers a hidden panel, or metrics that change one frame after a font
     * swap. Single trailing timer, so repeated calls coalesce.
     */
    _scheduleVerify() {
      if (this._verifyTimer !== null) return;
      this._verifyTimer = window.setTimeout(() => {
        this._verifyTimer = null;
        this._fitNow();
      }, 80);
    }

    activate() {
      /* no-op: activation happens in _attach */
    }

    dispose() {
      if (this._verifyTimer !== null) {
        clearTimeout(this._verifyTimer);
        this._verifyTimer = null;
      }
      if (this._real) {
        try {
          this._real.dispose();
        } catch {
          /* already disposed */
        }
        this._real = null;
      }
    }
  }

  // ------------------------------------------------------------------ //
  //  GhosttyAdapter — xterm.js-shaped facade over a replaceable Terminal.
  // ------------------------------------------------------------------ //
  class GhosttyAdapter {
    constructor(xtermOptions) {
      const opts = xtermOptions || {};
      this._xtermOptions = opts;
      this._term = null;
      this._element = null;
      this._disposed = false;
      this._rebuilding = false;

      // Queued work, replayed in order once WASM resolves.
      this._writeQueue = [];
      this._pendingAddons = [];
      this._onDataHandlers = [];
      this._onResizeHandlers = [];
      this._onScrollHandlers = [];
      this._keyHandler = null;

      // Retained output, replayed after a theme rebuild.
      this._replayLog = [];
      this._replayBytes = 0;
      this._replaying = false;

      // Last theme/font pushed into the terminal — exposed for tests.
      this._appliedTheme = null;
      this._appliedFont = null;

      this.cols = opts.cols || 80;
      this.rows = opts.rows || 24;

      // Buffer stub until the real terminal exists; liveAgentConsole reads
      // buffer.active.{viewportY,length} from its onScroll handler.
      this._bufferStub = { active: { viewportY: 0, length: 0 } };
    }

    get buffer() {
      return this._term ? this._term.buffer : this._bufferStub;
    }

    // ---------------------------------------------------------------- //
    //  Mount
    // ---------------------------------------------------------------- //
    open(element) {
      this._element = element;
      element.classList.add('ghostty-active');

      readyPromise.then((ok) => {
        if (!ok || this._disposed || !this._element) return;
        try {
          this._buildTerminal({ replay: true });
          liveAdapters.add(this);
          // Re-read theme/font in case the palette changed while WASM loaded.
          this._applyThemeAndFont('mount');
        } catch (err) {
          console.error('[ghostty-adapter] terminal construction failed:', err);
        }
      });
    }

    /**
     * Create the underlying ghostty Terminal, wire it up and open it.
     *
     * Used for the initial mount and for theme rebuilds, so the two paths
     * cannot drift apart.
     *
     * @param {{replay: boolean}} options replay=true replays retained output.
     */
    _buildTerminal({ replay }) {
      const font = computeFont();
      const theme = computeTheme();

      const term = new GW.Terminal({
        cols: this.cols,
        rows: this.rows,
        cursorBlink: this._xtermOptions.cursorBlink !== false,
        cursorStyle: this._xtermOptions.cursorStyle || 'bar',
        scrollback: this._xtermOptions.scrollback || 5000,
        convertEol: this._xtermOptions.convertEol === true,
        fontFamily: font.fontFamily,
        fontSize: font.fontSize,
        theme: theme,
      });

      this._term = term;
      this._appliedTheme = theme;
      this._appliedFont = font;

      // Wire events BEFORE open() so nothing emitted during startup is lost.
      term.onData((data) => {
        for (const h of this._onDataHandlers) h(data);
      });
      term.onResize(({ cols, rows }) => {
        this.cols = cols;
        this.rows = rows;
        for (const h of this._onResizeHandlers) h({ cols, rows });
      });
      term.onScroll((y) => {
        for (const h of this._onScrollHandlers) h(y);
      });
      if (this._keyHandler) {
        term.attachCustomKeyEventHandler(this._wrapKeyHandler(this._keyHandler));
      }

      term.open(this._element);

      // Attach addons (FitAddon in practice), then fit now the canvas exists.
      for (const addon of this._pendingAddons) {
        if (addon && typeof addon._attach === 'function') {
          addon._attach(term);
        } else if (addon) {
          try {
            term.loadAddon(addon);
          } catch {
            /* incompatible addon — skip */
          }
        }
      }
      this._refit();

      this.cols = term.cols;
      this.rows = term.rows;

      if (replay) this._replayOutput();
    }

    /**
     * Replay retained output into the current terminal.
     *
     * `_replaying` stops the replayed chunks being appended to the log again.
     */
    _replayOutput() {
      const chunks = this._writeQueue.length ? this._writeQueue : this._replayLog;
      this._replaying = true;
      try {
        for (const chunk of chunks) {
          try {
            this._term.write(chunk);
          } catch (err) {
            console.warn('[ghostty-adapter] replay write failed:', err);
          }
        }
      } finally {
        this._replaying = false;
      }
      // Anything queued pre-WASM is now in the terminal and in the log.
      this._writeQueue = [];
    }

    // ---------------------------------------------------------------- //
    //  Theme + font propagation
    // ---------------------------------------------------------------- //

    /**
     * Push the current CSS-derived theme and font into the terminal.
     *
     * Font uses the supported `options` proxy (ghostty-web re-measures and
     * repaints), followed by a re-fit because cell metrics changed.
     *
     * Theme cannot use that path. ghostty-web 0.4.0 stores default fg/bg in
     * the WASM terminal config with no setter, so `renderer.setTheme()` is
     * overwritten by the next frame's render(). The terminal is therefore
     * rebuilt with the new theme and the retained output replayed.
     */
    _applyThemeAndFont(reason) {
      const term = this._term;
      if (!term || this._disposed || this._rebuilding) return false;

      let changed = false;

      // ---- font (supported runtime path) ----
      const font = computeFont();
      const prevFont = this._appliedFont || {};
      let fontChanged = false;
      if (font.fontFamily !== prevFont.fontFamily) {
        try {
          term.options.fontFamily = font.fontFamily;
          fontChanged = true;
        } catch (err) {
          console.warn('[ghostty-adapter] fontFamily update failed:', err);
        }
      }
      if (font.fontSize !== prevFont.fontSize) {
        try {
          term.options.fontSize = font.fontSize;
          fontChanged = true;
        } catch (err) {
          console.warn('[ghostty-adapter] fontSize update failed:', err);
        }
      }
      this._appliedFont = font;
      if (fontChanged) {
        // Cell metrics changed, so the fitting column/row count changed too.
        this._refit();
        changed = true;
      }

      // ---- theme (requires a rebuild) ----
      const theme = computeTheme();
      if (!sameTheme(theme, this._appliedTheme)) {
        if (this._rebuildWithTheme()) changed = true;
      }

      // Keep the mount's own background in step so the letterbox area around
      // the canvas matches the palette.
      if (this._element) {
        this._element.style.backgroundColor = theme.background;
      }

      if (changed) restyleCount += 1;
      void reason;
      return changed;
    }

    /**
     * Rebuild the terminal so the new theme reaches the WASM config.
     *
     * Preserves everything liveAgentConsole depends on: the adapter identity,
     * its onData/onResize/onScroll handler lists, the key handler and the
     * FitAddon. Only the inner Terminal is replaced, so the PTY WebSocket
     * (which talks to the adapter) never notices.
     *
     * @returns {boolean} true if a rebuild happened.
     */
    _rebuildWithTheme() {
      if (!this._term || !this._element || this._rebuilding) return false;

      this._rebuilding = true;
      try {
        try {
          this._term.dispose();
        } catch (err) {
          console.warn('[ghostty-adapter] disposing old terminal failed:', err);
        }
        this._term = null;

        // dispose() detaches the canvas/textarea it created; clear any
        // residue so the rebuilt terminal starts from a clean mount.
        this._element.innerHTML = '';

        this._buildTerminal({ replay: true });
        rebuildCount += 1;
        return true;
      } catch (err) {
        console.error('[ghostty-adapter] theme rebuild failed:', err);
        return false;
      } finally {
        this._rebuilding = false;
      }
    }

    /** Re-fit the grid via every attached fit addon. */
    _refit() {
      for (const addon of this._pendingAddons) {
        if (addon && typeof addon.fit === 'function') {
          try {
            addon.fit();
          } catch (err) {
            console.warn('[ghostty-adapter] refit failed:', err);
          }
        }
      }
    }

    // ---------------------------------------------------------------- //
    //  Addons
    // ---------------------------------------------------------------- //
    loadAddon(addon) {
      if (!addon) return;
      if (typeof addon._bind === 'function') addon._bind(this);
      // Always retain, so a theme rebuild can re-attach it.
      if (!this._pendingAddons.includes(addon)) this._pendingAddons.push(addon);
      if (this._term) {
        if (typeof addon._attach === 'function') {
          addon._attach(this._term);
        } else {
          try {
            this._term.loadAddon(addon);
          } catch {
            /* incompatible addon — skip */
          }
        }
      }
    }

    // ---------------------------------------------------------------- //
    //  Output
    // ---------------------------------------------------------------- //
    write(data) {
      if (this._disposed) return;
      if (!this._replaying) this._retain(data);
      if (this._term) {
        try {
          this._term.write(data);
        } catch (err) {
          console.warn('[ghostty-adapter] write failed:', err);
        }
      } else {
        // Pre-WASM: _replayOutput() flushes this once the terminal exists.
        this._writeQueue.push(data);
      }
    }

    /** Retain a chunk for replay, trimming the oldest past the cap. */
    _retain(data) {
      const size = typeof data === 'string' ? data.length : data.byteLength || 0;
      this._replayLog.push(data);
      this._replayBytes += size;
      while (this._replayBytes > REPLAY_CAP_BYTES && this._replayLog.length > 1) {
        const dropped = this._replayLog.shift();
        const droppedSize =
          typeof dropped === 'string' ? dropped.length : dropped.byteLength || 0;
        this._replayBytes -= droppedSize;
      }
    }

    writeln(text) {
      this.write(text + '\r\n');
    }

    /**
     * Paste text as if the user pasted it (xterm API parity).
     *
     * The route non-BMP input must take: ghostty's key handler only forwards
     * keys whose `key.length === 1`, so emoji and other surrogate-pair
     * characters cannot arrive as keydown events. Paste (and IME composition)
     * carry them instead. Emits through onData, so it reaches the PTY.
     */
    paste(data) {
      if (this._disposed || !this._term) return;
      try {
        this._term.paste(data);
      } catch (err) {
        console.warn('[ghostty-adapter] paste failed:', err);
      }
    }

    /**
     * Inject input as if the user produced it (xterm API parity).
     *
     * Unlike write(), this travels *outbound* via onData rather than being
     * rendered directly.
     */
    input(data, wasUserInput = true) {
      if (this._disposed || !this._term) return;
      try {
        this._term.input(data, wasUserInput);
      } catch (err) {
        console.warn('[ghostty-adapter] input failed:', err);
      }
    }

    // ---------------------------------------------------------------- //
    //  Events
    // ---------------------------------------------------------------- //
    onData(handler) {
      this._onDataHandlers.push(handler);
      return {
        dispose: () => {
          this._onDataHandlers = this._onDataHandlers.filter((h) => h !== handler);
        },
      };
    }

    onResize(handler) {
      this._onResizeHandlers.push(handler);
      return {
        dispose: () => {
          this._onResizeHandlers = this._onResizeHandlers.filter((h) => h !== handler);
        },
      };
    }

    onScroll(handler) {
      this._onScrollHandlers.push(handler);
      return {
        dispose: () => {
          this._onScrollHandlers = this._onScrollHandlers.filter((h) => h !== handler);
        },
      };
    }

    /**
     * Bridge xterm's key-handler contract onto ghostty's, which is inverted.
     *
     * xterm.js:  `attachCustomKeyEventHandler(fn)` — returning **false**
     *            stops the event being sent to the terminal. Returning true
     *            means "carry on, handle it normally".
     *
     * ghostty-web: the opposite. From its InputHandler.handleKeyDown:
     *
     *     if (this.customKeyEventHandler && this.customKeyEventHandler(ev)) {
     *       ev.preventDefault();
     *       return;                       // <-- key is SWALLOWED
     *     }
     *
     * so returning **true** consumes the event.
     *
     * Passing an xterm-style handler through unwrapped therefore swallows
     * every keystroke, because liveAgentConsole()'s handler returns true for
     * all normal keys. The terminal renders agent output perfectly and the
     * learner cannot type — invisible to any test that writes bytes directly
     * instead of pressing keys.
     */
    _wrapKeyHandler(fn) {
      return (event) => {
        let passThrough = true;
        try {
          // Treat only an explicit `false` as "consume", matching xterm, where
          // a handler returning undefined means "carry on".
          passThrough = fn(event) !== false;
        } catch (err) {
          console.warn('[ghostty-adapter] key handler threw:', err);
          passThrough = true;
        }
        // ghostty consumes when the handler returns true.
        return !passThrough;
      };
    }

    attachCustomKeyEventHandler(fn) {
      this._keyHandler = fn;
      if (this._term) {
        this._term.attachCustomKeyEventHandler(this._wrapKeyHandler(fn));
      }
    }

    // ---------------------------------------------------------------- //
    //  UX helpers
    // ---------------------------------------------------------------- //
    focus() {
      if (this._term) this._term.focus();
    }

    blur() {
      if (this._term) {
        this._term.blur();
      } else if (this._element) {
        this._element.blur();
      }
    }

    scrollToBottom() {
      if (this._term) this._term.scrollToBottom();
    }

    getSelection() {
      if (this._term) {
        try {
          return this._term.getSelection();
        } catch {
          /* fall through to DOM selection */
        }
      }
      const sel = window.getSelection();
      return sel ? sel.toString() : '';
    }

    // ghostty-web's Terminal forwards all five selection methods to its
    // selectionManager, but this facade forwarded only getSelection(), so
    // `term.selectAll` was undefined for every caller that went through the
    // adapter -- which is every caller, since liveAgentConsole() never touches
    // the underlying Terminal. Selection is NOT DOM-selectable here: ghostty-web
    // paints to a canvas, so window.getSelection() cannot substitute for these.
    selectAll() {
      if (this._term) this._term.selectAll();
    }

    hasSelection() {
      if (!this._term) return false;
      try {
        return Boolean(this._term.hasSelection());
      } catch {
        return false;
      }
    }

    clearSelection() {
      if (this._term) this._term.clearSelection();
    }

    selectLines(start, end) {
      if (this._term) this._term.selectLines(start, end);
    }

    resize(cols, rows) {
      this.cols = cols;
      this.rows = rows;
      if (this._term) this._term.resize(cols, rows);
    }

    clear() {
      // Clearing the screen also clears what a rebuild should replay,
      // otherwise a later palette change would resurrect cleared output.
      this._replayLog = [];
      this._replayBytes = 0;
      if (this._term) this._term.clear();
    }

    // ---------------------------------------------------------------- //
    //  Lifecycle
    // ---------------------------------------------------------------- //
    dispose() {
      this._disposed = true;
      liveAdapters.delete(this);
      if (this._element) {
        this._element.classList.remove('ghostty-active');
      }
      for (const addon of this._pendingAddons) {
        if (addon && typeof addon.dispose === 'function') {
          try {
            addon.dispose();
          } catch {
            /* ignore */
          }
        }
      }
      if (this._term) {
        try {
          this._term.dispose();
        } catch {
          /* already gone */
        }
        this._term = null;
      }
      this._writeQueue = [];
      this._replayLog = [];
      this._replayBytes = 0;
      this._pendingAddons = [];
      this._onDataHandlers = [];
      this._onResizeHandlers = [];
      this._onScrollHandlers = [];
    }
  }

  // ------------------------------------------------------------------ //
  //  Patch the xterm.js globals liveAgentConsole() reaches for.
  // ------------------------------------------------------------------ //
  window.Terminal = GhosttyAdapter;
  window.FitAddon = { FitAddon: AdapterFitAddon };

  // ghostty-web ships its own canvas renderer — the xterm WebGL and clipboard
  // addons have no counterpart, so their `if (window.X)` guards must be falsy
  // rather than loading a foreign addon.
  window.WebglAddon = null;
  window.ClipboardAddon = null;

  // ------------------------------------------------------------------ //
  //  Inspection surface — used by the Playwright suite and for debugging.
  // ------------------------------------------------------------------ //
  window.__studyloopGhostty = {
    engine: 'ghostty-web',
    version: '0.4.0',
    get ready() {
      return wasmReady;
    },
    get error() {
      return wasmError ? String(wasmError) : null;
    },
    readyPromise: readyPromise,
    /** Live adapters (normally 0 or 1). */
    get adapters() {
      // Filter rather than trust the set. open() registers inside
      // readyPromise.then(), so a mount that straddles WASM readiness can add
      // *after* dispose() removed the entry — leaving a dead adapter in the
      // set. That matters because everything below reads through `adapter`: a
      // stale entry makes readBuffer() report an empty, disposed terminal while
      // the live one has the agent's output, which reads as "the terminal
      // stopped working" in any test or debugging session after a session ends.
      return Array.from(liveAdapters).filter((a) => !a._disposed);
    },
    /** The newest live adapter, or null. The newest is the one on screen. */
    get adapter() {
      const live = this.adapters;
      return live.length ? live[live.length - 1] : null;
    },
    /** Theme/font currently applied to the terminal. */
    get appliedTheme() {
      const a = this.adapter;
      return a ? a._appliedTheme : null;
    },
    get appliedFont() {
      const a = this.adapter;
      return a ? a._appliedFont : null;
    },
    /** Successful restyles since page load. */
    get restyleCount() {
      return restyleCount;
    },
    /** Theme-driven terminal rebuilds since page load. */
    get rebuildCount() {
      return rebuildCount;
    },
    computeTheme: computeTheme,
    computeFont: computeFont,
    /** Force propagation now, bypassing the rAF debounce. */
    restyle: () => {
      restyleAll('manual');
      return restyleCount;
    },

    /**
     * Visible buffer text via the xterm-compatible API.
     *
     * NOTE: lossy for combining marks. translateToString() returns one
     * codepoint per cell, so 'नमस्ते' comes back as 'नमसत'. Use
     * readBufferGraphemes() when grapheme fidelity matters.
     */
    readBuffer: () => {
      const a = window.__studyloopGhostty.adapter;
      if (!a || !a._term) return null;
      const term = a._term;
      const buf = term.buffer.active;
      const lines = [];
      for (let y = 0; y < term.rows; y += 1) {
        const line = buf.getLine(buf.viewportY + y);
        lines.push(line ? line.translateToString(true) : '');
      }
      return lines;
    },

    /**
     * Visible buffer text with full grapheme clusters.
     *
     * Reads through the WASM terminal's getGraphemeString(), which preserves
     * combining marks and ZWJ sequences — 'स्' (U+0938 U+094D) and the family
     * emoji U+1F468 U+200D U+1F469 U+200D U+1F467 survive intact. This is the
     * accurate view of what libghostty stored and drew; the xterm-compatible
     * readBuffer() above is the lossy shim.
     */
    readBufferGraphemes: () => {
      const a = window.__studyloopGhostty.adapter;
      if (!a || !a._term || !a._term.wasmTerm) return null;
      const term = a._term;
      const wasm = term.wasmTerm;
      const lines = [];
      for (let y = 0; y < term.rows; y += 1) {
        let line = '';
        for (let x = 0; x < term.cols; x += 1) {
          let cell = '';
          try {
            cell = wasm.getGraphemeString(y, x) || '';
          } catch {
            cell = '';
          }
          // Unset cells come back as NUL; treat them as blanks.
          line += cell === '\u0000' ? ' ' : cell;
        }
        lines.push(line.replace(/\s+$/, ''));
      }
      return lines;
    },
  };

  console.info(
    '[ghostty-adapter] active — xterm.js replaced by ghostty-web 0.4.0 (libghostty WASM)',
  );
})();
