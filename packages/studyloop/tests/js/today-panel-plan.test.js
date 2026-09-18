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
