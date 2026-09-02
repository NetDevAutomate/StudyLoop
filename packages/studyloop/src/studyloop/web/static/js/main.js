/**
 * Frontend module entry point.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The SPA's component logic historically lived in two places with no principle
 * deciding which: a 1,859-line inline <script> in index.html, and components.js.
 * `liveAgentConsole` was in the HTML; `bodyDoubleView` was in the JS. This module
 * is the seam that pattern is being unwound into - one module per component, each
 * independently readable and unit-testable.
 *
 * WHY FACTORIES ARE ASSIGNED TO `window`
 * --------------------------------------
 * Alpine evaluates `x-data="sessionTimer()"` as an expression in GLOBAL scope, so
 * a factory that is only a module export is invisible to it. Assigning to
 * `window` is not laziness - it is the contract between ES modules and Alpine's
 * template expressions. The alternative (Alpine.data() registration) would require
 * rewriting every x-data attribute in the markup, and those attribute strings are
 * asserted by name in dozens of tests.
 *
 * WHY FACTORIES AND NOT CLASSES
 * -----------------------------
 * Alpine wraps whatever the factory returns in a reactive Proxy. Class instances
 * carry their methods on the prototype rather than as own-properties, which makes
 * both reactivity and this-binding subtly wrong. A module exporting a factory
 * gives the encapsulation and testability that classes are wanted for, without
 * fighting the framework.
 *
 * ORDERING
 * --------
 * Module scripts are deferred, and all deferred scripts run before
 * DOMContentLoaded - which is when Alpine starts. So every assignment here lands
 * before any x-data expression is evaluated. `tts-engine.js` has loaded as a
 * module in this app since before this refactor, which is the empirical proof that
 * the ordering holds.
 *
 * FREE-VARIABLE DEPENDENCIES
 * --------------------------
 * `session-timer.js` reads `THRESHOLDS` and `energyBand` as FREE identifiers - it
 * does not import them. That works because an ES module's scope falls through to
 * globalThis for identifiers it never declares, exactly as it did when the factory
 * lived in a classic <script>. It is why the two assignments below must happen,
 * and why they are grouped and labelled rather than left to look incidental:
 * remove either one and the timer breaks at runtime with no build-time warning.
 */

import { extractChunkText, energyBand } from './lib/chunk-text.js';
import { THRESHOLDS } from './lib/timer-thresholds.js';

import { generatePanel } from './components/generate-panel.js';
import { liveAgentConsole } from './components/live-agent-console.js';
import { plansPanel, registerPlansStore } from './components/plans-panel.js';
import { sessionTimer } from './components/session-timer.js';
import { settingsPanel } from './components/settings-panel.js';

/* Shared helpers. Legacy global names preserved exactly: the markup and the
   remaining inline script still call these identifiers, so this refactor moves
   code without renaming anything. */
window._extractChunkText = extractChunkText;
window.energyBand = energyBand;

/* Free-variable dependency of session-timer.js - see the header note. */
window.THRESHOLDS = THRESHOLDS;

/* Alpine component factories, addressed by name from x-data attributes.
   liveAgentConsole is instantiated TWICE per page - once per origin - and its
   default argument is load-bearing: the study console's markup calls it with no
   argument and dozens of assertions address that exact attribute string. */
window.generatePanel = generatePanel;
window.liveAgentConsole = liveAgentConsole;
window.plansPanel = plansPanel;
window.sessionTimer = sessionTimer;
window.settingsPanel = settingsPanel;

/* The plan panel is the first component here needing an Alpine STORE as well as a
   factory, because its two halves live in different DOM subtrees: the plan list is
   inside nav.sidebar and the reader is in the content column, so they cannot share
   one x-data. The store is the seam between them - selecting in the sidebar drives
   the reader.
   Registered on `alpine:init` rather than immediately, because Alpine.store() does
   not exist until Alpine boots. Alpine then calls the store's own init(), which
   loads the plan list - that is what makes a full browser reload repopulate the
   sidebar instead of showing an empty list until something is clicked. */
document.addEventListener('alpine:init', () => registerPlansStore(window.Alpine));
