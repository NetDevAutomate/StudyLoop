/** Contract tests for the browser Plan Architect state machine. */

import { afterEach, beforeEach, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  PLANNING_PRIVACY_NOTICE,
  createPlanningConversation,
} from '../../src/studyloop/web/static/js/components/planning-conversation.js';
import {
  ARCHITECT_PHASES,
  createPlanArchitectPanel,
  waitForVisibleLayout,
} from '../../src/studyloop/web/static/js/components/plan-architect-panel.js';

const realFetch = globalThis.fetch;
const realWebSocket = globalThis.WebSocket;

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const privacy = {
  text: PLANNING_PRIVACY_NOTICE,
  local_recovery_state: true,
  automatic_expiry: false,
  configured_model_context: true,
};

const capacity = (current = 0) => ({
  current,
  max: 3,
  available: 3 - current,
  can_create: current < 3,
});

const created = (over = {}) => ({
  conversation_id: 'conversation-1',
  mode: 'create',
  plan_id: null,
  phase: 'ready',
  privacy_notice: privacy,
  capacity: capacity(),
  csrf_token: 'csrf-1',
  ...over,
});

const snapshot = (over = {}) => ({
  conversation_id: 'conversation-1',
  mode: 'create',
  plan_id: null,
  phase: 'conversation',
  capacity: capacity(),
  messages: [],
  latest_turn: null,
  proposal: null,
  events_url: '/api/planning/conversations/conversation-1/events',
  ...over,
});

beforeEach(() => {
  globalThis.document = { cookie: 'studyloop_csrf=cookie-token' };
});

afterEach(() => {
  globalThis.fetch = realFetch;
  globalThis.WebSocket = realWebSocket;
  delete globalThis.document;
});

test('privacy notice is the exact release-one disclosure and promises no expiry', () => {
  assert.equal(
    PLANNING_PRIVACY_NOTICE,
    'Planning text and proposals are stored locally for recovery and may remain ' +
      'after rejection or replacement. StudyLoop sends the bounded planning context ' +
      'to your configured model. This release provides no automatic expiry.'
  );
});

test('conversation adapter sends the closed create, context, turn and CSRF contract', async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options });
    if (url === '/api/planning/conversations') return json(201, created());
    if (url.endsWith('/context')) {
      return json(201, {
        context_id: 'context-1',
        label: 'Course outline',
        content_digest: 'sha256:context',
        size: 12,
        tier: 4,
      });
    }
    if (url.endsWith('/turns')) {
      return json(202, { turn_id: 'turn-1', status: 'scheduled', turn_version: 1 });
    }
    throw new Error(`unexpected ${url}`);
  };

  const api = createPlanningConversation({
    origin: 'http://127.0.0.1:8765',
    idFactory: () => 'browser-idempotency-1',
  });
  const run = await api.create({ mode: 'create' });
  await api.attachPastedContext(run.conversation_id, {
    label: 'Course outline',
    content: 'Week 1: APIs',
  });
  await api.submitTurn(run.conversation_id, 'I need to learn backend design');

  assert.deepEqual(JSON.parse(calls[0].options.body), { mode: 'create' });
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    kind: 'pasted',
    label: 'Course outline',
    content: 'Week 1: APIs',
  });
  assert.deepEqual(JSON.parse(calls[2].options.body), {
    text: 'I need to learn backend design',
    idempotency_key: 'browser-idempotency-1',
  });
  assert.equal(calls[1].options.headers['X-CSRF-Token'], 'csrf-1');
  assert.equal(calls[2].options.headers.Origin, 'http://127.0.0.1:8765');
  assert.equal(calls[2].options.headers['Sec-Fetch-Site'], 'same-origin');
});

test('plain-text browser upload uses multipart without leaking a local source path', async () => {
  let captured;
  globalThis.fetch = async (url, options = {}) => {
    captured = { url, options };
    return json(201, {
      context_id: 'context-file',
      label: 'outline.md',
      content_digest: 'sha256:file',
      size: 17,
      tier: 4,
    });
  };
  const api = createPlanningConversation({ origin: 'http://127.0.0.1:8765' });
  const file = new File(['# Course outline\n'], 'outline.md', { type: 'text/markdown' });
  await api.attachTextFile('conversation-1', file);

  assert.match(captured.url, /conversation-1\/context$/);
  assert.ok(captured.options.body instanceof FormData);
  assert.equal(captured.options.body.get('file').name, 'outline.md');
  assert.deepEqual([...captured.options.body.keys()], ['label', 'file']);
  assert.equal(captured.options.headers['Content-Type'], undefined);
  assert.equal(JSON.stringify([...captured.options.body]).includes('/Users/'), false);
});

