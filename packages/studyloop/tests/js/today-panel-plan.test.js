/**
 * Today panel — plan relevance rendering (issue #10, design §3).
 *
 * The Today card shows WHICH active plan an action advances, which next
 * milestones the current energy deferred, and what to do about a plan whose
 * every milestone is checked. It never re-ranks: the labels are derived from
 * the payload `/api/now` already ranked (`primary.plan_refs`, `active_plans`,
 * `energy_deferred`, `completion_actions`), and a payload without those keys —
 * the pre-#10 shape a learner with no active plan still gets — renders no
 * plan text at all.
 *
 * Same `node --test` seam as today-panel.test.js: the factory is a plain
 * object, so the helpers can be exercised with fixture payloads and no DOM.
 */
// Run with:  node --test 'packages/studyloop/tests/js/**/*.test.js'

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { todayPanel } from
  '../../src/studyloop/web/static/js/components/today-panel.js';

/* A ranked payload with one plan-related primary, one deferred milestone. */
const PLAN_PAYLOAD = {
  energy: 'low',
  starter: false,
  primary: {
    concept: 'window function',
    action_type: 'hands-on',
    estimated_minutes: 20,
    reason: 'Recorded as struggling',
    plan_refs: [{ plan_id: 'sql-windows', milestone_index: null }],
  },
  alternates: [
    {
      concept: 'window frame',
      action_type: 'conversation',
      estimated_minutes: 20,
      reason: 'Next milestone 2/2 of plan \u2018SQL Windows\u2019: Frames',
      plan_refs: [{ plan_id: 'sql-windows', milestone_index: 1 }],
    },
    { concept: 'decorators', action_type: 'recall', estimated_minutes: 10, reason: 'due' },
  ],
  active_plans: [
    {
      plan_id: 'sql-windows',
      title: 'SQL Windows',
      target_urgency: 'undated',
      days_until_target: null,
      energy_floor: 5,
      eligible: false,
      next_milestone: 'Frames',
      next_milestone_index: 1,
      milestone_done: 1,
      milestone_total: 2,
      ready: true,
    },
  ],
  energy_deferred: [
    {
      plan_id: 'sql-windows',
      plan_title: 'SQL Windows',
      milestone_index: 1,
      title: 'Frames',
      energy_floor: 5,
      energy_capability: 3,
      reason: 'low energy carries 3/10; \u2018SQL Windows\u2019 asks for at least 5/10',
    },
  ],
};

/* The pre-#10 payload shape: no plan keys anywhere. */
const NO_PLAN_PAYLOAD = {
  energy: 'medium',
  starter: false,
  primary: { concept: 'decorators', action_type: 'recall', estimated_minutes: 10, reason: 'due' },
  alternates: [],
};

test('planLabel: names the plan an action advances, with its milestone when one is referenced', () => {
  const panel = todayPanel();
  panel.plan = PLAN_PAYLOAD;

  assert.equal(panel.planLabel(PLAN_PAYLOAD.primary), 'SQL Windows');
  assert.equal(panel.planLabel(PLAN_PAYLOAD.alternates[0]), 'SQL Windows \u00b7 milestone 2: Frames');
  assert.equal(panel.planLabel(PLAN_PAYLOAD.alternates[1]), '', 'an unrelated action has no plan label');
});

test('planLabel: keeps every referenced plan, in the order the engine ranked them', () => {
  const panel = todayPanel();
  panel.plan = {
    ...PLAN_PAYLOAD,
    active_plans: [
      { ...PLAN_PAYLOAD.active_plans[0], plan_id: 'soon-plan', title: 'Soon Plan', next_milestone_index: 0, next_milestone: 'Start' },
      PLAN_PAYLOAD.active_plans[0],
    ],
  };
  const rec = {
    concept: 'window frame',
    plan_refs: [
      { plan_id: 'soon-plan', milestone_index: 0 },
      { plan_id: 'sql-windows', milestone_index: null },
    ],
  };

  assert.equal(panel.planLabel(rec), 'Soon Plan \u00b7 milestone 1: Start; SQL Windows');
});

