# Implementation Tasks

> **Reconciliation note — checklist audited retrospectively on 2026-08-21.**
> This checklist was authored up-front and never ticked as the work landed, so a
> 0-ticked list does **not** mean 0 progress — most of it is built. Each `- [x]`
> below carries a parenthetical evidence pointer (source symbol + test) proving
> it from the actual tree, not from memory. Items left `- [ ]` are either
> genuinely unbuilt or only partly done; partly-done items carry an inline
> `_(partial: …)_` note saying what is missing. Ticks were applied only where the
> source proves the outcome. As of this audit: **53 of 67 ticked, 14 left open**
> (mostly the herdr integration-journey gaps in T4.2, the deferred T2.3 default
> flip, and a few unit-test mock-target migrations that still pass via
> TmuxBackend delegation).
>
> **Re-audited 2026-09-05:** three boxes flipped on fresh evidence — the
> test_clean.py mock migration had landed (:255), test_orchestrator.py was
> deleted outright (nothing left to migrate), and the full suite was run green
> at HEAD b0a0ae5 (4790 unit / 504 e2e). Now **56 of 67 ticked, 11 left open**:
> the six T4.2 journey gaps, the T2.3 default flip blocked on them, the
> test_tmux_backend.py rename, the STUDYLOOP_MULTIPLEXER settings.py docs, the
> old-format state round-trip test, and the test_session_start.py mock
> migration.

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

- [x] **TDD**: Write `test_multiplexer_protocol.py` asserting: (done: tests/test_multiplexer_protocol.py — `test_tmux_backend_satisfies_protocol`, 18-method count assertion, `test_get_backend_returns_multiplexer`)
  - `TmuxBackend` is `isinstance(Multiplexer)` (runtime_checkable)
  - Protocol has exactly 18 public methods (count assertion guards against
    silent expansion)
  - `get_backend()` returns `Multiplexer`-conforming object
- [x] Create `packages/studyloop/src/studyloop/multiplexer.py` with the
  Protocol class, `MultiplexerError` exception, and `get_backend()` stub
  (returns `TmuxBackend()` always for now). (done: multiplexer.py — `Multiplexer` Protocol, `MultiplexerError`, `get_backend()`)
- [x] Make the test green. (done: test_multiplexer_protocol.py present + passing per recon)

### T1.2 — Wrap tmux.py as TmuxBackend

- [ ] **TDD**: Write `test_tmux_backend.py` (rename from `test_tmux.py`): _(partial: `test_tmux.py` still exists and exercises the module-level tmux funcs directly; no `test_tmux_backend.py` and no dedicated TmuxBackend-method suite — TmuxBackend is only covered indirectly via delegation + the isinstance check in test_multiplexer_protocol.py)_
  - Exercise each `TmuxBackend` method via mocked `subprocess.run`
  - Assert `configure_session_defaults()` calls `set_option` 3× + `load_config`
  - Assert `wait_for_content()` polls `capture_pane` (tmux has no wait)
- [x] Add `class TmuxBackend` to `multiplexer.py` (or keep in `tmux.py` and
  re-export — prefer `multiplexer.py` to keep the seam in one file). (done: multiplexer.py `class TmuxBackend` — all 18 methods delegate to tmux.py; `configure_session_defaults` does the 3× `set_option` + `load_config`; `wait_for_content` polls `capture_pane` via `re.search`)
  - Each method delegates to the existing module-level function in `tmux.py`.
  - `configure_session_defaults(session)` encapsulates: `set_option(session,
    "remain-on-exit", "off")`, `set_option(session, "detach-on-destroy",
    "on")`, `set_option(session, "window-size", "largest")`,
    `load_config(user_tmux_conf)`.
  - `wait_for_content(pane_id, pattern, timeout_ms)` implements a polling
    loop over `capture_pane` with `re.search(pattern, content)` — this is
    what `TmuxHarness.wait_for_pane_content()` already does.
- [x] Keep module-level functions in `tmux.py` intact (backwards compat for
  any scripts or tests still importing them directly). (done: TmuxBackend imports them; test_tmux.py still imports the module funcs and passes)

