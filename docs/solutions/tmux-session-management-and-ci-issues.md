---
title: "tmux session management, CI failures, and Copilot review fixes"
date: 2026-04-02
categories: [integration-issues]
tags: [tmux, ci, pytest, ruff, path-resolution, ipc, sqlite, pexpect, zombie-sessions, service-worker]
status: resolved
---

# tmux Session Management, CI Failures & Copilot Review Fixes

## Summary

Seven distinct issues surfaced during a single session covering CI pipeline failures, GitHub Copilot review comments, and persistent tmux session-management bugs. All were resolved.

---

## 1. CI Lint Failure — ruff formatting

**Symptom**: CI failed on `test_cli.py` with ruff formatting violations.

**Root cause**: File was not formatted to ruff's opinionated style before commit.

**Fix**:
```bash
uv run ruff format tests/test_cli.py
uv run ruff check --fix tests/test_cli.py
```

**Prevention**: Add `uv run ruff format . && uv run ruff check .` as a pre-commit hook.

---

## 2. CI Test Timeout — Integration Tests on Headless CI

**Symptom**: Integration tests (tmux-based) timed out after ~7 minutes on CI.

**Root cause**: Tests required a real tmux server with an attached terminal. CI runners are headless; tmux sessions that need a client attachment block indefinitely.

**Fix**: Skip tmux-dependent tests when `CI=true`:
```python
import os
import pytest

ci = os.getenv("CI") == "true"

@pytest.mark.skipif(ci, reason="tmux tests require interactive terminal")
def test_session_lifecycle():
    ...
```

Alternatively, set `TMUX_TMPDIR` to an isolated socket and run `tmux new-session -d` (detached) for purely command-driven tests that don't need a client.

**Prevention**: Separate test markers: `@pytest.mark.tmux` for interactive tests, gate them in CI with `pytest -m "not tmux"`.

---

## 3. Copilot Review Fixes (7 issues)

### 3a. migrations `CURRENT_VERSION` mismatch
Applied schema version constant consistently across migration runner and schema definition so the guard check `db_version == CURRENT_VERSION` never produces a false positive.

### 3b. `session_end` clearing state file prematurely
`session_end()` was removing the IPC state file before the UI had read the final state. Fix: write a terminal sentinel value (`{"status": "ended"}`) and let the reader clean up, or delay file removal with a short grace period.

### 3c. IPC file permissions
State file was created world-readable. Fix:
```python
import os
STATE_FILE.write_text(json.dumps(state))
os.chmod(STATE_FILE, 0o600)
```

### 3d. `INSERT OR IGNORE` lastrowid gotcha
`INSERT OR IGNORE` returns `lastrowid=0` when the row already exists (conflict ignored). Fix: query for the existing ID explicitly:
```python
cursor.execute("INSERT OR IGNORE INTO sessions (key) VALUES (?)", (key,))
if cursor.lastrowid == 0:
    cursor.execute("SELECT id FROM sessions WHERE key = ?", (key,))
    row_id = cursor.fetchone()[0]
else:
    row_id = cursor.lastrowid
```

### 3e. `user-scalable=no` accessibility
Removed `user-scalable=no` from the viewport meta tag — it prevents users with low vision from zooming. Use `maximum-scale=5` if layout constraints require a cap.

### 3f. Auto notification prompt
Browser notification permission was requested on page load. Fix: gate the `Notification.requestPermission()` call behind a user-initiated action (button click).

### 3g. Service Worker cache routing
SW cache strategy wasn't excluding API routes, causing stale API responses to be served. Fix: add a network-first or bypass rule for `/api/` paths in the SW fetch handler.

---

## 4. Q Quit Not Killing tmux Session

**Symptom**: Pressing Q to quit left orphaned tmux sessions.

**Root causes** (multiple, all required fixing):

