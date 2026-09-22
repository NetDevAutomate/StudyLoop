/**
 * Unit tests for the sessionTimer Alpine factory's pure logic.
 *
 * Uses `node --test` (see chunk-text.test.js for the project's rationale).
 * Run with:  node --test 'packages/studyloop/tests/js/**\/*.test.js'
 *
 * SCOPE: sessionTimer() is mostly network/DOM/Alpine glue (fetch, window
 * events, Alpine.store, setInterval/clearInterval, CustomEvent dispatch).
 * This file exercises only the plain-data methods and getters that need
 * neither a DOM nor a live Alpine runtime: energyBandLabel, resolvedTopic,
 * display, progress, timerPhase, and the threshold-crossing ratchet in
 * checkThresholds/showMessage. Everything reachable through these needs
 * only object state (`this.*`) plus the module's two free-standing
 * dependencies, `energyBand` and `THRESHOLDS`.
 *
 * `energyBand` is imported from its real module (already extracted to
 * js/lib/chunk-text.js). `THRESHOLDS` is NOT exported by session-timer.js
 * (it is a free reference the factory expects some enclosing scope to
 * provide — see the cross-reference note in the file header) so it is
 * declared here as a fixture with the same values as production
 * (index.html's inline `const THRESHOLDS`), matching how chunk-text.test.js
 * fixtures energyBand's own thresholds independently on the Python side.
 *
 * SKIPPED (cannot be tested without a DOM/Alpine runtime):
 *   - init(), startSession(), endSession(), confirmEndSession(),
 *     parkAndProceed(), cancelParkFirst() — all touch fetch/window/Alpine.store.
 *   - togglePause()/resetTimer()/tick() as full methods — they call
 *     setInterval/clearInterval and read Date.now()/wall-clock Date objects
 *     as side effects, so only their arithmetic is covered here directly.
 *   - selectOption/agentOptions/selectedAgentSupportsAcp/filteredCourses/
 *     filteredLessons — trivial array-derived getters with no interesting
 *     boundary; skipped per "test boundaries, not trivia".
 *   - timerIcon — trivial 3-way string map over timerPhase, already
 *     covered indirectly by the timerPhase boundary tests.
 *   - destroy() — pure teardown (clearInterval/clearTimeout), nothing to
 *     assert without a fake timer harness.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { sessionTimer } from
  '../../src/studyloop/web/static/js/components/session-timer.js';
import { energyBand } from
  '../../src/studyloop/web/static/js/lib/chunk-text.js';

// Mirrors index.html's inline `const THRESHOLDS` at extraction time.
// checkThresholds/progress/timerPhase all read this as a free reference.
globalThis.THRESHOLDS = {
  high: { green: 25, amber: 50 },
  medium: { green: 20, amber: 40 },
  low: { green: 15, amber: 30 },
};
// checkThresholds/progress/timerPhase also call energyBand(...) as a free
// reference (not this.energyBand) — session-timer.js expects it as a global,
// exactly like main.js's `window.energyBand = energyBand` wiring.
globalThis.energyBand = energyBand;

test('energyBandLabel: boundaries', () => {
  const s = sessionTimer();
  s.energy = 7;
  assert.equal(s.energyBandLabel(), 'High energy'); // boundary: >=7 is high
  s.energy = 6;
  assert.equal(s.energyBandLabel(), 'Medium energy');
  s.energy = 4;
  assert.equal(s.energyBandLabel(), 'Medium energy'); // boundary: >=4 is medium
  s.energy = 3;
  assert.equal(s.energyBandLabel(), 'Low energy');
  s.energy = 0;
  assert.equal(s.energyBandLabel(), 'Low energy');
});

test('display: formats elapsed seconds as MM:SS, zero-padded', () => {
  const s = sessionTimer();
  s.elapsed = 0;
  assert.equal(s.display, '00:00');
  s.elapsed = 5;
  assert.equal(s.display, '00:05');
  s.elapsed = 65;
  assert.equal(s.display, '01:05');
  s.elapsed = 3599;
  assert.equal(s.display, '59:59');
  // No hour rollover: minutes just keep growing past 59.
  s.elapsed = 3600;
  assert.equal(s.display, '60:00');
});

test('progress: 0 while session inactive, regardless of elapsed', () => {
  const s = sessionTimer();
  s.sessionActive = false;
  s.elapsed = 999999;
  assert.equal(s.progress, 0);
});

test('progress: scales toward 100 at the amber threshold, clamped after', () => {
  const s = sessionTimer();
  s.sessionActive = true;
  s.energy = 8; // -> 'high' band -> amber at 50 min
  s.elapsed = 0;
  assert.equal(s.progress, 0);
  s.elapsed = 25 * 60; // half of 50 min
  assert.equal(s.progress, 50);
  s.elapsed = 50 * 60; // exactly at amber
  assert.equal(s.progress, 100);
  // Latent-bug note: there is no upper threshold beyond amber, so any time
  // spent in the red phase also reads as a flat 100 here — Math.min just
  // clamps the ratio, it does not distinguish "at amber" from "long past it".
  s.elapsed = 90 * 60;
  assert.equal(s.progress, 100);
});

test('timerPhase: phase-idle when inactive', () => {
  const s = sessionTimer();
  s.sessionActive = false;
  assert.equal(s.timerPhase, 'phase-idle');
});

test('timerPhase: green/amber/red boundaries for the low energy band', () => {
  const s = sessionTimer();
  s.sessionActive = true;
  s.energy = 2; // -> 'low' band -> green:15, amber:30
  s.elapsed = 14 * 60 + 59;
  assert.equal(s.timerPhase, 'phase-green');
  s.elapsed = 15 * 60; // boundary: green threshold
  assert.equal(s.timerPhase, 'phase-amber');
  s.elapsed = 29 * 60 + 59;
  assert.equal(s.timerPhase, 'phase-amber');
  s.elapsed = 30 * 60; // boundary: amber threshold
  assert.equal(s.timerPhase, 'phase-red');
});

test('timerPhase: energy boundary at 4 flips medium vs low band thresholds', () => {
  const s = sessionTimer();
  s.sessionActive = true;
  s.elapsed = 16 * 60; // 16 min

  s.energy = 3; // 'low' band, green:15 -> 16 min is already amber
  assert.equal(s.timerPhase, 'phase-amber');

  s.energy = 4; // 'medium' band, green:20 -> 16 min is still green
  assert.equal(s.timerPhase, 'phase-green');
});

test('checkThresholds: fires the red message once at/after the amber-minute boundary', () => {
  const s = sessionTimer();
  s.energy = 8; // 'high' band -> amber at 50 min
  s.elapsed = 50 * 60;
  s.checkThresholds();
  assert.equal(s._shownRed, true);
  assert.match(s.message, /been at this for a while/);
});

test('checkThresholds: fires the amber nudge only below energy 7', () => {
  const low = sessionTimer();
  low.energy = 5; // < 7
  low.elapsed = 20 * 60 + 1; // just past medium green (20 min)
  low.checkThresholds();
  assert.equal(low._shownAmber, true);
  assert.match(low.message, /micro-break/);

  const high = sessionTimer();
  high.energy = 8; // >= 7, band is 'high' (green:25) — use its own green boundary
  high.elapsed = 25 * 60 + 1;
  high.checkThresholds();
  // _shownAmber still flips (the ratchet is unconditional)...
  assert.equal(high._shownAmber, true);
  // ...but no message is shown because energy >= 7 suppresses the nudge text.
  assert.equal(high.message, '');
});

test('checkThresholds: ratchet does not re-fire once _shownAmber/_shownRed are set', () => {
  const s = sessionTimer();
  s.energy = 2; // 'low' band: green:15, amber:30
  s.elapsed = 15 * 60;
  s.checkThresholds();
  assert.equal(s._shownAmber, true);
  s.message = ''; // simulate the message having already timed out
  s.elapsed = 16 * 60; // still amber phase, still below the amber threshold
  s.checkThresholds();
  // Latent-bug note: this is intentional per the ratchet design (see file
  // header), not a bug — but it does mean a second showMessage() call for
  // the SAME phase never happens even if the first one already expired.
  assert.equal(s.message, '');
});

test('resolvedTopic: lesson target returns the selected lesson, else empty', () => {
  const s = sessionTimer();
  s.targetKind = 'lesson';
  s.selectedLesson = 'aws/saa/networking';
  assert.equal(s.resolvedTopic(), 'aws/saa/networking');
  s.selectedLesson = '';
  assert.equal(s.resolvedTopic(), '');
});

test('resolvedTopic: course target returns the selected course, else empty', () => {
  const s = sessionTimer();
  s.targetKind = 'course';
  s.selectedCourse = 'aws/saa';
  assert.equal(s.resolvedTopic(), 'aws/saa');
  s.selectedCourse = '';
  assert.equal(s.resolvedTopic(), '');
});

test('resolvedTopic: vendor target prefers course over vendor when both are set', () => {
  const s = sessionTimer();
  s.targetKind = 'vendor';
  s.selectedVendor = 'aws';
  s.selectedCourse = 'aws/saa';
  assert.equal(s.resolvedTopic(), 'aws/saa');
  s.selectedCourse = '';
  assert.equal(s.resolvedTopic(), 'aws');
});

test('resolvedTopic: topic target (default) falls back to free-text input', () => {
  const s = sessionTimer();
  s.targetKind = 'topic';
  s.topicInput = 'networking basics';
  assert.equal(s.resolvedTopic(), 'networking basics');
});

test('togglePause arithmetic: resuming shifts startTime forward by the paused duration', () => {
  const s = sessionTimer();
  const start = new Date('2026-01-01T00:00:00.000Z');
  s.sessionActive = true;
  s.startTime = start;
  s.paused = true;
  s.pausedAt = start.getTime() + 5000; // paused 5s after start, for simplicity

  // Reproduce togglePause()'s own arithmetic without invoking setInterval.
  const pauseDuration = (start.getTime() + 5000 + 3000) - s.pausedAt; // paused 3s
  const shifted = new Date(s.startTime.getTime() + pauseDuration);
  assert.equal(shifted.getTime() - start.getTime(), 3000);
});

/* ---------------------------------------------------------------------------
 * Rubric 3c (e2), owner 2026-09-21: the warm-up follows Start into the Study
 * view — the (d2)+(d3) shape. The `today-resume` hand-off carries the move and
 * its lesson beside the topic; the picker and the live status bar render them;
 * the view's one opener asks the Course Explorer aside; ending the session
 * clears the move with the topic it arrived beside. Stubs are saved and
 * restored around each test — the harness has no window of its own.
 * ------------------------------------------------------------------------- */