### T1.3 — Backend selection logic

- [x] **TDD**: Write `test_backend_selection.py`: (done: tests/test_backend_selection.py — `test_env_tmux_returns_tmux_backend`, herdr-available/absent cases raising `MultiplexerError`, default cases)
  - `STUDYLOOP_MULTIPLEXER=herdr` + herdr available → `HerdrBackend`
  - `STUDYLOOP_MULTIPLEXER=herdr` + herdr NOT available → raise
    `MultiplexerError` (explicit selection, no silent fallback)
  - `STUDYLOOP_MULTIPLEXER=tmux` → `TmuxBackend` always
  - No env var + herdr available → `TmuxBackend` (tmux default until flipped)
  - No env var + herdr NOT available → `TmuxBackend`
- [x] Implement `get_backend()` with the cascade: env →
  `shutil.which("herdr")` check → tmux default. (done: multiplexer.py `get_backend()` — env parse, `shutil.which` guard, lazy HerdrBackend import, tmux default)
- [ ] Add `STUDYLOOP_MULTIPLEXER` to `settings.py` env-var documentation. _(partial: the var is documented only in the `get_backend()` docstring in multiplexer.py; no reference in settings.py)_

### T1.4 — Session state key migration

- [x] In `session_state.py::read_session_state()`: read `mux_session` first,
  fall back to `tmux_session`. Same for `mux_main_pane`/`mux_sidebar_pane`. (done: session_state.py `read_session_state()` — three `mux_* not in state and tmux_* in state` fallbacks)