test('deferredNotes: one readable line per energy-deferred milestone', () => {
  const panel = todayPanel();
  panel.plan = PLAN_PAYLOAD;

  assert.deepEqual(panel.deferredNotes(), [
    'SQL Windows \u2014 \u201cFrames\u201d waits for more energy (needs 5/10, low energy carries 3/10)',
  ]);
});

test('completionNotes: the engine\u2019s completion actions, verbatim', () => {
  const panel = todayPanel();
  panel.plan = {
    ...NO_PLAN_PAYLOAD,
    active_plans: [{ plan_id: 'done', title: 'Done', next_milestone: '', next_milestone_index: null }],
    completion_actions: [
      { plan_id: 'done', plan_title: 'Done', action: "Every milestone of 'Done' is checked off \u2014 close the plan." },
    ],
  };

  assert.deepEqual(panel.completionNotes(), [
    "Every milestone of 'Done' is checked off \u2014 close the plan.",
  ]);
  assert.equal(panel.hasPlanContext, true);
});

test('completionEvidence: the closing review\u2019s lines, in the engine\u2019s order, across actions', () => {
  const panel = todayPanel();
  panel.plan = {
    ...NO_PLAN_PAYLOAD,
    completion_actions: [
      {
        plan_id: 'done',
        plan_title: 'Done',
        action: 'closing review proposes extending the plan',
        due_reviews: 1,
        struggles: 0,
        unverified_milestones: 1,
        proposal: 'extend',
        evidence: [
          'Due review: alpha \u2014 overdue',
          'Unverified milestone: B \u2014 marked done, no evidence on its concepts',
        ],
      },
      // A pre-D-G entry (no evidence key) and a failed assessment (proposal null,
      // evidence empty) both contribute nothing.
      { plan_id: 'old', plan_title: 'Old', action: 'plain sentence' },
      { plan_id: 'unread', plan_title: 'Unread', action: 'plain sentence', proposal: null, evidence: [] },
    ],
  };

  assert.deepEqual(panel.completionEvidence(), [
    'Due review: alpha \u2014 overdue',
    'Unverified milestone: B \u2014 marked done, no evidence on its concepts',
  ]);
  assert.equal(panel.completionNotes().length, 3);
});

/* Council review 6, GPT F6 (🟡): the card printed every sentence, then every
 * evidence line flattened beneath them, so with two finished plans a line
 * lost the plan it belonged to. The card renders one block per action —
 * the sentence and its own lines — keyed by plan_id, in the engine's order.
 * A partial review (proposal null, council F1) keeps its 'Not read:' lines. */
test('completionReviews: one block per finished plan, each with its own evidence, in the engine\u2019s order', () => {
  const panel = todayPanel();
  panel.plan = {
    ...NO_PLAN_PAYLOAD,
    completion_actions: [
      {
        plan_id: 'sql', plan_title: 'SQL', action: 'SQL: proposes extending', proposal: 'extend',
        due_reviews: 1, struggles: 0, unverified_milestones: 0,
        evidence: ['Due review: window function \u2014 overdue'],
      },
      {
        plan_id: 'py', plan_title: 'Python', action: 'Python: partial', proposal: null, partial: true,
        due_reviews: 0, struggles: 0, unverified_milestones: 0,
        evidence: ['Not read: due reviews unavailable \u2014 evaluation is partial'],
      },
      { plan_id: 'old', plan_title: 'Old', action: 'plain sentence' },
    ],
  };

  assert.deepEqual(panel.completionReviews(), [
    { planId: 'sql', sentence: 'SQL: proposes extending', evidence: ['Due review: window function \u2014 overdue'] },
    { planId: 'py', sentence: 'Python: partial', evidence: ['Not read: due reviews unavailable \u2014 evaluation is partial'] },
    { planId: 'old', sentence: 'plain sentence', evidence: [] },
  ]);
  // The flat helpers stay for callers that want them, and agree with the blocks.
  assert.deepEqual(panel.completionNotes(), panel.completionReviews().map((r) => r.sentence));
  assert.deepEqual(panel.completionEvidence(), panel.completionReviews().flatMap((r) => r.evidence));
});

