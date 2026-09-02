# Session authority — the contract M2 is tested against

**Status:** written 2026-09-02 as the M2 lane's step 0 (no code changes accompany
this document). Supersedes the 2026-09-01 plan's §2.1 sketch with the sharper
version the 2026-09-02 full-repo review's R-01/R-02 findings require. See
[ADR-0009](../adr/0009-one-session-authority.md) for the decision record.

This is the contract `tests/test_session_authority_matrix.py` is written
against. Code changes land clause by clause; each clause names the step that
makes it true.

## 1. One claim, one cache

`session-state.json` (`session_state.py`) is the **cross-process CLAIM** to the
single-session slot. `session/active.py`'s module-level `_active` is an
in-process **CACHE** of that claim, valid only for a PTY/ACP session started by
*this* web server process.

Every start path reads the claim before proceeding. Every end path clears only
what it owns — never a blanket sweep. (§4.)

**C1 (council, High, closed):** "reads the claim before proceeding" used to
be two separate steps -- read the file (unlocked), decide whether it
blocks, THEN (much later, after real work: spawning a transport, creating
a DB record) write the new claim. A second start landing in that window
read the same "not blocked" state and could race the first one's
eventual write -- the R-01 clobber, by timing instead of by the R-01 bug
itself (which this lane already closed). `session_state.try_claim_session
(reservation, blocks, *, on_reclaim=None) -> dict | None` closes it: under
the SAME `fcntl.flock` `write_session_state` uses, read the current
claim, decide via `blocks`, and (if not blocked) write `reservation` as
the new claim -- **REPLACING** whatever was there, not merged over it
(C10, council: an earlier version merge-wrote, which resurrected a stale
claim's own fields -- `mux_session`, `child_pid`, `session_dir`, etc --
that the reservation does not name, into the brand-new session's state;
see clause 4's own note on this). All of this happens in one lock
acquisition. `on_reclaim(previous_state)` runs inside
that same lock, before the write, so a caller's IPC-file clear (C2) and
reclaim log (C4) are atomic with the claim itself, not a separate,
racy step. Every start path now calls this at the point of its own old
"unlocked read" (`_session_conflict()` for web; `session/start.py`'s
guard for CLI), with a reservation shape of `{"study_session_id": "<a
placeholder id, since the real one is not known yet>", "mode":
"starting", "transport": <"pty"|"acp"|absent for CLI>, "pid":
os.getpid(), "topic": …, "started_at": …}`. `mode="starting"` reads as
active (`is_session_active()` already treats anything but `"ended"` as
active) and, for a web reservation, as genuinely LIVE to anyone else
checking it cross-process (its own `pid` is this process, alive). Any
failure between the reservation and the real, final claim clears the
reservation (`clear_session_files()`); each start path scopes this
narrowly to its own actual risk window (the web paths wrap their entire
post-reservation body in a `claim_finalized` flag + `finally`, since many
failure points exist between reservation and the final write; the CLI
path's own window is much shorter -- only the DB-record call sits between
its reservation and its write). **Was residual, closed by C9 (below):** a
CLI reservation carries no `mux_session` (that name is not chosen until
later in the CLI's own flow), so a second, concurrent CLI start's own
`claim_blocks_cli_start` check could not see the first one's reservation
as live via the mux-session-exists check alone. Closed by checking the
reservation's `pid` BEFORE either owner-type branch, in both
`claim_blocks_cli_start` and `claim_blocks_web_start` -- see clause 2's
"Reservation" row.

## 2. Liveness

A claim is **LIVE** iff `session_state.is_session_active()` is true (a
`study_session_id` is set and `mode != "ended"`) **and its owner is alive**:

| Owner | How liveness is checked |
| --- | --- |
| CLI (`studyloop study`) — no `transport` key, or one outside `{"pty","acp"}` | Its recorded multiplexer session (`mux_session`/`tmux_session`) still exists (`get_backend().session_exists(name)`). No name recorded ⇒ not alive. A backend that raises while answering also fails open (not alive) — logged at WARNING (C5, council) rather than silently swallowed, so a genuinely broken backend is visible instead of indistinguishable from "no live session". |
| Web PTY/ACP, checked by the web server process that could hold it | `session/active.py`'s singleton is the *only* way a pty/acp claim can be genuinely live in THIS process — this codebase runs one web server process per machine (`active.py`'s own docstring: "One process, one session"). A check that reaches the file only after finding the singleton empty has therefore already proven the claim is not live in this process. **C3 (council):** it may still be live in a DIFFERENT web server process (a different port, or a restart racing the old instance before it exits) — since R-01b records `pid` on every web claim, `claim_blocks_web_start` now blocks iff that `pid` is recorded, alive, and not this process's own pid; own-pid or no-pid claims are unchanged (always stale here). |
| Web PTY/ACP, read cross-process (R-01b: `studyloop study`, i.e. `session/start.py`, checking a web-owned claim) | The web server process's own pid, recorded on the claim by `build_session_state_payload` (`"pid": os.getpid()`) at start time. Live iff `os.kill(pid, 0)` doesn't raise `ProcessLookupError`; a `PermissionError` (pid reused by a process this CLI invocation doesn't own) also counts as alive, since a real process IS sitting on that pid. **No `pid` recorded blocks conservatively** — a claim written by a build before this field existed can't be verified either way, and refusing (with the existing message telling the user how to end it) is safer than silently reclaiming a claim of unknown liveness. Implemented as `claim_blocks_cli_start` in `session_state.py`, next to `claim_blocks_web_start`; the two share the CLI-owned branch via a private `_cli_owned_claim_is_live` helper. **Accepted residual risk: pid reuse** between the web server's death and this check — an unrelated process now holding that pid reads as "alive," so the claim still blocks. The failure mode is a false block ("run `--end`"), never a false reclaim of a genuinely live session. |
| **Reservation (`mode="starting"`, C1/C9, council)** | Live iff its recorded `pid` is alive and is not the CHECKING process's own pid — checked BEFORE either owner-type row above, in both `claim_blocks_web_start` and `claim_blocks_cli_start` (shared private helper `_reservation_pid_is_live_and_foreign`). A reservation has no `mux_session` yet (the CLI chooses that name later in its own flow) and no in-process singleton either (the web singleton is populated only after `active.acquire()` succeeds, after the reservation already exists) — judging it by either of those signals alone reads it as stale to anyone else checking it, which is exactly the gap C9 closed: a fresh reservation must read as live to a concurrent second start of EITHER kind, or `try_claim_session`'s own locking (C1) only makes the READ consistent, not the outcome. The CLI keeps its pid through `os.execvp` into the tmux attach (the same OS pid survives an exec) and every later merge-write leaves `pid` untouched (`write_session_state` merges, never replaces) until `mux_session` is recorded, so this rule holds for the reservation's whole risk window. |

A **stale** claim (owner dead) never blocks a new start. The next start
**RECLAIMS** it: log a warning naming the previous owner's `study_session_id`
and transport, then proceed exactly as if no claim existed. It does not 409
forever. This is the crash-then-restart cell.

**C2 (council):** "exactly as if no claim existed" includes the IPC files,
not just the state file's claim fields. A reclaim (web or CLI) calls
`clear_session_files()` before proceeding, so the new session never shows
the dead session's `TOPICS_FILE`/`PARKING_FILE` content. Before this, both
start paths only `touch()`ed those files after a reclaim, so a crashed
session's leftover topics/parking stayed visible to whoever reclaimed the
slot. A live (blocking) claim's files are never touched -- clearing is a
reclaim-only side effect.

**C4 (council, residual, recorded not fixed):** a reclaim never checks --
and never kills -- a live PTY child the crashed server's process left
running (a "server restart with the agent still alive" case). Both
`PTYTransport` and `ACPTransport` now expose their child's pid via a
`.pid` property; the web start paths read it via `getattr(transport,
"pid", None)` (`None` for `StubTransport`, used in tests) and record it on
the claim as `child_pid` (`build_session_state_payload`). A reclaim's log
line (`session_state.reclaim_log_message`) names it when the PREVIOUS
claim had one, so a human (or a future `clean`/`doctor` orphan report,
item R-01g, 0.2.0) has it to hand -- reclaim itself takes no action on it.
Rejected: killing it on reclaim. The pid could have been reused by an
unrelated process by the time this runs, and the child may be the user's
own still-useful agent that simply outlived a crashed web server; neither
risk is worth taking to tidy up an orphan that costs nothing but a stray
process entry.

## 3. Start matrix

| | new start: CLI | new start: web (pty/acp) |
| --- | --- | --- |
| **existing: CLI live** | `session/start.py` now consults `claim_blocks_cli_start()`: blocks with the existing message iff the recorded multiplexer session still exists (R-01b — a stale one is reclaimed instead, see below) | **409**, same body `_session_conflict()` already builds for the in-process case (R-01) |
| **existing: web live** | `claim_blocks_cli_start()`: blocks with the existing message iff the recorded owner pid is alive (R-01b — a stale one is reclaimed instead, see below) | existing behaviour: `_session_conflict()` reads `session/active.py`'s singleton — **unchanged**, pinned by test |
| **existing: stale/crashed claim (CLI or web owner dead), singleton empty for the web column** | **proceeds** — reclaimed, with a logged warning naming the claim's `study_session_id` and transport (R-01b) | **201** — reclaimed, with a logged warning (the crash-then-restart cell, R-01) |

Cells, named per the brief:

1. **web-then-web** — existing, unchanged.
2. **cli-then-cli** (R-01b, the fix) — `session/start.py`'s own guard used to
   call `is_session_active()`, which only asked whether a claim existed, so
   it blocked a new CLI start unconditionally even when the recorded owner
   was provably dead. It now calls `claim_blocks_cli_start()`, sharing the
   CLI-owned-claim liveness check with `claim_blocks_web_start()` (does its
   recorded multiplexer session still exist?). A live claim blocks with the
   unchanged message; a stale one is reclaimed and logged, exactly like the
   web path already did for its own crash-then-restart cell.
   `is_session_active()` itself is unchanged — it still answers "does a
   claim exist," it just no longer gates the start on its own.
3. **cli-then-web** (the R-01 fix) — web start now consults the file claim
   before acquiring. A live CLI claim blocks with the same 409 shape
   `_session_conflict()` already builds for the in-process case.
4. **web-then-cli** (R-01b, the fix) — `session/start.py`'s guard used to
   block unconditionally whenever the file said ANY session was live,
   including a web PTY/ACP claim whose owning server process had crashed.
   `claim_blocks_cli_start()` now checks the claim's recorded `pid`
   cross-process (`os.kill(pid, 0)`); a live server process still blocks
   with the unchanged message, a dead one is reclaimed and logged. A claim
   with **no `pid` recorded** (written by a build before this fix) blocks
   conservatively — see clause 2's per-owner liveness table.

Crash-then-restart is cell 3's stale-claim branch (web start, singleton
empty) and cell 2/4's stale-claim branch (CLI start, either owner shape):
the recorded owner is provably dead — reclaimed, not blocked, in both
directions.

**C6 (council, matrix gap, closed):** cell 4's live-pid branch is also
exercised while the web session is merely DETACHED within its grace
window (`_grace.has_pending_release()` true — client's tab closed, agent
still running, not yet released) — `TestWebThenCli::
test_cli_start_is_refused_while_a_web_session_is_detached_within_grace`.
`claim_blocks_cli_start` does not consult grace state at all (only pid
liveness), which is exactly why this cell was worth pinning explicitly:
proof the two mechanisms compose correctly, not merely that each is
individually correct.

## 4. End matrix

| Ends | Effect |
| --- | --- |
| Web ends (`POST /session/end`) while a CLI tmux session happens to be live | `active.release()` tears down the web slot; `end_session_common` → `_cleanup_tmux_and_files` kills **only** the ending session's own multiplexer name (`None` for PTY/ACP, so nothing is killed). The CLI's tmux session is untouched. |
| CLI ends (`studyloop study --end`) while a web session happens to be live | `end_session_common` kills only the CLI's own tmux name. The web session's slot is unaffected by this call; it is released by the existing `_grace.py` reaper on its own schedule if the web session's owning process observes the file changed (out of scope for this clause — the reaper is not modified by this lane). |

**C10 (council, closed):** this invariant ("end kills only its own name")
depends on the state a session's end path reads NEVER carrying another
session's multiplexer name. `try_claim_session` reclaiming a stale claim
used to merge-write the reservation over it, so a stale CLI claim's
`mux_session` (plus `child_pid`, `session_dir`, and anything else the
reservation does not name) survived into the brand-new session's own
state — a web session started over a reclaimed CLI claim would then end
by calling `kill_session` on a tmux name that was never its own,
violating this exact row silently. Fixed by making the reservation write
REPLACE, not merge (clause 1) — a fresh start never inherits a stale
claim's other fields, full stop. Pinned by
`TestEndMatrix::test_a_web_session_started_over_a_reclaimed_stale_cli_claim_ends_without_kill_session`.

**`kill_all_study_sessions()`** (`tmux.py`, `herdr.py`'s `HerdrBackend`) keeps
its exact semantics — kill every `study-*` session, unconditionally, current
one last. It is a deliberate blunt instrument, not a bug. This lane removes
its call sites from every per-session end path (`session/cleanup.py`'s
`_cleanup_tmux_and_files`, R-02; `tui/sidebar.py`'s `action_end_session`,
R-02b — see below) and gives it exactly one deliberate, explicit caller:
`studyloop clean --all` (`cli/_clean.py`). Default `clean` (no `--all`) keeps
its existing, safer, zombie-only sweep (`plan_clean`'s `sessions_to_kill`,
individually killed via `mux.kill_session`) — `--all` widens that to every
`study-*` session, live or dead, for the rare case a user genuinely wants
the machine wiped. **Revision note:** an earlier draft of this clause
decided NOT to wire the function into `clean` at all, reasoning that
`clean`'s existing sweep already served the "no non-technical user
stranded" goal. That call is superseded by DECISIONS.md §E17: R-02's
definition of done is *exactly one* production caller, and with R-02b (below)
also in this lane's remit, "zero callers" was no longer an available answer
without leaving the function itself looking unreachable dead code.

**R-02b (DECISIONS §E17 — reassigned to this lane, closed):** `tui/sidebar.py`'s
`action_end_session` (the sidebar TUI's "End Session" key) also called
`mux.kill_all_study_sessions(current_session=session_name)` directly, in
addition to calling `cleanup_on_exit()` — reproducing R-02 through a third
surface the original review's finding didn't name. `tui/sidebar.py` is
dual-owned m2/m5 for this item (`tests/fixtures/lane_ownership.yaml`); the
direct call is deleted, `cleanup_on_exit()` (which now kills only this
session's own multiplexer name) and `self.exit()` are unchanged. See
`evidence/M2/BLOCKED.md` for the full history of this item, kept as the
record of what was found and why this lane initially could not act on it.

## 5. Reconcile rules (existing, restated so they are testable against this
   contract — not changed by this lane)

`web/routes/session/_grace.py`'s reaper already implements, in priority order:

1. Dead agent (`transport.is_running()` false) → release, `reason=agent_exited`.
2. Grace timer expiry (WS detached ≥ 90s) → release, `reason=grace_expired`
   or `agent_exited_while_detached`.
3. IPC disagreement (file says `mode=ended` / file replaced / cleared while
   the slot is still held) → release.
4. Never-attached timeout (90s, no WS ever connected) → release,
   `reason=never_attached`.

None of these rules change. They already satisfy "CLI end while web session is
live" (clause 4, second row) for the case where the CLI's end also happens to
be the thing that changes the file the web process is polling.

## 6. Scope decisions carried from M3

- **`studyloop/tmux.py:LOCK_FILE`** (`~/.config/studyloop/studyloop-tmux.lock`,
  hardcoded, not derived from `STUDYLOOP_SESSION_DIR`) — **in scope for this
  lane's spirit but not touched by it.** It is a real gap (a test run that
  legitimately wants an isolated `STUDYLOOP_SESSION_DIR` still serialises tmux
  *creation* through the real, shared machine-wide lock file), but no step in
  this lane's brief creates a new tmux session under test, and R-49 (fixing
  the integration harness's hardcoded paths generally) is explicitly M3's
  item, already delivered. Changing `LOCK_FILE` to derive from
  `session_state.SESSION_DIR` is a one-line, low-risk follow-up that belongs
  with R-49's own file list, not bundled into a session-authority contract
  commit. Recorded, not fixed, here. **Observed concretely (C8/C11, council):** the
  `integration`-marked suite (`test_harness_matrix.py`, real tmux) always
  bumps this file's mtime, which the unit suite's own session-runtime
  snapshot guard (C8/R-49d, `conftest.py`) then reports as "changed"
  whenever that suite runs -- a known, accepted false positive from an
  already-recorded gap, not a new defect either guard introduces.
- **`data/tmux-studyloop.conf:16`** (hardcodes the real
  `~/.config/studyloop/session-oneline.txt` path) — out of scope for the same
  reason: it is a static config asset outside every file this lane owns
  (`tests/fixtures/lane_ownership.yaml` does not list `data/`), and no step in
  this brief exercises it under test. Recorded, not fixed.

## 7. Docs that must change

Once the code lands, these public/internal pages describe the start/end
behaviour and must be updated in the same commit as the change that makes
their claim true (not before — R-59's lesson):

- `docs/system-overview.md` — the "web start/end" and "CLI start/end"
  narrative sections.
- `docs/web-ui-guide.md` — anywhere it describes what happens when a session
  is already active.
- `docs/cli-reference.md` — `studyloop study --end` and `studyloop clean`.

## Resolved notes

- **cli-then-cli's own staleness gap (R-01b, closed in `8a01a5e`).** `session/start.py`'s
  `is_session_active()` check used to block a new CLI start unconditionally,
  even when the recorded owner (CLI or web) was provably dead — unlike the
  web start path, which reclaimed a stale claim from the start. Fixed by
  `claim_blocks_cli_start()` (`session_state.py`), which checks CLI-owned
  claims the same way `claim_blocks_web_start()` does (multiplexer session
  still exists?) and web-owned claims by their recorded pid
  (`build_session_state_payload` now writes `"pid": os.getpid()` on every
  web claim). `session/start.py`'s guard reads the state once, blocks iff
  `claim_blocks_cli_start()` says so, and otherwise logs the same "Reclaiming
  stale session claim" warning the web path already used. See clause 2's
  per-owner liveness table and clause 3's matrix, cells 2 and 4.
  `is_session_active()` itself is unchanged; its only remaining production
  caller is `cli/_session.py`'s separate, simpler `studyloop session start`
  command (see below).

## Open questions

- **`cli/_session.py`'s `studyloop session start` claims carry no liveness
  signal (R-01h, filed for 0.2.0 — no code change in this lane).** This
  command keeps the unconditional `is_session_active()` guard, not
  `claim_blocks_cli_start()`/`try_claim_session()` (R-01b, C1). It is a
  different shape from `studyloop study`: it never records a
  `mux_session`/`tmux_session` name (no tmux environment is created), so
  the CLI-owned branch `claim_blocks_cli_start()` shares with
  `claim_blocks_web_start()` — "does the recorded multiplexer session still
  exist?" — can never confirm one of its own claims alive; every claim this
  command writes would read as stale and be silently reclaimed on the next
  start, removing the fail-closed guarantee `test_cli_session.py::
  test_session_start_rejects_when_already_active` pins, with no liveness
  signal (no pid, no session name) to replace it. R-01b's and C1's defect
  reports are both specifically about `studyloop study`
  (`session/start.py`); this command needs its own liveness signal (most
  plausibly a pid recorded at write time, mirroring the web claim) before
  the same reclaim rule can apply safely. Tracked as R-01h, 0.2.0.
- **Web-owned claim liveness checked cross-process.** Now exercised by
  `claim_blocks_cli_start()` (R-01b, above) for the one caller that needs
  it (`studyloop study`). A second future caller (e.g. a `studyloop session
  status` command) can reuse `claim_blocks_cli_start()`'s pid check as-is.
