/**
 * Frontend module entry point.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The SPA's component logic historically lived in two places with no principle
 * deciding which: a 1,859-line inline <script> in index.html, and components.js.
 * `liveAgentConsole` was in the HTML; `bodyDoubleView` was in the JS. This module
 * is the single seam that pattern is being unwound into — one module per
 * component, each independently readable and unit-testable.
 *
 * WHY FACTORIES ARE ASSIGNED TO `window`
 * --------------------------------------
 * Alpine evaluates `x-data="energyBand()"` as an expression in GLOBAL scope, so a
 * factory that is only a module export is invisible to it. Assigning to `window`
 * is not laziness — it is the contract between ES modules and Alpine's template
 * expressions. The alternative (Alpine.data() registration) would require
 * rewriting every x-data attribute in the markup, and those attribute strings are
 * asserted by name in dozens of tests.
 *
 * WHY FACTORIES AND NOT CLASSES
 * -----------------------------
 * Alpine wraps whatever the factory returns in a reactive Proxy. Class instances
 * carry their methods on the prototype rather than as own-properties, which makes
 * both reactivity and `this` binding subtly wrong. A module exporting a factory
 * gives the encapsulation and testability that classes are wanted for, without
 * fighting the framework.
 *
 * ORDERING
 * --------
 * Module scripts are deferred, and all deferred scripts run before
 * DOMContentLoaded — which is when Alpine starts. So every assignment here lands
 * before any x-data expression is evaluated. `tts-engine.js` has loaded as a
 * module in this app since before this refactor, which is the empirical proof
 * that the ordering holds.
 */

import { extractChunkText, energyBand } from './lib/chunk-text.js';

/* Legacy global names preserved exactly. The inline script still calls
   _extractChunkText, and the markup still calls energyBand(...), so both keep
   the identifiers they already had - this refactor moves code, it does not
   rename anything. */
window._extractChunkText = extractChunkText;
window.energyBand = energyBand;
