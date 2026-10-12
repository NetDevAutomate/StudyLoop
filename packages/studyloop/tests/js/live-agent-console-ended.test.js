/**
 * The live console must tell the view that owns it when the session it shows
 * has ended WITHOUT the learner pressing End. Until it did, a Body Double tab
 * whose server was restarted underneath it (a re-run `studyloop web`) kept its
 * live strip — Pomodoro timer, End button, a dead console — and hid its picker
 * for good: "the option to start a session has disappeared, only a pomodoro
 * timer" (2026-10-11). The event is `study-session-ended`, origin-tagged like
 * the start/stop events, and the socket wiring in _openWebSocket is what
 * decides when it fires:
 *
 *   - a 'stopped' frame announces once, with the server's reason, and the
 *     socket closing afterwards is not a second ending;
 *   - a close the OWNER caused (stop() nulls _ws first) announces nothing;
 *   - a close the server did not explain is checked against
 *     /api/session/state — gone/ended/another session → announced; still live
 *     (grace window) → silence; unreachable → retried, not guessed.
 *
 * Run with:  node --test 'packages/studyloop/tests/js/**\/*.test.js'
 */

import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { liveAgentConsole } from
  '../../src/studyloop/web/static/js/components/live-agent-console.js';

/* A WebSocket double: records listeners so the test can play the server. */
class FakeSocket {
  static OPEN = 1;
  constructor(url) {
    this.url = url;
    this.readyState = FakeSocket.OPEN;
    this.sent = [];
    this._listeners = {};
  }
  addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
  send(data) { this.sent.push(data); }
  close() { this.readyState = 3; }
  emit(type, event = {}) { for (const fn of this._listeners[type] || []) fn(event); }
}

const realWebSocket = globalThis.WebSocket;
const realFetch = globalThis.fetch;
const realWindow = globalThis.window;
const realSetTimeout = globalThis.setTimeout;

let dispatched;
let stateResponses;   /* queue of responses /api/session/state returns, in order */
let stateCalls;

beforeEach(() => {
  dispatched = [];
  stateResponses = [];
  stateCalls = 0;
  globalThis.WebSocket = FakeSocket;
  globalThis.window = {
    location: { protocol: 'http:', host: '127.0.0.1:1' },
    dispatchEvent: (event) => { dispatched.push(event); return true; },
    addEventListener: () => {},
  };
  globalThis.fetch = async (url) => {
    assert.match(String(url), /\/api\/session\/state$/);
    stateCalls += 1;
    const next = stateResponses.shift();
    if (next === 'unreachable') throw new TypeError('fetch failed');
    return { ok: true, json: async () => next };
  };
  /* The probe backs off between attempts; run those waits instantly so the
     test asserts the retry LOGIC, not wall-clock seconds. */
  globalThis.setTimeout = (fn) => { fn(); return 0; };
});

afterEach(() => {
  globalThis.WebSocket = realWebSocket;
  globalThis.fetch = realFetch;
  globalThis.window = realWindow;
  globalThis.setTimeout = realSetTimeout;
});

const DETAIL = {
  topic: 'Window functions', origin: 'body-double', transport: 'pty',
  studySessionId: 'sess-1', wsUrl: '/api/session/ws?study_session_id=sess-1',
  resolvedAgent: 'codex',
};

function connect(origin = 'body-double') {
  const view = liveAgentConsole(origin);
  view.transport = 'pty';
  view._openWebSocket(DETAIL);
  const ws = view._ws;
  ws.emit('open');
  return { view, ws };
}

const endedEvents = () => dispatched.filter((e) => e.type === 'study-session-ended');
const settle = () => new Promise((resolve) => realSetTimeout(resolve, 0));

