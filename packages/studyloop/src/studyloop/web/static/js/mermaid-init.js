/**
 * Mermaid initialization — moved out of an inline <script> in index.html
 * (ttyd retirement stage 4, R-13b) so `script-src 'self'` can be a strict
 * Content-Security-Policy with no `'unsafe-inline'` exception. Runs as a
 * plain classic script at the same position the inline block used to
 * occupy, so it still executes before Alpine's deferred script (Alpine only
 * runs after the whole document has parsed).
 *
 * securityLevel: 'strict' is deliberate, not a default — it is the
 * documented mitigation for mermaid's history of `securityLevel: 'loose'`
 * XSS advisories, since diagram source can come from agent-authored
 * markdown. components.js's `_mermaidInitForPalette()` re-initializes with
 * theme-matched colours before a themed render; this call is only the
 * page-load default so `securityLevel: 'strict'` is set from the moment
 * `window.mermaid` exists, before anything else can call it.
 */
if (window.mermaid) {
  window.mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' });
}
