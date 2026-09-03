# ADR-0008 — Retire ttyd entirely; the Web UI owns interactive sessions

**Status:** Accepted, 2026-09-02. **Supersedes** the second half of
[ADR-0005](0005-retire-ttyd-browser-surface.md), which retired the ttyd *browser
surface* and deliberately **kept** the ttyd *server transport*. (Renumbered from
0006 — that number collided with 0006-bridge-aware-deferred-topics.md.)

## Context

ADR-0005 kept the server transport for one reason: the PTY path had a reload bug,
and a fallback was worth its cost until that was fixed. That reason has expired —
`live-agent-console.js:794` records the iframe being retired "once the pty path
survived a page reload", and the xterm/PTY path has since carried the full e2e
suite (see the Verification section below for the current pass counts, not a
fixed number here — R-62: a count belongs to the evidence file it was measured
in, not to prose that outlives the run that produced it).

What the kept transport actually left behind:

- `studyloop study --transport` advertised `[pty|ttyd]` and defaulted to ttyd
  while refusing `pty` outright — an option whose choice list named a value it
  rejected, in user-facing `--help`.
- `doctor` stopped checking for the ttyd binary (`cli/_doctor.py`, citing
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
iframe path, config and session-state keys, and a wide swath of test files
(full classification in `evidence/M1/stage-6/04-manifest.md` — R-62: a count
belongs to the evidence file it was measured in).

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

`X-Frame-Options` was `SAMEORIGIN` rather than `DENY` for one stated reason: "so
our same-origin /terminal/ iframe can embed ttyd" (`web/app.py`). With no iframe
surface that justification was void — done: `X-Frame-Options: DENY`, plus a full
CSP, `Referrer-Policy` and `Permissions-Policy` (ttyd retirement stage 4).

`ttyd_port` config is fully removed, not merely inert: `Settings.ttyd_port` and
its `_SCALAR_FIELDS` entry are deleted (stage 5). An orphaned `ttyd_port` line in
an existing `config.yaml` is no longer silently-ignored-but-present — `doctor`
now reports it by name via `known_top_level_keys()`/`unknown_top_level_keys()`
(`settings.py`), a general unknown-top-level-key check built for this and reusable
beyond it.

Two invariants that had to survive the removal, both had comments calling them
"legacy ttyd" while being load-bearing for something else, and both were renamed
rather than deleted (stage 5):

- `/session/state`'s file fallback (`web/routes/session/_dashboard.py`).
  Out-of-process CLI tmux sessions never hold the web singleton, so the fallback
  is what makes a CLI session visible to the dashboard at all.
- Clearing inherited multiplexer keys for PTY/ACP sessions (`session_state.py`).
- A third, found only once cleanup work started: the stale-multiplexer reconcile
  in `_ipc.py` that clears zombie IPC state — only the ttyd-kill half of it went.

## What was considered and rejected

**Keep ttyd as a maintainer-only flag.** Rejected: that is the status quo, and the
status quo is what produced a `--help` advertising a refused value, a `doctor`
blind to a default transport, and a spawn function that publishes an
unauthenticated writable shell if a caller forgets. An escape hatch nobody
exercises is not tested by use.

**Delete it in one commit.** Rejected: too many source and test files touch
ttyd for a single commit not to risk landing half-migrated, and a half-landed
state is worse than either end — the frontend would probe a proxy that
no longer exists, or the CLI would spawn a process nothing cleans up (full
scope in `evidence/M1/stage-6/04-manifest.md`). Staged
across 6 commits (stages 2-7), with the spawn/cleanup ordering enforced by a test
rather than by prose — the first draft of the retirement plan removed the cleanup
while leaving the spawn; that class of defect was subsequently generalised into
`packages/studyloop/tests/test_ttyd_retirement_ordering.py
::test_no_frontend_module_imports_a_deleted_component`, the one ordering guard
this retirement still needs (its ttyd-specific sibling was deleted once its own
precondition became permanently true — see that test file's module docstring).

## Verification

Evidence lives with the work, not in this file (R-62: a number belongs to the
run that produced it). See `reviews/2026-09-02-full-repo-review/evidence/M1/`,
one `stage-<n>/` directory per commit (stages 2-7), each with a DoD written
before the change, red/green test output, the `just preflight`/`just e2e` gate
tail, and the manifest of every test that died, was retargeted, or survived
renamed. The final `just e2e` run of this retirement (stage 6) was the first
fully uncontended run of the lane — see `evidence/M1/stage-6/03-gate.txt` for
the pass/skip/fail counts that run actually produced.