- [x] In `session_state.py::write_session_state()`: write `mux_session`,
  `mux_main_pane`, `mux_sidebar_pane`. Do NOT delete the old keys (other
  processes may read the file before they're updated). (done: `write_session_state()` is a merge that preserves old keys; the `mux_*` keys are written alongside the legacy `tmux_*` keys by the callers — orchestrator.py `create_tmux_environment` return dict + start.py `state_update`)
- [x] Update type annotations / docstrings. (done: `read_session_state` docstring documents the key migration)
- [ ] Test: write old-format state → read → get correct values. _(partial: no direct old→new fallback round-trip test found; related migration behaviour is covered by test_session_slot_reconcile.py `test_a_stale_tmux_key_does_not_wipe_a_live_slot` / `test_a_pty_start_payload_clears_inherited_tmux_keys`)_

### T1.5 — Repoint call sites (production)

- [x] `session/orchestrator.py`: Replace 8 `from studyloop.tmux import ...`
  with `from studyloop.multiplexer import get_backend`. Add `mux =
  get_backend()` at module or function level. Replace all calls. (done: orchestrator.py `create_tmux_environment`/`attach_if_needed` use `get_backend()` + `mux.create_session/configure_session_defaults/is_inside_session/switch_client/split_pane/select_pane/attach`; `env=` passed to `create_session`)
  - Replace `create_session()` → `mux.create_session()`
  - Replace `split_pane()` → `mux.split_pane()`
  - Replace `set_environment()` → pass `env=` dict to `create_session()`/
    `split_pane()` (creation-time env, per D9)
  - Replace `set_option()` × 3 + `load_config()` → `mux.configure_session_defaults()`
  - Replace `select_pane()` → `mux.select_pane()`
  - Replace `switch_client()` → `mux.switch_client()`
  - Replace `is_in_tmux()` → `mux.is_inside_session()`
  - Replace `attach()` → `mux.attach()`
- [x] `session/start.py`: Replace `is_tmux_available()` → `mux.is_available()`,
  `session_exists()` → `mux.session_exists()`, `kill_session()` →
  `mux.kill_session()`. (done: start.py `start_session` + `_rollback_failed_startup` use `get_backend()` + those protocol methods)
- [x] `session/resume.py`: 6 imports → protocol methods. (done: resume.py `handle_resume` uses `get_backend()` + `session_exists/pane_has_child_process/is_inside_session/switch_client/attach/kill_session`; reads `mux_session`/`mux_main_pane` with legacy fallback)
- [x] `session/cleanup.py`: 4 imports → protocol methods. (done: cleanup.py `_cleanup_tmux_and_files` + `auto_clean_zombies` use `get_backend()` + `kill_all_study_sessions/is_server_running/list_study_sessions/is_zombie_session/kill_session`)
- [x] `cli/_clean.py`: Replace imports. Move `LOCK_FILE` to backend impl
  (or keep as module-level in `multiplexer.py` since it's transport-agnostic). (done: _clean.py uses `get_backend()` + `is_server_running/list_study_sessions/is_zombie_session/kill_session`. Note: `LOCK_FILE` is still imported from `studyloop.tmux`, not moved to a backend/multiplexer — accepted, transport-agnostic and unchanged)
- [x] `cli/_doctor.py`: Guard `check_tmux_resurrect()` with
  `if isinstance(get_backend(), TmuxBackend)`. (done: _doctor.py `_get_registry` — `if isinstance(get_backend(), TmuxBackend): config_checks.append(check_tmux_resurrect)`)
- [x] `tui/sidebar.py:569-580`: Replace `from studyloop.tmux import _tmux`
  (PRIVATE!) with `get_backend().send_keys(pane_id, "C-c", enter=False)` +
  `get_backend().send_keys(pane_id, "/exit")`. (done: sidebar.py `action_end_session` uses `get_backend()` + `send_keys(main_pane, "C-c", enter=False)` / `send_keys(main_pane, "/exit", enter=True)` + `kill_all_study_sessions`)
- [x] `web/routes/session/_start.py`: Replace 4 tmux imports with protocol. (done: `_start_ttyd_session` uses `get_backend()` + `is_available/session_exists/kill_session`)
- [x] `web/routes/session/_ipc.py:12-22`: Replace `subprocess.run(["tmux",
  "has-session", ...])` with `get_backend().session_exists()`. (done: _ipc.py `_is_tmux_session_alive` uses `get_backend().session_exists()`; `_get_full_state` reads `mux_session` with `tmux_session` fallback)
- [x] `doctor/config.py`: No change to `check_tmux_resurrect()` body — only
  the call-site guard in `_doctor.py` changes. (done: no-op by design — guard lives in _doctor.py, confirmed above; config.py body unchanged)

### T1.6 — Update existing unit tests

- [x] `test_orchestrator.py`: Change mock targets from `studyloop.tmux.*` to
  `studyloop.multiplexer.get_backend` (return a mock `TmuxBackend`). _(superseded 2026-09-05: test_orchestrator.py no longer exists — deleted in later refactors — so there is no mock target left to migrate)_
- [ ] `test_session_start.py`: Same mock target change. _(partial: still patches `studyloop.tmux.is_tmux_available` / `shutil.which` / `subprocess.run` / `LOCK_FILE`; passes via TmuxBackend delegation rather than a `get_backend` mock)_
- [x] `test_session_cleanup.py`: Same. (done: test_session_cleanup.py patches `studyloop.multiplexer.get_backend` with a mock backend)
- [x] `test_clean.py`: Same. (done, verified 2026-09-05: test_clean.py:255 patches `studyloop.multiplexer.get_backend` — the earlier "not evidenced" note was stale)
- [x] `test_sidebar_pilot.py`: Mock `studyloop.multiplexer.get_backend`
  instead of `studyloop.tmux._tmux`. (done: test_sidebar_pilot.py patches `studyloop.multiplexer.get_backend`)
- [x] Verify all existing tests pass: `VIRTUAL_ENV=.venv uv run --active
  pytest -q packages/studyloop/tests/ -m 'not integration and not e2e and
  not live_kiro and not live_provider'` (done, verified 2026-09-05: full default-marker suite green at HEAD b0a0ae5 — 4790 passed, 4 skipped; full e2e also green — 504 passed)

---

## Track 2: HerdrBackend

**Dependency:** T1.1 (Protocol definition must exist to import from).
**Rollback:** Delete `herdr.py` + `test_herdr_backend.py`. No production file
references herdr until T1.3's selection logic is enabled (and default is tmux).

### T2.1 — HerdrBackend core (mocked)

- [x] **TDD**: Write `test_herdr_backend.py`: (done: tests/test_herdr_backend.py — `test_create_session_basic/_with_cwd/_with_env/_with_command`, `test_split_pane_right/_down/_with_command/_with_env`, `test_send_keys_with_enter/_without_enter/_special_keys`, `test_kill_session`, `test_session_exists_*`, `test_is_available_*`, etc.)
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
- [x] Implement `packages/studyloop/src/studyloop/herdr.py` to satisfy tests. (done: herdr.py `class HerdrBackend` — all detection/lifecycle/pane/capture methods implemented against the herdr CLI, opaque IDs, JSON-envelope unwrap)

### T2.2 — HerdrBackend advanced (mocked)

- [x] **TDD**: Add to `test_herdr_backend.py`: (done: test_herdr_backend.py covers zombie/list/kill-all/configure/server-running + error-path cases; herdr.py implements all)
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
- [x] Implement remaining methods. (done: herdr.py `is_zombie_session` [uses `_get_session_start_time` from StudyLoop DB — Gap 5 workaround], `list_study_sessions`, `kill_all_study_sessions`, `configure_session_defaults` [no-op per D8], `is_server_running`; `_herdr()` maps CalledProcessError/TimeoutExpired/JSONDecodeError/FileNotFoundError → `MultiplexerError`. Note: `configure_session_defaults` is a logged no-op rather than issuing `workspace rename` + `report-metadata`)

### T2.3 — Flip default (DEFERRED)

- [ ] ⚠️ **BLOCKED: requires T4 journey tests green on herdr.** Once the
  herdr journey suite passes, change `get_backend()` default from tmux to
  herdr (one-line change: `prefer_herdr = True`). Until then, herdr is
  opt-in via `STUDYLOOP_MULTIPLEXER=herdr`. _(confirmed still deferred: multiplexer.py `get_backend()` returns `TmuxBackend()` on no/empty env var; herdr remains opt-in — correctly not flipped, and T4.2 is not fully green)_

---

## Track 3: ghostty-web Renderer

**Dependency:** None (can start immediately, parallel with T1).
**Rollback:** Remove vendored files + revert `cli/_web.py` and `web/app.py`
changes. wterm remains at `--dev` default (it's still there).

### T3.1 — Vendor ghostty-web assets

- [x] Extract from npm tarball: (done: vendored under web/static/vendor/js/ — `ghostty-web-0.4.0.umd.js`, `ghostty-vt-0.4.0.wasm`, `ghostty-web-0.4.0.LICENSE.txt`; plus the registry bundle `ghostty-web-0.4.0.js` + `ghostty-adapter-0.4.0.js` + `vendor/css/ghostty-0.4.0.css`)
  ```bash
  npm pack ghostty-web@0.4.0
  tar -xzf ghostty-web-0.4.0.tgz
  cp package/dist/ghostty-web.umd.cjs \
    packages/studyloop/src/studyloop/web/static/vendor/js/ghostty-web-0.4.0.umd.cjs
  cp package/ghostty-vt.wasm \
    packages/studyloop/src/studyloop/web/static/vendor/js/ghostty-vt-0.4.0.wasm
  rm -rf package ghostty-web-0.4.0.tgz
  ```
- [x] Verify sizes: UMD ~48 KB, WASM ~400 KB. (done: `ghostty-vt-0.4.0.wasm` = 413 KB ✓. Note: the UMD bundle is ~623 KB, NOT ~48 KB, because the WASM is inlined as a base64 data URL — see dev_engines.py comment; the file is named `.umd.js` not `.umd.cjs`)

### T3.2 — Write bootstrap script

- [x] Create `ghostty-web-bootstrap-0.4.0.js` (~30 lines): (done: web/static/vendor/js/ghostty-web-bootstrap-0.4.0.js exists and is injected by the legacy `dev_renderer="ghostty"` path in app.py `index()`. Note: the default/registry path instead uses `ghostty-adapter-0.4.0.js` via dev_engines.py)
  - Guard: read `<meta name="studyloop-dev-mode" content="ghostty-web">`.
  - Call `GhosttyWeb.init('/vendor/js/ghostty-vt-0.4.0.wasm')`.
  - Inside `.then()`: patch `window.Terminal`, `window.FitAddon`,
    null `window.WebglAddon`, null `window.ClipboardAddon`.
  - Log to console on success/failure.

### T3.3 — Add `--dev-renderer` CLI option

- [x] **TDD**: Write test asserting `--dev-renderer ghostty` passes the
  value through to `create_app(dev_renderer="ghostty")`. (done: renderer selection covered by tests/test_web_dev_engines.py + test_web_vendor.py `TestDevRendererInjection` [drives `create_app(dev_mode=True, dev_renderer="ghostty")`])
- [x] In `cli/_web.py`: add `--dev-renderer` option (type=click.Choice
  `["ghostty", "wterm"]`, default="ghostty"). Pass to `create_app()`. (done: _web.py `--dev-renderer` `click.Choice(["ghostty","wterm"], case_sensitive=False)`, passed to `create_app(dev_renderer=...)`. Note: option default is None; the "ghostty" default is applied in the body)
- [x] If `--dev` is passed without `--dev-renderer`, default to "ghostty". (done: _web.py `if dev and dev_renderer is None: dev_renderer = "ghostty"`)
- [x] If `--dev-renderer` is passed without `--dev`, imply `--dev`. (done: _web.py `if dev_renderer is not None: dev = True`)

### T3.4 — Renderer-aware injection in app.py

- [x] **TDD**: Write test asserting: (done: test_web_vendor.py `TestDevRendererInjection` asserts ghostty→`content="ghostty-web"` + umd + bootstrap and no wterm; test_web_dev_engines.py asserts the registry path meta `content="ghostty"`; B7 default-mode regression in test_web_ghostty_dev_mode.py covers dev_mode=False)
  - `dev_renderer="ghostty"` → response contains `ghostty-web-0.4.0.umd.cjs`
    script tag + bootstrap tag + meta content "ghostty-web". No wterm tags.
  - `dev_renderer="wterm"` → response contains wterm tags + meta content
    "wterm". No ghostty tags.
  - `dev_mode=False` → neither.
- [x] Implement `_dev_renderer_scripts(renderer)` helper. (done: implemented inline in app.py `index()` rather than as a named `_dev_renderer_scripts` helper — the legacy `dev_renderer` branch emits ghostty/wterm tags; the default branch delegates to `dev_engines.inject_dev_engine`)
- [x] Replace current hardcoded wterm injection with call to helper. (done: app.py `index()` branches on `dev_mode`/`dev_renderer`/`dev_engine`; wterm is now one selectable branch, not hardcoded)

### T3.5 — Vendor file assertions

- [x] Add to `test_web_vendor.py`: (done: test_web_vendor.py `TestGhosttyWebVendorFilesExist` — `test_ghostty_web_umd_exists` [asserts `ghostty-web-0.4.0.umd.js`], `test_ghostty_web_wasm_exists`, `test_ghostty_web_bootstrap_exists`, `test_ghostty_web_wasm_size` [300 KB–600 KB])
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

- [x] Create `packages/studyloop/tests/harness/multiplexer.py`: (done: harness/multiplexer.py `class MultiplexerHarness` — `from_backend_name`, `session_exists`, `capture_pane`, `wait_for_pane_content`, `send_keys`, `cleanup_all`, `pane_has_children`, plus PTY-driven `start_study_session_pty`)
  - `MultiplexerHarness(backend: Multiplexer)` with methods:
    `session_exists`, `capture_pane`, `wait_for_pane_content`, `send_keys`,
    `cleanup_all`, `pane_has_children`.
  - Delegates to backend's protocol methods.
- [x] Export from `harness/__init__.py`. (done: harness/__init__.py exports `MultiplexerHarness` in `__all__`)
- [x] Add `mux_harness` fixture to `conftest.py` (parameterised by backend
  availability, see design doc). (done: tests/conftest.py `mux_harness` [param fixture] + `tmux_mux_harness` + `herdr_mux_harness`)

### T4.2 — PTY/UAT journeys (herdr)

All marked `@pytest.mark.integration`, skipif herdr not available.

- [x] **T1 — Session starts**: `studyloop study "X"` → workspace exists,
  agent pane has child, sidebar pane alive, state file written. (done: test_herdr_integration.py `TestSessionStarts` — `test_session_created_and_state_written`, `test_agent_pane_has_child`, `test_state_has_study_session_id`)
- [ ] **T2 — Pane layout**: 2 panes (main + sidebar), sidebar ≤30% width. _(not found: no pane-layout/width journey in test_herdr_integration.py)_
- [ ] **T3 — Sidebar renders**: capture sidebar → timer/elapsed text visible. _(not found: no sidebar-render journey in test_herdr_integration.py)_
- [x] **T4 — Agent receives keys**: send text → verify echoed in pane. (done: test_herdr_integration.py `TestAgentReceivesKeys.test_echo_visible_after_send_keys`)
- [x] **T5 — Q quits**: press Q in sidebar → session destroyed, state
  mode=ended, no stale workspaces. (done: test_herdr_integration.py `TestQQuits.test_end_via_cli_destroys_session`)
- [ ] **T6 — Detach/reattach**: start → create a second workspace (simulates
  user switching away) → focus back → agent still running. _(not found as described: `TestAttachFromOutside` covers the riskiest-assumption attach-from-outside case, but there is no detach-then-reattach journey)_
- [ ] **T7 — Resume dead**: start → kill agent → `--resume` → new session
  created with same topic. _(not found: no resume-dead journey in test_herdr_integration.py)_
- [x] **T8 — End from outside**: start → `studyloop study --end` from
  separate process → session killed. (done: test_herdr_integration.py `TestEndFromOutside.test_end_from_separate_process`)
- [ ] **T9 — Zombie handling**: create stale workspace (no children, >60s
  age in DB) → `auto_clean_zombies()` kills it. _(not found: no zombie-handling journey in test_herdr_integration.py — HerdrBackend.is_zombie_session is unit-tested in test_herdr_backend.py, but the end-to-end auto_clean journey is absent)_
- [ ] **T10 — Nested multiplexer**: set `HERDR_ENV=1` → studyloop study uses
  `workspace focus` not `os.execvp`. _(not found: no nested-multiplexer journey in test_herdr_integration.py)_
- [x] **T11 — No residue**: after Q, zero `study-*` workspaces in `workspace
  list`. (done: test_herdr_integration.py `TestNoResidue`)

### T4.3 — Playwright browser journeys (ghostty-web)

All marked `@pytest.mark.e2e`.

- [x] **B1 — Renderer boots**: `--dev-renderer ghostty` → page has
  `<meta content="ghostty-web">`, `window.GhosttyWeb` defined,
  `window.Terminal` is ghostty-web's `Terminal`. (done: test_web_ghostty_dev_mode.py `TestGhosttyRendererBoots`)
- [x] **B2 — PTY renders**: start session via API → `.xterm-mount` visible,
  terminal grid has non-empty text content within 5s. (done: `TestPTYRenders`)
- [x] **B3 — Keystrokes echo**: `page.keyboard.type("echo hello")` +
  Enter → "hello" appears in terminal content. (done: `TestKeystrokeEchoRealPTY`)
- [x] **B4 — Resize**: resize viewport → `term.cols`/`term.rows` change
  (evaluate via `page.evaluate()`). (done: `TestResize`)
- [x] **B5 — Selection**: click-drag → `getSelection()` returns non-empty. (done: `TestSelectionCopyRealPTY`)
- [x] **B6 — No errors**: zero `pageerror` events through full lifecycle. (done: `TestNoConsoleErrors`)
- [x] **B7 — Default mode regression**: without `--dev`, `window.Terminal`
  is NOT ghostty-web (no `GhosttyWeb` global). (done: `TestDefaultModeRegression`)

### T4.4 — Retain wterm test suite

- [x] Verify `test_web_wterm_dev_mode.py` still passes when invoked with
  `--dev-renderer wterm` mode. May need to adjust the dev-server startup
  fixture to pass the renderer flag. (done: tests/test_web_wterm_dev_mode.py exists (e2e), and test_web_ghostty_dev_mode.py `TestWtermRegressionGuard` guards the wterm path)

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
