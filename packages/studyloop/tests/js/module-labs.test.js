/**
 * Lane W (module-contract v1): the Labs client module, `static/js/labs.js`.
 *
 * Pure functions first -- they decide what the DOM may ever show (C7: one entry,
 * hidden with no module, nothing from `hint` / `solution` / `mentorNotes`) -- then
 * the Alpine store/view factories driven with a fake `fetch`, the same way
 * `session-timer.test.js` drives its component: no browser, no server.
 *
 * Run with:  node --test packages/studyloop/tests/js/module-labs.test.js
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MENTOR_ONLY_FIELDS,
  containsMentorOnlyFields,
  drillCommands,
  labsEntries,
  labsStore,
  labsView,
} from '../../src/studyloop/web/static/js/labs.js';

const TASK = {
  id: 'echo-01',
  ref: 'echo-drills/echo-basics/echo-01',
  prompt: 'Print the word `ready` to standard output.',
  successCriteria: ['The word `ready` is printed'],
  phases: ['check'],
  commands: ['studyloop drill check echo-drills/echo-basics/echo-01'],
};

const MODULE = {
  module_id: 'echo-drills',
  version: '0.1.0',
  title: 'Echo drills (offline fixture)',
  topic: 'shell',
  decks: [{ id: 'echo-basics', title: 'Echo basics', tasks: [TASK] }],
};

/* A fetch double keyed by "METHOD path" that records every call. */
function fakeFetch(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    const key = `${method} ${url}`;
    calls.push({ key, body: init.body ? JSON.parse(init.body) : null });
    const route = routes[key];
    if (!route) return { ok: false, status: 404, text: async () => '{"error":"no route"}' };
    const status = route.status || 200;
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => JSON.stringify(route.body),
      json: async () => route.body,
    };
  };
  return { fetch, calls };
}

/* ---- pure helpers ------------------------------------------------------------ */

test('the mentor-only field list is exactly the three §5.6 fields (plus the snake_case twin)', () => {
  assert.deepEqual([...MENTOR_ONLY_FIELDS].sort(), ['hint', 'mentorNotes', 'mentor_notes', 'solution']);
});

test('containsMentorOnlyFields finds a forbidden key anywhere in a payload', () => {
  assert.equal(containsMentorOnlyFields(MODULE), false);
  assert.equal(containsMentorOnlyFields({ labs: [MODULE] }), false);
  const leaked = { labs: [{ ...MODULE, decks: [{ id: 'd', tasks: [{ ...TASK, solution: 'echo ready' }] }] }] };
  assert.equal(containsMentorOnlyFields(leaked), true);
  assert.equal(containsMentorOnlyFields({ a: [{ b: { mentorNotes: 'x' } }] }), true);
  assert.equal(containsMentorOnlyFields(null), false);
});

test('labsEntries is empty for an options payload with no labs key, and for a non-array', () => {
  assert.deepEqual(labsEntries({ topics: [], agents: [] }), []);
  assert.deepEqual(labsEntries({ labs: null }), []);
  assert.deepEqual(labsEntries(null), []);
});

test('labsEntries keeps ids, prompts and success criteria and drops anything mentor-side', () => {
  const tainted = {
    labs: [{
      ...MODULE,
      decks: [{
        id: 'echo-basics',
        title: 'Echo basics',
        tasks: [{ ...TASK, hint: 'Which command prints?', solution: 'echo ready', mentorNotes: 'n' }],
      }],
    }],
  };
  const entries = labsEntries(tainted);
  assert.equal(entries.length, 1);
  const task = entries[0].decks[0].tasks[0];
  assert.equal(task.id, 'echo-01');
  assert.equal(task.prompt, TASK.prompt);
  assert.deepEqual(task.successCriteria, TASK.successCriteria);
  assert.equal(containsMentorOnlyFields(entries), false, 'the client scrubs even if the server slipped');
});

test('drillCommands prefers the server commands and otherwise derives them from the phases', () => {
  assert.deepEqual(drillCommands(TASK), ['studyloop drill check echo-drills/echo-basics/echo-01']);
  assert.deepEqual(
    drillCommands({ ref: 'm/d/t', phases: ['setup', 'check', 'cleanup'] }),
    ['studyloop drill setup m/d/t', 'studyloop drill check m/d/t', 'studyloop drill cleanup m/d/t'],
  );
  assert.deepEqual(drillCommands({ ref: 'm/d/t' }), []);
});

