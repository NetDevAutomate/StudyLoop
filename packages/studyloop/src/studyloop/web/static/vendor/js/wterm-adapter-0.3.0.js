/**
 * wterm-adapter-0.3.0.js
 *
 * Thin adapter that bridges the StudyLoop liveAgentConsole() xterm.js
 * API surface onto @wterm/dom 0.3.0 (WtermLib.WTerm).
 *
 * Active only when the server injects:
 *   <meta name="studyloop-dev-mode" content="wterm">
 *
 * The adapter monkey-patches window.Terminal so that liveAgentConsole()
 * calls new window.Terminal(opts) and gets a WTermAdapter instance back,
 * keeping the console JS untouched and the default xterm.js path unchanged.
 *
 * API surface implemented (matches what liveAgentConsole() actually calls):
 *   term.open(element)          — sync; init() is deferred async
 *   term.loadAddon(addon)       — no-op (fit/webgl/clipboard not needed)
 *   term.write(data)            — string or Uint8Array
 *   term.writeln(text)          — string
 *   term.onData(handler)        — register PTY-input callback
 *   term.onResize(handler)      — register resize callback
 *   term.onScroll(handler)      — no-op (jump-to-bottom unsupported in dev)
 *   term.attachCustomKeyEventHandler(fn) — no-op (Ctrl-\ escape handled natively)
 *   term.blur()                 — remove focus
 *   term.scrollToBottom()       — no-op (wterm handles it internally)
 *   term.getSelection()         — returns native window.getSelection() text
 *   term.dispose()              — destroy the wterm instance
 *   term.buffer.active          — stub {viewportY: 0, length: 0}
 *   term.cols / term.rows       — live dimensions
 *
 * Known limitations (dev mode):
 *   - No WebGL renderer (DOM rendering only).
 *   - No xterm clipboard addon (OSC 52 write not supported).
 *   - jump-to-bottom pill always hidden (onScroll is a no-op).
 *   - Ctrl-\ focus-escape relies on browser default, not custom handler.
 *   - FitAddon.fit() triggers a wterm resize via ResizeObserver instead.
 *
 * Source: bundled from @wterm/dom@0.3.0 + @wterm/core@0.3.0 (Apache-2.0)
 */

