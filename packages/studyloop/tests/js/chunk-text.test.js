/**
 * First frontend unit tests.
 *
 * Uses `node --test` — built into Node, zero dependencies and no npm install.
 * The package metadata declares ESM only, preserving the project's no-build step.
 *
 * Run with:  node --test packages/studyloop/tests/js/*.test.js
 *
 * WHY THIS MATTERS: before this file, every frontend assertion in the repo cost a
 * Playwright browser launch (the full e2e suite takes ~24 minutes). Logic that
 * lives in an importable module can be proven in milliseconds instead. That is
 * the concrete payoff of the modular refactor, not an aesthetic one.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { extractChunkText, energyBand } from
  '../../src/studyloop/web/static/js/lib/chunk-text.js';

test('extractChunkText: single content object', () => {
  assert.equal(extractChunkText({ content: { text: 'hello' } }), 'hello');
});

test('extractChunkText: content array takes the first entry', () => {
  assert.equal(
    extractChunkText({ content: [{ text: 'first' }, { text: 'second' }] }),
    'first',
  );
});

test('extractChunkText: flat payload', () => {
  assert.equal(extractChunkText({ text: 'flat' }), 'flat');
});

test('extractChunkText: malformed frames yield empty string, never throw', () => {
  // A bad frame must not be able to tear down a live session, so every one of
  // these is a '' rather than an exception.
  for (const bad of [
    null, undefined, {}, { content: null }, { content: [] }, { content: [42] },
    { content: { text: 99 } }, { text: 99 }, { content: 'string' },
  ]) {
    assert.equal(extractChunkText(bad), '', `payload: ${JSON.stringify(bad)}`);
  }
});

test('energyBand: thresholds match the Python side', () => {
  assert.equal(energyBand(10), 'high');
  assert.equal(energyBand(7), 'high');    // boundary
  assert.equal(energyBand(6), 'medium');
  assert.equal(energyBand(4), 'medium');  // boundary
  assert.equal(energyBand(3), 'low');
  assert.equal(energyBand(0), 'low');
});
