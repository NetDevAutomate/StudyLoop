/**
 * ACP chunk-text extraction.
 *
 * Pure logic, deliberately: an ACP `session/update` payload carries its text in
 * one of three shapes depending on the agent, and picking the right one is the
 * kind of thing that should be provable in milliseconds rather than by launching
 * a browser. This module exists so it can be unit-tested directly — see
 * tests/js/chunk-text.test.js.
 *
 *   { content: { text } }      single content object
 *   { content: [ { text } ] }  content array, first entry wins
 *   { text }                   flat payload
 *
 * Anything else yields '' rather than throwing: a malformed frame should not be
 * able to take the terminal down mid-session.
 */
export function extractChunkText(payload) {
  if (!payload) return '';
  const content = payload.content;
  if (content && typeof content === 'object' && !Array.isArray(content)) {
    return typeof content.text === 'string' ? content.text : '';
  }
  if (Array.isArray(content) && content.length > 0 && typeof content[0] === 'object') {
    return typeof content[0].text === 'string' ? content[0].text : '';
  }
  return typeof payload.text === 'string' ? payload.text : '';
}

/**
 * Energy → band name. Thresholds match the Python side (`energy_band` in
 * studyloop/session.py) and the CSS colour phases; changing one without the
 * others desynchronises the timer's colour from the sidebar's label.
 */
export function energyBand(energy) {
  if (energy >= 7) return 'high';
  if (energy >= 4) return 'medium';
  return 'low';
}
