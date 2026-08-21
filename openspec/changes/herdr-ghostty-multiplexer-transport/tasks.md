# Implementation Tasks

## Executive Summary

| Track | Estimated Diff | Owned Files (new + modified) |
|---|---|---|
| T1 — Protocol + TmuxBackend | ~350 LOC | `multiplexer.py` (NEW), `tmux.py` (wrap), 10 call-site files, session-state migration |
| T2 — HerdrBackend | ~250 LOC | `herdr.py` (NEW), `tests/test_herdr_backend.py` (NEW) |
| T3 — ghostty-web renderer | ~150 LOC + 450 KB vendor | `cli/_web.py`, `web/app.py`, 3 vendor files (NEW), bootstrap (NEW) |
| T4 — Journey tests | ~500 LOC | `tests/harness/multiplexer.py` (NEW), 3 new test files, fixture updates |
| **Total** | **~1,250 LOC** + 450 KB vendor assets | |

**Riskiest assumption:** herdr's `workspace create --no-focus` + `workspace
focus` flow is equivalent to tmux's detached-create → attach pattern for the
terminal-handover UX (verified in recon, but only manually — no automated
journey test exists yet). If the `os.execvp("herdr", ["herdr"])` attach
pattern doesn't cleanly take over a terminal that was previously NOT running
herdr, the entire herdr session-start flow breaks. Mitigation: T4 includes an
explicit attach-from-outside journey test (T4.11) that proves this before any
call-site is repointed.

---

## Track Ownership (Disjoint File Sets)

### T1 — Protocol Extraction + TmuxBackend

**Owned files (new):**
- `packages/studyloop/src/studyloop/multiplexer.py`
- `packages/studyloop/tests/test_multiplexer_protocol.py`
- `packages/studyloop/tests/test_backend_selection.py`

**Owned files (modify):**
- `packages/studyloop/src/studyloop/tmux.py` (add class wrapper, keep
  module-level functions for backwards compat)
- `packages/studyloop/src/studyloop/session/orchestrator.py`
- `packages/studyloop/src/studyloop/session/start.py`
- `packages/studyloop/src/studyloop/session/resume.py`
- `packages/studyloop/src/studyloop/session/cleanup.py`
- `packages/studyloop/src/studyloop/cli/_clean.py`
- `packages/studyloop/src/studyloop/cli/_doctor.py`
- `packages/studyloop/src/studyloop/tui/sidebar.py`
- `packages/studyloop/src/studyloop/web/routes/session/_start.py`
- `packages/studyloop/src/studyloop/web/routes/session/_ipc.py`
- `packages/studyloop/src/studyloop/doctor/config.py`
- `packages/studyloop/src/studyloop/session_state.py` (key migration)
- `packages/studyloop/tests/test_tmux.py` (rename to `test_tmux_backend.py`)
- `packages/studyloop/tests/test_orchestrator.py` (mock target changes)
- `packages/studyloop/tests/test_session_start.py`
- `packages/studyloop/tests/test_session_cleanup.py`
- `packages/studyloop/tests/test_clean.py`
- `packages/studyloop/tests/test_sidebar_pilot.py`

### T2 — HerdrBackend

**Owned files (new):**
- `packages/studyloop/src/studyloop/herdr.py`
- `packages/studyloop/tests/test_herdr_backend.py`

**Owned files (modify):** NONE (T2 depends on T1 for the Protocol definition
but does not modify T1's files — it only imports from `multiplexer.py`).

### T3 — ghostty-web Renderer

**Owned files (new):**
- `packages/studyloop/src/studyloop/web/static/vendor/js/ghostty-web-0.4.0.umd.cjs`
- `packages/studyloop/src/studyloop/web/static/vendor/js/ghostty-vt-0.4.0.wasm`
- `packages/studyloop/src/studyloop/web/static/vendor/js/ghostty-web-bootstrap-0.4.0.js`

**Owned files (modify):**
- `packages/studyloop/src/studyloop/cli/_web.py` (add `--dev-renderer`)
- `packages/studyloop/src/studyloop/web/app.py` (renderer-aware injection)
- `packages/studyloop/tests/test_web_vendor.py` (add ghostty assertions)

**NOT touched:** `web/static/vendor/js/wterm-*.js`, `wterm-adapter-*.js`,
`vendor/css/wterm-*.css`, `tests/test_web_wterm_dev_mode.py` — these stay
intact behind `--dev-renderer wterm`.

### T4 — Journey Tests

**Owned files (new):**
- `packages/studyloop/tests/harness/multiplexer.py`
- `packages/studyloop/tests/test_herdr_integration.py`
- `packages/studyloop/tests/test_web_ghostty_dev_mode.py`

**Owned files (modify):**
- `packages/studyloop/tests/conftest.py` (add `mux_harness` fixture)
- `packages/studyloop/tests/harness/__init__.py` (export new harness)

### Non-Overlap Assertion

| File | T1 | T2 | T3 | T4 |
|---|---|---|---|---|
| `multiplexer.py` | ✎ | reads | — | reads |
| `herdr.py` | — | ✎ | — | reads |
| `cli/_web.py` | — | — | ✎ | — |
| `web/app.py` | — | — | ✎ | — |
| `session/orchestrator.py` | ✎ | — | — | — |
| `tests/conftest.py` | — | — | — | ✎ |
| `tests/harness/multiplexer.py` | — | — | — | ✎ |

No file is ✎ (write) in more than one track. T2 and T4 have read-only
dependencies on T1's `multiplexer.py` (Protocol import).

---

## Track 1: Protocol Extraction + TmuxBackend

**Dependency:** None (can start immediately).  
**Rollback:** Revert T1 commit(s) → all call-sites return to direct `tmux.*`
imports. The module-level functions in `tmux.py` are preserved (not deleted),
so reverting is clean.

### T1.1 — Define the Multiplexer Protocol

- [ ] **TDD**: Write `test_multiplexer_protocol.py` asserting:
  - `TmuxBackend` is `isinstance(Multiplexer)` (runtime_checkable)
  - Protocol has exactly 18 public methods (count assertion guards against
    silent expansion)
  - `get_backend()` returns `Multiplexer`-conforming object
- [ ] Create `packages/studyloop/src/studyloop/multiplexer.py` with the
  Protocol class, `MultiplexerError` exception, and `get_backend()` stub
  (returns `TmuxBackend()` always for now).
- [ ] Make the test green.

### T1.2 — Wrap tmux.py as TmuxBackend

- [ ] **TDD**: Write `test_tmux_backend.py` (rename from `test_tmux.py`):
  - Exercise each `TmuxBackend` method via mocked `subprocess.run`
  - Assert `configure_session_defaults()` calls `set_option` 3× + `load_config`
  - Assert `wait_for_content()` polls `capture_pane` (tmux has no wait)
- [ ] Add `class TmuxBackend` to `multiplexer.py` (or keep in `tmux.py` and
  re-export — prefer `multiplexer.py` to keep the seam in one file).
  - Each method delegates to the existing module-level function in `tmux.py`.
  - `configure_session_defaults(session)` encapsulates: `set_option(session,
    "remain-on-exit", "off")`, `set_option(session, "detach-on-destroy",
    "on")`, `set_option(session, "window-size", "largest")`,
    `load_config(user_tmux_conf)`.
  - `wait_for_content(pane_id, pattern, timeout_ms)` implements a polling
    loop over `capture_pane` with `re.search(pattern, content)` — this is
    what `TmuxHarness.wait_for_pane_content()` already does.
- [ ] Keep module-level functions in `tmux.py` intact (backwards compat for
  any scripts or tests still importing them directly).

### T1.3 — Backend selection logic

- [ ] **TDD**: Write `test_backend_selection.py`:
  - `STUDYLOOP_MULTIPLEXER=herdr` + herdr available → `HerdrBackend`
  - `STUDYLOOP_MULTIPLEXER=herdr` + herdr NOT available → raise
    `MultiplexerError` (explicit selection, no silent fallback)
  - `STUDYLOOP_MULTIPLEXER=tmux` → `TmuxBackend` always
  - No env var + herdr available → `TmuxBackend` (tmux default until flipped)
  - No env var + herdr NOT available → `TmuxBackend`
- [ ] Implement `get_backend()` with the cascade: env →
  `shutil.which("herdr")` check → tmux default.
- [ ] Add `STUDYLOOP_MULTIPLEXER` to `settings.py` env-var documentation.

### T1.4 — Session state key migration

- [ ] In `session_state.py::read_session_state()`: read `mux_session` first,
  fall back to `tmux_session`. Same for `mux_main_pane`/`mux_sidebar_pane`.
- [ ] In `session_state.py::write_session_state()`: write `mux_session`,
  `mux_main_pane`, `mux_sidebar_pane`. Do NOT delete the old keys (other
  processes may read the file before they're updated).
- [ ] Update type annotations / docstrings.
- [ ] Test: write old-format state → read → get correct values.

### T1.5 — Repoint call sites (production)

- [ ] `session/orchestrator.py`: Replace 8 `from studyloop.tmux import ...`
  with `from studyloop.multiplexer import get_backend`. Add `mux =
  get_backend()` at module or function level. Replace all calls.
  - Replace `create_session()` → `mux.create_session()`
  - Replace `split_pane()` → `mux.split_pane()`
  - Replace `set_environment()` → pass `env=` dict to `create_session()`/
    `split_pane()` (creation-time env, per D9)
  - Replace `set_option()` × 3 + `load_config()` → `mux.configure_session_defaults()`
  - Replace `select_pane()` → `mux.select_pane()`
  - Replace `switch_client()` → `mux.switch_client()`
  - Replace `is_in_tmux()` → `mux.is_inside_session()`
  - Replace `attach()` → `mux.attach()`
- [ ] `session/start.py`: Replace `is_tmux_available()` → `mux.is_available()`,
  `session_exists()` → `mux.session_exists()`, `kill_session()` →
  `mux.kill_session()`.
- [ ] `session/resume.py`: 6 imports → protocol methods.
- [ ] `session/cleanup.py`: 4 imports → protocol methods.
- [ ] `cli/_clean.py`: Replace imports. Move `LOCK_FILE` to backend impl
  (or keep as module-level in `multiplexer.py` since it's transport-agnostic).
- [ ] `cli/_doctor.py`: Guard `check_tmux_resurrect()` with
  `if isinstance(get_backend(), TmuxBackend)`.
- [ ] `tui/sidebar.py:569-580`: Replace `from studyloop.tmux import _tmux`
  (PRIVATE!) with `get_backend().send_keys(pane_id, "C-c", enter=False)` +
  `get_backend().send_keys(pane_id, "/exit")`.
- [ ] `web/routes/session/_start.py`: Replace 4 tmux imports with protocol.
- [ ] `web/routes/session/_ipc.py:12-22`: Replace `subprocess.run(["tmux",
  "has-session", ...])` with `get_backend().session_exists()`.
- [ ] `doctor/config.py`: No change to `check_tmux_resurrect()` body — only
  the call-site guard in `_doctor.py` changes.

### T1.6 — Update existing unit tests

- [ ] `test_orchestrator.py`: Change mock targets from `studyloop.tmux.*` to
  `studyloop.multiplexer.get_backend` (return a mock `TmuxBackend`).
- [ ] `test_session_start.py`: Same mock target change.
- [ ] `test_session_cleanup.py`: Same.
- [ ] `test_clean.py`: Same.
- [ ] `test_sidebar_pilot.py`: Mock `studyloop.multiplexer.get_backend`
  instead of `studyloop.tmux._tmux`.
- [ ] Verify all existing tests pass: `VIRTUAL_ENV=.venv uv run --active
  pytest -q packages/studyloop/tests/ -m 'not integration and not e2e and
  not live_kiro and not live_provider'`