test('at capacity the panel refuses before conversation creation or model egress', async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    return json(200, {
      plans: [{ plan_id: 'a' }, { plan_id: 'b' }, { plan_id: 'c' }],
      capacity: {
        max_current: 3,
        current_count: 3,
        slots_free: 0,
        at_capacity: true,
        counted_statuses: ['draft', 'active', 'paused'],
      },
    });
  };
  const panel = createPlanArchitectPanel({
    api: createPlanningConversation({ origin: 'http://127.0.0.1:8765' }),
  });

  await panel.beginCreate();
  panel.brainDump = 'Make me a fourth current plan';
  await panel.startConversation();

  assert.deepEqual(calls, ['/api/plans']);
  assert.equal(panel.phase, ARCHITECT_PHASES.CAPACITY);
  assert.match(panel.error, /3 of 3 current plans/i);
});

test('brain dump is the only required input and a clarification remains conversational', async () => {
  const calls = [];
  const api = {
    async readCapacity() {
      return capacity();
    },
    async create(input) {
      calls.push(['create', input]);
      return created();
    },
    async attachPastedContext(id, context) {
      calls.push(['context', id, context]);
    },
    async submitTurn(id, text) {
      calls.push(['turn', id, text]);
      return { turn_id: 'turn-1', status: 'scheduled', turn_version: 1 };
    },
    connect() {
      calls.push(['connect']);
      return () => {};
    },
  };
  const panel = createPlanArchitectPanel({ api });
  await panel.beginCreate();
  assert.equal(panel.canStart(), false);

  panel.brainDump = 'I can follow Python but cannot design a service yet.';
  panel.contextText = 'Module 1: dependency inversion';
  panel.contextLabel = 'Course outline';
  assert.equal(panel.canStart(), true);
  await panel.startConversation();

  assert.equal(panel.phase, ARCHITECT_PHASES.CONVERSATION);
  assert.deepEqual(calls.slice(0, 4), [
    ['create', { mode: 'create' }],
    [
      'context',
      'conversation-1',
      { label: 'Course outline', content: 'Module 1: dependency inversion' },
    ],
    ['turn', 'conversation-1', panel.brainDump],
    ['connect'],
  ]);

  panel.applySnapshot(
    snapshot({
      messages: [
        { role: 'learner', content: panel.brainDump, sequence: 1 },
        {
          role: 'assistant',
          content: 'Which real service would make this useful first?',
          sequence: 2,
        },
      ],
    })
  );
  assert.equal(panel.phase, ARCHITECT_PHASES.CONVERSATION);
  assert.match(panel.messages[1].content, /which real service/i);
});

test('context file preflight matches the server 100,000-byte UTF-8 boundary', () => {
  const panel = createPlanArchitectPanel({ api: {} });
  panel.readContextFile({
    target: {
      files: [new File(['x'.repeat(100_001)], 'too-large.md', { type: 'text/markdown' })],
    },
  });
  assert.equal(panel.contextFile, null);
  assert.match(panel.error, /100 KB/i);
});

test('proposal requires exact digest and base binding; revise returns to the composer', async () => {
  const decisions = [];
  let refreshedPlan = '';
  const panel = createPlanArchitectPanel({
    api: {
      async decide(proposal, outcome) {
        decisions.push({ proposal, outcome });
        return { intent_id: 'intent-1', status: 'applied', outcome, plan_id: 'plan-1' };
      },
    },
    onPlanApplied: async (planId) => {
      refreshedPlan = planId;
    },
  });
  panel.conversationId = 'conversation-1';
  panel.applySnapshot(
    snapshot({
      phase: 'proposal',
      proposal: {
        proposal_id: 'proposal-1',
        proposal_digest: 'sha256:proposal',
        mode: 'create',
        title: 'Design one service',
        markdown: '# Design one service',
        plan: { mission: { why: 'Own a service' } },
        unknowns: ['Which service is first?'],
        evidence_dispositions: [{ source: 'notes', disposition: 'context_only' }],
        base: {
          document_digest: 'sha256:doc',
          structure_digest: 'sha256:structure',
          document_revision: 0,
          structure_revision: 0,
        },
      },
    })
  );
  assert.equal(panel.phase, ARCHITECT_PHASES.PROPOSAL);

  panel.reviseProposal();
  assert.equal(panel.phase, ARCHITECT_PHASES.CONVERSATION);
  assert.match(panel.turnText, /change/i);

  panel.applySnapshot(snapshot({ phase: 'proposal', proposal: panel.proposal }));
  await panel.decide('approve');
  assert.equal(decisions[0].outcome, 'approve');
  assert.equal(decisions[0].proposal.proposal_id, 'proposal-1');
  assert.equal(decisions[0].proposal.proposal_digest, 'sha256:proposal');
  assert.deepEqual(decisions[0].proposal.base, {
    document_digest: 'sha256:doc',
    structure_digest: 'sha256:structure',
    document_revision: 0,
    structure_revision: 0,
  });
  assert.equal(refreshedPlan, 'plan-1');
  assert.equal(panel.phase, ARCHITECT_PHASES.DETAIL);
  panel.applySnapshot(snapshot({ phase: 'proposal', proposal: panel.proposal }));
  assert.equal(panel.phase, ARCHITECT_PHASES.DETAIL, 'late WS replay must not reopen applied proposal');
});