/* ---- the store: one entry, hidden with no module ------------------------------ */

test('the store is unavailable until a refresh finds an installed module', async () => {
  const { fetch, calls } = fakeFetch({ 'GET /api/modules/labs': { body: { labs: [], agents: [] } } });
  const store = labsStore({ fetch });
  assert.equal(store.available, false);
  await store.refresh();
  assert.equal(store.available, false, 'no module -> no Labs entry');
  assert.deepEqual(store.modules, []);
  assert.equal(calls[0].key, 'GET /api/modules/labs');
});

test('the store becomes available with one installed module and exposes it scrubbed', async () => {
  const { fetch } = fakeFetch({
    'GET /api/modules/labs': { body: { labs: [MODULE], agents: [{ value: 'codex', available: true }] } },
  });
  const store = labsStore({ fetch });
  await store.refresh();
  assert.equal(store.available, true);
  assert.equal(store.modules.length, 1);
  assert.equal(store.modules[0].module_id, 'echo-drills');
  assert.deepEqual(store.agents.map((a) => a.value), ['codex']);
  assert.equal(containsMentorOnlyFields(store.modules), false);
});

test('a failed refresh hides Labs rather than showing a stale list', async () => {
  const { fetch } = fakeFetch({ 'GET /api/modules/labs': { status: 500, body: { error: 'boom' } } });
  const store = labsStore({ fetch });
  store.modules = [MODULE];
  store.available = true;
  await store.refresh();
  assert.equal(store.available, false);
  assert.deepEqual(store.modules, []);
  assert.match(store.error, /labs/i);
});

/* ---- the view: start inside the one claimed session, cancel, no execution ----- */

function viewWith(routes, extra = {}) {
  const { fetch, calls } = fakeFetch(routes);
  const store = labsStore({ fetch });
  const navigated = [];
  const reloads = [];
  const storage = new Map();
  const view = labsView({
    fetch,
    store,
    navigate: (v) => navigated.push(v),
    reload: () => reloads.push(true),
    storage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, v),
      removeItem: (k) => storage.delete(k),
    },
    ...extra,
  });
  return { view, store, calls, navigated, reloads, storage };
}

const START_201 = {
  status: 201,
  body: {
    study_session_id: 'study-1',
    topic: 'Lab: echo-drills/echo-basics/echo-01',
    transport: 'pty',
    ws_url: '/api/session/ws?study_session_id=study-1',
    attached: false,
    drill: { module_id: 'echo-drills', deck_id: 'echo-basics', task_id: 'echo-01', ref: TASK.ref,
      prompt: TASK.prompt, successCriteria: TASK.successCriteria, phases: ['check'], commands: TASK.commands },
  },
};

test('starting a drill posts the drill identity (and the chosen agent) to the labs start route', async () => {
  const { view, calls } = viewWith({ 'POST /api/modules/labs/start': START_201 });
  view.agent = 'codex';
  const ok = await view.startDrill(MODULE, TASK);
  assert.equal(ok, true);
  const start = calls.find((c) => c.key === 'POST /api/modules/labs/start');
  assert.ok(start, 'the UI never issued POST /api/modules/labs/start');
  assert.deepEqual(start.body, {
    module_id: 'echo-drills', deck_id: 'echo-basics', task_id: 'echo-01', agent: 'codex', transport: 'pty',
  });
});

test('a fresh start (201) lands the learner in the Study Session view and re-reads the live session', async () => {
  const { view, navigated, reloads, storage } = viewWith({ 'POST /api/modules/labs/start': START_201 });
  view.agent = 'codex';
  await view.startDrill(MODULE, TASK);
  assert.deepEqual(navigated, ['study-session']);
  assert.equal(reloads.length, 1, 'the one start path re-adopts the session on load');
  assert.equal(view.activeDrill.ref, TASK.ref);
  assert.ok(storage.size >= 1, 'the live drill survives the reload');
});