---

## Track 2: HerdrBackend

**Dependency:** T1.1 (Protocol definition must exist to import from).  
**Rollback:** Delete `herdr.py` + `test_herdr_backend.py`. No production file
references herdr until T1.3's selection logic is enabled (and default is tmux).

### T2.1 — HerdrBackend core (mocked)

- [ ] **TDD**: Write `test_herdr_backend.py`:
  - `is_available()`: mock `subprocess.run(["herdr", "--version"])` → True/False
  - `is_inside_session()`: mock `os.environ.get("HERDR_ENV")` == "1"
  - `create_session(name, cwd, env)`: verify CLI args =
    `["herdr", "workspace", "create", "--label", name, "--cwd", cwd,
    "--no-focus", "--env", "K=V"]`, parse JSON response for `workspace_id`
  - `split_pane(target, direction, size)`: verify
    `["herdr", "pane", "split", target, "--direction", dir, "--ratio", ratio,
    "--no-focus"]`, parse JSON for `pane_id`
  - `send_keys(target, keys, enter=True)`: verify `pane send-text` +
    optional `pane send-keys enter`
  - `send_keys(target, keys, enter=False)`: verify only `pane send-text`
  - `kill_session(name)`: verify `workspace close`
  - `session_exists(name)`: verify `workspace list` → filter by label
  - `pane_has_child_process(pane_id)`: verify `pane process-info` → check
    `foreground_processes` length
  - `wait_for_content(pane_id, pattern, timeout_ms)`: verify
    `["herdr", "wait", "output", pane_id, "--match", pattern, "--regex",
    "--timeout", str(timeout_ms)]`, return matched text
  - `capture_pane(pane_id, lines)`: verify
    `["herdr", "pane", "read", pane_id, "--source", "recent-unwrapped",
    "--lines", str(lines)]`
  - `attach(name)`: verify `os.execvp` args