test('Mermaid scheduling waits for a visible nonzero panel layout', async () => {
  let checks = 0;
  const element = {
    getClientRects() {
      checks += 1;
      return checks < 3 ? [] : [{ width: 720, height: 320 }];
    },
    getBoundingClientRect() {
      return checks < 3 ? { width: 0, height: 0 } : { width: 720, height: 320 };
    },
  };
  const frames = [];
  const visible = await waitForVisibleLayout(element, {
    attempts: 5,
    nextFrame: () => {
      frames.push('frame');
      return Promise.resolve();
    },
  });
  assert.equal(visible, true);
  assert.equal(frames.length, 2);
});

test('websocket resume cursor is monotonic and does not duplicate transcript events', () => {
  const sockets = [];
  class FakeSocket {
    constructor(url) {
      this.url = url;
      sockets.push(this);
    }
    close() {}
  }
  globalThis.WebSocket = FakeSocket;
  const api = createPlanningConversation({
    origin: 'http://127.0.0.1:8765',
    websocketFactory: (url) => new FakeSocket(url),
  });
  const seen = [];
  api.connect('conversation-1', 7, (event) => seen.push(event));
  assert.match(sockets[0].url, /events\?after_seq=7$/);

  sockets[0].onmessage({ data: JSON.stringify({ sequence: 8, type: 'message', data: {} }) });
  sockets[0].onmessage({ data: JSON.stringify({ sequence: 8, type: 'message', data: {} }) });
  sockets[0].onmessage({ data: JSON.stringify({ sequence: 9, type: 'proposal', data: {} }) });
  assert.deepEqual(
    seen.map((event) => event.sequence),
    [8, 9]
  );
});

test('plan markup exposes capture, conversation and exact proposal decisions without questionnaire fields', () => {
  const source = readFileSync(
    new URL('../../src/studyloop/web/static/index.html', import.meta.url),
    'utf8'
  );
  const panel = source.slice(
    source.indexOf('<!-- STUDY PLANS VIEW'),
    source.indexOf('<!-- SETTINGS VIEW')
  );
  assert.match(panel, /x-data="planArchitectPanel\(\)"/);
  assert.match(panel, /data-testid="architect-privacy-notice"/);
  assert.match(panel, /data-testid="architect-brain-dump"/);
  assert.match(panel, /data-testid="architect-conversation"/);
  assert.match(panel, /data-testid="architect-proposal"/);
  assert.match(panel, /data-testid="architect-approve"/);
  assert.match(panel, /data-testid="architect-revise"/);
  assert.match(panel, /data-testid="architect-reject"/);
  assert.equal(panel.includes('data-testid="plan-field-title"'), false);
  assert.equal(panel.includes('data-testid="plan-field-milestones"'), false);
  assert.ok(
    panel.indexOf('data-testid="architect-privacy-notice"') <
      panel.indexOf('data-testid="architect-start"'),
    'privacy disclosure must precede the first request control in document order'
  );
});

test('architect CSS declares tablet flow, sticky decisions and explicit phone exclusion', () => {
  const source = readFileSync(
    new URL('../../src/studyloop/web/static/style.css', import.meta.url),
    'utf8'
  );
  assert.match(source, /\.architect-decision-bar\s*\{[^}]*position:\s*sticky/s);
  assert.match(source, /@media\s*\(max-width:\s*599px\)/);
  assert.match(source, /\.planning-supported-layout\s*\{\s*display:\s*none/s);
  assert.match(source, /@media\s*\(min-width:\s*600px\)/);
  assert.match(source, /\.planning-phone-unsupported\s*\{\s*display:\s*none/s);
  assert.match(source, /\.architect-proposal-document[^}]*overflow-x:\s*auto/s);
});
