# ADR-0006 — Retire ttyd entirely; the Web UI owns interactive sessions

**Status:** accepted, 2026-09-02. **Supersedes** the second half of
[ADR-0005](0005-retire-ttyd-browser-surface.md), which retired the ttyd *browser
surface* and deliberately **kept** the ttyd *server transport*.

## Context

ADR-0005 kept the server transport for one reason: the PTY path had a reload bug,
and a fallback was worth its cost until that was fixed. That reason has expired —
`live-agent-console.js:794` records the iframe being retired "once the pty path
survived a page reload", and the xterm/PTY path has since carried the full e2e
suite (502 browser tests, unscaled, green in CI).

What the kept transport actually left behind:

- `studyloop study --transport` advertised `[pty|ttyd]` and defaulted to ttyd
  while refusing `pty` outright — an option whose choice list named a value it
  rejected, in user-facing `--help`.
- `doctor` stopped checking for the ttyd binary (`cli/_doctor.py:78-79`, citing
  ADR-0005's retirement of the browser surface) while the CLI still named ttyd as
  its default transport. So the one diagnostic that would have told a user their
  default transport was unavailable had been removed on the strength of a
  decision that only covered the other half.
- `start_ttyd_background` binds `0.0.0.0` with `-W` (writable) when `lan` is set,
  applying HTTP Basic Auth only when both credentials are non-empty. Both current
  callers do supply them, so this was never reachable — but the contract was "the
  caller must remember", and what it publishes when a caller forgets is an
  interactive shell attached to the learner's session.

A fallback nobody selects still costs: a transport axis in two CLIs, a
reverse-proxy route with its own auth and origin checks, a frontend panel and
iframe path, config and session-state keys, and ~20 test files.

## Decision

Retire ttyd completely. Interactive sessions live in the Web UI. The CLI keeps
configuration, `doctor`, content and utility commands.

`studyloop study` **survives**: ttyd was never what made it work. That session
creates its tmux environment and enters it via `os.execvp`/attach
(`session/start.py:431-454,532`); ttyd was started afterwards, guarded by
`shutil.which`, purely to add browser/iPad reach. Removing it costs remote access
to a CLI-owned tmux session — not the command, and not the Web UI's PTY or ACP
sessions.

## Consequences

`X-Frame-Options` is currently `SAMEORIGIN` rather than `DENY` for one stated
reason: "so our same-origin /terminal/ iframe can embed ttyd" (`web/app.py:57`).
With no iframe surface that justification is void, and the header should tighten
to `DENY` unless another embedding need is recorded here.

Existing `ttyd_port` config needs no migration. `load_settings()` applies only
keys present in `_SCALAR_FIELDS` (`settings.py:550-560`), so an orphaned key is
silently ignored — it loads clean, and is inert rather than broken. The setup
guide now says so, because a setting that looks active and does nothing is its own
kind of defect.

Two invariants must survive the removal, and both have comments that call them
"legacy ttyd" while being load-bearing for something else:

- `/session/state`'s file fallback (`web/routes/session/_dashboard.py:25-40`).
  Out-of-process CLI tmux sessions never hold the web singleton, so the fallback
  is what makes a CLI session visible to the dashboard at all.
- Clearing inherited multiplexer keys for PTY/ACP sessions
  (`session_state.py:54-70`).

Rename the comments; keep the code.

## What was considered and rejected

**Keep ttyd as a maintainer-only flag.** Rejected: that is the status quo, and the
status quo is what produced a `--help` advertising a refused value, a `doctor`
blind to a default transport, and a spawn function that publishes an
unauthenticated writable shell if a caller forgets. An escape hatch nobody
exercises is not tested by use.

**Delete it in one commit.** Rejected: 25 source and 20 test files, where a
half-landed state is worse than either end — the frontend would probe a proxy that
no longer exists, or the CLI would spawn a process nothing cleans up. Staged, with
the ordering enforced by
`packages/studyloop/tests/test_ttyd_retirement_ordering.py` rather than by
prose, because the first draft of that plan removed the cleanup while leaving the
spawn.