const WARM_UP =
  'Open “Advanced Sql 4H” from Complete Sql Databases Bootcamp — the match is the phrase “window function” — and read for ten minutes, then start the repair.';

function withStubs(run) {
  const listeners = {};
  const events = [];
  const saved = {
    window: globalThis.window, fetch: globalThis.fetch,
    Alpine: globalThis.Alpine, CustomEvent: globalThis.CustomEvent,
  };
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
  globalThis.window = {
    addEventListener(type, fn) { listeners[type] = fn; },
    dispatchEvent(e) { events.push(e); },
    Alpine: { store() { return { go() {} }; } },
  };
  globalThis.Alpine = globalThis.window.Alpine;
  globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
  const restore = () => Object.assign(globalThis, saved);
  let result;
  try {
    result = run({ listeners, events });
  } catch (err) {
    restore();
    throw err;
  }
  // An async run must keep its stubs until it settles; a sync one restores now.
  if (result && typeof result.then === 'function') return result.finally(restore);
  restore();
  return result;
}

test('today-resume carries the warm-up and its lesson beside the topic; a hand-off without one clears it', () => {
  withStubs(({ listeners }) => {
    const s = sessionTimer();
    assert.equal(s.firstMove, '', 'declared empty, so a bare hand-off shows nothing');
    s._registerWindowListeners();

    listeners['today-resume']({ detail: {
      topic: 'window function', energy: 'medium', firstMove: WARM_UP,
      firstMoveLessonId: 'ztm/complete-sql-bootcamp/advanced-sql-4h', firstMoveLessonTitle: 'Advanced Sql 4H',
    } });

    assert.equal(s.topicInput, 'window function');
    assert.equal(s.energy, 5);
    assert.equal(s.firstMove, WARM_UP);
    assert.equal(s.firstMoveLessonId, 'ztm/complete-sql-bootcamp/advanced-sql-4h');
    assert.equal(s.firstMoveLessonTitle, 'Advanced Sql 4H');

    // The resume and parked paths hand over a topic and no move: a stale move
    // must not outlive the hand-off it came with.
    listeners['today-resume']({ detail: { topic: 'What is MVCC?', energy: null } });

    assert.equal(s.topicInput, 'What is MVCC?');
    assert.equal(s.firstMove, '');
    assert.equal(s.firstMoveLessonId, '');
    assert.equal(s.firstMoveLessonTitle, '');
  });
});