(function () {
  'use strict';

  const DEV_META = document.querySelector('meta[name="studyloop-dev-mode"]');
  if (!DEV_META || DEV_META.content !== 'wterm') {
    // Not in dev mode — leave window.Terminal as-is.
    return;
  }

  // Guard: WtermLib must be available (loaded by <script src=".../wterm-0.3.0.js">)
  if (typeof window.WtermLib === 'undefined') {
    console.warn('[wterm-adapter] WtermLib not found — adapter inactive');
    return;
  }

  const { WTerm } = window.WtermLib;

  /**
   * WTermAdapter — wraps WTerm in an xterm.js-compatible API.
   */
  class WTermAdapter {
    constructor(xtermOptions) {
      // xterm options we honour: fontSize, fontFamily, cursorBlink, scrollback
      this._xtermOptions = xtermOptions || {};
      this._wterm = null;
      this._element = null;
      this._onDataHandlers = [];
      this._onResizeHandlers = [];
      // Mutable cols/rows; updated by wterm's onResize callback.
      this.cols = xtermOptions.cols || 80;
      this.rows = xtermOptions.rows || 24;
      // Minimal buffer stub so liveAgentConsole's scroll check doesn't throw.
      this.buffer = { active: { viewportY: 0, length: 0 } };
    }

    /**
     * Mount the wterm terminal inside `element` (replaces xterm Terminal.open).
     * wterm.init() is async; we fire-and-forget and rely on the ResizeObserver
     * inside wterm to trigger the first render.
     */
    open(element) {
      this._element = element;

      // Apply a class so CSS can target the wterm container.
      element.classList.add('wterm-active');

      this._wterm = new WTerm(element, {
        cols: this.cols,
        rows: this.rows,
        autoResize: true,
        cursorBlink: this._xtermOptions.cursorBlink !== false,
        onData: (data) => {
          for (const handler of this._onDataHandlers) {
            handler(data);
          }
        },
        onResize: (cols, rows) => {
          this.cols = cols;
          this.rows = rows;
          for (const handler of this._onResizeHandlers) {
            handler({ cols, rows });
          }
        },
      });

      // init() is async (WASM decode + DOM setup). Errors are surfaced to
      // the console; the terminal shows nothing until init resolves.
      this._wterm.init().catch((err) => {
        console.error('[wterm-adapter] init failed:', err);
      });
    }

    // ------------------------------------------------------------------ //
    //  Addons — no-op (wterm has no addon API)
    // ------------------------------------------------------------------ //
    loadAddon(_addon) {
      // Intentional no-op. FitAddon, WebglAddon, ClipboardAddon all skipped.
    }

    // ------------------------------------------------------------------ //
    //  Output
    // ------------------------------------------------------------------ //
    write(data) {
      if (!this._wterm) return;
      if (typeof data === 'string') {
        this._wterm.write(data);
      } else {
        // Uint8Array — wterm.write accepts both
        this._wterm.write(data);
      }
    }

    writeln(text) {
      this.write(text + '\r\n');
    }

    // ------------------------------------------------------------------ //
    //  Input / resize callbacks
    // ------------------------------------------------------------------ //
    onData(handler) {
      this._onDataHandlers.push(handler);
      // Return a disposable-like object (xterm API compat)
      return { dispose: () => { this._onDataHandlers = this._onDataHandlers.filter(h => h !== handler); } };
    }

    onResize(handler) {
      this._onResizeHandlers.push(handler);
      return { dispose: () => { this._onResizeHandlers = this._onResizeHandlers.filter(h => h !== handler); } };
    }

    // Scroll events — no-op; jump-to-bottom pill stays hidden in dev mode.
    onScroll(_handler) {
      return { dispose: () => {} };
    }

    // Custom key handler (Ctrl-\ escape) — no-op; browser default handles it.
    attachCustomKeyEventHandler(_fn) {}

    // ------------------------------------------------------------------ //
    //  UX helpers
    // ------------------------------------------------------------------ //
    focus() {
      if (this._wterm) this._wterm.focus();
    }

    blur() {
      if (this._element) this._element.blur();
    }

    scrollToBottom() {
      // wterm tracks scroll internally; no public API needed.
    }

    getSelection() {
      // DOM-rendered text — native selection works; just return it.
      const sel = window.getSelection();
      return sel ? sel.toString() : '';
    }

    // ------------------------------------------------------------------ //
    //  Lifecycle
    // ------------------------------------------------------------------ //
    dispose() {
      if (this._wterm) {
        this._wterm.destroy();
        this._wterm = null;
      }
      this._onDataHandlers = [];
      this._onResizeHandlers = [];
    }
  }

  // --------------------------------------------------------------------- //
  //  Patch window.Terminal so liveAgentConsole() picks up the adapter.
  //  FitAddon, WebglAddon, ClipboardAddon are patched to no-ops so the
  //  existing `if (window.FitAddon)` / `if (window.WebglAddon)` guards
  //  still resolve truthy but the addon itself does nothing.
  // --------------------------------------------------------------------- //

  /** Stub addon returned by loadAddon — exposes .fit() as a no-op. */
  class _NoOpFitAddon {
    fit() {}
  }

  const _NoOpAddonFactory = { [Symbol.hasInstance]: () => false };

  window.Terminal = WTermAdapter;

  // Keep FitAddon truthy (liveAgentConsole checks `new window.FitAddon.FitAddon()`)
  // but make the resulting object harmless.
  window.FitAddon = { FitAddon: _NoOpFitAddon };

  // Nullify WebglAddon and ClipboardAddon so their `if (window.X)` guards
  // evaluate to false — cleaner than a no-op that might throw on context loss.
  window.WebglAddon = null;
  window.ClipboardAddon = null;

  console.info('[wterm-adapter] active — xterm.js replaced by @wterm/dom 0.3.0');
})();
