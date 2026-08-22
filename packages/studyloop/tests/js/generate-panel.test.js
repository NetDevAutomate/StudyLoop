/**
 * Unit tests for the generatePanel component factory.
 *
 * Uses `node --test` — built into Node, zero dependencies, no package.json and
 * no build step (same rationale as chunk-text.test.js).
 *
 * Run with the quoted-glob form noted on the next line (a bare directory
 * argument fails on Node 26 with MODULE_NOT_FOUND; the glob cannot be
 * written inside this block comment because it contains the sequence
 * that closes one).
 *
 * WHY THIS IS POSSIBLE WITHOUT A BROWSER: the factory returns a plain object —
 * no DOM and no Alpine are touched at construction time. `fetch`, `WebSocket`
 * and `window.location` are only referenced inside methods, so stubbing those
 * three globals lets the failure paths (malformed WS frame, transport error,
 * 409 job conflict) be proven in milliseconds. Alpine's reactive Proxy adds
 * observation, not behaviour, so `this` binding on the plain object is the
 * same one Alpine sees.
 */
// Run with:  node --test 'packages/studyloop/tests/js/**/*.test.js'

import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { generatePanel } from
  '../../src/studyloop/web/static/js/components/generate-panel.js';

/* ---------------------------------------------------------------- *
 * Test doubles for the transport globals.
 * ---------------------------------------------------------------- */

class FakeWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.closed = false;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    FakeWebSocket.instances.push(this);
  }
  // Recorder only. The real WebSocket fires `close` asynchronously; tests
  // that care about the onclose safety net invoke ws.onclose() explicitly.
  close() { this.closed = true; }
}

const jsonResponse = (status, body, statusText = '') =>
  new Response(JSON.stringify(body), { status, statusText });

const realFetch = globalThis.fetch;
const realWebSocket = globalThis.WebSocket;
const hadWindow = 'window' in globalThis;

beforeEach(() => {
  FakeWebSocket.instances.length = 0;
  globalThis.WebSocket = FakeWebSocket;
  globalThis.window = { location: { protocol: 'https:', host: 'studyloop.test' } };
});

afterEach(() => {
  globalThis.fetch = realFetch;
  globalThis.WebSocket = realWebSocket;
  if (!hadWindow) delete globalThis.window;
  else globalThis.window = undefined;
});

/* Fill in the minimum the form needs to pass canSubmit(). */
function fillValidForm(panel) {
  panel.form.publisher = 'ArjanCodes';
  panel.form.course = 'python-masterclass';
  panel.form.kinds = ['flashcards'];
}

const PROVIDERS = [
  { slug: 'openai', label: 'OpenAI', adapter: 'openai_compat', available: false, models: ['gpt-4o'] },
  { slug: 'bedrock', label: 'Bedrock', adapter: 'bedrock', available: false, models: [] },
  { slug: 'anthropic', label: 'Anthropic', adapter: 'anthropic_compat', available: true, models: ['claude'] },
];

/* Run submit() against a stubbed fetch and return the panel. */
async function submitWith(response) {
  globalThis.fetch = async () => {
    if (response instanceof Error) throw response;
    return response;
  };
  const panel = generatePanel();
  fillValidForm(panel);
  await panel.submit();
  return panel;
}

/* ---------------------------------------------------------------- *
 * progressPct — pure state → number.
 * ---------------------------------------------------------------- */

test('progressPct: 0 with no plan and 0 with a zero task_count (no divide-by-zero)', () => {
  const panel = generatePanel();
  assert.equal(panel.progressPct(), 0);
  panel.plan = { task_count: 0 };
  assert.equal(panel.progressPct(), 0);
});

test('progressPct: rounds, and clamps at 100 when tasks overshoot task_count', () => {
  const panel = generatePanel();
  panel.plan = { task_count: 3 };
  panel.tasks = [{}];
  assert.equal(panel.progressPct(), 33);
  panel.tasks = [{}, {}, {}, {}];  // server sent more frames than the estimate
  assert.equal(panel.progressPct(), 100);
});