- [ ] Implement `packages/studyloop/src/studyloop/herdr.py` to satisfy tests.

### T2.2 — HerdrBackend advanced (mocked)

- [ ] **TDD**: Add to `test_herdr_backend.py`:
  - `is_zombie_session(name, min_age)`: mock `pane process-info` +
    `pane get` (agent_status). Use StudyLoop DB for age (mock
    `read_session_state()`).
  - `list_study_sessions()`: mock `workspace list` JSON, verify label
    prefix filter.
  - `kill_all_study_sessions(current)`: verify iterates and closes all
    `study-*` workspaces except `current`.
  - `configure_session_defaults(session)`: verify `workspace rename` +
    `pane report-metadata` calls.
  - `is_server_running()`: mock `herdr session list` success/failure.
  - Error handling: `subprocess.CalledProcessError` → `MultiplexerError`.
  - Error handling: `subprocess.TimeoutExpired` → `MultiplexerError`.
  - Error handling: invalid JSON response → `MultiplexerError`.
- [ ] Implement remaining methods.

### T2.3 — Flip default (DEFERRED)

- [ ] ⚠️ **BLOCKED: requires T4 journey tests green on herdr.** Once the
  herdr journey suite passes, change `get_backend()` default from tmux to
  herdr (one-line change: `prefer_herdr = True`). Until then, herdr is
  opt-in via `STUDYLOOP_MULTIPLEXER=herdr`.

