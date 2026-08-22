# ADR-0005 — Retire the ttyd browser surface, keep the server transport

Status: **Accepted** (2026-08-22)

Supersedes the part of [ADR-0004](./0004-retire-terminal-panel-from-body-double.md)
that names `_mountLegacyIframe()` as the single surviving ttyd code path.

## Context

StudyLoop had three browser terminal surfaces, chosen by `transport`:

| Surface | `transport` | How it renders |
|---|---|---|
xterm | `pty` | PTY streamed to xterm.js over a WebSocket |
ACP chat | `acp` | structured ACP events |
ttyd iframe | anything else | `<iframe src="/terminal/…">` |

ADR-0004 consolidated Body Double onto `liveAgentConsole()` for all three and
named `_mountLegacyIframe()` as the goal: one ttyd code path rather than two. It
assumed ttyd rendering would survive "one deprecation window".

Three things have changed since.

**The reason for keeping a fallback was the reload bug.** Removing the ttyd
surface was gated on the primary PTY path surviving a page refresh. It now does:
`liveAgentConsole.init()` reads `GET /api/session/state` and adopts a live
session it owns, so `test_refresh_reattaches_the_terminal_and_the_agent_still_answers`
passes — the console reconnects with no user action and the same process answers a
freshly typed line.

**The fallback needed a binary that is usually absent.** ttyd is an external
dependency (`brew install ttyd`). Without it the iframe renders an EMPTY frame,
which is indistinguishable from a hang. That is the recurring failure shape in
this codebase — an empty surface that reads as broken rather than as degraded —
and here we were *falling back* to it.

**It was offered in the UI.** Both start pickers carried
`<option value="ttyd">Legacy terminal (ttyd iframe)</option>`, so a learner could
select the path most likely to look broken on their machine.

## Decision

Retire the ttyd **browser surface**. Keep the ttyd **server transport**.

1. Remove the `ttyd` option from both transport selects.
2. Remove both legacy `<iframe>` panels from the markup.
3. Replace `_mountLegacyIframe()` with `_mountUnavailable()`: an explicit error
   state naming what happened and what to do, instead of a blank frame.
4. `POST /api/session/start` still honours `transport: "ttyd"` and
   `STUDYLOOP_TRANSPORT=ttyd`. `/terminal/{path}` and `terminal_proxy.py` stay.
5. Delete the tests that drove the removed surface (see Verification).

`terminalMode` is now `'xterm' | 'acp-chat' | 'unavailable' | null`.

## Why the server path stays

Deleting it would touch `_start_ttyd_session`, `_ttyd_credentials` (LAN
Basic-Auth), `start_ttyd_background`, `_get_ttyd_port`, `_kill_stale_ttyd`,
`terminal_proxy.py` and 12+ test files — auth-adjacent code, in the same diff as
a session-recovery feature. Worse, **ttyd is not installed on the development
machine**, so those tests skip: we would be deleting code whose tests cannot be
run here, and a LAN regression would surface only in use.

It also belongs with a different piece of work. `multiplexer.py` is mid-migration
from tmux to herdr (`STUDYLOOP_MULTIPLEXER=herdr`, "default until herdr journey
suite is green"), and the tmux+ttyd session flow is part of that story. Removing
the server transport is naturally the same change as flipping that default.

## Alternatives considered

**Delete the whole ttyd stack now.** Rejected: unverifiable here (no ttyd
binary), touches auth code, and merges with an in-flight multiplexer migration.

**Keep the iframe as a fallback.** Rejected: it is a fallback to another broken
thing. When the WebSocket path fails, an iframe pointing at an absent binary adds
a second silent failure rather than a recovery.

**Delete the `else` branch entirely.** Rejected: a missing `wsUrl` would then
render nothing at all — the same "looks broken, says nothing" defect in a new
costume. An honest error state is the point of the change, not a side effect.

## Consequences

- A `transport: "ttyd"` session started via the env var has **no browser
  renderer**: it reports `unavailable` with an explanation. Acceptable, because
  that path is now explicitly opt-in for maintainers, not a learner-facing option.
- The UI transport surface is deliberately NARROWER than the API surface. The
  Body Double contract test asserts `["pty", "acp"]` and says why, so the
  divergence is documented where someone would otherwise "fix" it.
- `test_remaining_surface.py::test_terminal_proxy_degrades_when_ttyd_is_absent`
  becomes the only full-stack coverage of `/terminal/`. Its docstring is updated
  to say so.
- `terminalPanel()` remains unmounted-but-present per ADR-0004 step 2, which is
  still the right call and still outstanding.

## Verification

- unit **3592 passed / 0 failed**, JS **38/38**
- `test_body_double_workspace` 23/23, `test_body_double_journey` 11/11
- `test_web_acp_chat_ui` 87/87, `test_ghostty_dev_terminal` 31/31
- `TestLiveRefresh` 3/4 — the reattach proof is green; the remaining red waits on
  the server's dim-line marker and is tracked separately
- Deleted: `tests/test_web_terminal.py` (every test drove the retired surface;
  ADR-0004 step 2 anticipated this), `TestRealTtyd` (drove the removed iframe via
  the never-mounted `terminalPanel()`), and
  `test_terminal_proxy.py::test_iframe_waits_for_successful_terminal_probe` (its
  `about:blank` invariant died with the iframe)
