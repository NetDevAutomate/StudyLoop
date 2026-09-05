/**
 * Unit tests for the Today panel component factory.
 *
 * Uses `node --test` — built into Node, zero dependencies, no package.json and
 * no build step (same rationale as plans-panel.test.js and
 * generate-panel.test.js).
 *
 * WHY THIS IS POSSIBLE WITHOUT A BROWSER: the factory returns a plain object —
 * no DOM and no Alpine are touched at construction time. `fetch` and `window`
 * are only referenced inside methods, so stubbing those globals proves the
 * launch-state loading and the one-click navigation contract in milliseconds.
 * The first test is a characterization of the factory's pre-existing surface:
 * it moved here verbatim from the legacy components.js monolith, and the
 * markup addresses every one of these names.
 */
// Run with:  node --test 'packages/studyloop/tests/js/**/*.test.js'

import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { todayPanel } from
  '../../src/studyloop/web/static/js/components/today-panel.js';

/* ---------------------------------------------------------------- *
 * Test doubles — fetch routed by URL, window as a navigation recorder.
 * ---------------------------------------------------------------- */

const jsonResponse = (body) => new Response(JSON.stringify(body), { status: 200 });

/** Stub fetch so each URL prefix resolves to its own JSON body (or a miss). */
function stubFetch(routes) {
  globalThis.fetch = async (url) => {
    for (const [prefix, body] of Object.entries(routes)) {
      if (String(url).startsWith(prefix)) {
        if (body instanceof Error) throw body;
        return jsonResponse(body);
      }
    }
    return new Response('missing', { status: 404 });
  };
}

/** A window whose only job is to record navigation attempts. */
function navRecorder() {
  return {
    opened: [],
    assigned: [],
    open(url, target, features) {
      this.opened.push({ url, target, features });
      return null;
    },
    location: {
      assign(url) {
        globalThis.window.assigned.push(url);
      },
    },
    dispatchEvent() {},
  };
}

const XTILES_TARGET = {
  provider: 'xtiles',
  label: 'xTiles',
  href: 'https://xtiles.app/view/test-project',
  enabled: true,
  disabled_reason: null,
  device_locality: 'not_applicable',
};

const realFetch = globalThis.fetch;
const hadWindow = 'window' in globalThis;

beforeEach(() => {
  globalThis.window = navRecorder();
});

afterEach(() => {
  globalThis.fetch = realFetch;
  if (!hadWindow) delete globalThis.window;
  else globalThis.window = undefined;
});

/* ---------------------------------------------------------------- *
 * Characterization — the moved factory keeps its existing surface.
 * ---------------------------------------------------------------- */

test('todayPanel: the moved factory keeps the surface the markup addresses', () => {
  const panel = todayPanel();

  assert.equal(panel.loading, true);
  assert.equal(panel.plan, null);
  assert.deepEqual(panel.parked, []);
  assert.equal(panel.resumeKind, null);
  assert.equal(panel.resumeLabel, '');
  assert.equal(panel.showAlternates, false);

  for (const method of [
    'init',
    'resumeAction',
    'startPrimary',
    'startAction',
    'pickUpParked',
    'dismissParked',
    '_viewFor',
  ]) {
    assert.equal(typeof panel[method], 'function', `${method} must be a function`);
  }
  /* The action_type → view map is behaviour the Today buttons depend on. */
  assert.equal(panel._viewFor('review'), 'flashcards');
  assert.equal(panel._viewFor('conversation'), 'study-session');
  assert.equal(panel._viewFor('unknown-kind'), 'flashcards');
});


/* ---------------------------------------------------------------- *
 * Launch-state loading — Gherkin: "Page loads with an enabled target
 * → no provider navigation occurs".
 * ---------------------------------------------------------------- */

test('init: loads the launch target without navigating, even when it is enabled', async () => {
  stubFetch({ '/api/second-brain/launch-target': XTILES_TARGET });
  const panel = todayPanel();

  await panel.init();

  assert.deepEqual(panel.launchTarget, XTILES_TARGET);
  assert.equal(panel.loading, false);
  assert.deepEqual(globalThis.window.opened, []);
  assert.deepEqual(globalThis.window.assigned, []);
});


