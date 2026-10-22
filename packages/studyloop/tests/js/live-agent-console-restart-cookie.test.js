/**
 * A restarted `studyloop web` mints a new server secret (lane 3, F-WEB-20), so
 * a tab left open across the restart probes /api/session/state with a cookie
 * the new process does not know and gets 403 `server_secret_required`.
 *
 * Contract history:
 * - 51ad9487: the probe treated that 403 as "server unreachable, retry", spent
 *   all six attempts (~31 s) on it and never announced the ending, so the fix
 *   was to GET / once for the new cookie and retry.
 * - D2 (council pass 3, 2026-10-22, this file updated by lane E): GET / no
 *   longer hands out a cookie; only a browser presenting the new process's
 *   token gets one, and this tab cannot obtain that token. Silent recovery is
 *   impossible by design, so the honest contract is: the 403 is an answer (the
 *   server is back, the session that lived in the old process is gone), the
 *   probe does NOT fetch /, and the owning view is told the session ended with
 *   a message saying to reopen StudyLoop from the terminal or launcher.
 *
 * Run with:  node --test 'packages/studyloop/tests/js/*.test.js'
 */

import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { liveAgentConsole } from
  '../../src/studyloop/web/static/js/components/live-agent-console.js';

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
const realWindow = globalThis.window;
const realFetch = globalThis.fetch;
const realSetTimeout = globalThis.setTimeout;
const realCustomEvent = globalThis.CustomEvent;

let dispatched;
let fetched;

beforeEach(() => {
  dispatched = [];
  fetched = [];
  globalThis.WebSocket = FakeSocket;
  globalThis.CustomEvent = realCustomEvent || class CustomEvent {
    constructor(type, init) { this.type = type; this.detail = init && init.detail; }
  };
  globalThis.window = {
    location: { protocol: 'http:', host: '127.0.0.1:1' },
    dispatchEvent: (ev) => { dispatched.push(ev); return true; },
    addEventListener: () => {},
  };
  /* Backoff delays collapse to zero so the probe loop runs in one tick. */
  globalThis.setTimeout = (fn) => realSetTimeout(fn, 0);
});

afterEach(() => {
  globalThis.WebSocket = realWebSocket;
  globalThis.window = realWindow;
  globalThis.fetch = realFetch;
  globalThis.setTimeout = realSetTimeout;
  globalThis.CustomEvent = realCustomEvent;
});

const DETAIL = {
  topic: 'Window functions', origin: 'study', transport: 'pty',
  studySessionId: 'sess-1', wsUrl: '/api/session/ws?study_session_id=sess-1',
  resolvedAgent: 'codex',
};

const jsonResponse = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
  clone() { return jsonResponse(status, body); },
});

/* A server that was restarted under this tab: every state probe sees the
   old cookie and is refused; GET / would only answer the sign-in page. */
function restartedServer() {
  return async (url) => {
    fetched.push(url);
    if (url === '/') return jsonResponse(200, {});
    if (url.startsWith('/api/session/state')) {
      return jsonResponse(403, {
        code: 'server_secret_required',
        detail: 'This request lacks the StudyLoop server cookie. Reload the page.',
      });
    }
    throw new Error(`unexpected fetch ${url}`);
  };
}

function connectedConsole() {
  const view = liveAgentConsole('study');
  view.$nextTick = (fn) => fn();
  view.$refs = {};
  view._openWebSocket(DETAIL);
  const ws = view._ws;
  ws.emit('open');
  return { view, ws };
}

const endedEvents = () => dispatched.filter((ev) => ev.type === 'study-session-ended');

test('a stale server cookie after a restart announces the ending and says to reopen, without fetching /', async () => {
  globalThis.fetch = restartedServer();
  const { view, ws } = connectedConsole();

  await view._reportIfSessionGone(DETAIL, ws);

  assert.equal(fetched.filter((u) => u === '/').length, 0,
    'no GET /: it can no longer hand out a cookie, only the sign-in page');
  assert.equal(fetched.filter((u) => u.startsWith('/api/session/state')).length, 1,
    'the first 403 is the answer; no retries spent on it');
  const ended = endedEvents();
  assert.equal(ended.length, 1, 'the owning view is told the session ended');
  assert.equal(ended[0].detail.reason, 'server_restarted');
  assert.match(ended[0].detail.message, /^Your session ended/);
  assert.match(ended[0].detail.message, /was studyloop web restarted\?/);
  assert.match(ended[0].detail.message, /Reopen StudyLoop from the terminal or launcher/);
  assert.match(view.status, /reopen StudyLoop from the terminal/);
});

test('a probe abandoned by a newer socket announces nothing, even on the stale-cookie 403', async () => {
  globalThis.fetch = restartedServer();
  const { view, ws } = connectedConsole();
  view._ws = new FakeSocket('/api/session/ws?study_session_id=sess-2');

  await view._reportIfSessionGone(DETAIL, ws);

  assert.equal(endedEvents().length, 0);
});

test('a 403 that is not the stale-cookie code is still treated as unreachable (no cookie refresh)', async () => {
  globalThis.fetch = async (url) => {
    fetched.push(url);
    return jsonResponse(403, { detail: 'forbidden for another reason' });
  };
  const { view, ws } = connectedConsole();

  await view._reportIfSessionGone(DETAIL, ws);

  assert.equal(fetched.filter((u) => u === '/').length, 0, 'no GET / for an unrelated 403');
  assert.equal(endedEvents().length, 0, 'nothing announced without an answer from the server');
});