test('the Today card markup renders one keyed block per closing review with its evidence nested inside', () => {
  const html = fs.readFileSync(
    new URL('../../src/studyloop/web/static/index.html', import.meta.url), 'utf8',
  );
  const start = html.indexOf('class="today-plan-notes"');
  const end = html.indexOf('</div>', html.indexOf('warningNotes()', start));
  const block = html.slice(start, end);
  assert.match(block, /x-for="review in completionReviews\(\)" :key="'c' \+ review\.planId"/);
  assert.match(block, /class="today-plan-review" :data-plan-id="review\.planId"/);
  assert.match(block, /Closing review: <span x-text="review\.sentence">/);
  assert.match(block, /x-for="\(line, i\) in review\.evidence"/, 'evidence is nested in its plan\u2019s block');
  assert.doesNotMatch(block, /completionEvidence\(\)/, 'no flat evidence loop beside the sentences');
  assert.doesNotMatch(block, /Plan complete/, 'an active plan is not labelled complete');
});

test('a payload without plan keys renders no plan text, before and after init-like assignment', () => {
  const panel = todayPanel();

  assert.equal(panel.planLabel(null), '');
  assert.deepEqual(panel.deferredNotes(), []);
  assert.deepEqual(panel.completionNotes(), []);
  assert.deepEqual(panel.completionEvidence(), []);
  assert.equal(panel.hasPlanContext, false);

  panel.plan = NO_PLAN_PAYLOAD;

  assert.equal(panel.planLabel(NO_PLAN_PAYLOAD.primary), '');
  assert.deepEqual(panel.deferredNotes(), []);
  assert.deepEqual(panel.completionNotes(), []);
  assert.equal(panel.hasPlanContext, false);
});

test('a plan_ref whose plan is missing from active_plans falls back to the id, never throws', () => {
  const panel = todayPanel();
  panel.plan = { ...NO_PLAN_PAYLOAD, active_plans: [] };

  assert.equal(
    panel.planLabel({ concept: 'x', plan_refs: [{ plan_id: 'ghost', milestone_index: 0 }] }),
    'ghost',
  );
});


/* Council review 3 (Grok 🔵): the engine's `warnings` — an unready plan's
   blockers, an unreadable document — were visible on the CLI and in the JSON
   but not on the Today card. They are rendered verbatim, as data. */
test('warningNotes: the engine\u2019s warnings, verbatim, and they count as plan context', () => {
  const panel = todayPanel();
  panel.plan = {
    ...NO_PLAN_PAYLOAD,
    active_plans: [{ plan_id: 'husk', title: 'Husk', next_milestone: 'Frames', next_milestone_index: 0, ready: false }],
    warnings: ["active plan 'husk' is not ready (Mission 'why' is empty) \u2014 pause or repair it"],
  };

  assert.deepEqual(panel.warningNotes(), [
    "active plan 'husk' is not ready (Mission 'why' is empty) \u2014 pause or repair it",
  ]);
  assert.equal(panel.hasPlanContext, true);
});

test('warningNotes: absent key renders no warning text', () => {
  const panel = todayPanel();

  assert.deepEqual(panel.warningNotes(), []);

  panel.plan = NO_PLAN_PAYLOAD;

  assert.deepEqual(panel.warningNotes(), []);
  assert.equal(panel.hasPlanContext, false);
});

/* Item 5 (D-F): a repair the day's energy cannot carry, in its own additive key
   (design §5 amendment 2 — `energy_deferred` is milestone-shaped), and the
   body-double proposal the engine synthesises when nothing plan-related fits. */
const DEFERRED_REPAIR_PAYLOAD = {
  ...PLAN_PAYLOAD,
  primary: {
    concept: 'Sit with SQL Windows',
    action_type: 'conversation',
    estimated_minutes: 25,
    reason: 'Nothing plan-related fits low energy today',
    source: 'body_double',
    evidence_command: 'studyloop study "SQL Windows" --mode co-study',
    plan_refs: [{ plan_id: 'sql-windows', milestone_index: null }],
  },
  energy_deferred_repairs: [
    {
      plan_id: 'sql-windows',
      plan_title: 'SQL Windows',
      concept: 'window function',
      topic: 'sql',
      confidence: 'struggling',
      energy_demand: 'high',
      required_capability: 6,
      energy_capability: 3,
      reason: 'low energy carries 3/10; repairing a live struggle asks for at least 6/10',
    },
  ],
};