---

## Track 3: ghostty-web Renderer

**Dependency:** None (can start immediately, parallel with T1).  
**Rollback:** Remove vendored files + revert `cli/_web.py` and `web/app.py`
changes. wterm remains at `--dev` default (it's still there).

### T3.1 — Vendor ghostty-web assets

- [ ] Extract from npm tarball:
  ```bash
  npm pack ghostty-web@0.4.0
  tar -xzf ghostty-web-0.4.0.tgz
  cp package/dist/ghostty-web.umd.cjs \
    packages/studyloop/src/studyloop/web/static/vendor/js/ghostty-web-0.4.0.umd.cjs
  cp package/ghostty-vt.wasm \
    packages/studyloop/src/studyloop/web/static/vendor/js/ghostty-vt-0.4.0.wasm
  rm -rf package ghostty-web-0.4.0.tgz
  ```
- [ ] Verify sizes: UMD ~48 KB, WASM ~400 KB.

### T3.2 — Write bootstrap script

- [ ] Create `ghostty-web-bootstrap-0.4.0.js` (~30 lines):
  - Guard: read `<meta name="studyloop-dev-mode" content="ghostty-web">`.
  - Call `GhosttyWeb.init('/vendor/js/ghostty-vt-0.4.0.wasm')`.
  - Inside `.then()`: patch `window.Terminal`, `window.FitAddon`,
    null `window.WebglAddon`, null `window.ClipboardAddon`.
  - Log to console on success/failure.

### T3.3 — Add `--dev-renderer` CLI option

- [ ] **TDD**: Write test asserting `--dev-renderer ghostty` passes the
  value through to `create_app(dev_renderer="ghostty")`.
- [ ] In `cli/_web.py`: add `--dev-renderer` option (type=click.Choice
  `["ghostty", "wterm"]`, default="ghostty"). Pass to `create_app()`.
- [ ] If `--dev` is passed without `--dev-renderer`, default to "ghostty".
- [ ] If `--dev-renderer` is passed without `--dev`, imply `--dev`.

### T3.4 — Renderer-aware injection in app.py

- [ ] **TDD**: Write test asserting:
  - `dev_renderer="ghostty"` → response contains `ghostty-web-0.4.0.umd.cjs`
    script tag + bootstrap tag + meta content "ghostty-web". No wterm tags.
  - `dev_renderer="wterm"` → response contains wterm tags + meta content
    "wterm". No ghostty tags.
  - `dev_mode=False` → neither.
- [ ] Implement `_dev_renderer_scripts(renderer)` helper.
- [ ] Replace current hardcoded wterm injection with call to helper.

### T3.5 — Vendor file assertions

- [ ] Add to `test_web_vendor.py`:
  - `test_ghostty_web_umd_exists` — file at expected path.
  - `test_ghostty_web_wasm_exists` — file at expected path.
  - `test_ghostty_web_bootstrap_exists` — file at expected path.
  - `test_ghostty_web_wasm_size` — between 300 KB and 600 KB.

---

## Track 4: Journey Tests

**Dependency:** T1.1 (Protocol), T2.1 (HerdrBackend basic), T3.4 (renderer
injection). Can start the harness (T4.1) in parallel once T1.1 lands.  
**Rollback:** Delete new test files. No production code depends on them.

### T4.1 — MultiplexerHarness

- [ ] Create `packages/studyloop/tests/harness/multiplexer.py`:
  - `MultiplexerHarness(backend: Multiplexer)` with methods:
    `session_exists`, `capture_pane`, `wait_for_pane_content`, `send_keys`,
    `cleanup_all`, `pane_has_children`.
  - Delegates to backend's protocol methods.
- [ ] Export from `harness/__init__.py`.
- [ ] Add `mux_harness` fixture to `conftest.py` (parameterised by backend
  availability, see design doc).

### T4.2 — PTY/UAT journeys (herdr)

All marked `@pytest.mark.integration`, skipif herdr not available.

- [ ] **T1 — Session starts**: `studyloop study "X"` → workspace exists,
  agent pane has child, sidebar pane alive, state file written.
- [ ] **T2 — Pane layout**: 2 panes (main + sidebar), sidebar ≤30% width.
- [ ] **T3 — Sidebar renders**: capture sidebar → timer/elapsed text visible.
- [ ] **T4 — Agent receives keys**: send text → verify echoed in pane.
- [ ] **T5 — Q quits**: press Q in sidebar → session destroyed, state
  mode=ended, no stale workspaces.
- [ ] **T6 — Detach/reattach**: start → create a second workspace (simulates
  user switching away) → focus back → agent still running.
- [ ] **T7 — Resume dead**: start → kill agent → `--resume` → new session
  created with same topic.
- [ ] **T8 — End from outside**: start → `studyloop study --end` from
  separate process → session killed.
- [ ] **T9 — Zombie handling**: create stale workspace (no children, >60s
  age in DB) → `auto_clean_zombies()` kills it.
- [ ] **T10 — Nested multiplexer**: set `HERDR_ENV=1` → studyloop study uses
  `workspace focus` not `os.execvp`.
- [ ] **T11 — No residue**: after Q, zero `study-*` workspaces in `workspace
  list`.

### T4.3 — Playwright browser journeys (ghostty-web)

All marked `@pytest.mark.e2e`.

- [ ] **B1 — Renderer boots**: `--dev-renderer ghostty` → page has
  `<meta content="ghostty-web">`, `window.GhosttyWeb` defined,
  `window.Terminal` is ghostty-web's `Terminal`.
- [ ] **B2 — PTY renders**: start session via API → `.xterm-mount` visible,
  terminal grid has non-empty text content within 5s.
- [ ] **B3 — Keystrokes echo**: `page.keyboard.type("echo hello")` +
  Enter → "hello" appears in terminal content.
- [ ] **B4 — Resize**: resize viewport → `term.cols`/`term.rows` change
  (evaluate via `page.evaluate()`).
- [ ] **B5 — Selection**: click-drag → `getSelection()` returns non-empty.
- [ ] **B6 — No errors**: zero `pageerror` events through full lifecycle.
- [ ] **B7 — Default mode regression**: without `--dev`, `window.Terminal`
  is NOT ghostty-web (no `GhosttyWeb` global).

### T4.4 — Retain wterm test suite

- [ ] Verify `test_web_wterm_dev_mode.py` still passes when invoked with
  `--dev-renderer wterm` mode. May need to adjust the dev-server startup
  fixture to pass the renderer flag.

---

## Verification Gate

After all tracks are complete, run the full verification:

```bash
# Unit tests (always run in CI)
VIRTUAL_ENV=.venv uv run --active pytest -q \
  packages/studyloop/tests/ \
  -m 'not integration and not e2e and not live_kiro and not live_provider'

# E2E browser tests
VIRTUAL_ENV=.venv uv run --active pytest -q \
  packages/studyloop/tests/test_web_ghostty_dev_mode.py \
  packages/studyloop/tests/test_web_wterm_dev_mode.py \
  -m e2e

# Integration tests (herdr, requires binary)
VIRTUAL_ENV=.venv uv run --active pytest -q \
  packages/studyloop/tests/test_herdr_integration.py \
  -m integration

# Integration tests (tmux, requires binary)
VIRTUAL_ENV=.venv uv run --active pytest -q \
  packages/studyloop/tests/test_study_integration.py \
  packages/studyloop/tests/test_study_lifecycle.py \
  packages/studyloop/tests/test_uat_terminal.py \
  -m integration

# just-based preflight (runs ruff + pyright + unit tests)
just preflight
```

**Pass criteria:**
- Zero new failures in unit test suite.
- wterm e2e tests pass with `--dev-renderer wterm`.
- ghostty-web e2e tests pass with `--dev-renderer ghostty`.
- herdr integration tests pass (or skip cleanly if binary absent).
- tmux integration tests pass unchanged (regression gate).
- `just preflight` green.

---

## Rollback Stories

### T1 Rollback (Protocol)

`git revert <T1 commits>`. Module-level functions in `tmux.py` are preserved
(never deleted), so reverting removes the Protocol + TmuxBackend wrapper and
restores direct imports. All call-sites return to `from studyloop.tmux
import ...`. Tests return to mocking `studyloop.tmux.*`. Zero runtime impact.

### T2 Rollback (herdr)

Delete `herdr.py` and `test_herdr_backend.py`. Remove the `HerdrBackend`
import from `get_backend()`. Since default was never flipped (T2.3 is
blocked), no user ever received herdr as their backend. Zero runtime impact.

### T3 Rollback (ghostty-web)

Revert `cli/_web.py` and `web/app.py` changes. Delete vendored ghostty-web
files. `--dev` reverts to wterm-only (no `--dev-renderer` option). Existing
wterm files untouched. Zero runtime impact.

### T4 Rollback (journey tests)

Delete new test files and harness. Remove `mux_harness` fixture from
`conftest.py`. No production code depends on these files. Zero runtime impact.

---

## Blocked / Under-Specified Tasks

| Task | Blocked On | Resolution Path |
|---|---|---|
| T2.3 (flip default) | T4.2 all green on herdr | Run full journey suite; flip when pass rate = 100% |
| T4.2 T9 (zombie age) | Session DB stores workspace creation time | Verify `write_session_state()` already records `started_at`; if not, add field in T1.4 |
| T4.3 B2/B3 (PTY render) | Web session-start must work with `--dev-renderer ghostty` | Depends on T3.4 being complete; test startup fixture must pass renderer |

---

## Explicit Gap Decisions (from recon)

| tmux Function | Status in herdr | Decision | Implementation |
|---|---|---|---|
| `display_popup(target, cmd, title, w, h)` | ❌ No CLI equivalent | **Accept-loss.** Drop from protocol. tmux-only callers (keybinding in `tmux-studyloop.conf`) are tmux-backend-specific config. Web dashboard handles pickers. | T1.1: not in Protocol |
| `set_option(target, opt, val)` | ❌ No runtime options | **Encapsulate.** `configure_session_defaults()` abstracts backend-specific setup. | T1.2: TmuxBackend calls set_option internally; HerdrBackend uses report-metadata |
| `set_environment(target, k, v)` | ⚠️ Creation-time only | **Accept.** Pass `env=` dict at creation. Mutable state via IPC files (existing pattern). | T1.5: orchestrator passes env dict to create_session/split_pane |
| `load_config(path)` | ⚠️ Main config only | **tmux-only.** Encapsulated in TmuxBackend's `configure_session_defaults()`. HerdrBackend no-ops. | T1.2: TmuxBackend-internal |
| `is_zombie_session` (age from tmux) | ⚠️ No creation timestamp | **Workaround.** Use StudyLoop DB `started_at` for age. | T2.2: HerdrBackend reads DB |
