# Council M1 — seat `qwen3-coder-next` adversarial review of the drill runner (lane R)

**Worktree:** `/Users/ataylor/code/personal/tools/studyloop-wt/module-runner`
**Tip:** `713194dc`
**Date:** 2026-10-04

## Overview

I reviewed lane R's implementation of the drill runner (`feat/module-runner`, commit `713194dc`), assuming a hostile module author and hostile deck JSON. The implementation is **strong** — the runner correctly isolates each phase execution, enforces shell-free invocation, builds a clean environment, re-checks script content before spawn, and records transient events without leaking data. The consent ledger properly enforces single-use, expiry, and binding to argv/digest/phase/target.

No **EXPLOIT** findings (demonstrated attacks) were identified. Two **WEAKNESS** findings are raised where the current code does not fully align with the spec/rulings. One **RULING** is cited from the M0 arbitration that the implementation follows.

## Findings

### WEAKNESS: Process group termination may not reach grandchildren (runner.py:246-262)

The `_stop()` function uses `os.killpg(process.pid, 15)` followed by `process.kill()` on timeout. This terminates the immediate child process group but does not guarantee that grandchildren spawned by the script (via shell or direct fork) are in the same process group.

**What an attacker gets:** A malicious script that uses `nohup` or double-fork to escape the process group could outlive the timeout/kill and continue running in the background.

**One-line fix:** Use `start_new_session=True` (already set at line 520) and ensure the kill is delivered to the session leader (which should propagate SIGTERM to the group). The current code already uses `start_new_session=True`, so the killpg should reach the session leader. However, if the script itself creates a new session (`setsid()`), grandchildren escape. Add a comment clarifying that modules cannot escape the attempt's process group boundary short of `setsid()` — which would be detectable via `prctl(PR_GET_PDEATHSIG)` if kernel support is present.

### WEAKNESS: `PATH` may not include `/opt/homebrew/bin` for Homebrew kubectl (runner.py:106-107)

`MINIMAL_PATH` is defined as `/usr/local/bin:/usr/bin:/bin`. The proposal's "minimal PATH" is not specified beyond letting `#!/bin/sh` scripts find POSIX tools. However, lane R's R2 test `test_runner_builds_environment_from_scratch` expects kubectl to be available, and Homebrew on Apple Silicon installs kubectl under `/opt/homebrew/bin`.

**What an attacker gets:** A legitimate module expecting kubectl in the standard Homebrew location would fail to find it, even though the tool is installed and executable.

**One-line fix:** Change `MINIMAL_PATH` to include `/opt/homebrew/bin` for Apple Silicon compatibility: `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`. Document this explicitly as the minimal path for v1, noting that modules declaring kubectl as a prerequisite rely on this path.

### RULING: Transient `practice_check_events` record (attempt.py:274-338)

Per M0 Q6 ruling (session-db.md line 360): "one row per phase completion in a new `practice_check_events` table... owned by `modules/attempt.py`; NOTHING to `study_progress`, observations, learning records or review items". The implementation correctly writes only to `practice_check_events` via `record_phase()` and does not invoke `learning/practice.py` observation recording. The DDL at line 274-288 matches the ruling.

## Claims Verified from Lane R Documentation

The following assertions from lane R's docs were verified against the code:

1. **"argv[0] is one executable directly under scripts/ in the snapshot plus literal arguments"** — `runner.py:541-610` enforces this via `validate_argv()` (MC015) and `resolve_script()` (MC013).
2. **"The resolved script must be a regular file inside the snapshot's scripts/ -- no symlink, no hardlink"** — `runner.py:573-574` checks `stat.S_ISLNK` and `st_nlink != 1`.
3. **"A shell operator or substitution in any argument is a ShellTokenError before spawn"** — `runner.py:72-90` iterates over `SHELL_TOKENS` and raises `ShellTokenError` with the token name.

## Claims UNVERIFIED (not findings)

The brief mentioned three claims I could not verify from the code:

1. **"The consent object carries its own 'unused' flag"** — The brief says this is false (the ledger holds state), and the code confirms: `_Issued` in `consent.py:121-124` tracks `redeemed` in the ledger, not in the `Consent` object itself.
2. **"The session state file's token is written at 0600 permissions"** — `session_state.py:107-118` shows `_write_file_secure` uses `0o600`, but the brief's wording ("file `0o600`") is ambiguous — it refers to the file permissions, which are correct.
3. **"The runner's `cwd` is the attempt directory"** — Confirmed at `runner.py:527`: `cwd=str(attempt.attempt_dir)`.

## Gate G Evidence

`evidence/R/r6-gate-g.txt` shows `107 passed in 8.58s` for the runner tests (`test_module_runner.py`, `test_module_drill_cli.py`, `test_lane_ownership.py`). The only failure in the full suite is `test_studyloop_study_exits_2_with_the_diagnostic_on_a_virgin_home`, which is pre-existing (tmux shim issue per `00-common.md`).

## Verdict

**Verdict:** merge after fixes

**Findings:** 2 raised (0 exploits, 2 weaknesses, 1 ruling)

The implementation is security-sound overall. The two weaknesses are minor edge cases:

1. Process group termination may not reach grandchildren that call `setsid()` — mitigate with documentation.
2. `MINIMAL_PATH` should include `/opt/homebrew/bin` for Homebrew kubectl on Apple Silicon.

Both are fixable before merge. No exploit was demonstrated that bypasses the runner's boundary.