/* ---------------------------------------------------------------- *
 * canSubmit / provider gating — pure state → boolean.
 * ---------------------------------------------------------------- */

test('canSubmit: true only once publisher, course and kinds are present', () => {
  const panel = generatePanel();
  assert.equal(panel.canSubmit(), false);          // empty form
  fillValidForm(panel);
  assert.equal(panel.canSubmit(), true);
  panel.form.kinds = [];
  assert.equal(panel.canSubmit(), false);          // no kinds
});

test('canSubmit: blocked while running, and section scope requires a section', () => {
  const panel = generatePanel();
  fillValidForm(panel);
  panel.running = true;
  assert.equal(panel.canSubmit(), false);
  panel.running = false;
  panel.form.scope_kind = 'section';
  assert.equal(panel.canSubmit(), false);
  panel.form.section = 'lesson-01.md';
  assert.equal(panel.canSubmit(), true);
});

test('canSubmit: keyless keyed provider and credential-less Bedrock both block', () => {
  const panel = generatePanel();
  fillValidForm(panel);
  panel.providers = PROVIDERS;
  panel.form.provider = 'openai';                  // keyed, no key stored
  assert.equal(panel.needsKey, true);
  assert.equal(panel.canSubmit(), false);
  panel.form.provider = 'bedrock';                 // AWS creds unresolved
  assert.equal(panel.needsKey, false);             // never keyed here
  assert.equal(panel.needsBedrockCreds, true);
  assert.equal(panel.canSubmit(), false);
  panel.form.provider = 'anthropic';               // available
  assert.equal(panel.canSubmit(), true);
});

test('providerOptionLabel: suffix depends on adapter, absent when available', () => {
  const panel = generatePanel();
  const [openai, bedrock, anthropic] = PROVIDERS;
  assert.equal(panel.providerOptionLabel(anthropic), 'Anthropic');
  assert.equal(panel.providerOptionLabel(openai), 'OpenAI — needs API key');
  assert.equal(panel.providerOptionLabel(bedrock), 'Bedrock — needs AWS credentials');
});

/* ---------------------------------------------------------------- *
 * submit — failure paths first (409 conflict, HTTP error, network error).
 * ---------------------------------------------------------------- */

test('submit: 409 conflict goes to conflictBanner, job never starts', async () => {
  const panel = await submitWith(
    jsonResponse(409, { detail: 'job abc123 is already running' }));
  assert.equal(panel.conflictBanner, 'job abc123 is already running');
  assert.equal(panel.formError, '');
  assert.equal(panel.running, false);
  assert.equal(FakeWebSocket.instances.length, 0);  // no WS opened
});

test('submit: 409 without a detail field falls back to the default banner', async () => {
  const panel = await submitWith(jsonResponse(409, {}));
  assert.equal(panel.conflictBanner, 'another job is already running');
});

test('submit: non-JSON HTTP error falls back to "<status> <statusText>"', async () => {
  const panel = await submitWith(
    new Response('boom', { status: 500, statusText: 'Internal Server Error' }));
  assert.equal(panel.formError, '500 Internal Server Error');
  assert.equal(panel.running, false);
  assert.equal(FakeWebSocket.instances.length, 0);
});

test('submit: network failure sets formError and never opens a WS', async () => {
  const panel = await submitWith(new TypeError('fetch failed'));
  assert.match(panel.formError, /^Network error: fetch failed/);
  assert.equal(panel.running, false);
  assert.equal(FakeWebSocket.instances.length, 0);
});

/* ---------------------------------------------------------------- *
 * submit 202 → WS frame handling.
 * ---------------------------------------------------------------- */

