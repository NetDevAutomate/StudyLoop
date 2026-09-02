# ADR-0009 — The session-state file is the claim; the in-process slot is a cache

**Status:** Accepted, 2026-09-02. Written as the M2 lane's step 0 contract
stub; finalised here against the landed code. Motivated by the 2026-09-02
full-repo review's R-01 and R-02 findings and the 2026-09-01
purpose-congruence review's C1 finding.

## Context

Two live-session authorities existed side by side. `studyloop study` (CLI)
writes `session-state.json` directly and never touches `session/active.py`'s
in-process singleton. The Web UI's PTY/ACP start path checked only that
singleton (`_session_conflict()` → `session/active.py::current()`), never the
file. The two authorities could disagree, and did: starting a web session
while a CLI session's claim was live in the file returned `201`, silently
overwrote the shared state file, and orphaned the CLI's running agent with no
way for either side to detect the other (R-01, reproduced live against
`0fdd204`). Once two live agents existed, ending *either* one called
`kill_all_study_sessions()`, which kills every `study-*` tmux session on the
machine unconditionally — destroying the other, unrelated session too (R-02).

The full liveness contract (what "live" means for each kind of claim, how a
stale claim left by a crashed process gets reclaimed rather than blocking
forever, and the exact start/end matrices) is written out in
[`docs/architecture/session-authority.md`](../architecture/session-authority.md),
which this ADR points to rather than restates — the contract doc is the
tested artefact and is expected to be read alongside the matrix test file
(`tests/test_session_authority_matrix.py`); this ADR records why the shape
was chosen, not the mechanics.

## Decision

- `session-state.json` is the single cross-process CLAIM to "a study session
  is running." `session/active.py`'s singleton is a CACHE of that claim,
  valid only for a PTY/ACP session held by the current web server process.
- Every start path (CLI, web PTY, web ACP) atomically claims the slot
  (`session_state.try_claim_session`, C1, council -- read, decide, and
  write the claim under one file lock, not read-then-decide followed by a
  separate, later write with real work in between). A live claim owned by
  someone else blocks with the same 409 shape (web) or the same exit-1
  message (CLI) either surface already used for its own in-process
  conflict. A stale claim (owner's process/tmux session no longer exists,
  or — for a web-owned claim read by the CLI, R-01b — its recorded pid is
  dead) is reclaimed, logged, and never blocks a start forever. The CLI's
  own start path originally checked only "does a claim exist"
  (`is_session_active()`), blocking unconditionally even when the owner
  was provably dead; R-01b closed that gap with `claim_blocks_cli_start()`,
  giving the CLI start path the same owner-liveness check the web path
  already had.
- `kill_all_study_sessions()` keeps its blunt "kill everything" semantics —
  that is a legitimate, separate operation — but every per-session end path
  (`end_session_common` → `_cleanup_tmux_and_files`, and the study sidebar's
  End Session key, R-02b) no longer calls it. Each kills only the ending
  session's own multiplexer name (nothing, for PTY/ACP). Per
  DECISIONS.md §E17, R-02's definition of done is *exactly one* production
  caller, not zero — `studyloop clean --all` (a new flag) is that one
  caller, a deliberate, explicit "kill everything" sweep for the rare case
  it's actually wanted. Default `clean` (no `--all`) is unchanged: a safer,
  zombie-only sweep.
- Rejected alternative: giving the CLI a control socket into the web server
  so a CLI end could directly call `active.release()` on a live web session.
  The existing `_grace.py` reaper already reconciles "the file changed
  out-of-process while a slot is held" within its poll interval; adding a
  second, synchronous IPC mechanism for the same problem was assessed and
  rejected as unnecessary complexity for a local, single-user tool.

## Consequences

**Before -> after**, per `tests/test_session_authority_matrix.py`:

