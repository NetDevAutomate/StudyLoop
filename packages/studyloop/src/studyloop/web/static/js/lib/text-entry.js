/**
 * Is this keyboard event headed for a text-entry surface?
 *
 * Every global single-key hotkey in the app must ask this question before
 * acting, and each one answering it privately is how the quick-park 'p'
 * hotkey shipped a bug: its inline INPUT/TEXTAREA/SELECT allowlist missed
 * the ghostty terminal, which keeps focus on a DIV (.xterm-mount). Typing
 * any word containing 'p' into the terminal opened the park dialog
 * mid-word, and the dialog's focus grab swallowed the rest of the word.
 *
 * This module is that question answered once. Pure logic against the event
 * object so it is unit-testable without a browser — see
 * tests/js/text-entry.test.js.
 *
 * A target counts as text entry when it is:
 *   - a form field (INPUT / TEXTAREA / SELECT), or
 *   - contenteditable, or
 *   - inside a terminal mount (.xterm-mount) — the terminal consumes raw
 *     keystrokes even though no form element holds focus.
 *
 * A non-Element target (window/document, as when nothing has focus) is NOT
 * text entry: global hotkeys should work there.
 */

const TEXT_ENTRY_TAGS = ['INPUT', 'TEXTAREA', 'SELECT'];

/**
 * @param {Event} event — a keyboard event (only `.target` is consulted)
 * @returns {boolean} true when the event's target is a text-entry surface
 */
export function isTextEntryTarget(event) {
  const t = event.target;
  if (!t || typeof t.closest !== 'function') return false;
  if (TEXT_ENTRY_TAGS.includes(t.tagName)) return true;
  if (t.isContentEditable) return true;
  if (t.closest('.xterm-mount')) return true;
  return false;
}