test('deferredRepairNotes: one readable line per energy-deferred repair', () => {
  const panel = todayPanel();
  panel.plan = DEFERRED_REPAIR_PAYLOAD;

  assert.deepEqual(panel.deferredRepairNotes(), [
    'SQL Windows \u2014 repairing \u201cwindow function\u201d (struggling) waits for more energy '
    + '(asks for 6/10, low energy carries 3/10)',
  ]);
});

test('deferredRepairNotes: a repair unrelated to any plan names no plan, and counts as plan context alone', () => {
  const panel = todayPanel();
  panel.plan = {
    ...NO_PLAN_PAYLOAD,
    energy: 'low',
    energy_deferred_repairs: [
      {
        plan_id: null,
        plan_title: null,
        concept: 'decorators',
        topic: 'python',
        confidence: 'struggling',
        energy_demand: 'high',
        required_capability: 6,
        energy_capability: 3,
        reason: 'low energy carries 3/10',
      },
    ],
  };

  assert.deepEqual(panel.deferredRepairNotes(), [
    'Repairing \u201cdecorators\u201d (struggling) waits for more energy '
    + '(asks for 6/10, low energy carries 3/10)',
  ]);
  assert.equal(panel.hasPlanContext, true);
});

test('deferredRepairNotes: absent key renders nothing, before and after assignment', () => {
  const panel = todayPanel();

  assert.deepEqual(panel.deferredRepairNotes(), []);

  panel.plan = PLAN_PAYLOAD;

  assert.deepEqual(panel.deferredRepairNotes(), []);
});

test('a body-double primary starts in the Body Double view; every other action keeps its view', () => {
  const panel = todayPanel();

  assert.equal(panel.viewForAction(DEFERRED_REPAIR_PAYLOAD.primary), 'body-double');
  assert.equal(panel.viewForAction(PLAN_PAYLOAD.primary), 'study-session');
  assert.equal(panel.viewForAction(NO_PLAN_PAYLOAD.primary), 'flashcards');
});

test('the Today card markup renders the deferred repairs beside the deferred milestones', () => {
  const html = fs.readFileSync(
    new URL('../../src/studyloop/web/static/index.html', import.meta.url), 'utf8',
  );
  const start = html.indexOf('class="today-plan-notes"');
  const end = html.indexOf('</div>', html.indexOf('warningNotes()', start));
  const block = html.slice(start, end);
  assert.match(block, /x-for="\(note, i\) in deferredRepairNotes\(\)" :key="'r' \+ i"/);
  assert.match(block, /Deferred for energy: <span x-text="note">/);
  const show = html.slice(html.lastIndexOf('x-show=', start), start);
  assert.match(show, /deferredRepairNotes\(\)\.length > 0/, 'the notes block shows for a deferred repair alone');
});

test('starting a body-double primary hands its plan to the Body Double view, then navigates (review 7, F7)', () => {
  const events = [];
  const gone = [];
  const savedWindow = globalThis.window;
  const savedAlpine = globalThis.Alpine;
  const savedEvent = globalThis.CustomEvent;
  globalThis.window = { dispatchEvent(e) { events.push(e); } };
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  globalThis.Alpine = { store() { return { go(view) { gone.push(view); } }; } };
  try {
    const panel = todayPanel();
    panel.plan = DEFERRED_REPAIR_PAYLOAD;
    panel.plan.primary.metadata = { plan_id: 'sql-windows', deferred_milestones: 1, deferred_repairs: 1 };

    panel.startPrimary();

    assert.deepEqual(gone, ['body-double']);
    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'body-double-request');
    assert.deepEqual(events[0].detail, { activity: 'SQL Windows', energy: 'low' });

    events.length = 0; gone.length = 0;
    panel.startAction(PLAN_PAYLOAD.primary);

    assert.deepEqual(gone, ['study-session']);
    assert.equal(events.length, 0, 'an ordinary action dispatches nothing');
  } finally {
    globalThis.window = savedWindow;
    globalThis.Alpine = savedAlpine;
    globalThis.CustomEvent = savedEvent;
  }
});

