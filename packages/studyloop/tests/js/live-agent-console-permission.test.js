/**
 * An ACP permission request is the learner's decision, including during the
 * invisible persona-injection turn (F-WEB-02@gpt-5.6-terra, 2026-10-21 review).
 *
 * The console used to answer any `request_permission` raised while the persona
 * prompt was running by itself: allow_once, else allow_always, else the first
 * option, with no prompt and no click. That removed the consent boundary for
 * whatever tool call the persona turn triggered. A request must render the
 * prompt and send nothing until the learner picks an option.
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

beforeEach(() => {
  globalThis.WebSocket = FakeSocket;
  globalThis.window = {
    location: { protocol: 'http:', host: '127.0.0.1:1' },
    dispatchEvent: () => true,
    addEventListener: () => {},
  };
});

afterEach(() => {
  globalThis.WebSocket = realWebSocket;
  globalThis.window = realWindow;
});

const DETAIL = {
  topic: 'Window functions', origin: 'study', transport: 'acp',
  studySessionId: 'sess-1', wsUrl: '/api/session/ws?study_session_id=sess-1',
  resolvedAgent: 'kiro', personaText: 'You are the study mentor.',
};

const PERMISSION_FRAME = {
  type: 'agent_message',
  kind: 'request_permission',
  payload: {
    _request_id: 7,
    toolCallId: 'tc-1',
    toolCall: { toolCallId: 'tc-1', title: 'Run shell command' },
    options: [
      { optionId: 'allow-once', kind: 'allow_once', name: 'Allow once' },
      { optionId: 'allow-always', kind: 'allow_always', name: 'Always allow' },
      { optionId: 'reject', kind: 'reject_once', name: 'Reject' },
    ],
  },
};

/* An ACP chat console with its socket open: Alpine's $nextTick and $refs are
   stood in for, since the component runs here without Alpine. */
function connectAcp() {
  const view = liveAgentConsole('study');
  view.transport = 'acp';
  view.terminalMode = 'acp-chat';
  view.toolCallsById = new Map();
  view.$nextTick = (fn) => fn();
  view.$refs = {};
  view._openWebSocket(DETAIL);
  const ws = view._ws;
  ws.emit('open');
  return { view, ws };
}

const permissionResponses = (ws) =>
  ws.sent.map((raw) => JSON.parse(raw)).filter((f) => f.type === 'permission_response');

test('a permission request during the persona turn is shown, not answered', () => {
  const { view, ws } = connectAcp();
  assert.equal(view._suppressStreamingBubble, true, 'precondition: persona turn in flight');

  ws.emit('message', { data: JSON.stringify(PERMISSION_FRAME) });

  assert.deepEqual(permissionResponses(ws), [], 'nothing is granted without a click');
  assert.ok(view.pendingPermission, 'the prompt renders');
  assert.equal(view.pendingPermission.requestId, 7);
  assert.deepEqual(
    view.pendingPermission.options.map((o) => o.optionId),
    ['allow-once', 'allow-always', 'reject'],
  );
});

test("the learner's click is the only answer sent, with the option they chose", () => {
  const { view, ws } = connectAcp();
  ws.emit('message', { data: JSON.stringify(PERMISSION_FRAME) });

  view._selectPermissionOption('reject');

  assert.deepEqual(permissionResponses(ws), [
    { type: 'permission_response', requestId: 7, outcome: { outcome: 'selected', optionId: 'reject' } },
  ]);
  assert.equal(view.pendingPermission, null);
});

test('a permission request after the persona turn is shown the same way', () => {
  const { view, ws } = connectAcp();
  ws.emit('message', {
    data: JSON.stringify({ type: 'agent_message', kind: 'turn_end', payload: { reason: 'end_turn' } }),
  });
  assert.equal(view._suppressStreamingBubble, false, 'precondition: persona turn finished');

  ws.emit('message', { data: JSON.stringify(PERMISSION_FRAME) });

  assert.deepEqual(permissionResponses(ws), []);
  assert.ok(view.pendingPermission);
});
