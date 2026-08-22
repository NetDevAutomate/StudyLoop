/**
 * ghostty-web-bootstrap-0.4.0.js
 *
 * Bootstraps ghostty-web as the dev-mode terminal renderer.
 * Active only when: <meta name="studyloop-dev-mode" content="ghostty-web">
 *
 * This is just init + global patch, not a full API shim:
 * ghostty-web IS the xterm.js API — no translation needed.
 */
(function () {
  'use strict';

  var DEV_META = document.querySelector('meta[name="studyloop-dev-mode"]');
  if (!DEV_META || DEV_META.content !== 'ghostty-web') return;

  if (typeof window.GhosttyWeb === 'undefined') {
    console.warn('[ghostty-web-bootstrap] GhosttyWeb not loaded — inactive');
    return;
  }

  // Init WASM before patching (non-blocking — Terminal constructor will
  // throw if used before init resolves, but liveAgentConsole only creates
  // the terminal inside $nextTick which fires after DOMContentLoaded).
  window.GhosttyWeb.init('/vendor/js/ghostty-vt-0.4.0.wasm')
    .then(function () {
      console.info('[ghostty-web-bootstrap] WASM loaded — terminal ready');
    })
    .catch(function (err) {
      console.error('[ghostty-web-bootstrap] WASM init failed:', err);
    });

  // Patch globals so liveAgentConsole picks up ghostty-web
  window.Terminal = window.GhosttyWeb.Terminal;
  window.FitAddon = { FitAddon: window.GhosttyWeb.FitAddon };

  // Shim: ghostty-web's InputHandler treats a truthy return from the custom
  // key handler as "I handled it — stop processing", which is the INVERSE of
  // xterm.js convention (truthy = "let xterm handle it normally").
  // liveAgentConsole returns true for most keys (xterm convention: "process
  // normally"). Without this shim, ghostty-web drops every keystroke.
  var _origAttach = window.GhosttyWeb.Terminal.prototype.attachCustomKeyEventHandler;
  window.GhosttyWeb.Terminal.prototype.attachCustomKeyEventHandler = function (handler) {
    _origAttach.call(this, function (ev) {
      return !handler(ev);  // invert: xterm true ("handle it") → ghostty false ("don't stop")
    });
  };

  // ghostty-web has canvas rendering — no WebGL addon needed.
  // Null out so the `if (window.WebglAddon)` guard in liveAgentConsole skips it.
  window.WebglAddon = null;

  // ClipboardAddon: not yet supported in ghostty-web 0.4.0 — null it out.
  window.ClipboardAddon = null;

  console.info('[ghostty-web-bootstrap] active — xterm.js replaced by ghostty-web 0.4.0');
})();