test('bodyDoubleActivity: the named plan\u2019s title, else the proposal\u2019s concept', () => {
  const panel = todayPanel();
  panel.plan = DEFERRED_REPAIR_PAYLOAD;

  assert.equal(panel.bodyDoubleActivity({ concept: 'Sit with SQL Windows', metadata: { plan_id: 'sql-windows' } }), 'SQL Windows');
  assert.equal(panel.bodyDoubleActivity({ concept: 'Sit with your plans', metadata: { plan_id: 'missing' } }), 'Sit with your plans');
  assert.equal(panel.bodyDoubleActivity(null), '');
});

test('planNotesLabel: "Your plans" when a plan is involved, "Set aside today" for a no-plan deferred repair (review 7, grok)', () => {
  const panel = todayPanel();
  panel.plan = DEFERRED_REPAIR_PAYLOAD;
  assert.equal(panel.planNotesLabel(), 'Your plans');

  panel.plan = {
    ...NO_PLAN_PAYLOAD,
    energy: 'low',
    energy_deferred_repairs: [
      { plan_id: null, plan_title: null, concept: 'decorators', topic: 'python', confidence: 'struggling',
        energy_demand: 'high', required_capability: 6, energy_capability: 3, reason: 'r' },
    ],
  };
  assert.equal(panel.planNotesLabel(), 'Set aside today');
  assert.equal(panel.hasPlanContext, true);
});

/* Issue #30: the body-double proposal carries one tiny, passive first move on the
   deferred material (`metadata.first_move`, engine-derived). The card shows it as
   its own line beside the sit-with door and hands it to the Body Double view with
   the plan title, so the session does not open on a blank page. Additive: a
   payload without the field renders nothing and the hand-off detail is unchanged. */
const FIRST_MOVE =
  'Open your Frames material and read for ten minutes, nothing more — no indexed lesson mentions “window frame” yet.';

test('firstMoveNote: the engine\u2019s first move verbatim, nothing when the payload carries none', () => {
  const panel = todayPanel();
  const withMove = { ...DEFERRED_REPAIR_PAYLOAD.primary,
    metadata: { plan_id: 'sql-windows', deferred_milestones: 1, deferred_repairs: 1, first_move: FIRST_MOVE } };

  assert.equal(panel.firstMoveNote(withMove), FIRST_MOVE);
  assert.equal(panel.firstMoveNote(DEFERRED_REPAIR_PAYLOAD.primary), '');
  /* Rubric 3c (e1)/(e2): the engine puts a warm-up on a plan-related ACTIVE
     primary too, so the card reads the field wherever the engine put it — it
     never re-derives or second-guesses the source. */
  assert.equal(panel.firstMoveNote({ ...withMove, source: 'study_progress:sql:window function' }),
    FIRST_MOVE, 'the card renders the move for any recommendation that carries one');
  assert.equal(panel.firstMoveNote(null), '');
});

test('starting a body-double primary hands the first move to the Body Double view beside the plan', () => {
  const events = [];
  const savedWindow = globalThis.window;
  const savedAlpine = globalThis.Alpine;
  const savedEvent = globalThis.CustomEvent;
  globalThis.window = { dispatchEvent(e) { events.push(e); } };
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  globalThis.Alpine = { store() { return { go() {} }; } };
  try {
    const panel = todayPanel();
    panel.plan = { ...DEFERRED_REPAIR_PAYLOAD,
      primary: { ...DEFERRED_REPAIR_PAYLOAD.primary,
        metadata: { plan_id: 'sql-windows', deferred_milestones: 1, deferred_repairs: 1, first_move: FIRST_MOVE } } };

    panel.startPrimary();

    assert.equal(events.length, 1);
    assert.deepEqual(events[0].detail, { activity: 'SQL Windows', energy: 'low', firstMove: FIRST_MOVE });
  } finally {
    globalThis.window = savedWindow;
    globalThis.Alpine = savedAlpine;
    globalThis.CustomEvent = savedEvent;
  }
});

