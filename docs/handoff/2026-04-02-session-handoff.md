# Session Handoff — 2026-04-02

## What Was Done

### CI Fixes
- `test_cli.py` ruff formatting
- Integration tests marked `@pytest.mark.integration`, excluded from CI with `-m "not integration"`
- 7 Copilot review comments resolved (migrations v15, session state cleanup, IPC chmod, parking dedup, accessibility, notification prompt, SW cache routing)

### Study Session Bug Fixes
- **Q quit**: Kills ALL `study-*` sessions (stale first, current last). `detach-on-destroy on` ensures user returns to original shell, not another tmux session.
- **Resume**: Zombie detection via `pgrep -P <pane_pid>` (not `pane_current_command` which reports the wrapper shell). `kill_session` has retry loop for async kills.
- **Agent not starting**: `claude` binary resolved to absolute path via `shutil.which()` in `agent_launcher.py:get_launch_command()`. Non-interactive tmux shells don't source `.zshrc`, so `~/.local/bin` isn't in PATH.
- **tmux-resurrect**: User's `tmux-resurrect` plugin was restoring killed sessions. Identified as root cause of persistent zombie sessions. Documented in setup-guide.md.

### Test Harness (747 tests total)
Three layers in `packages/studyctl/tests/`:

| Layer | File | Tests | Needs tmux | CI-safe |
|-------|------|-------|-----------|---------|
| Textual Pilot | `test_sidebar_pilot.py` | 5 | No | Yes |
| Lifecycle | `test_study_lifecycle.py` | 15 | Yes | No |
| UAT Terminal | `test_uat_terminal.py` | 6 | Yes | No |

Harness modules in `tests/harness/`:
- `tmux.py` — `TmuxHarness` with poll-based `wait_for()`, pane capture, child process detection
- `study.py` — `StudySession` lifecycle API (start, resume, end_via_q, assertions)
- `agents.py` — Mock agent script builders (long_running, topic_logger, fast_exit, parking, crash)
- `terminal.py` — `TerminalSession` pexpect driver for real terminal UAT

### Documentation
- `docs/roadmap.md` — updated with v2.2.1, restructured phases
- `TODO.md` — comprehensive with estimates, testing mandate, study backlog feature
- `docs/setup-guide.md` — tmux prerequisite + resurrect compatibility note
- `docs/session-protocol.md` — tmux environment section added
- `docs/solutions/tmux-session-management-and-ci-issues.md` — full solution doc
- `docs/brainstorms/2026-04-02-test-harness-framework-brainstorm.md` — harness design

## Current State

- **Branch**: `main` (6 commits ahead of origin, not yet pushed)
- **Both machines in sync**: `user` + `user@192.168.1.22`
- **Stale branches removed**: `compact/core-only`, `feat/phase9-tui-polish`, `worktree-feat+live-session-dashboard`
- **Clean working tree**: no uncommitted changes

## Key Files Modified

| File | What changed |
|------|-------------|
| `packages/studyctl/src/studyctl/cli/_study.py` | Resume zombie detection, Q cleanup, detach-on-destroy, remain-on-exit |
| `packages/studyctl/src/studyctl/tmux.py` | `pane_has_child_process()`, `kill_all_study_sessions()`, `kill_session` retry |
| `packages/studyctl/src/studyctl/tui/sidebar.py` | Q action: fire-and-forget kill, cleanup all study sessions |
| `packages/studyctl/src/studyctl/agent_launcher.py` | Absolute path resolution for agent binary |
| `packages/studyctl/src/studyctl/session_state.py` | `clear_session_files(keep_state=)` parameter |
| `packages/studyctl/src/studyctl/parking.py` | INSERT OR IGNORE + rowcount check for dedup |
| `.github/workflows/ci.yml` | `-m "not integration"` for pytest |

## Known Issues / Gaps

1. **Nested tmux not tested**: `is_in_tmux()` → `switch_client()` path has no UAT test. Running `studyctl study` from inside an existing tmux session is untested.
2. **tmux-resurrect**: Works when plugin is disabled. Need to programmatically exclude `study-*` sessions from resurrect.
3. **`--end` from outside**: The `studyctl study --end` CLI path uses `kill_all_study_sessions()` but has no UAT test.
4. **Origin not pushed**: 6 commits ahead — push when ready to trigger CI.

## Next Session — Recommended Start

1. **Push to origin** and verify CI is green
2. **`studyctl clean` command** (~1-2 hrs) — quick win, kills stale sessions + IPC files
3. **tmux-resurrect compat** (~2-3 hrs) — exclude study sessions from resurrect
4. **Study Backlog Phase 1** (~1-2 sessions) — `studyctl topics list/add/resolve`, session-db migration, agent integration

## Run Commands

```bash
# Full CI-safe suite (what GitHub Actions runs)
uv run ruff check . && uv run ruff format --check . && uv run pytest --tb=short -m "not integration"

# Integration + UAT (local only, needs tmux)
uv run pytest packages/studyctl/tests/test_study_lifecycle.py packages/studyctl/tests/test_sidebar_pilot.py packages/studyctl/tests/test_uat_terminal.py -v

# Single lifecycle test
uv run pytest packages/studyctl/tests/test_study_lifecycle.py -v -k "test_q_kills"

# Live test
uv run studyctl study "Python Decorators" --energy 7
```