1. `switch_client(":{previous}")` switched to stale sessions before `kill-session`, causing the current client to re-attach elsewhere.
2. `kill_all_study_sessions()` killed the current session first; the process received SIGHUP before it could kill the remaining sessions.
3. `detach-on-destroy` was not set, so tmux automatically switched the client to another session instead of exiting cleanly.
4. `tmux-resurrect` plugin restored killed sessions on next tmux start.

**Fix**:
```python
def kill_all_study_sessions():
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True, text=True
    )
    sessions = [s for s in result.stdout.splitlines() if s.startswith("study-")]
    current = os.environ.get("TMUX_SESSION", "")
    # Kill others first, current last
    others = [s for s in sessions if s != current]
    for s in others:
        subprocess.run(["tmux", "kill-session", "-t", s])
    # Detach client before killing current session
    subprocess.run(["tmux", "detach-client"])
    if current:
        subprocess.run(["tmux", "kill-session", "-t", current])
```

Set `detach-on-destroy on` in `~/.tmux.conf` to prevent auto-switching:
```
set -g detach-on-destroy on
```

Add `@resurrect-processes ''` in tmux-resurrect config to prevent resurrection of study sessions.

---

## 5. Resume Attaching to Zombie Sessions

**Symptom**: `resume` re-attached to sessions where the agent had already exited, but the pane showed a shell prompt.

**Root cause**: `pane_current_command` reports the wrapper shell (`zsh`), not the child process (`claude`). A finished agent leaves the pane in the shell, indistinguishable from an active one by this check.

**Fix**: Use `pgrep -P` to check for the child process:
```python
def is_agent_running(pane_pid: int) -> bool:
    result = subprocess.run(
        ["pgrep", "-P", str(pane_pid), "-x", "claude"],
        capture_output=True
    )
    return result.returncode == 0
```

---

## 6. Agent Not Starting in tmux Panes

**Symptom**: `claude` command not found when launched inside a new tmux pane.

**Root cause**: New panes open non-interactive, non-login shells that do not source `.zshrc`. `~/.local/bin` (where `claude` lives) was not in `PATH`.

**Fix**: Resolve the absolute path at launch time using `shutil.which()`:
```python
import shutil

def get_claude_path() -> str:
    path = shutil.which("claude")
    if path is None:
        raise RuntimeError("claude not found in PATH. Is it installed?")
    return path
```

Pass the absolute path to `tmux send-keys` or `tmux new-window -e PATH=...`.

---

## 7. Stale Sessions Accumulating

**Symptom**: After repeated study sessions, `tmux ls` showed many old `study-*` sessions.

**Root cause**: No cleanup of previous sessions on start or exit.

**Fix**: Call `kill_all_study_sessions()` (see §4) at session start, killing any pre-existing `study-*` sessions before creating a new one.

---

## Test Harness Built

| File | Purpose |
|------|---------|
| `tests/harness/tmux.py` | `TmuxHarness` — poll-based waits, session/pane lifecycle |
| `tests/harness/study.py` | `StudySession` — high-level lifecycle API |
| `tests/harness/agents.py` | Mock agent script builders |
| `tests/harness/terminal.py` | pexpect UAT driver |
| `tests/test_study_lifecycle.py` | 15 tests — real tmux + mock agents |
| `tests/test_sidebar_pilot.py` | 5 tests — Textual headless |
| `tests/test_uat_terminal.py` | 6 tests — pexpect terminal UAT |

---

## Prevention Strategies

- **CI guard**: Skip all `@pytest.mark.tmux` tests in CI; run them only locally or in a dedicated runner with a display.
- **PATH hygiene**: Always resolve tool paths with `shutil.which()` before embedding in tmux commands.
- **Session cleanup**: Kill stale `study-*` sessions at both startup and shutdown.
- **IPC discipline**: Write sentinel before removing state files; chmod 0o600 on creation.
- **ruff pre-commit**: `ruff format` + `ruff check --fix` in pre-commit prevents lint CI failures.
- **tmux-resurrect exclusion**: Exclude transient session prefixes from resurrection.
