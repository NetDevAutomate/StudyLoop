---
title: "studyctl Web UI: Four-Bug Fix (Pomodoro Config, ttyd Auth, Port Cleanup, Terminal Resilience)"
date: 2026-04-07
category: integration-issues
tags:
  - web-ui
  - pomodoro
  - ttyd
  - security
  - process-management
  - terminal-health
  - fastapi
  - websocket
  - alpine-js
affected_modules:
  - studyctl.settings
  - studyctl.session.orchestrator
  - studyctl.session.cleanup
  - studyctl.web.routes.session
  - studyctl.web.routes.terminal_proxy
  - studyctl.web.static (components.js, index.html, style.css)
  - studyctl.tui.sidebar
  - studyctl.cli._study
severity: high
resolution_time: "~2 hours (fixes only; split layout rewrite is separate)"
---

# Web UI: Four-Bug Fix Session

## Problem Summary

Four user-reported issues with the studyctl web UI during v2.2.0 usage:

1. **Pomodoro timer hardcoded to 25 minutes** — no way to adjust focus/break durations
2. **ttyd terminal accessible without auth** — `-c` flag not passed, WebSocket proxy didn't forward credentials
3. **Stale ttyd/web server processes blocked new sessions** — orphaned processes on ports 7681/8567 prevented startup
4. **Terminal panel showed raw tmux error** — "can't find session: study-harness-matrix-1d96f243" when ttyd attached to dead session

## Root Causes

### 1. Pomodoro Hardcoded
Module-level constants in `sidebar.py` (`POMODORO_FOCUS = 25 * 60`) and `components.js` (`STUDY: 25 * 60`). No config path existed — `Settings` dataclass had no pomodoro fields.

### 2. ttyd No Auth
`start_ttyd_background()` built the ttyd command without `-c` credentials. The WebSocket proxy in `terminal_proxy.py` connected to upstream ttyd without forwarding the browser's `Authorization` header — HTTP proxy forwarded it but WS didn't.

### 3. Stale Processes
`end_session_common()` killed processes by PID only (from session state). When cleanup didn't run (abrupt exit, test harness crash), PIDs were lost. New session's `start_web_background()` / `start_ttyd_background()` silently failed to bind the occupied port.

### 4. Terminal Panel Error
The `terminalPanel()` Alpine component checked `state.ttyd_port` to set `available=true` but never verified ttyd was actually reachable. ttyd stayed running after tmux session died (no `--once` flag), serving the raw tmux "can't find session" error to every new client.

## Solutions

### Fix 1: Configurable Pomodoro Timer

**Settings layer** (`settings.py`):
```python
@dataclass
class PomodoroConfig:
    focus: int = 25        # minutes
    short_break: int = 5
    long_break: int = 15
    cycles: int = 4
```
Added to `Settings`, loaded from YAML `pomodoro:` section.

**API endpoint** (`web/routes/session.py`):
```python
@router.get("/settings/pomodoro")
def get_pomodoro_settings() -> dict:
    pomo = load_settings().pomodoro
    return {"focus": pomo.focus, "short_break": pomo.short_break, ...}
```

**Web UI** (`components.js`): Alpine store loads `localStorage > API > defaults`. `saveDurations()` persists to localStorage. Editable number inputs in header overlay and body-double panel.

**TUI sidebar** (`sidebar.py`): Reads from `load_settings().pomodoro`. Keybindings: `s` start/stop, `+/-` adjust focus, `p` pause, `r` reset.

### Fix 2: ttyd Authentication

**Credential passthrough** (`orchestrator.py`):
```python
def start_ttyd_background(session_name, *, lan=False, username="", password=""):
    if username and password:
        cmd.extend(["-c", f"{username}:{password}"])
```

**WebSocket auth** (`terminal_proxy.py`):
```python
auth_header = ws.headers.get("authorization")
if auth_header:
    upstream_kwargs["additional_headers"] = {"Authorization": auth_header}
```

Both CLI (`_study.py`) and web route (`session.py`) read config credentials and pass them through.

### Fix 3: Stale Process Cleanup

**Port-based kill** (`orchestrator.py`):
```python
def _kill_port_occupant(port: int, expected_cmd: str = "") -> None:
    """Kill any process listening on port. Safety guard: only kills if command matches."""
    # Uses lsof -ti :port, ps -p PID -o command=, os.kill(SIGTERM)
    # 0.5s grace period after kill for port release
```

Called before `start_ttyd_background()` and `start_web_background()`. Port-based fallback also added to `end_session_common()` in `cleanup.py`. `web_port` now stored in session state.

### Fix 4: Terminal Panel Resilience

**Zombie ttyd killer** (`session.py`):
```python
def _kill_stale_ttyd(state: dict) -> None:
    """Kill stale ttyd process if the tmux session it attaches to is gone."""
```
Called from `_get_full_state()` during zombie detection.

**Health check** (`index.html`): `terminalPanel()` component split into `available` (state has ttyd_port) vs `connected` (probe `/terminal/` succeeds). 10s periodic health check. `.terminal-unavailable` overlay shows "Terminal session ended" when connected=false.

## Investigation Steps That Failed

- **Split-pane resizable layout**: Attempted CSS Flexbox, CSS Grid, absolute positioning (Alpine), absolute positioning (vanilla JS). ALL produced correct DOM values in Playwright but didn't render correctly in real browsers (Chrome/Brave/Firefox on macOS). Deferred to next session — see handoff document.

## Prevention Strategies

1. **Always pass auth credentials through the full chain** — HTTP proxy, WebSocket proxy, and the underlying service. Test with `curl -u` against both the proxy and direct endpoints.
2. **Kill by port, not just PID** — PIDs are fragile (recycling, lost state). Port-based cleanup is reliable. Always call `_kill_port_occupant()` before binding.
3. **Health-check backing services** — don't assume a port number in state means the service is actually running. Probe the endpoint before showing UI.
4. **Config should flow to ALL consumers** — if a value is configurable, wire it through to every place that uses it (API, web UI, TUI, CLI).

## Test Coverage

20 new tests in `tests/test_fixes_pomodoro_auth_terminal.py`:
- `TestPomodoroConfig` (4 tests): defaults, custom values, YAML loading
- `TestPomodoroAPI` (3 tests): endpoint returns config/defaults/fallback
- `TestTtydAuth` (3 tests): `-c` flag present/absent based on credentials
- `TestTtydLifecycle` (4 tests): kill stale ttyd, zombie detector integration
- `TestPomodoroWebUI` (4 Playwright E2E): settings row visible/hidden, custom duration, API
- `TestTerminalResilience` (2 Playwright E2E): unavailable message, hidden when no ttyd

## Related Documentation

- `docs/plans/2026-04-04-ttyd-integration.md` — original ttyd integration plan
- `docs/plans/2026-04-05-web-ui-alpine-sidebar-plan.md` — Alpine sidebar plan
- `docs/internal/solutions/tmux-session-management-and-ci-issues.md` — prior session cleanup patterns
- `docs/internal/solutions/parallel-research-catches-pre-implementation-assumptions.md` — ttyd auth research (Note: `-c` flag IS supported despite this doc's finding about `TTYD_CREDENTIAL`)
- `.claude/handoffs/2026-04-07-184001-web-ui-split-layout-rewrite.md` — handoff for the unfinished split layout rewrite
