/**
 * "Plan with architect" — the launch hand-off between the Plans view, the
 * session timer and the live console (#14, design §5, T5.1).
 *
 * Three components share one contract and none of them may duplicate another's
 * job:
 *
 *   plansStore.startArchitect()   dispatches ONE `plan-architect-request`
 *                                  window event carrying the purpose and the
 *                                  learner's subject — it never posts, never
 *                                  opens a socket, never listens for the
 *                                  console's `study-session-start`.
 *   sessionTimer                   owns the POST to /api/session/start (with
 *                                  `purpose`), the 409 handling and the ONE
 *                                  `study-session-start` event the console
 *                                  mounts on — the same path the Start button
 *                                  takes, so a planning launch cannot drift
 *                                  from a focus launch.
 *   liveAgentConsole               reads `purpose` from the start event (first
 *                                  paint) and from /api/session/state (reload)
 *                                  and renders the planning label.
 *
 * `node --test`, no DOM: `window` is a bare EventTarget with a `location`,
 * `fetch` is a recorder, `Alpine.store('nav')` records `go()`. The parts that
 * need xterm are stubbed on the instance (`_mountXterm`), which is exactly the
 * seam the test is about: the console must be TOLD to mount once, by one
 * event, not mounted twice by two.
 */
// Run with:  node --test 'packages/studyloop/tests/js/**/*.test.js'

import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { plansStore } from
  '../../src/studyloop/web/static/js/components/plans-panel.js';
import { sessionTimer } from
  '../../src/studyloop/web/static/js/components/session-timer.js';
import { liveAgentConsole } from
  '../../src/studyloop/web/static/js/components/live-agent-console.js';
import { energyBand } from
  '../../src/studyloop/web/static/js/lib/chunk-text.js';

/* Free references session-timer.js expects from the page (see session-timer.test.js). */
globalThis.THRESHOLDS = {
  high: { green: 25, amber: 50 },
  medium: { green: 20, amber: 40 },
  low: { green: 15, amber: 30 },
};
globalThis.energyBand = energyBand;

const realFetch = globalThis.fetch;
const realWindow = globalThis.window;
const realAlpine = globalThis.Alpine;
const realWebSocket = globalThis.WebSocket;

class FakeWindow extends EventTarget {
  constructor() {
    super();
    this.location = { hash: '', protocol: 'http:', host: 'studyloop.test' };
    this.listeners = {};
  }