/* Rubric 3c (d2), owner 2026-09-21: "Open X" actually opens X. When the engine
   resolved a lesson (`metadata.first_move_lesson_id` + `_title`), the card offers
   a control that opens it in the Course Explorer panel — the aside beside the
   current view, so the learner stays on Today (or in the Body Double view) with
   the lesson open next to it. The control exists only when a lesson resolved;
   the sentence has already stated the lesson's evidence (course, matched word),
   so what opens is what the learner has judged. */
const LESSON_MOVE =
  'Open “Decorators 29M” from The Ultimate Typescript — the match is the word “decorators” — and read for ten minutes, nothing more.';
const WITH_LESSON = { ...DEFERRED_REPAIR_PAYLOAD.primary,
  metadata: { plan_id: 'sql-windows', deferred_milestones: 1, deferred_repairs: 1, first_move: LESSON_MOVE,
    first_move_lesson_id: 'udemy/the-ultimate-typescript/decorators-29m', first_move_lesson_title: 'Decorators 29M' } };

test('firstMoveLesson: the resolved lesson (id + title) from the payload, null when none resolved', () => {
  const panel = todayPanel();
  assert.deepEqual(panel.firstMoveLesson(WITH_LESSON),
    { id: 'udemy/the-ultimate-typescript/decorators-29m', title: 'Decorators 29M' });
  const noLesson = { ...WITH_LESSON, metadata: { ...WITH_LESSON.metadata } };
  delete noLesson.metadata.first_move_lesson_id;
  delete noLesson.metadata.first_move_lesson_title;
  assert.equal(panel.firstMoveLesson(noLesson), null, 'a milestone-form move offers nothing to open');
  assert.deepEqual(panel.firstMoveLesson({ ...WITH_LESSON, source: 'study_progress:sql:decorators' }),
    { id: 'udemy/the-ultimate-typescript/decorators-29m', title: 'Decorators 29M' },
    'the control follows the move onto a plan-related active primary too (rubric 3c (e2))');
  assert.equal(panel.firstMoveLesson(null), null);
});

test('openFirstMoveLesson: asks the Course Explorer to open the lesson beside the view, and does not navigate', () => {
  const events = [];
  let navigated = null;
  const savedWindow = globalThis.window;
  const savedAlpine = globalThis.Alpine;
  const savedEvent = globalThis.CustomEvent;
  globalThis.window = { dispatchEvent(e) { events.push(e); } };
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  globalThis.Alpine = { store() { return { go(view) { navigated = view; } }; } };
  try {
    const panel = todayPanel();
    panel.plan = { ...DEFERRED_REPAIR_PAYLOAD, primary: WITH_LESSON };

    panel.openFirstMoveLesson();

    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'explorer-open-lesson');
    assert.deepEqual(events[0].detail,
      { lessonId: 'udemy/the-ultimate-typescript/decorators-29m', title: 'Decorators 29M' });
    assert.equal(navigated, null, 'the learner stays on Today; the lesson opens in the aside');

    panel.plan = { ...DEFERRED_REPAIR_PAYLOAD };
    panel.openFirstMoveLesson();
    assert.equal(events.length, 1, 'nothing to open, nothing dispatched');
  } finally {
    globalThis.window = savedWindow;
    globalThis.Alpine = savedAlpine;
    globalThis.CustomEvent = savedEvent;
  }
});

test('starting a body-double primary hands the resolved lesson to the Body Double view beside the move', () => {
  const events = [];
  const savedWindow = globalThis.window;
  const savedAlpine = globalThis.Alpine;
  const savedEvent = globalThis.CustomEvent;
  globalThis.window = { dispatchEvent(e) { events.push(e); } };
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  globalThis.Alpine = { store() { return { go() {} }; } };
  try {
    const panel = todayPanel();
    panel.plan = { ...DEFERRED_REPAIR_PAYLOAD, primary: WITH_LESSON };

    panel.startPrimary();

    assert.equal(events.length, 1);
    assert.deepEqual(events[0].detail, { activity: 'SQL Windows', energy: 'low', firstMove: LESSON_MOVE,
      firstMoveLessonId: 'udemy/the-ultimate-typescript/decorators-29m', firstMoveLessonTitle: 'Decorators 29M' });
  } finally {
    globalThis.window = savedWindow;
    globalThis.Alpine = savedAlpine;
    globalThis.CustomEvent = savedEvent;
  }
});

