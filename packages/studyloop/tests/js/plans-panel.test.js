/**
 * Unit tests for the study-plan panel's logic half.
 *
 * Uses `node --test` — built into Node, zero dependencies, no package.json and
 * no build step (same rationale as chunk-text.test.js and generate-panel.test.js).
 *
 * WHY THIS IS POSSIBLE WITHOUT A BROWSER: `plansStore` is a plain object and
 * `plansPanel()` returns one, so nothing touches the DOM or Alpine at
 * construction time. The `(concepts: …)` parser and the progress formatter are
 * pure functions — the two pieces of logic that must agree with the server's
 * own parser and with the sidebar, and the two places a silent mismatch would
 * be invisible in the rendered page. `fetch` is the only global the store
 * methods need, so stubbing it proves the create payload, the activation
 * refusal, the record ordering and the epoch guard in milliseconds.
 */
// Run with:  node --test 'packages/studyloop/tests/js/**/*.test.js'

import { test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import {
  plansStore,
  plansPanel,
  parseMilestoneLine,
  parseMilestoneLines,
  progressPercent,
  formatProgress,
  splitLines,
  stripFrontmatter,
} from '../../src/studyloop/web/static/js/components/plans-panel.js';

/* ---------------------------------------------------------------- *
 * The exact strings the e2e journey types into the wizard. Pinning
 * them here is the point: if the parser and the journey ever disagree,
 * this file fails in milliseconds instead of the browser suite failing
 * in minutes.
 * ---------------------------------------------------------------- */

const E2E_MILESTONES =
  'Understand Glue job anatomy (concepts: glue job, job bookmark)\n' +
  'Write the transform (concepts: dynamicframe)\n' +
  'Schedule and monitor it (concepts: cloudwatch)';

const E2E_SUCCESS =
  'Deploy a Glue job unaided\nExplain the job bookmark to a colleague';

/* ---------------------------------------------------------------- *
 * stripFrontmatter — metadata must not leak into the document.
 * ---------------------------------------------------------------- */

test('stripFrontmatter: removes the opening block so YAML keys cannot leak', () => {
  const raw =
    '---\ntitle: Ship a Glue ETL Job\nreview_cadence_days: 3\n---\n# Ship a Glue ETL Job\n';
  const out = stripFrontmatter(raw);
  assert.equal(out.includes('review_cadence_days:'), false);
  assert.ok(out.startsWith('# Ship a Glue ETL Job'));
});

test('stripFrontmatter: CRLF documents strip too', () => {
  const out = stripFrontmatter('---\r\nreview_cadence_days: 3\r\n---\r\n# Title\r\n');
  assert.equal(out.includes('review_cadence_days:'), false);
  assert.ok(out.startsWith('# Title'));
});

test('stripFrontmatter: leaves a document with no frontmatter untouched', () => {
  assert.equal(stripFrontmatter('# Title\n\nbody'), '# Title\n\nbody');
  assert.equal(stripFrontmatter(''), '');
});

test('stripFrontmatter: an unclosed block is left alone rather than eating the body', () => {
  const raw = '---\ntitle: broken\n# Title\n';
  assert.equal(stripFrontmatter(raw), raw);
});

/* ---------------------------------------------------------------- *
 * splitLines — textarea value → API list.
 * ---------------------------------------------------------------- */

test('splitLines: splits on newlines, trims, and drops blank lines', () => {
  assert.deepEqual(splitLines(E2E_SUCCESS), [
    'Deploy a Glue job unaided',
    'Explain the job bookmark to a colleague',
  ]);
  assert.deepEqual(splitLines('data-engineering\npython'), ['data-engineering', 'python']);
  assert.deepEqual(splitLines('  a  \n\n\n  b  \n'), ['a', 'b']);
});

test('splitLines: a pasted bullet prefix is stripped, a bare hyphen is not', () => {
  assert.deepEqual(splitLines('- one\n* two\n+ three'), ['one', 'two', 'three']);
  /* No whitespace after the hyphen, so it is part of the value. */
  assert.deepEqual(splitLines('data-engineering'), ['data-engineering']);
});

test('splitLines: empty input yields an empty list, never [""]', () => {
  assert.deepEqual(splitLines(''), []);
  assert.deepEqual(splitLines('   \n  \n'), []);
  assert.deepEqual(splitLines(undefined), []);
});

/* ---------------------------------------------------------------- *
 * parseMilestoneLine — the (concepts: …) parser.
 * Mirrors planning/markdown.py `_parse_milestone_line`.
 * ---------------------------------------------------------------- */

test('parseMilestoneLine: the journey line yields the title and both concepts', () => {
  const m = parseMilestoneLine('Understand Glue job anatomy (concepts: glue job, job bookmark)');
  assert.equal(m.title, 'Understand Glue job anatomy');
  assert.deepEqual(m.concepts, ['glue job', 'job bookmark']);
  assert.equal(m.notes, '');
  assert.equal(m.done, false);
});

test('parseMilestoneLine: no concepts tail leaves the title whole', () => {
  const m = parseMilestoneLine('Write the transform');
  assert.equal(m.title, 'Write the transform');
  assert.deepEqual(m.concepts, []);
});

test('parseMilestoneLine: a backtick-wrapped tail parses (the rendered document form)', () => {
  const m = parseMilestoneLine('Closures — cell variables `(concepts: closures, cell-vars)`');
  assert.equal(m.title, 'Closures');
  assert.equal(m.notes, 'cell variables');
  assert.deepEqual(m.concepts, ['closures', 'cell-vars']);
});

test('parseMilestoneLine: em dash, en dash and -- all split title from notes', () => {
  assert.equal(parseMilestoneLine('Title \u2014 notes here').notes, 'notes here');
  assert.equal(parseMilestoneLine('Title \u2013 notes here').notes, 'notes here');
  assert.equal(parseMilestoneLine('Title -- notes here').notes, 'notes here');
  assert.equal(parseMilestoneLine('Title -- notes here').title, 'Title');
});

test('parseMilestoneLine: bold markers are stripped from the title', () => {
  const m = parseMilestoneLine('**Understand Glue job anatomy** (concepts: glue job)');
  assert.equal(m.title, 'Understand Glue job anatomy');
  assert.deepEqual(m.concepts, ['glue job']);
});

test('parseMilestoneLine: a pasted task-list checkbox is honoured, not treated as text', () => {
  const done = parseMilestoneLine('- [x] Understand Glue job anatomy (concepts: glue job)');
  assert.equal(done.done, true);
  assert.equal(done.title, 'Understand Glue job anatomy');
  assert.deepEqual(done.concepts, ['glue job']);

  const open = parseMilestoneLine('- [ ] Write the transform');
  assert.equal(open.done, false);
  assert.equal(open.title, 'Write the transform');
});

test('parseMilestoneLine: the concepts keyword is case-insensitive and spacing-tolerant', () => {
  assert.deepEqual(parseMilestoneLine('T (Concepts:  a ,  b )').concepts, ['a', 'b']);
  assert.deepEqual(parseMilestoneLine('T (CONCEPTS: a)').concepts, ['a']);
});

test('parseMilestoneLine: an empty concepts list is empty, not [""]', () => {
  const m = parseMilestoneLine('Title (concepts: )');
  assert.deepEqual(m.concepts, []);
  assert.equal(m.title, 'Title');
});

test('parseMilestoneLine: blank input yields an empty milestone rather than throwing', () => {
  const m = parseMilestoneLine('   ');
  assert.equal(m.title, '');
  assert.deepEqual(m.concepts, []);
});

/* ---------------------------------------------------------------- *
 * parseMilestoneLines — the whole textarea.
 * ---------------------------------------------------------------- */

test('parseMilestoneLines: the journey block becomes three milestones with concepts', () => {
  const list = parseMilestoneLines(E2E_MILESTONES);
  assert.equal(list.length, 3);
  assert.deepEqual(
    list.map((m) => m.title),
    ['Understand Glue job anatomy', 'Write the transform', 'Schedule and monitor it']
  );
  assert.deepEqual(list[0].concepts, ['glue job', 'job bookmark']);
  assert.deepEqual(list[1].concepts, ['dynamicframe']);
  assert.deepEqual(list[2].concepts, ['cloudwatch']);
  /* At least one milestone naming concepts is what makes the rendered document
     carry inline <code> spans and what lets confidence evidence be joined. */
  assert.ok(list.some((m) => m.concepts.length > 0));
});

test('parseMilestoneLines: blank lines and a trailing newline add no milestones', () => {
  assert.equal(parseMilestoneLines('a\n\n\nb\n').length, 2);
  assert.deepEqual(parseMilestoneLines(''), []);
  assert.deepEqual(parseMilestoneLines('  \n  '), []);
});

/* ---------------------------------------------------------------- *
 * progressPercent / formatProgress — one formatter for reader + sidebar.
 * ---------------------------------------------------------------- */

test('progressPercent: the server percentage wins over a recomputation', () => {
  /* Python's round() is banker's rounding, Math.round is half-up: 1/8 is 12
     server-side and 13 here. The server is authoritative, so it must win. */
  assert.equal(progressPercent(1, 8, 12), 12);
  assert.equal(progressPercent(1, 8, undefined), 13);
});

test('progressPercent: computes from the counts when no percentage is supplied', () => {
  assert.equal(progressPercent(0, 3), 0);
  assert.equal(progressPercent(1, 3), 33);
  assert.equal(progressPercent(2, 3), 67);
  assert.equal(progressPercent(3, 3), 100);
});

test('progressPercent: no milestones is 0%, never NaN or a divide-by-zero', () => {
  assert.equal(progressPercent(0, 0), 0);
  assert.equal(progressPercent(1, 0), 0);
  assert.equal(progressPercent(undefined, undefined), 0);
  assert.equal(progressPercent('x', 'y'), 0);
});

test('progressPercent: clamps into 0-100', () => {
  assert.equal(progressPercent(9, 3), 100);
  assert.equal(progressPercent(0, 3, 250), 100);
  assert.equal(progressPercent(0, 3, -5), 0);
});

test('formatProgress: renders "0/3 · 0%" before any milestone is ticked', () => {
  const label = formatProgress(0, 3, 0);
  assert.ok(label.includes('0/3'), label);
  assert.ok(label.includes('0%'), label);
});

test('formatProgress: one of three renders both "1/3" and "33%"', () => {
  /* Exactly the two substrings the journey asserts on, in both the reader and
     the sidebar entry — which is why there is one formatter and not two. */
  const fromServer = formatProgress(1, 3, 33);
  assert.ok(fromServer.includes('1/3'), fromServer);
  assert.ok(fromServer.includes('33%'), fromServer);

  const computed = formatProgress(1, 3);
  assert.ok(computed.includes('1/3'), computed);
  assert.ok(computed.includes('33%'), computed);
});

test('formatProgress: missing or junk counts degrade to 0/0 · 0%', () => {
  assert.equal(formatProgress(undefined, undefined), '0/0 \u00b7 0%');
  assert.equal(formatProgress(-2, -9), '0/0 \u00b7 0%');
});

/* ================================================================ *
 * Store behaviour — fetch is the only global these paths need.
 * ================================================================ */

const realFetch = globalThis.fetch;

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const summary = (over = {}) => ({
  plan_id: 'p1',
  title: 'Ship a Glue ETL Job',
  status: 'draft',
  topics: [],
  milestone_total: 3,
  milestone_done: 0,
  progress_pct: 0,
  ...over,
});

const detail = (over = {}) => ({
  plan: summary(over.plan || {}),
  markdown: over.markdown ?? '# Ship a Glue ETL Job\n',
  mission: { why: 'because', success: [], constraints: [], out_of_scope: [] },
  milestones:
    over.milestones ?? [{ index: 0, title: 'A', done: false, concepts: ['glue job'], notes: '' }],
  learning_records: [],
  resources: [],
  checkpoints: over.checkpoints ?? [],
  readiness: over.readiness ?? { plan_id: 'p1', ready: false, blockers: [], nudges: [] },
});

/** Reset the module singleton — Alpine has one store, so do the tests. */
function resetStore() {
  Object.assign(plansStore, {
    items: [],
    selected: null,
    markdown: '',
    markdownHtml: '',
    evaluation: null,
    loading: false,
    error: '',
    recordStatus: '',
    creating: false,
    form: {
      braindump: '',
      title: '',
      why: '',
      success: '',
      topics: '',
      milestones: '',
    },
    interview: { questions: [], seed: null },
    evalPhase: '',
    pendingPhase: '',
    saving: false,
    evaluating: false,
    recording: false,
    activating: false,
    togglingIndex: -1,
    initDone: false,
    _epoch: 0,
    _afterRender: [],
    _evalPromise: null,
  });
}

beforeEach(resetStore);

afterEach(() => {
  globalThis.fetch = realFetch;
});

/**
 * Install a fetch stub routed by "METHOD /path", recording every call.
 * An unrouted request is a test bug, so it 500s loudly rather than silently
 * returning something plausible.
 */
function server(routes) {
  const calls = [];
  globalThis.fetch = async (url, opts = {}) => {
    const method = (opts.method || 'GET').toUpperCase();
    const path = String(url);
    const body = opts.body ? JSON.parse(opts.body) : null;
    calls.push({ method, path, body });
    const handler = routes[`${method} ${path}`];
    if (!handler) return new Response('unrouted', { status: 500, statusText: 'unrouted' });
    return typeof handler === 'function' ? handler({ body, calls }) : handler;
  };
  return calls;
}

/* ---------------------------------------------------------------- *
 * load — the list, and the honest empty state.
 * ---------------------------------------------------------------- */

test('load: populates items and reports a real completion flag', async () => {
  server({ 'GET /api/plans': () => json(200, { plans: [summary()], count: 1 }) });
  assert.equal(plansStore.initDone, false);
  await plansStore.load();
  assert.equal(plansStore.items.length, 1);
  assert.equal(plansStore.loading, false);
  assert.equal(plansStore.initDone, true);
  assert.equal(plansStore.error, '');
});

test('isEmpty is not gated on `loading`, so a stuck flag cannot blank the list', () => {
  plansStore.loading = true;
  assert.equal(plansStore.isEmpty, true);
  plansStore.items = [summary()];
  assert.equal(plansStore.isEmpty, false);
});

test('load: a failing list surfaces an error and still finishes loading', async () => {
  server({ 'GET /api/plans': () => json(500, { detail: 'index is corrupt' }) });
  await plansStore.load();
  assert.equal(plansStore.error, 'index is corrupt');
  assert.equal(plansStore.loading, false);
});

/* ---------------------------------------------------------------- *
 * create — the payload the API actually receives.
 * ---------------------------------------------------------------- */

test('submitPlan: newline fields become lists and milestone tails become concepts', async () => {
  const calls = server({
    'POST /api/plans': () => json(201, { created: true, plan: summary() }),
    'GET /api/plans': () => json(200, { plans: [summary()], count: 1 }),
    'GET /api/plans/p1': () => json(200, detail()),
  });

  Object.assign(plansStore.form, {
    title: 'Ship a Glue ETL Job',
    why: 'Own the nightly customer-events pipeline without pairing.',
    success: E2E_SUCCESS,
    topics: 'data-engineering\npython',
    milestones: E2E_MILESTONES,
    braindump: 'I can read a Glue job but I freeze when asked to write one.',
  });
  await plansStore.submitPlan();

  const post = calls.find((c) => c.method === 'POST' && c.path === '/api/plans');
  assert.ok(post, 'the plan was POSTed');
  assert.equal(post.body.title, 'Ship a Glue ETL Job');
  assert.deepEqual(post.body.answers.topics, ['data-engineering', 'python']);
  assert.deepEqual(post.body.answers.success, [
    'Deploy a Glue job unaided',
    'Explain the job bookmark to a colleague',
  ]);
  assert.equal(post.body.answers.milestones.length, 3);
  assert.deepEqual(post.body.answers.milestones[0], {
    title: 'Understand Glue job anatomy',
    concepts: ['glue job', 'job bookmark'],
    notes: '',
    done: false,
  });
  /* The brain dump rides along so the reasoning survives the plan. */
  assert.match(post.body.answers.notes, /^I can read a Glue job/);

  /* And the new plan is opened, which is what the reader waits for. */
  assert.equal(plansStore.selected.title, 'Ship a Glue ETL Job');
  assert.equal(plansStore.creating, false);
  assert.equal(plansStore.items.length, 1);
});

test('submitPlan: a title is required, and a double submit is refused', async () => {
  const calls = server({ 'POST /api/plans': () => json(201, { created: true, plan: summary() }) });
  await plansStore.submitPlan(); // no title
  assert.equal(calls.length, 0);

  plansStore.form.title = 'x';
  plansStore.saving = true; // a submit already in flight
  await plansStore.submitPlan();
  assert.equal(calls.length, 0);
});

test('submitPlan: a rejected create reports the reason and keeps the form open', async () => {
  server({ 'POST /api/plans': () => json(409, { detail: 'a plan with that id exists' }) });
  plansStore.creating = true;
  plansStore.form.title = 'Ship a Glue ETL Job';
  await plansStore.submitPlan();
  assert.equal(plansStore.error, 'a plan with that id exists');
  assert.equal(plansStore.creating, true);
  assert.equal(plansStore.selected, null);
});

test('startCreate: clears the reader so a stale plan cannot be mistaken for the new one', () => {
  server({ 'GET /api/plans/interview': () => json(200, { questions: [], seed: null }) });
  plansStore.selected = summary({ title: 'An Older Plan' });
  plansStore.markdown = '# An Older Plan';
  plansStore.markdownHtml = '<h1>An Older Plan</h1>';
  plansStore.evaluation = { verdict: 'on-track', headline: 'x', recommendations: ['y'] };
  plansStore.recordStatus = 'Recorded start checkpoint';
  plansStore.form.title = 'leftover';

  plansStore.startCreate();

  assert.equal(plansStore.creating, true);
  assert.equal(plansStore.selected, null);
  assert.equal(plansStore.markdown, '');
  assert.equal(plansStore.markdownHtml, '');
  assert.equal(plansStore.evaluation, null);
  assert.equal(plansStore.recordStatus, '');
  assert.equal(plansStore.form.title, '');
});

/* ---------------------------------------------------------------- *
 * evaluation + recording.
 * ---------------------------------------------------------------- */

const EVALUATION = {
  plan_id: 'p1',
  plan_title: 'Ship a Glue ETL Job',
  phase: 'start',
  verdict: 'on-track',
  headline: 'Two milestones left and time to spare.',
  recommendations: ['Start with the job bookmark.'],
};

test('evaluate: verdict, headline and recommendations land from the preview', async () => {
  server({
    'GET /api/plans/p1/evaluate?phase=start': () =>
      json(200, { evaluation: EVALUATION, markdown: '### checkpoint' }),
  });
  plansStore.selected = summary();
  await plansStore.evaluate('start');
  assert.equal(plansStore.verdict, 'on-track');
  assert.ok(plansStore.headline.length > 0);
  assert.equal(plansStore.recommendations.length, 1);
  assert.equal(plansStore.evalPhase, 'start');
  assert.equal(plansStore.evaluating, false);
});

test('evaluate: the phase is only published once its verdict has arrived', async () => {
  let release;
  globalThis.fetch = async () => {
    await new Promise((r) => {
      release = r;
    });
    return json(200, { evaluation: { ...EVALUATION, phase: 'mid' }, markdown: '' });
  };
  plansStore.selected = summary();
  plansStore.evalPhase = 'start';
  const pending = plansStore.evaluate('mid');
  /* pendingPhase is optimistic (button state); evalPhase is not, so markup
     bound to it never claims a phase whose verdict is still in flight. */
  assert.equal(plansStore.pendingPhase, 'mid');
  assert.equal(plansStore.evalPhase, 'start');
  release();
  await pending;
  assert.equal(plansStore.evalPhase, 'mid');
});

test('recordCheckpoint: status is published only after the document is re-read', async () => {
  const observed = {};
  server({
    'POST /api/plans/p1/evaluate': ({ body }) => {
      observed.phase = body.phase;
      return json(201, { recorded: true, evaluation: EVALUATION, markdown: '' });
    },
    'GET /api/plans': () => json(200, { plans: [summary()], count: 1 }),
    'GET /api/plans/p1': () => {
      /* The journey waits on plan-record-status and then reads the checkpoint
         table, so the status must not appear before the table exists. */
      observed.statusAtReload = plansStore.recordStatus;
      return json(200, detail({ checkpoints: [{ phase: 'start', verdict: 'on-track' }] }));
    },
  });
  plansStore.selected = summary();
  plansStore.pendingPhase = 'start';

  await plansStore.recordCheckpoint();

  assert.equal(observed.phase, 'start');
  assert.equal(observed.statusAtReload, '');
  assert.match(plansStore.recordStatus.toLowerCase(), /recorded/);
  assert.match(plansStore.recordStatus, /start/);
  assert.equal(plansStore.recording, false);
});

test('recordCheckpoint: records the phase the learner clicked, not a stale one', async () => {
  /* Phase 5 leaves the panel showing 'end'; phase 6 clicks start and records
     immediately. Without the synchronous pendingPhase the wrong checkpoint
     gets written. */
  const observed = {};
  server({
    'GET /api/plans/p1/evaluate?phase=start': () =>
      json(200, { evaluation: EVALUATION, markdown: '' }),
    'POST /api/plans/p1/evaluate': ({ body }) => {
      observed.phase = body.phase;
      return json(201, { recorded: true, evaluation: EVALUATION, markdown: '' });
    },
    'GET /api/plans': () => json(200, { plans: [summary()], count: 1 }),
    'GET /api/plans/p1': () => json(200, detail()),
  });
  plansStore.selected = summary();
  plansStore.evaluation = { ...EVALUATION, phase: 'end' };
  plansStore.evalPhase = 'end';

  const previewing = plansStore.evaluate('start'); // not awaited by the "user"
  await plansStore.recordCheckpoint();
  await previewing;

  assert.equal(observed.phase, 'start');
});

/* ---------------------------------------------------------------- *
 * milestones.
 * ---------------------------------------------------------------- */

test('toggleMilestone: the server summary drives both the reader and the sidebar', async () => {
  const ticked = summary({ milestone_done: 1, progress_pct: 33 });
  server({
    'POST /api/plans/p1/milestones/0/toggle': () =>
      json(200, { updated: true, index: 0, done: true, plan: ticked }),
    'GET /api/plans/p1': () =>
      json(200, {
        ...detail({ plan: { milestone_done: 1, progress_pct: 33 } }),
        milestones: [{ index: 0, title: 'A', done: true, concepts: ['glue job'], notes: '' }],
      }),
  });
  plansStore.items = [summary()];
  plansStore.selected = summary();

  await plansStore.toggleMilestone(0);

  /* Same formatter, same numbers — the whole reason this state is in a store. */
  assert.equal(plansStore.progressLabel(plansStore.items[0]), '1/3 \u00b7 33%');
  assert.equal(plansStore.progressText, '1/3 \u00b7 33%');
  assert.equal(plansStore.milestones[0].done, true);
  assert.equal(plansStore.togglingIndex, -1);
});

test('toggleMilestone: ignores a bad index and a toggle already in flight', async () => {
  const calls = server({});
  plansStore.selected = summary();
  await plansStore.toggleMilestone(-1);
  await plansStore.toggleMilestone('nope');
  plansStore.togglingIndex = 0;
  await plansStore.toggleMilestone(1);
  assert.equal(calls.length, 0);
});

/* ---------------------------------------------------------------- *
 * activation — the refusal must actually refuse.
 * ---------------------------------------------------------------- */

test('activate: a refusal names the blockers, keeps the status, and says "cannot activate"', async () => {
  const blockers = [
    "Mission 'why' is empty \u2014 interview the learner first.",
    'No observable success criteria.',
    'No milestones \u2014 the plan cannot be evaluated.',
  ];
  server({
    'PATCH /api/plans/p1': () =>
      json(422, {
        detail: {
          message: 'plan is not ready to activate',
          plan_id: 'p1',
          ready: false,
          blockers,
          nudges: [],
        },
      }),
  });
  plansStore.selected = {
    ...summary({ title: 'Vague Someday Plan', status: 'draft' }),
    readiness: { plan_id: 'p1', ready: false, blockers: [], nudges: [] },
  };

  await plansStore.activate();

  const error = plansStore.error.toLowerCase();
  assert.match(error, /cannot activate/);
  assert.match(error, /mission/);
  assert.match(error, /milestone/);
  /* Refusing means the status does not move. */
  assert.equal(plansStore.selected.status, 'draft');
  /* And the fresh readiness from the refusal feeds the blockers list. */
  assert.equal(plansStore.blockers.length, 3);
  assert.equal(plansStore.ready, false);
  assert.equal(plansStore.activating, false);
});

test('activate: a refusal with no blockers still says "cannot activate"', async () => {
  server({ 'PATCH /api/plans/p1': () => json(400, { detail: 'unparseable markdown' }) });
  plansStore.selected = summary();
  await plansStore.activate();
  assert.match(plansStore.error.toLowerCase(), /cannot activate/);
  assert.match(plansStore.error, /unparseable markdown/);
});

test('activate: success applies the new status', async () => {
  const active = summary({ status: 'active' });
  server({
    'PATCH /api/plans/p1': () =>
      json(200, { updated: true, plan: active, readiness: { ready: true, blockers: [], nudges: [] } }),
    'GET /api/plans/p1': () => json(200, detail({ plan: { status: 'active' } })),
  });
  plansStore.items = [summary()];
  plansStore.selected = summary();
  await plansStore.activate();
  assert.equal(plansStore.selected.status, 'active');
  assert.equal(plansStore.items[0].status, 'active');
  assert.equal(plansStore.error, '');
});

/* ---------------------------------------------------------------- *
 * the epoch guard.
 * ---------------------------------------------------------------- */

test('a slow selection cannot overwrite a newer one', async () => {
  let release;
  globalThis.fetch = async (url) => {
    const path = String(url);
    if (path === '/api/plans/slow') {
      await new Promise((r) => {
        release = r;
      });
      return json(200, detail({ plan: { plan_id: 'slow', title: 'Slow Plan' } }));
    }
    return json(200, detail({ plan: { plan_id: 'fast', title: 'Fast Plan' } }));
  };

  const slow = plansStore.select('slow');
  const fast = plansStore.select('fast');
  await fast;
  assert.equal(plansStore.selected.title, 'Fast Plan');
  release();
  await slow;
  /* The stale response lands last and must be discarded, not rendered. */
  assert.equal(plansStore.selected.title, 'Fast Plan');
  assert.equal(plansStore.loading, false);
});

test('the epoch starts at 0 so the first bump is 1, never NaN', () => {
  assert.equal(plansStore._epoch, 0);
  assert.equal(plansStore._bump(), 1);
  assert.equal(plansStore._bump(), 2);
});

test('select: ignores a missing id and accepts a summary object', async () => {
  const calls = server({ 'GET /api/plans/p1': () => json(200, detail()) });
  await plansStore.select('');
  await plansStore.select(null);
  await plansStore.select({});
  assert.equal(calls.length, 0);
  await plansStore.select(summary());
  assert.equal(plansStore.selected.plan_id, 'p1');
  assert.equal(plansStore.isSelected('p1'), true);
  assert.equal(plansStore.isSelected('other'), false);
});

/* ---------------------------------------------------------------- *
 * the panel facade.
 * ---------------------------------------------------------------- */

test('plansPanel: a factory returning a plain object, never a class instance', () => {
  const panel = plansPanel();
  assert.equal(typeof panel, 'object');
  assert.equal(Object.getPrototypeOf(panel), Object.prototype);
  /* Own-properties, because Alpine proxies the returned object and prototype
     methods are invisible to it. */
  assert.ok(Object.prototype.hasOwnProperty.call(panel, 'init'));
  assert.ok(Object.prototype.hasOwnProperty.call(panel, 'toggleMilestone'));
});

test('plansPanel: getters forward to the store and form writes land on it', () => {
  const panel = plansPanel();
  plansStore.items = [summary()];
  plansStore.selected = summary({ milestone_done: 1, progress_pct: 33 });
  assert.equal(panel.items.length, 1);
  assert.equal(panel.selected.title, 'Ship a Glue ETL Job');
  assert.equal(panel.progressText, '1/3 \u00b7 33%');
  assert.equal(panel.isEmpty, false);

  /* x-model="form.title" must write through, not shadow. */
  panel.form.title = 'typed by the learner';
  assert.equal(plansStore.form.title, 'typed by the learner');
});

test('plansPanel: scalars markup assigns to have setters, not getters alone', () => {
  const panel = plansPanel();
  panel.creating = true;
  assert.equal(plansStore.creating, true);
  panel.error = 'boom';
  assert.equal(plansStore.error, 'boom');
  panel.error = null;
  assert.equal(plansStore.error, '');
});

test('plansPanel: init registers the after-render hook before it awaits anything', async () => {
  /* The hook must exist before the first await: a listener registered after two
     awaits loses every event dispatched in that window, permanently. */
  server({ 'GET /api/plans': () => json(200, { plans: [], count: 0 }) });
  const panel = plansPanel();
  const pending = panel.init();
  assert.equal(plansStore._afterRender.length, 1);
  await pending;
  assert.equal(plansStore.initDone, true);
});

test('plansPanel: init does not re-load a store that has already loaded', async () => {
  const calls = server({ 'GET /api/plans': () => json(200, { plans: [], count: 0 }) });
  plansStore.initDone = true;
  await plansPanel().init();
  assert.equal(calls.length, 0);
});