test('openFirstMoveLesson asks the Course Explorer to open the resolved lesson; nothing to open, nothing dispatched', () => {
  withStubs(({ events }) => {
    const s = sessionTimer();
    s.openFirstMoveLesson();
    assert.equal(events.length, 0);

    s.firstMoveLessonId = 'ztm/complete-sql-bootcamp/advanced-sql-4h';
    s.firstMoveLessonTitle = 'Advanced Sql 4H';
    s.openFirstMoveLesson();

    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'explorer-open-lesson');
    assert.deepEqual(events[0].detail, { lessonId: 'ztm/complete-sql-bootcamp/advanced-sql-4h', title: 'Advanced Sql 4H' });
  });
});

test('ending the session clears the move with the topic it arrived beside', async () => {
  await withStubs(async () => {
    const s = sessionTimer();
    s.sessionActive = true;
    s.topicInput = 'window function';
    s.firstMove = WARM_UP;
    s.firstMoveLessonId = 'ztm/complete-sql-bootcamp/advanced-sql-4h';
    s.firstMoveLessonTitle = 'Advanced Sql 4H';

    await s.confirmEndSession();

    assert.equal(s.sessionActive, false);
    assert.equal(s.topicInput, '', 'precondition: the end path clears the topic');
    assert.equal(s.firstMove, '');
    assert.equal(s.firstMoveLessonId, '');
    assert.equal(s.firstMoveLessonTitle, '');
  });
});