test('an attached start (200) does not reload: the session was already the learner\'s', async () => {
  const attached = { status: 200, body: { ...START_201.body, attached: true, reattach_url: START_201.body.ws_url } };
  const { view, navigated, reloads } = viewWith({ 'POST /api/modules/labs/start': attached });
  view.agent = 'codex';
  await view.startDrill(MODULE, TASK);
  assert.deepEqual(navigated, ['study-session']);
  assert.equal(reloads.length, 0);
  assert.equal(view.activeDrill.ref, TASK.ref);
});

test('the active drill never carries mentor-side fields, whatever the server sent', async () => {
  const leaky = { status: 201, body: { ...START_201.body, drill: { ...START_201.body.drill, hint: 'h', solution: 's', mentorNotes: 'm' } } };
  const { view } = viewWith({ 'POST /api/modules/labs/start': leaky });
  view.agent = 'codex';
  await view.startDrill(MODULE, TASK);
  assert.equal(containsMentorOnlyFields(view.activeDrill), false);
});

test('a refused start (409 from another view, 503 without an agent) is shown, not swallowed', async () => {
  const { view, navigated } = viewWith({
    'POST /api/modules/labs/start': { status: 409, body: { error: 'A session is live in Body Double', study_session_id: 'x', origin: 'body-double' } },
  });
  view.agent = 'codex';
  const ok = await view.startDrill(MODULE, TASK);
  assert.equal(ok, false);
  assert.match(view.startError, /Body Double/);
  assert.deepEqual(navigated, []);
  assert.equal(view.activeDrill, null);
});

test('start without an agent is refused locally with the picker\'s own hint', async () => {
  const { view, calls } = viewWith({ 'POST /api/modules/labs/start': START_201 });
  view.agent = '';
  const ok = await view.startDrill(MODULE, TASK);
  assert.equal(ok, false);
  assert.match(view.startError, /agent/i);
  assert.equal(calls.length, 0, 'nothing was posted');
});

test('cancel posts to the cancel route, clears the drill and leaves the session alone', async () => {
  const { view, calls, storage } = viewWith({
    'POST /api/modules/labs/start': START_201,
    'POST /api/modules/labs/cancel': { body: { cancelled: true, study_session_id: 'study-1' } },
  });
  view.agent = 'codex';
  await view.startDrill(MODULE, TASK);
  await view.cancelDrill();
  assert.ok(calls.some((c) => c.key === 'POST /api/modules/labs/cancel'));
  assert.ok(!calls.some((c) => c.key === 'POST /api/session/end'), 'cancel never ends the session');
  assert.equal(view.activeDrill, null);
  assert.equal(storage.size, 0);
});

test('a start in flight can be cancelled: the late 201 is dropped and nothing is adopted', async () => {
  let resolveStart;
  const pending = new Promise((resolve) => { resolveStart = resolve; });
  const fetch = async (url, init = {}) => {
    if ((init.method || 'GET') === 'POST' && url === '/api/modules/labs/start') {
      await pending;
      return { ok: true, status: 201, text: async () => JSON.stringify(START_201.body) };
    }
    return { ok: true, status: 200, text: async () => '{"cancelled":true}', json: async () => ({ cancelled: true }) };
  };
  const navigated = [];
  const view = labsView({ fetch, store: labsStore({ fetch }), navigate: (v) => navigated.push(v), reload: () => {}, storage: null });
  view.agent = 'codex';
  const started = view.startDrill(MODULE, TASK);
  assert.equal(view.starting, true);
  await view.cancelDrill();
  resolveStart();
  const ok = await started;
  assert.equal(ok, false);
  assert.equal(view.activeDrill, null);
  assert.deepEqual(navigated, []);
});

test('the view restores a live drill from storage on init and reads the agents from the store', async () => {
  const { view, store, storage } = viewWith({
    'GET /api/modules/labs': { body: { labs: [MODULE], agents: [{ value: 'codex', available: true }, { value: 'claude', available: false }] } },
  });
  storage.set('studyloop.labs.activeDrill', JSON.stringify(START_201.body.drill));
  await view.init();
  assert.equal(store.available, true);
  assert.equal(view.activeDrill.ref, TASK.ref);
  assert.equal(view.agent, 'codex', 'the first available agent is pre-selected, as in the picker');
});