| Cell | Test | Before | After |
| --- | --- | --- | --- |
| web-then-web | `TestWebThenWeb::test_second_web_start_is_refused` | 409 | 409 (unchanged) |
| cli-then-cli | `TestCliThenCli::test_a_live_cli_claim_reports_active` | blocks | blocks (unchanged) |
| cli-then-cli, live | `TestCliThenCli::test_a_live_cli_claim_still_blocks_a_cli_start` | blocks | blocks (unchanged) |
| **cli-then-cli, stale claim (R-01b)** | `TestCliThenCli::test_a_dead_cli_claim_is_reclaimed_by_a_cli_start` | **blocked unconditionally, no log** | **proceeds, logged as a reclaim** |
| cli-then-web | `TestCliThenWeb::test_web_start_is_refused_when_cli_claim_is_live` | **201, clobbered the file** | **409** |
| cli-then-web (ACP) | `TestCliThenWeb::test_web_acp_start_is_also_refused` | **real spawn attempted, opaque error** | **409** |
| cli-then-web, stale claim | `TestCliThenWeb::test_a_dead_cli_claim_is_reclaimed_not_blocked` | 201 (coincidentally), no log | 201, logged as a reclaim |
| web-then-cli | `TestWebThenCli::test_a_live_web_claim_reports_active` | blocks | blocks (unchanged) |
| web-then-cli, live pid (R-01b) | `TestWebThenCli::test_a_live_web_claim_still_blocks_a_cli_start` | blocked unconditionally | blocks (pid checked, same message) |
| **web-then-cli, stale claim (R-01b)** | `TestWebThenCli::test_a_dead_web_claim_is_reclaimed_by_a_cli_start` | **blocked unconditionally, no log** | **proceeds, logged as a reclaim** |
| web-then-cli, no pid recorded (R-01b) | `TestWebThenCli::test_a_web_claim_without_a_pid_blocks_conservatively` | blocked unconditionally | blocks (conservative default, unverifiable claim) |
| crash-then-restart | `TestCrashThenRestart::test_stale_web_claim_is_reclaimed` | 201, no log | 201, logged as a reclaim |
| no claim | `TestNoClaim::test_an_ended_claim_never_blocks` | 201 | 201 (unchanged) |
| end: PTY/ACP owns nothing | `TestEndMatrix::test_ending_a_pty_session_kills_no_multiplexer_session` | **called `kill_all_study_sessions`** | kills nothing |
| end: CLI owns its own name | `TestEndMatrix::test_ending_a_cli_session_kills_only_its_own_tmux_name` | **called `kill_all_study_sessions`** | kills only its own name |
| end: shared path | `TestEndMatrix::test_web_end_common_never_reaches_for_kill_all` | **called `kill_all_study_sessions`** | never calls it |

**R-02b** (`tests/test_sidebar_pilot.py::TestSidebarKeyBindings::
test_end_session_leaves_an_unrelated_study_session_alive`): the study
sidebar's End Session key called `kill_all_study_sessions()` directly, in
addition to `cleanup_on_exit()` — the same defect, a third surface the
original review's finding didn't name. Now: the direct call is deleted;
`cleanup_on_exit()` alone (already scoped by the fix above) handles it.

**Commits:** `1f5f371` (contract + ADR stub), `2d901c9` (red matrix),
`16b451f` (R-01), `cdac20b` (R-02), `704f1e2` + `5835e4d` + `9f5769f`
(R-02b and lint/format follow-ups), `863f0ea` (R-04, delete
`session_runtime/`), `7e9786a` (R-06, R-08), `2ddebb9` (R-07), `847aad3`
(R-09c) — all on `lane/m2-session-authority`.

**Verified:** `kill_all_study_sessions` (`tmux.py`, `herdr.py`) has exactly
one production caller left — `cli/_clean.py`'s `--all` flag
(`rg -n "kill_all_study_sessions\(" packages/studyloop/src` after this
lane: `cli/_clean.py:109` is the only call against a `mux`/`Multiplexer`
instance; the rest are the two backends' own definitions and
`multiplexer.py`'s Protocol delegation). `just preflight` green at every
step; the full unit suite gained tests at every step and lost none it
didn't delete on purpose (R-04's 7-test pass-count floor, exact match).