test("a 'stopped' frame announces the end once, with the server's reason", async () => {
  const { view, ws } = connect();

  ws.emit('message', { data: JSON.stringify({ type: 'stopped', reason: 'exit', returncode: 0 }) });
  ws.emit('close');
  await settle();

  const events = endedEvents();
  assert.equal(events.length, 1, 'one announcement, not one per signal');
  assert.deepEqual(events[0].detail, {
    origin: 'body-double',
    studySessionId: 'sess-1',
    reason: 'exit',
    returncode: 0,
    message: 'Your session ended (exit, rc=0). Start a new one when you are ready.',
  });
  assert.equal(stateCalls, 0, 'the frame is the answer; nothing to ask the server');
  assert.equal(view.connected, false);
  assert.match(view.status, /^Session ended \(exit, rc=0\)/);
  assert.equal(ws.readyState, 3, 'hung up: the server releases the slot on socket teardown');
});

test('the event carries the console origin, so the Study view ignores a Body Double ending', () => {
  const { ws } = connect('study');
  ws.emit('message', { data: JSON.stringify({ type: 'stopped', reason: 'exit', returncode: 1 }) });
  assert.equal(endedEvents()[0].detail.origin, 'study');
});

test('a close the owner caused (stop) announces nothing and asks nothing', async () => {
  const { view, ws } = connect();

  view.stop();        /* nulls _ws, then the close event lands */
  ws.emit('close');
  await settle();

  assert.equal(endedEvents().length, 0);
  assert.equal(stateCalls, 0);
});

test('a close replaced by a newer start announces nothing for the old socket', async () => {
  const { view, ws } = connect();

  view._openWebSocket(DETAIL);          /* a newer socket owns the console now */
  ws.emit('close');
  await settle();

  assert.equal(endedEvents().length, 0);
  assert.equal(stateCalls, 0);
});

test('an unexplained close with the session gone is announced as a lost connection', async () => {
  const { view, ws } = connect();
  stateResponses.push({ topics: [], parking: [] });   /* a fresh server: no session at all */

  ws.emit('close');
  await settle();

  const events = endedEvents();
  assert.equal(events.length, 1);
  assert.equal(events[0].detail.reason, 'connection_lost');
  assert.match(events[0].detail.message, /was studyloop web restarted\?/);
  assert.equal(view.status, 'Session ended (connection_lost)');
});

test("an unexplained close with the session marked ended uses the server's release reason", async () => {
  const { ws } = connect();
  stateResponses.push({
    study_session_id: 'sess-1', mode: 'ended',
    last_release: { study_session_id: 'sess-1', reason: 'agent_exited' },
  });

  ws.emit('close');
  await settle();

  assert.equal(endedEvents()[0].detail.reason, 'agent_exited');
});

test('another session now holding the slot means ours is gone', async () => {
  const { ws } = connect();
  stateResponses.push({ study_session_id: 'sess-2', mode: 'focus', origin: 'study' });

  ws.emit('close');
  await settle();

  assert.equal(endedEvents().length, 1);
});

test('a session still live in its grace window is left alone', async () => {
  const { view, ws } = connect();
  stateResponses.push({ study_session_id: 'sess-1', mode: 'focus', origin: 'body-double', detached: true });

  ws.emit('close');
  await settle();

  assert.equal(endedEvents().length, 0, 'reattachable, not ended — the recovery block is the path');
  assert.equal(view.status, 'Disconnected');
});

test('a server mid-restart is asked again rather than guessed about', async () => {
  const { ws } = connect();
  stateResponses.push('unreachable', 'unreachable', { topics: [], parking: [] });

  ws.emit('close');
  await settle();

  assert.equal(stateCalls, 3);
  assert.equal(endedEvents().length, 1);
});

test('a server that never comes back gets no verdict', async () => {
  const { view, ws } = connect();
  stateResponses.push(...Array(6).fill('unreachable'));

  ws.emit('close');
  await settle();

  assert.equal(stateCalls, 6, 'every retry spent');
  assert.equal(endedEvents().length, 0);
  assert.equal(view.status, 'Disconnected');
});
