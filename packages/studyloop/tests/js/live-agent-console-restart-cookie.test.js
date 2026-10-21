/**
 * A restarted `studyloop web` mints a new server secret (lane 3, F-WEB-20), so
 * a tab left open across the restart probes /api/session/state with a cookie
 * the new process does not know and gets 403 `server_secret_required`. The
 * probe loop in _reportIfSessionGone used to treat every non-2xx as "server
 * unreachable, try again", so all six attempts (~31 s) were spent on 403s and
 * the "Your session ended … (was studyloop web restarted?)" announcement never
 * fired: the owning view kept its dead live layout and the picker never came
 * back (e2e test_server_restart_under_a_live_tab_returns_the_picker).
 *
 * The 403 means the server IS back. GET / hands out the new cookie, so the
 * probe refreshes it once and retries, then the normal ended path runs.
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

/* A server that was restarted under this tab: the first state probe sees the
   old cookie and refuses; GET / hands out the new one; the next probe answers
   with no live session. */
function restartedServer() {
  let cookieRefreshed = false;
  return async (url) => {
    fetched.push(url);
    if (url === '/') { cookieRefreshed = true; return jsonResponse(200, {}); }
    if (url.startsWith('/api/session/state')) {
      if (!cookieRefreshed) {
        return jsonResponse(403, {
          code: 'server_secret_required',
          detail: 'This request lacks the StudyLoop server cookie. Reload the page.',
        });
      }
      return jsonResponse(200, { study_session_id: null, mode: null, last_release: null });
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

test('a stale server cookie after a restart is refreshed once and the ended session is announced', async () => {
  globalThis.fetch = restartedServer();
  const { view, ws } = connectedConsole();

  await view._reportIfSessionGone(DETAIL, ws);

  assert.equal(fetched.filter((u) => u === '/').length, 1, 'GET / exactly once for the new cookie');
  const ended = endedEvents();
  assert.equal(ended.length, 1, 'the owning view is told the session ended');
  assert.equal(ended[0].detail.reason, 'connection_lost');
  assert.match(ended[0].detail.message, /was studyloop web restarted\?/);
  assert.match(view.status, /Session ended/);
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
