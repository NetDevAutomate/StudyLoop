/**
 * The live console's "No terminal available" fallback must say what actually
 * went wrong. A KNOWN transport ('pty', 'acp') arriving without a connection
 * URL is a missing connection, not a transport this view cannot render; only
 * an unrecognised transport gets the "cannot render" sentence.
 *
 * Found live: after `studyloop web` was restarted, a session whose server had
 * stopped was adopted with transport "pty" and no URL, and the learner read
 * 'This session reports transport "pty", which this view cannot render' —
 * about the one transport the view renders with xterm. The "did not return a
 * connection" sentence the troubleshooting guide describes for exactly this
 * case was unreachable, because every caller passes a transport.
 */
// Run with:  node --test 'packages/studyloop/tests/js/**/*.test.js'

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { liveAgentConsole } from
  '../../src/studyloop/web/static/js/components/live-agent-console.js';

for (const transport of ['pty', 'acp']) {
  test(`a known transport (${transport}) with no URL is reported as a missing connection`, () => {
    const view = liveAgentConsole('study');

    view.start({ transport, wsUrl: null, topic: 'Decorators', studySessionId: 's-1' });

    assert.equal(view.terminalMode, 'unavailable');
    assert.doesNotMatch(view.statusMessage, /cannot render/);
    assert.match(view.statusMessage, /did not return a connection/);
  });
}

test('an unrecognised transport still names the transport it cannot render', () => {
  const view = liveAgentConsole('study');

  view.start({ transport: 'carrier-pigeon', wsUrl: '/api/session/ws?study_session_id=s-1' });

  assert.equal(view.terminalMode, 'unavailable');
  assert.match(view.statusMessage, /transport "carrier-pigeon", which this view cannot render/);
});
