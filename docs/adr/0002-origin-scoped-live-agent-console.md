# ADR-0002 — Origin-scoped addressing for `liveAgentConsole()`

- **Status**: Accepted (2026-09-05 — implemented and shipped; accepted retrospectively during the body-double-own-agent-picker reconciliation)
- **Date**: 2026-07-25
- **Change**: `openspec/changes/body-double-own-agent-picker`
- **Deciders**: repo owner

## Context

`liveAgentConsole()` (`web/static/index.html:2951`) is the modern agent
surface: xterm.js for `pty`, ACP chat for `acp`, same-origin iframe for
`ttyd`. It is **broadcast-driven**, not view-scoped:

```js
init() {
  window.addEventListener('study-session-start', (e) => this.start(e.detail));
  window.addEventListener('study-session-stop',  ()  => this.stop());
}
```

Body Double needs a live console. The obvious move — a second
`x-data="liveAgentConsole()"` in the Body Double view — is a trap. Alpine
initialises `x-data` on elements hidden by `x-show`, because `x-show` only
toggles `display`. Both instances would be alive at all times, both would
hear the same `window` event, and one start would:

- mount **two** xterm instances (one in a zero-height hidden container, so
  `fit()` fails and `ResizeObserver` fires against a collapsed box), and
- open **two** WebSockets to the same PTY session, so the hidden terminal
  consumes a share of the agent's output bytes.

That is a data-loss bug, not a cosmetic one. It must be decided before any
markup is written.

## Decision

Address the event instead of broadcasting it. Add an `origin` field to the
event detail and an `origin` argument to the factory:

```js
function liveAgentConsole(origin = 'study') { ... }

init() {
  window.addEventListener('study-session-start', (e) => {
    if ((e.detail.origin || 'study') !== this.origin) return;
    this.start(e.detail);
  });
  window.addEventListener('study-session-stop', (e) => {
    if (((e.detail && e.detail.origin) || 'study') !== this.origin) return;
    this.stop();
  });
}
```

- Study Session mounts `liveAgentConsole('study')` and dispatches
  `origin: 'study'`.
- Body Double mounts `liveAgentConsole('body-double')` and dispatches
  `origin: 'body-double'`.
- The `|| 'study'` default keeps any un-migrated dispatcher working, so the
  change is not a flag-day across all call sites.

The consoles stay two independent instances with independent lifecycles.

## Alternatives considered

**(a) One shared instance hoisted above both views.** The single console lives
in a common ancestor and both views render into it. Rejected: the two views
have structurally different layouts — Study Session stacks the console under a
status bar inside `.session-active-layout`; Body Double puts it in a Split.js
pane next to the timer. A shared instance means either one view gets the wrong
layout, or the DOM node is physically moved between containers at runtime.
Moving a live xterm canvas between parents forces a re-fit and risks WebGL
context loss — `_mountXterm` already has a `webgl.onContextLoss` handler
because that path is fragile. High risk for no gain.

**(c) Rely on the views being mutually exclusive.** Rejected: false premise.
Nav exclusivity controls *visibility*, not *instantiation*. Both components
init at page load regardless of which view is showing. This is the exact class
of bug that caused the original breakage (`x-show` gating on `state.ttyd_port`,
a field nothing writes any more) — visibility and liveness are different
things, and conflating them is what we are here to fix.

**(d) Lazy-mount the Body Double console with `x-if` so only the visible view
has an instance.** Genuinely viable and would also solve it. Rejected as the
primary mechanism because it makes correctness depend on template structure —
any future refactor that swaps `x-if` for `x-show` silently reintroduces the
double-WebSocket bug with no test failure. `origin` makes the invariant
explicit in JS where it can be asserted directly. `x-if` may still be layered
on later as a resource optimisation; it is not load-bearing for correctness.

## Consequences

- Every dispatcher of `study-session-start` / `study-session-stop` must set
  `origin`. Today that is `sessionTimer().startSession()` /
  `confirmEndSession()` plus the new `bodyDoubleSession()`.
- Two live xterm-capable components exist in the page, but at most one is ever
  mounted to a WebSocket, because the backend permits one active session
  (ADR-0001) and the non-addressed console ignores the event entirely.
- The invariant is directly testable without a browser: dispatch a
  `body-double`-origin event and assert the study console's `terminalMode`
  stays `null`.
- **Teaching moment (bank via `/teaching-moment`)**: broadcast events are a
  hidden global. The moment a second listener can exist, the event needs an
  address. Alpine makes this sharp because `x-data` under `x-show` is *live,
  not lazy* — visibility is not liveness.

## Verification

- Unit-ish DOM test: two consoles, dispatch each origin in turn, assert only
  the addressed one leaves `terminalMode: null` and only one WebSocket is
  constructed (stub `window.WebSocket`, count instantiations).
- **Prove it can fail**: delete the `origin` guard, watch the WebSocket count
  assert go to 2, restore.
