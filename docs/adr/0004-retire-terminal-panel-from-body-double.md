# ADR-0004 — Unmount `terminalPanel()` without deleting it

> **Partly superseded by [ADR-0005](./0005-retire-ttyd-browser-surface.md) (2026-08-22).** This ADR
> names `_mountLegacyIframe()` as the single surviving ttyd code path. That
> function has since been removed: the ttyd BROWSER surface is retired and the
> `else` branch now renders an explicit error state. The `ttyd` server
> transport, `/terminal/` and the step-2 plan for `terminalPanel()` are
> unaffected and still stand.

- **Status**: Proposed
- **Date**: 2026-07-25
- **Change**: `openspec/changes/body-double-own-agent-picker`
- **Deciders**: repo owner (pending sign-off)

## Context

`terminalPanel()` (`web/static/index.html:2852`) is the legacy ttyd surface.
Its only remaining mount point is the Body Double view, and it is the direct
cause of that view's blank terminal:

```js
const state = await (await fetch('/api/session/state')).json();
if (!state.ttyd_port) { this.available = false; ... return; }   // :2874
```

`ttyd_port` is written in exactly one place — `session/orchestrator.py:451`,
on the deprecated tmux path. `pty` is the resolved default, so the field is
never set, `available` never becomes true, and the whole `.terminal-panel`
div (including its own "unavailable" message) is hidden by `x-show`.
`splitLayout()` (`:3658`) compounds it by force-hiding the terminal pane until
a `terminal-ready` event that never fires.

Replacing Body Double's terminal with `liveAgentConsole()` makes
`terminalPanel()` unmounted. The temptation is to delete it in the same change.

Countervailing facts:
- `transport: "ttyd"` is still a **supported** path with a live spec
  requirement (`session-transports`: "Legacy ttyd fallback remains
  available"), forceable via `STUDYLOOP_TRANSPORT=ttyd`.
- `liveAgentConsole()` already has its own ttyd branch —
  `_mountLegacyIframe()` (`:3607`) → `legacyTtydUrl` → the iframe at `:1840`.
  So the ttyd *transport* does not need `terminalPanel()`.
- Four test groups target `terminalPanel()` markup and the `/terminal/` proxy,
  including `test_terminal_proxy.py:153-157`, which asserts the source literal
  `:src="activeTtydUrl || 'about:blank'"` is present — a lazy-load invariant
  ("the hidden body-double panel must not eagerly request `/terminal/`")
  expressed as a string match. `activeTtydUrl` occurs only in the iframe being
  removed, so that assertion fails on removal and its intent must be
  re-expressed, not deleted.

## Decision

Split the two concerns:

1. **This change**: Body Double uses `liveAgentConsole('body-double')` for all
   three transports, including `ttyd` via `_mountLegacyIframe()`. The
   `terminalPanel()` mount and the `splitLayout()` `terminal-ready` gate are
   removed from the Body Double markup. The **`terminalPanel()` factory itself
   stays in the file**, unmounted, with a comment stating it is unmounted and
   naming the retirement change.
2. **A separate change**: delete `terminalPanel()`, the `terminal-ready`
   plumbing in `splitLayout()`, and the tests that exercise the
   `.split-terminal .terminal-panel` markup — as one reviewable diff whose
   only job is retirement.

Tests targeting `terminalPanel()` markup are **skipped with an explicit
reason** referencing this ADR, not deleted, in step 1. The lazy-load invariant
at `test_terminal_proxy.py:154` is **re-pointed** at the new markup: the Body
Double console must not request `/terminal/` while the view is hidden.

## Alternatives considered

**Delete `terminalPanel()` now.** Rejected: it merges a feature change with a
~200-line deletion across four test files. If Body Double then misbehaves in
`ttyd` mode, bisecting means untangling "did the new picker break it" from "did
we delete something still load-bearing". Two diffs, two verdicts.

**Keep `terminalPanel()` mounted in Body Double as a ttyd-only fallback
alongside the new console.** Rejected: two components rendering the same
`/terminal/` iframe in one view, with the broken `ttyd_port` gate still
deciding which. That is the bug, re-shipped with a sibling.

**Fix the `ttyd_port` gate so `terminalPanel()` works again.** Rejected: it
preserves a second, divergent terminal implementation for a transport slated
for removal after one deprecation window. One ttyd code path
(`_mountLegacyIframe`) is the goal.

## Consequences

- Dead-but-present code exists between the two changes. Mitigated by the
  comment naming its retirement, and by this ADR being discoverable from it.
- Some `test_web_terminal.py` tests are skipped rather than green-and-
  meaningful for one change window. The skip reason must name this ADR so the
  retirement change knows exactly what to delete.
- **Teaching moment (bank via `/teaching-moment`)**: retiring a code path
  leaves *dead gating conditions* behind. An `x-show` on a state field nothing
  writes any more does not error — the feature silently vanishes. When you
  retire a path, grep for who **reads** each state field, not just who writes
  it.

## Verification

- Body Double in `ttyd` mode renders the `_mountLegacyIframe()` iframe (browser
  check with `STUDYLOOP_TRANSPORT=ttyd`).
- Re-expressed lazy-load test: every ttyd iframe `src` binds to a field that is
  empty until `_mountLegacyIframe()` runs, so no `/terminal/` request occurs at
  page load. **Prove it can fail** by initialising `legacyTtydUrl` to
  `/terminal/` at component init.
- `grep -c 'terminalPanel()' index.html` returns exactly 1 (the factory
  definition, no mount).