async function startJob() {
  const panel = await submitWith(
    jsonResponse(202, { job_id: 'j-1', plan: { task_count: 4 } }));
  assert.equal(panel.running, true);
  assert.equal(panel.jobId, 'j-1');
  const ws = FakeWebSocket.instances.at(-1);
  assert.ok(ws, 'a WebSocket was opened');
  assert.ok(ws.url.includes('job_id=j-1'), `url carries the job id: ${ws.url}`);
  assert.ok(ws.url.startsWith('wss://studyloop.test'), 'https page → wss scheme');
  return { panel, ws };
}

test('WS: started frame reconciles the estimated plan with the authoritative count', async () => {
  const { panel, ws } = await startJob();
  ws.onmessage({ data: JSON.stringify({ type: 'started', task_count: 7, model: 'claude' }) });
  assert.equal(panel.plan.task_count, 7);
  assert.equal(panel.plan.model, 'claude');
});

test('WS: a malformed (non-JSON) frame is ignored and changes nothing', async () => {
  const { panel, ws } = await startJob();
  const before = JSON.stringify({ running: panel.running, tasks: panel.tasks, plan: panel.plan });
  ws.onmessage({ data: 'not json {{{' });
  const after = JSON.stringify({ running: panel.running, tasks: panel.tasks, plan: panel.plan });
  assert.equal(after, before);
  assert.equal(ws.closed, false);  // and it must not kill the job
});

test('WS: an unknown frame type is ignored', async () => {
  const { panel, ws } = await startJob();
  ws.onmessage({ data: JSON.stringify({ type: 'heartbeat' }) });
  assert.equal(panel.running, true);
  assert.equal(panel.tasks.length, 0);
});

test('WS: task_complete frames accumulate and drive progress', async () => {
  const { panel, ws } = await startJob();
  ws.onmessage({ data: JSON.stringify({ type: 'task_complete', source: 'a.md' }) });
  ws.onmessage({ data: JSON.stringify({ type: 'task_complete', source: 'b.md' }) });
  assert.equal(panel.tasks.length, 2);
  assert.equal(panel.progressPct(), 50);  // 2 of the estimated 4
});

test('WS: all_done is the success terminal — summary, running=false, socket closed', async () => {
  const { panel, ws } = await startJob();
  ws.onmessage({ data: JSON.stringify({ type: 'all_done', written: 12, failed: 1 }) });
  assert.equal(panel.finishedSummary, 'Done — 12 written, 1 failed.');
  assert.equal(panel.running, false);
  assert.equal(ws.closed, true);
});

test('WS: transport_error is the failure terminal — error summary, running=false, socket closed', async () => {
  const { panel, ws } = await startJob();
  ws.onmessage({ data: JSON.stringify({ type: 'transport_error', message: 'LLM exploded' }) });
  assert.equal(panel.finishedSummary, 'Job error: LLM exploded');
  assert.equal(panel.running, false);
  assert.equal(ws.closed, true);
});

test('WS: onerror surfaces formError; onclose is the running=false safety net', async () => {
  const { panel, ws } = await startJob();
  ws.onerror();
  assert.equal(panel.formError, 'WebSocket connection lost.');
  assert.equal(panel.running, true);   // onerror alone does not end the job…
  ws.onclose();
  assert.equal(panel.running, false);  // …the close that follows it does
});

/* ---------------------------------------------------------------- *
 * reset.
 * ---------------------------------------------------------------- */

test('reset: clears job state and closes a live socket', async () => {
  const { panel, ws } = await startJob();
  panel.formError = 'x';
  panel.conflictBanner = 'y';
  panel.reset();
  assert.equal(panel.jobId, '');
  assert.equal(panel.plan, null);
  assert.deepEqual(panel.tasks, []);
  assert.equal(panel.finishedSummary, '');
  assert.equal(panel.formError, '');
  assert.equal(panel.conflictBanner, '');
  assert.equal(panel._ws, null);
  assert.equal(ws.closed, true);
});