/* Rubric 3c (e2), owner 2026-09-21 ("build it now, the (d2)+(d3) shape on the
   Study view"). Before this, Start → on a study action navigated and handed the
   Study picker NOTHING — not the warm-up, not even the concept — so the learner
   retyped the topic from memory and the sentence the card had just shown was
   thrown away. Start now hands the primary over the existing `today-resume`
   event (the same shape the resume and parked paths use; no new event): topic,
   energy, and the move with its lesson when the engine put one there. The Study
   view starts nothing on its own; the learner still presses Start. */
const WARM_UP =
  'Open “Advanced Sql 4H” from Complete Sql Databases Bootcamp — the match is the phrase “window function” — and read for ten minutes, then start the repair.';
const REPAIR_PRIMARY = {
  concept: 'window function', topic: 'sql', action_type: 'hands-on',
  source: 'study_progress:sql:window function', reason: 'Guided repair + tiny practice',
  estimated_minutes: 15, evidence_command: 'studyloop progress "window function" -t "sql" -c learning',
  score: 108, plan_refs: [{ plan_id: 'sql-windows', milestone_index: null }],
  metadata: { confidence: 'struggling', energy_demand: 'high', first_move: WARM_UP,
    first_move_lesson_id: 'ztm/complete-sql-bootcamp/advanced-sql-4h', first_move_lesson_title: 'Advanced Sql 4H' },
};

function withStubbedWindow(run) {
  const events = [];
  const navigated = [];
  const savedWindow = globalThis.window;
  const savedAlpine = globalThis.Alpine;
  const savedEvent = globalThis.CustomEvent;
  globalThis.window = { dispatchEvent(e) { events.push(e); } };
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  globalThis.Alpine = { store() { return { go(view) { navigated.push(view); } }; } };
  try {
    return run(events, navigated);
  } finally {
    globalThis.window = savedWindow;
    globalThis.Alpine = savedAlpine;
    globalThis.CustomEvent = savedEvent;
  }
}

test('starting a study-session primary hands its topic, energy and warm-up to the Study view', () => {
  withStubbedWindow((events, navigated) => {
    const panel = todayPanel();
    panel.plan = { ...DEFERRED_REPAIR_PAYLOAD, energy: 'medium', primary: REPAIR_PRIMARY,
      energy_deferred: [], energy_deferred_repairs: [] };

    panel.startPrimary();

    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'today-resume', 'the resume/parked hand-off, not a new event');
    assert.deepEqual(events[0].detail, {
      topic: 'window function', energy: 'medium', firstMove: WARM_UP,
      firstMoveLessonId: 'ztm/complete-sql-bootcamp/advanced-sql-4h', firstMoveLessonTitle: 'Advanced Sql 4H',
    });
    assert.deepEqual(navigated, ['study-session']);
  });
});

test('a study-session primary without a move hands its topic and energy only', () => {
  withStubbedWindow((events, navigated) => {
    const panel = todayPanel();
    const { first_move, first_move_lesson_id, first_move_lesson_title, ...bare } = REPAIR_PRIMARY.metadata;
    panel.plan = { ...DEFERRED_REPAIR_PAYLOAD, energy: 'high',
      primary: { ...REPAIR_PRIMARY, metadata: bare }, energy_deferred: [], energy_deferred_repairs: [] };

    panel.startPrimary();

    assert.equal(events.length, 1);
    assert.deepEqual(events[0].detail, { topic: 'window function', energy: 'high' },
      'the concept was always lost on Start; it is handed over whether or not a move rides with it');
    assert.deepEqual(navigated, ['study-session']);
  });
});

test('starting a flashcards primary still hands nothing and navigates', () => {
  withStubbedWindow((events, navigated) => {
    const panel = todayPanel();
    panel.plan = { ...DEFERRED_REPAIR_PAYLOAD, energy: 'medium',
      primary: { ...REPAIR_PRIMARY, action_type: 'recall', metadata: {} },
      energy_deferred: [], energy_deferred_repairs: [] };

    panel.startPrimary();

    assert.equal(events.length, 0, 'the recall views have no topic picker to hand to');
    assert.deepEqual(navigated, ['flashcards']);
  });
});