  /* Count registrations per event name so a test can assert who listens. */
  addEventListener(type, listener, options) {
    this.listeners[type] = (this.listeners[type] || 0) + 1;
    return super.addEventListener(type, listener, options);
  }
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

let win;
let posts;
let navCalls;
let sockets;
/* Every timer built in a test, so afterEach can stop its setInterval tick —
   an open interval keeps the node process alive and the test file never exits. */
let timers;

beforeEach(() => {
  win = new FakeWindow();
  posts = [];
  navCalls = [];
  sockets = [];
  timers = [];
  globalThis.window = win;
  globalThis.WebSocket = class {
    constructor(url) { sockets.push(String(url)); }
  };
  globalThis.Alpine = {
    store(name) {
      if (name === 'nav') return { go: (view) => { navCalls.push(view); win.location.hash = view; } };
      if (name === 'terminalEngine') return { hydrate() {} };
      if (name === 'toast') return { show() {} };
      return undefined;
    },
  };
  /* In a browser `window.Alpine` IS `globalThis.Alpine`; mirror that on the fake. */
  win.Alpine = globalThis.Alpine;
  globalThis.fetch = async (url, opts = {}) => {
    const path = String(url);
    if (path.endsWith('/api/session/options')) return jsonResponse(200, null);
    if (path.endsWith('/api/session/state')) return jsonResponse(200, {});
    if (path.endsWith('/api/backlog')) return jsonResponse(200, { active_count: 0, max_active: 3 });
    if (path.endsWith('/api/plans')) return jsonResponse(200, { plans: [], count: 0 });
    if (path.endsWith('/api/session/start')) {
      const body = JSON.parse(opts.body);
      posts.push(body);
      return jsonResponse(201, {
        study_session_id: 'study-42',
        topic: body.topic || 'Study plan',
        energy: body.energy,
        agent: body.agent,
        transport: body.transport,
        purpose: body.purpose,
        ws_url: '/api/session/ws?study_session_id=study-42',
      });
    }
    throw new Error(`unexpected fetch ${path}`);
  };
  /* Reset the module singleton's launch state between tests. The result
     listener is re-hooked because each test gets a fresh fake window (in a
     browser the window never changes, so the hook is one-shot there). */
  plansStore.architectSubject = '';
  plansStore.architectBrainDump = '';
  plansStore.architectLaunching = false;
  plansStore.architectStatus = '';
  plansStore._architectHooked = false;
});

afterEach(() => {
  for (const timer of timers) {
    clearInterval(timer.interval);
    clearTimeout(timer.messageTimeout);
  }
  globalThis.fetch = realFetch;
  globalThis.window = realWindow;
  globalThis.Alpine = realAlpine;
  globalThis.WebSocket = realWebSocket;
});

/** A timer with init() run under the stubs and an agent already resolved. */
async function readyTimer() {
  const timer = sessionTimer();
  timers.push(timer);
  timer.$nextTick = (cb) => cb();
  await timer.init();
  timer.agent = 'claude';
  return timer;
}

function requestEvents() {
  const seen = [];
  win.addEventListener('plan-architect-request', (e) => seen.push(e.detail));
  return seen;
}

function startEvents() {
  const seen = [];
  win.addEventListener('study-session-start', (e) => seen.push(e.detail));
  return seen;
}

/* Let the async handler chain (fetch → dispatch) settle. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

/* ---------------------------------------------------------------- *
 * plansStore.startArchitect: one request event, nothing else
 * ---------------------------------------------------------------- */

test('startArchitect dispatches exactly one plan-architect-request with purpose planning and the subject', () => {
  const seen = requestEvents();
  plansStore.architectSubject = '  SQL window functions ';

  plansStore.startArchitect();

  assert.equal(seen.length, 1);
  assert.deepEqual(seen[0], { purpose: 'planning', topic: 'SQL window functions', brainDump: '' });
  assert.equal(plansStore.architectLaunching, true);
  assert.ok(plansStore.architectStatus.length > 0, 'the status region says what is happening');
});

test('startArchitect with no subject sends an empty topic — the server names it Study plan', () => {
  const seen = requestEvents();

  plansStore.startArchitect();

  assert.deepEqual(seen[0], { purpose: 'planning', topic: '', brainDump: '' });
});

test('startArchitect carries the learner\'s brain dump in the request detail, trimmed, never in the topic (#14, D-B)', () => {
  const seen = requestEvents();
  plansStore.architectSubject = 'SQL';
  plansStore.architectBrainDump = '  I keep guessing at window frames.\n\nTried the docs twice.  ';

  plansStore.startArchitect();

  assert.equal(seen.length, 1);
  assert.deepEqual(seen[0], {
    purpose: 'planning',
    topic: 'SQL',
    brainDump: 'I keep guessing at window frames.\n\nTried the docs twice.',
  });
});

test('the Plans view never posts, never opens a socket and never listens for the console event', async () => {
  plansStore.startArchitect();
  await settle();

  assert.equal(posts.length, 0, 'the Plans view must not POST /api/session/start itself');
  assert.equal(sockets.length, 0, 'the Plans view must not open a WebSocket');
  assert.equal(win.listeners['study-session-start'] || 0, 0,
    'the console mounts on study-session-start; the Plans view must not add a second listener');
});

test('a second click while a launch is in flight is a no-op', () => {
  const seen = requestEvents();
  plansStore.startArchitect();
  plansStore.startArchitect();
  assert.equal(seen.length, 1);
});

test('plan-architect-result resets the launch state and reports the outcome', async () => {
  await plansStore.init();
  plansStore.startArchitect();
  assert.equal(plansStore.architectLaunching, true);

  win.dispatchEvent(new CustomEvent('plan-architect-result', { detail: { ok: false, error: 'A session is already active' } }));
  assert.equal(plansStore.architectLaunching, false);
  assert.match(plansStore.architectStatus, /already active/);

  plansStore.startArchitect();
  win.dispatchEvent(new CustomEvent('plan-architect-result', { detail: { ok: true } }));
  assert.equal(plansStore.architectLaunching, false);
  assert.match(plansStore.architectStatus, /Study Session/);
});

/* ---------------------------------------------------------------- *
 * sessionTimer: the one owner of the POST and of study-session-start
 * ---------------------------------------------------------------- */

test('sessionTimer answers plan-architect-request with one POST carrying purpose planning and navigates to the console', async () => {
  const timer = await readyTimer();
  const starts = startEvents();

  win.dispatchEvent(new CustomEvent('plan-architect-request', { detail: { purpose: 'planning', topic: 'SQL' } }));
  await settle();

  assert.equal(posts.length, 1);
  assert.equal(posts[0].purpose, 'planning');
  assert.equal(posts[0].topic, 'SQL');
  assert.equal(posts[0].origin, 'study');
  assert.equal(posts[0].agent, 'claude');
  assert.deepEqual(navCalls, ['study-session']);
  assert.equal(starts.length, 1, 'exactly one study-session-start per launch');
  assert.equal(starts[0].purpose, 'planning');
  assert.equal(starts[0].origin, 'study');
  assert.equal(starts[0].wsUrl, '/api/session/ws?study_session_id=study-42');
  assert.equal(timer.sessionActive, true);
  assert.equal(timer.purpose, 'planning');
});

test('sessionTimer forwards the brain dump to the server as brain_dump, never as the topic', async () => {
  await readyTimer();

  win.dispatchEvent(new CustomEvent('plan-architect-request', {
    detail: { purpose: 'planning', topic: '', brainDump: 'Stuck on frames.' },
  }));
  await settle();
  assert.equal(posts.length, 1);
  assert.equal(posts[0].brain_dump, 'Stuck on frames.');
  assert.equal(posts[0].topic, '', 'the dump never becomes the topic');
  assert.equal(posts[0].purpose, 'planning');
});

test('a launch without a brain dump omits the key — the server treats a missing key and null alike', async () => {
  await readyTimer();

  win.dispatchEvent(new CustomEvent('plan-architect-request', { detail: { purpose: 'planning', topic: 'SQL' } }));
  await settle();
  assert.equal(posts.length, 1);
  assert.equal(Object.prototype.hasOwnProperty.call(posts[0], 'brain_dump'), false);
});

test('a focus start never carries a brain dump, even if the Plans view left one behind', async () => {
  const timer = await readyTimer();
  plansStore.architectBrainDump = 'left behind';
  timer.topicInput = 'Python';
  await timer.startSession();
  assert.equal(posts.length, 1);
  assert.equal(posts[0].purpose, 'focus');
  assert.equal(Object.prototype.hasOwnProperty.call(posts[0], 'brain_dump'), false);
});

test('an empty subject is posted as topic "" for a planning launch (the focus path still refuses a blank topic)', async () => {
  const timer = await readyTimer();

  win.dispatchEvent(new CustomEvent('plan-architect-request', { detail: { purpose: 'planning', topic: '' } }));
  await settle();
  assert.equal(posts.length, 1);
  assert.equal(posts[0].topic, '');
  assert.equal(posts[0].purpose, 'planning');

  await timer.confirmEndSession().catch(() => {});
  posts.length = 0;
  timer.topicInput = '';
  await timer.startSession();
  assert.equal(posts.length, 0, 'a focus start with no topic never reaches the server');
});

test('the Start button path is unchanged: a focus start posts purpose focus and one start event', async () => {
  const timer = await readyTimer();
  const starts = startEvents();
  timer.topicInput = 'Decorators';

  await timer.startSession();

  assert.equal(posts.length, 1);
  assert.equal(posts[0].purpose, 'focus');
  assert.equal(posts[0].topic, 'Decorators');
  assert.equal(starts.length, 1);
  assert.equal(starts[0].purpose, 'focus');
  assert.equal(timer.purpose, 'focus');
});

test('sessionTimer reports the outcome back to the Plans view once per launch', async () => {
  await readyTimer();
  const results = [];
  win.addEventListener('plan-architect-result', (e) => results.push(e.detail));

  win.dispatchEvent(new CustomEvent('plan-architect-request', { detail: { purpose: 'planning', topic: '' } }));
  await settle();

  assert.equal(results.length, 1);
  assert.equal(results[0].ok, true);
});

test('init() twice (Alpine auto-init + x-init="init()") still means one listener, one POST per click', async () => {
  /* The page runs init() twice per load — Alpine calls it for an x-data object
     that defines one AND the markup says x-init="init()". Two listeners meant
     two POSTs per click and a 409 for the second, found by the browser
     journey. Listener registration is idempotent. */
  const timer = await readyTimer();
  await timer.init();
  timer.agent = 'claude';
  const starts = startEvents();

  win.dispatchEvent(new CustomEvent('plan-architect-request', { detail: { purpose: 'planning', topic: '' } }));
  await settle();

  assert.equal(win.listeners['plan-architect-request'], 1);
  assert.equal(win.listeners['today-resume'], 1);
  assert.equal(posts.length, 1, 'one click, one POST — whatever init() was called');
  assert.equal(starts.length, 1);
});

test('a 409 on a planning launch keeps the existing conflict handling and reports failure', async () => {
  const timer = await readyTimer();
  const results = [];
  win.addEventListener('plan-architect-result', (e) => results.push(e.detail));
  const conflict = {
    error: 'A session is already active on "Study plan" — its browser tab may have closed but the agent is still running. Reattach to it, or end it first.',
    study_session_id: 'study-7', topic: 'Study plan', agent: 'claude', detached: false,
    reattach_url: '/api/session/ws?study_session_id=study-7',
  };
  const baseFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => (String(url).endsWith('/api/session/start')
    ? jsonResponse(409, conflict) : baseFetch(url, opts));

  win.dispatchEvent(new CustomEvent('plan-architect-request', { detail: { purpose: 'planning', topic: '' } }));
  await settle();

  assert.equal(timer.sessionActive, false);
  assert.ok(timer.conflictSession, 'the conflict block has the blocking session');
  assert.equal(timer.conflictSession.reattach_url, conflict.reattach_url);
  assert.equal(timer.conflictIsOwn, true, 'reattach is offerable');
  assert.equal(timer.startError, conflict.error);
  assert.equal(results.length, 1);
  assert.equal(results[0].ok, false);
  assert.equal(results[0].error, conflict.error);
});

/* ---------------------------------------------------------------- *
 * liveAgentConsole: the label follows purpose on first paint and on reload
 * ---------------------------------------------------------------- */

function consoleWithStubbedMount() {
  const con = liveAgentConsole();
  con._mountXterm = (detail) => { con.mounted = (con.mounted || 0) + 1; con.connected = true; con.terminalMode = 'xterm'; con.lastDetail = detail; };
  con._mountAcpChat = con._mountXterm;
  return con;
}

test('liveAgentConsole labels a planning start and clears the label on stop', () => {
  const con = consoleWithStubbedMount();

  con.start({ transport: 'pty', wsUrl: '/api/session/ws?study_session_id=s', purpose: 'planning', origin: 'study' });
  assert.equal(con.purpose, 'planning');
  assert.match(con.purposeLabel, /planning/i);
  assert.equal(con.mounted, 1, 'one mount per start event');

  con.stop();
  assert.equal(con.purpose, 'focus');
  assert.equal(con.purposeLabel, '');
});

test('liveAgentConsole treats a missing purpose as focus — no label for today\'s sessions', () => {
  const con = consoleWithStubbedMount();
  con.start({ transport: 'pty', wsUrl: '/api/session/ws?study_session_id=s', origin: 'study' });
  assert.equal(con.purpose, 'focus');
  assert.equal(con.purposeLabel, '');
});

test('liveAgentConsole adopts purpose from /api/session/state on reload', async () => {
  const baseFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => (String(url).endsWith('/api/session/state')
    ? jsonResponse(200, {
      study_session_id: 'study-42', topic: 'Study plan', agent: 'claude', transport: 'pty',
      origin: 'study', purpose: 'planning', mode: 'focus',
      reattach_url: '/api/session/ws?study_session_id=study-42',
    })
    : baseFetch(url, opts));
  const con = consoleWithStubbedMount();

  await con._adoptLiveSession();

  assert.equal(con.mounted, 1);
  assert.equal(con.purpose, 'planning');
  assert.equal(con.lastDetail.reattached, true);
  assert.match(con.purposeLabel, /planning/i);
});

/* ---------------------------------------------------------------- *
 * The cold-server race (CI e2e, PR #20 runs 35214968238 / 35216220593):
 * startPlanning() navigated to the console, then startSession() returned
 * false before any fetch because `this.agent` was still unset -- init()'s
 * /api/session/options had not resolved yet. The learner saw the console
 * with "Select an agent to continue." and no session; the journey saw a
 * navigated page and no POST. A planning launch must wait for the picker's
 * own options before deciding there is no agent.
 * ---------------------------------------------------------------- */

test('startPlanning made before the options resolve waits for the agent and still POSTs once', async () => {
  let releaseOptions;
  const optionsGate = new Promise((resolve) => { releaseOptions = resolve; });
  const baseFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => {
    if (String(url).endsWith('/api/session/options')) {
      await optionsGate;
      return jsonResponse(200, {
        agents: [{ value: 'claude', label: 'Claude', available: true }],
        topics: [], terminal_engine: {},
      });
    }
    return baseFetch(url, opts);
  };
  const timer = sessionTimer();
  timers.push(timer);
  timer.$nextTick = (cb) => cb();
  const initDone = timer.init(); // options still in flight: no agent yet
  const seen = startEvents();

  const launch = timer.startPlanning({ topic: 'SQL window functions' });
  await settle();
  assert.equal(posts.length, 0, 'nothing to POST until the picker knows its agent');
  assert.equal(timer.startError, '', 'must not refuse while the options are still loading');

  releaseOptions();
  await initDone;
  const ok = await launch;

  assert.equal(ok, true);
  assert.equal(posts.length, 1, 'exactly one POST once the agent is known');
  assert.equal(posts[0].purpose, 'planning');
  assert.equal(posts[0].agent, 'claude');
  assert.equal(seen.length, 1);
  assert.deepEqual(navCalls, ['study-session']);
});

test('startPlanning with no agent available after the options resolve still refuses by name', async () => {
  const baseFetch = globalThis.fetch;
  globalThis.fetch = async (url, opts) => (String(url).endsWith('/api/session/options')
    ? jsonResponse(200, { agents: [{ value: 'claude', label: 'Claude', available: false }], topics: [] })
    : baseFetch(url, opts));
  const timer = sessionTimer();
  timers.push(timer);
  timer.$nextTick = (cb) => cb();
  await timer.init();

  const ok = await timer.startPlanning({ topic: 'SQL window functions' });

  assert.equal(ok, false);
  assert.equal(posts.length, 0);
  assert.match(timer.startError, /select an agent/i);
});