test('launch state: provider none (or no state at all) renders no launcher action', async () => {
  stubFetch({
    '/api/second-brain/launch-target': {
      provider: 'none',
      label: 'Second Brain',
      href: null,
      enabled: false,
      disabled_reason: 'No second brain provider is selected.',
      device_locality: 'not_applicable',
    },
  });
  const panel = todayPanel();

  assert.equal(panel.hasBrainAction, false, 'no action before init');
  await panel.init();
  assert.equal(panel.hasBrainAction, false, 'no action for provider none');
});


/* Characterization: the shared `get` helper already swallows transport and
   non-2xx failures into null, so a broken launch API must degrade to "no
   action" rather than a thrown init or a phantom button. */
test('launch state: a failing launch API degrades to no action, init still completes', async () => {
  stubFetch({ '/api/second-brain/launch-target': new Error('connection refused') });
  const panel = todayPanel();

  await panel.init();

  assert.equal(panel.launchTarget, null);
  assert.equal(panel.hasBrainAction, false);
  assert.equal(panel.loading, false);
  assert.deepEqual(globalThis.window.opened, []);
  assert.deepEqual(globalThis.window.assigned, []);
});


test('launch state: re-running init (a refresh) adopts the new state without navigating', async () => {
  stubFetch({ '/api/second-brain/launch-target': XTILES_TARGET });
  const panel = todayPanel();
  await panel.init();
  assert.equal(panel.launchTarget.enabled, true);

  const cleared = {
    provider: 'none',
    label: 'Second Brain',
    href: null,
    enabled: false,
    disabled_reason: 'No second brain provider is selected.',
    device_locality: 'not_applicable',
  };
  stubFetch({ '/api/second-brain/launch-target': cleared });
  await panel.init();

  assert.deepEqual(panel.launchTarget, cleared);
  assert.equal(panel.hasBrainAction, false);
  assert.deepEqual(globalThis.window.opened, []);
  assert.deepEqual(globalThis.window.assigned, []);
});


/* ---------------------------------------------------------------- *
 * openBrain() — Gherkin: "Learner clicks enabled xTiles action →
 * the exact destination opens once in a new protected tab".
 * ---------------------------------------------------------------- */

test('openBrain: an enabled xTiles target opens exactly once in a protected tab', async () => {
  stubFetch({ '/api/second-brain/launch-target': XTILES_TARGET });
  const panel = todayPanel();
  await panel.init();

  panel.openBrain();

  assert.deepEqual(globalThis.window.opened, [
    {
      url: 'https://xtiles.app/view/test-project',
      target: '_blank',
      features: 'noopener,noreferrer',
    },
  ]);
  assert.deepEqual(globalThis.window.assigned, [], 'the current context must not navigate');
});


/* Gherkin: "Learner clicks enabled Obsidian action → the current browser
   context navigates once to the custom URI AND no empty tab is created". */
test('openBrain: an enabled Obsidian target navigates the current context, no new tab', async () => {
  const obsidianTarget = {
    provider: 'obsidian',
    label: 'Obsidian',
    href: 'obsidian://open?path=%2FUsers%2Flearner%2Fvault%2FStudy%2FToday.md',
    enabled: true,
    disabled_reason: null,
    device_locality: 'local',
  };
  stubFetch({ '/api/second-brain/launch-target': obsidianTarget });
  const panel = todayPanel();
  await panel.init();

  panel.openBrain();

  assert.deepEqual(globalThis.window.assigned, [obsidianTarget.href]);
  assert.deepEqual(globalThis.window.opened, [], 'no tab may be created for a custom URI');
});


/* Gherkin: "Today has a disabled configured provider → activating it
   performs no navigation" — the module-level half of that contract. */
test('openBrain: a disabled target never navigates, whatever the provider', async () => {
  stubFetch({
    '/api/second-brain/launch-target': {
      provider: 'xtiles',
      label: 'xTiles',
      href: null,
      enabled: false,
      disabled_reason:
        "No xTiles destination is retained. Run 'studyloop brain destination set "
        + "--provider xtiles --url URL' to retain one.",
      device_locality: 'not_applicable',
    },
  });
  const panel = todayPanel();
  await panel.init();
  assert.equal(panel.hasBrainAction, true, 'the disabled action is still rendered');

  panel.openBrain();

  assert.deepEqual(globalThis.window.opened, []);
  assert.deepEqual(globalThis.window.assigned, []);
});