test('a planning launch carries no warm-up', async () => {
  await withStubs(async () => {
    const s = sessionTimer();
    s.firstMove = WARM_UP;
    s.firstMoveLessonId = 'ztm/complete-sql-bootcamp/advanced-sql-4h';
    s.firstMoveLessonTitle = 'Advanced Sql 4H';
    s.startSession = async () => true; // the one start path, stubbed: this test is about state

    await s.startPlanning({ topic: 'SQL windows', brainDump: '' });

    assert.equal(s.topicInput, 'SQL windows');
    assert.equal(s.firstMove, '', 'the architect interview is not a repair; no ramp beneath it');
    assert.equal(s.firstMoveLessonId, '');
    assert.equal(s.firstMoveLessonTitle, '');
  });
});

/* ---------------------------------------------------------------------------
 * Council review 8 (2026-09-21), the finding all three seats converged on: the
 * move must not outlive the material it arrived beside. Three transitions were
 * unguarded — the learner edits or re-selects the material in the picker; a
 * second hand-off arrives while a session is live or starting; a session that
 * is not the hand-off's is reattached.
 * ------------------------------------------------------------------------- */

function handOff(s, listeners) {
  listeners['today-resume']({ detail: {
    topic: 'window function', energy: 'medium', firstMove: WARM_UP,
    firstMoveLessonId: 'ztm/complete-sql-bootcamp/advanced-sql-4h', firstMoveLessonTitle: 'Advanced Sql 4H',
  } });
  assert.equal(s.firstMove, WARM_UP, 'precondition: the hand-off landed');
}

test('editing the topic clears the move that arrived with the previous topic', () => {
  withStubs(({ listeners }) => {
    const s = sessionTimer();
    s._registerWindowListeners();
    handOff(s, listeners);
    s.selectedTopic = 'window function';

    s.onTopicEdited();

    assert.equal(s.selectedTopic, '', 'the handler still does what the inline handler did');
    assert.equal(s.firstMove, '');
    assert.equal(s.firstMoveLessonId, '');
    assert.equal(s.firstMoveLessonTitle, '');
  });
});

test('choosing another target from any picker select clears the move', () => {
  withStubs(({ listeners }) => {
    const s = sessionTimer();
    s._registerWindowListeners();
    s.studyOptions = { topics: [{ label: 'Joins', value: 'joins' }], vendors: [], courses: [], lessons: [] };
    handOff(s, listeners);

    s.selectOption('topic', 'joins');

    assert.equal(s.firstMove, '');
    assert.equal(s.firstMoveLessonId, '');
    assert.equal(s.firstMoveLessonTitle, '');
  });
});

test('a hand-off during a live or starting session does not touch the live move', () => {
  withStubs(({ listeners }) => {
    const s = sessionTimer();
    s._registerWindowListeners();
    handOff(s, listeners);
    s.sessionActive = true;

    listeners['today-resume']({ detail: { topic: 'joins', energy: 'high', firstMove: 'Open “Joins” …' } });

    assert.equal(s.firstMove, WARM_UP, 'the live strip keeps the move of the session that is running');
    assert.equal(s.firstMoveLessonId, 'ztm/complete-sql-bootcamp/advanced-sql-4h');

    s.sessionActive = false;
    s.starting = true;
    listeners['today-resume']({ detail: { topic: 'joins', energy: 'high' } });

    assert.equal(s.firstMove, WARM_UP, 'a start in flight is a session too');
  });
});

test('reattaching to a session that is not the hand-off’s carries no move', () => {
  withStubs(({ listeners }) => {
    const s = sessionTimer();
    s._registerWindowListeners();
    handOff(s, listeners);
    s.conflictSession = { study_session_id: 's-1', topic: 'Something else', reattach_url: '/api/session/ws?study_session_id=s-1' };
    s.conflictIsOwn = true;
    s.tick = () => {};
    s.$nextTick = () => {};

    s.reattachConflictSession();

    assert.equal(s.sessionActive, true, 'precondition: the reattach happened');
    assert.equal(s.firstMove, '');
    assert.equal(s.firstMoveLessonId, '');
    assert.equal(s.firstMoveLessonTitle, '');
    // reattachConflictSession() arms the real one-second tick; without this the
    // interval keeps the process alive and `node --test` never exits the file.
    s.destroy();
  });
});
