/**
 * Unit tests for isTextEntryTarget — the shared "is this keyboard event
 * headed for a text-entry surface?" predicate every global hotkey consults.
 *
 * Uses `node --test` (see chunk-text.test.js for the project's rationale).
 * Run with:  node --test packages/studyloop/tests/js/
 *
 * No DOM here: the helper deliberately consults only `event.target`'s
 * tagName / isContentEditable / closest(), so a plain-object fixture proves
 * the same contract a browser would — in milliseconds instead of a
 * Playwright launch. The e2e side of this contract (a real 'p' typed into
 * the real terminal leaves the quick-park dialog closed) lives in
 * tests/e2e/test_ghostty_dev_terminal.py.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { isTextEntryTarget } from
  '../../src/studyloop/web/static/js/lib/text-entry.js';

/** Build an event whose target mimics the DOM surface under test. */
function eventOn({ tagName = 'DIV', contentEditable = false, insideTerminal = false } = {}) {
  return {
    target: {
      tagName,
      isContentEditable: contentEditable,
      closest: (sel) => (sel === '.xterm-mount' && insideTerminal ? {} : null),
    },
  };
}

test('form fields are text entry', () => {
  for (const tagName of ['INPUT', 'TEXTAREA', 'SELECT']) {
    assert.equal(isTextEntryTarget(eventOn({ tagName })), true, tagName);
  }
});

test('contenteditable is text entry regardless of tag', () => {
  assert.equal(isTextEntryTarget(eventOn({ contentEditable: true })), true);
});

test('the terminal mount is text entry even though focus sits on a DIV', () => {
  // The regression this module exists for: ghostty keeps focus on
  // .xterm-mount (a DIV), which a tagName allowlist waves through — that is
  // how typing "keypath" into the terminal opened the quick-park dialog.
  assert.equal(isTextEntryTarget(eventOn({ tagName: 'DIV', insideTerminal: true })), true);
});

test('an ordinary element is not text entry — hotkeys stay live', () => {
  for (const tagName of ['DIV', 'BODY', 'BUTTON', 'A']) {
    assert.equal(isTextEntryTarget(eventOn({ tagName })), false, tagName);
  }
});

test('a non-Element target (window/document) is not text entry', () => {
  // Nothing focused: global hotkeys should work. window/document have no
  // closest(), which is the shape the guard keys on.
  assert.equal(isTextEntryTarget({ target: null }), false);
  assert.equal(isTextEntryTarget({ target: {} }), false);
});
