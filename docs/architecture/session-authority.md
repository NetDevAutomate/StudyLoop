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

## 2. Liveness

A claim is **LIVE** iff `session_state.is_session_active()` is true (a
`study_session_id` is set and `mode != "ended"`) **and its owner is alive**:

| Owner | How liveness is checked |
| --- | --- |
| CLI (`studyloop study`) — no `transport` key, or one outside `{"pty","acp"}` | Its recorded multiplexer session (`mux_session`/`tmux_session`) still exists (`get_backend().session_exists(name)`). No name recorded ⇒ not alive. |
| Web PTY/ACP, checked by the web server process that could hold it | `session/active.py`'s singleton is the *only* way a pty/acp claim can be genuinely live — this codebase runs one web server process per machine (`active.py`'s own docstring: "One process, one session"). A check that reaches the file only after finding the singleton empty has therefore already proven the claim is not live in this process. |
| Web PTY/ACP, read from a different process (no code path in this repo does this today) | Out of scope for this lane — tracked as an open question below, not a defect this lane closes. |

A **stale** claim (owner dead) never blocks a new start. The next start
**RECLAIMS** it: log a warning naming the previous owner's `study_session_id`
and transport, then proceed exactly as if no claim existed. It does not 409
forever. This is the crash-then-restart cell.

## 3. Start matrix

| | new start: CLI | new start: web (pty/acp) |
| --- | --- | --- |
| **existing: CLI live** | existing behaviour (`session/start.py`'s own `is_session_active()` check blocks unconditionally) — **unchanged by this lane**, documented and pinned by test only | **409**, same body `_session_conflict()` already builds for the in-process case (R-01 — this is the fix) |
| **existing: web live** | existing behaviour (`session/start.py`'s `is_session_active()` check blocks unconditionally) — **unchanged**, pinned by test | existing behaviour: `_session_conflict()` reads `session/active.py`'s singleton — **unchanged**, pinned by test |
| **existing: stale/crashed web claim, singleton empty** | out of scope (CLI's existing check is unrelated) | **201** — reclaimed, with a logged warning (the crash-then-restart cell) |

Cells, named per the brief:

1. **web-then-web** — existing, unchanged.
2. **cli-then-cli** — existing, unchanged. `session/start.py`'s own
   `is_session_active()` call already blocks unconditionally, regardless of
   whether the earlier claim's owner is actually still alive. This lane does
   not change that path; the asymmetry is real but is not R-01/R-02, and
   fixing it would touch `session/start.py`'s CLI-only control flow the M1
   ttyd-retirement lane also edits. Recorded as an open question below.
3. **cli-then-web** (the R-01 fix) — web start now consults the file claim
   before acquiring. A live CLI claim blocks with the same 409 shape
   `_session_conflict()` already builds for the in-process case.
4. **web-then-cli** — already correctly refused today by `session/start.py`'s
   unconditional `is_session_active()` check, with the message
   `session/start.py` prints ("A session is already active. Resume: ...").
   Unchanged; pinned by test so a future edit cannot silently reopen it.

Crash-then-restart is cell 3's stale-claim branch: singleton empty, file says a
pty/acp session is live, no genuine owner — reclaimed, not blocked.

## 4. End matrix

| Ends | Effect |
| --- | --- |
| Web ends (`POST /session/end`) while a CLI tmux session happens to be live | `active.release()` tears down the web slot; `end_session_common` → `_cleanup_tmux_and_files` kills **only** the ending session's own multiplexer name (`None` for PTY/ACP, so nothing is killed). The CLI's tmux session is untouched. |
| CLI ends (`studyloop study --end`) while a web session happens to be live | `end_session_common` kills only the CLI's own tmux name. The web session's slot is unaffected by this call; it is released by the existing `_grace.py` reaper on its own schedule if the web session's owning process observes the file changed (out of scope for this clause — the reaper is not modified by this lane). |

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
  commit. Recorded, not fixed, here.
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

## Open questions

- **cli-then-cli's own staleness gap.** `session/start.py`'s `is_session_active()`
  check blocks a new CLI start unconditionally, even when the recorded owner
  (CLI or web) is provably dead — unlike the web start path this lane fixes,
  which reclaims a stale claim. `auto_clean_zombies()` runs first and clears
  some staleness (zombie tmux sessions with no child process, aged 60s+), but
  not a state file left at `mode=focus` by a CLI process that died before
  writing `mode=ended`. This is a real, separate gap; fixing it touches
  `session/start.py`'s CLI-only control flow, which M1's ttyd-retirement lane
  also edited on the same head. Left open for a follow-up item, not folded
  into R-01/R-02.
- **Web-owned claim liveness checked cross-process.** No code path in this
  repository reads a pty/acp-owned claim from a process other than the one
  web server that could hold it. If a future feature needs that (e.g. a
  `studyloop session status` CLI command showing a live web session), it will
  need a real cross-process liveness signal (a pid check against the
  transport's child process, most likely) that this lane does not build,
  because nothing exercises it today.
