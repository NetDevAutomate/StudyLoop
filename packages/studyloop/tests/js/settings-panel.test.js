/**
 * Unit tests for the Settings panel's Second Brain section state.
 *
 * Uses `node --test` — built into Node, zero dependencies, no package.json and
 * no build step (same rationale as plans-panel.test.js and today-panel.test.js).
 *
 * WHY THIS IS POSSIBLE WITHOUT A BROWSER: `settingsPanel()` returns a plain
 * object and only its methods touch `fetch`, so stubbing that one global
 * proves the whole provider-card state matrix in milliseconds. The security
 * property under test is a NEGATIVE one — the stored brain state must never
 * retain the launch `href` — which is exactly the kind of assertion a
 * rendered-page test cannot make about component state.
 */
// Run with:  node --test 'packages/studyloop/tests/js/**/*.test.js'

import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { settingsPanel } from
  '../../src/studyloop/web/static/js/components/settings-panel.js';

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

const ENABLED_XTILES = {
  provider: 'xtiles',
  label: 'xTiles',
  href: 'https://xtiles.app/view/private-project-path',
  enabled: true,
  disabled_reason: null,
  device_locality: 'not_applicable',
};

const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});

/* ---------------------------------------------------------------- *
 * refreshBrain — the launch href must never survive into panel state,
 * so no Settings binding can ever disclose the complete retained URL.
 * ---------------------------------------------------------------- */

test('refreshBrain: stores the provider state with the href discarded', async () => {
  stubFetch({ '/api/second-brain/launch-target': ENABLED_XTILES });
  const panel = settingsPanel();

  await panel.refreshBrain();

  assert.equal(panel.brain.provider, 'xtiles');
  assert.equal(panel.brain.label, 'xTiles');
  assert.equal(panel.brain.enabled, true);
  assert.equal(panel.brain.disabled_reason, null);
  assert.equal('href' in panel.brain, false, 'the launch href must not be retained');
  assert.equal(
    JSON.stringify(panel.brain).includes('xtiles.app'),
    false,
    'no fragment of the destination URL may survive into panel state'
  );
});


/* ---------------------------------------------------------------- *
 * Card state matrix — Gherkin: "Settings shows selected and inactive
 * providers → the selected provider is active and the other is muted".
 * ---------------------------------------------------------------- */

test('brainCardState: the selected provider is active, the other is muted', async () => {
  stubFetch({ '/api/second-brain/launch-target': ENABLED_XTILES });
  const panel = settingsPanel();
  await panel.refreshBrain();

  assert.equal(panel.brainCardState('xtiles'), 'active');
  assert.equal(panel.brainCardState('obsidian'), 'muted');
});


/* The API reason for a disabled selected provider IS the configuration
   guidance: for xTiles with no destination it names the exact CLI command
   pattern, and Settings must surface it rather than invent its own. */
test('brainGuidance: an active-but-disabled provider surfaces the API reason', async () => {
  const reason =
    "No xTiles destination is retained. Run 'studyloop brain destination set "
    + "--provider xtiles --url URL' to retain one.";
  stubFetch({
    '/api/second-brain/launch-target': {
      provider: 'xtiles',
      label: 'xTiles',
      href: null,
      enabled: false,
      disabled_reason: reason,
      device_locality: 'not_applicable',
    },
  });
  const panel = settingsPanel();
  await panel.refreshBrain();

  assert.equal(panel.brainGuidance('xtiles'), reason);
});


test('brainGuidance: a muted provider gets selection guidance naming brain enable', async () => {
  stubFetch({ '/api/second-brain/launch-target': ENABLED_XTILES });
  const panel = settingsPanel();
  await panel.refreshBrain();

  const guidance = panel.brainGuidance('obsidian');
  assert.ok(
    guidance.includes('studyloop brain enable obsidian'),
    `guidance must name the selection command, got: ${guidance}`
  );
});


/* A broken launch API must degrade to two honest muted cards — never a
   thrown init and never a card claiming a provider is active. */
test('brain state: a failing launch API leaves both cards muted with guidance', async () => {
  stubFetch({ '/api/second-brain/launch-target': new Error('connection refused') });
  const panel = settingsPanel();

  await panel.refreshBrain();

  assert.equal(panel.brain, null);
  assert.equal(panel.brainCardState('obsidian'), 'muted');
  assert.equal(panel.brainCardState('xtiles'), 'muted');
  assert.ok(panel.brainGuidance('xtiles').includes('studyloop brain enable xtiles'));
});
