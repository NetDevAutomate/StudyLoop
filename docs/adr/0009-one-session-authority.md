# ADR-0009 — The session-state file is the claim; the in-process slot is a cache

**Status:** Proposed, 2026-09-02. Written as the M2 lane's step 0 contract stub;
finalised (status moved to Accepted, consequences filled in against the
landed code) in the lane's last step. Motivated by the 2026-09-02 full-repo
review's R-01 and R-02 findings and the 2026-09-01 purpose-congruence
review's C1 finding.

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
- Every start path (CLI, web PTY, web ACP) reads the claim before proceeding.
  A live claim owned by someone else blocks with the same 409 shape (web) or
  the same exit-1 message (CLI, unchanged) either surface already used for
  its own in-process conflict. A stale claim (owner's process/tmux session no
  longer exists) is reclaimed, logged, and never blocks a start forever.
- `kill_all_study_sessions()` keeps its blunt "kill everything" semantics —
  that is a legitimate, separate operation — but the per-session end path
  (`end_session_common` → `_cleanup_tmux_and_files`) no longer calls it. It
  kills only the ending session's own multiplexer name (nothing, for
  PTY/ACP).
- Rejected alternative: giving the CLI a control socket into the web server
  so a CLI end could directly call `active.release()` on a live web session.
  The existing `_grace.py` reaper already reconciles "the file changed
  out-of-process while a slot is held" within its poll interval; adding a
  second, synchronous IPC mechanism for the same problem was assessed and
  rejected as unnecessary complexity for a local, single-user tool.

## Consequences

Filled in against the landed code at the end of the lane (see the commit that
finalises this ADR for the concrete before/after and the matrix test IDs).
