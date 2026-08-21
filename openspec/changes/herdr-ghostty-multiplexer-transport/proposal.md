## Why

StudyLoop's live session orchestration is hard-coupled to tmux: 21 functions
in `tmux.py`, 12 call-site files using those functions directly, 2 files
shelling out to `tmux` bypassing the module entirely, and 20 test files
mocking or calling the real binary. This coupling means:

1. **No programmatic agent awareness.** StudyLoop polls `pane_has_child_process`
   (two subprocess calls: `display-message` → `pgrep`) to guess whether an
   agent is alive. herdr exposes first-class `agent_status` and `herdr wait
   agent-status` — a single call that blocks until the agent reaches a target
   state.
2. **String-parsing fragility.** Every tmux interaction parses untyped format
   strings. herdr returns structured JSON from every command.
3. **No wait primitives.** The test harness polls terminal content in a
   `time.sleep()` loop. herdr's `herdr wait output --match <pattern>` replaces
   the entire polling infrastructure with one atomic call.
4. **No popup/notification system.** Break reminders rely on `display_popup`
   (tmux-only, unsupported on all other terminal UIs). herdr has a native
   notification API.

Separately, the `--dev` terminal renderer (wterm 0.3.0) requires a 200-line
adapter shim, an esbuild step, and accepts three functional gaps (onScroll,
attachCustomKeyEventHandler, FitAddon) that ghostty-web 0.4.0 closes natively
while dropping the adapter entirely.

## What Changes

### A. Multiplexer Protocol Extraction + herdr Backend

- **Extract** a `Multiplexer` Protocol from the 21 tmux.py functions (16
  become protocol methods; 3 are tmux implementation details; 2 are
  test-harness-only).
- **Wrap** the existing tmux.py into a `TmuxBackend` class implementing the
  protocol — zero behaviour change.
- **Implement** a `HerdrBackend` class that speaks to the herdr CLI (JSON
  output, workspace-per-study model, `herdr wait` for event synchronisation).
- **Add** runtime backend selection: `HERDR_ENV=1` or `shutil.which("herdr")`
  → prefer herdr; fall back to tmux.
- **Preserve** tmux as the default until the herdr journey test suite is
  green.

### B. ghostty-web as `--dev` Terminal Renderer

- **Vendor** `ghostty-web@0.4.0` UMD + WASM (448 KB total — smaller than
  xterm.js's 730 KB, larger than wterm's 70 KB).
- **Add** a `--dev-renderer {ghostty,wterm}` selector (ghostty default) so
  the existing wterm test and prior work are preserved behind an explicit
  flag.
- **Delete** the 200-line wterm adapter shim — ghostty-web's xterm.js API
  compatibility means `liveAgentConsole()` works unchanged with only a thin
  bootstrap script (WASM init + global patch, ~30 lines).

### C. Simulated-User Journey Tests

- **7 Playwright browser journeys** covering the ghostty-web renderer
  lifecycle (boot, PTY render, keystrokes, resize, selection, no errors,
  regression).
- **11 PTY/UAT harness journeys** covering the multiplexer session lifecycle
  (start, layout, sidebar, keystrokes, Q-quit, detach/reattach, resume dead,
  end-from-outside, zombie, nested, no residue).
- Journey tests are parameterised by backend (`tmux` | `herdr`) — each marks
  which backends it requires.

## Capabilities

### New Capabilities
- `multiplexer-protocol`: the backend-agnostic `Multiplexer` protocol, its
  two implementations (`TmuxBackend`, `HerdrBackend`), the runtime selector,
  and the session-state key migration (`tmux_session` → `mux_session`).

### Modified Capabilities
- `session-transports`: the session transport layer gains a dependency on the
  multiplexer protocol rather than directly on `tmux.py`. The ttyd transport
  path's tmux calls route through the protocol.
- `live-session-orchestration`: orchestrator/start/resume/cleanup call the
  protocol instead of importing `tmux.*`. The zombie-detection heuristic
  gains a herdr-native `agent_status` path.
- `web-ui`: the `--dev` flag adds a renderer selector; the meta-tag content
  and vendor injection logic support both ghostty-web and wterm.
- `health-and-diagnostics`: the tmux-resurrect doctor check becomes
  conditional on `isinstance(backend, TmuxBackend)`.

## Impact

- `packages/studyloop/src/studyloop/tmux.py` — retained, wrapped as
  `TmuxBackend`.
- `packages/studyloop/src/studyloop/multiplexer.py` — NEW: Protocol +
  `get_backend()` factory + `TmuxBackend` class.
- `packages/studyloop/src/studyloop/herdr.py` — NEW: `HerdrBackend` class.
- `packages/studyloop/src/studyloop/session/orchestrator.py` — repointed to
  protocol.
- `packages/studyloop/src/studyloop/session/start.py` — repointed to
  protocol.
- `packages/studyloop/src/studyloop/session/resume.py` — repointed to
  protocol.
- `packages/studyloop/src/studyloop/session/cleanup.py` — repointed to
  protocol.
- `packages/studyloop/src/studyloop/cli/_clean.py` — repointed to protocol.
- `packages/studyloop/src/studyloop/cli/_web.py` — `--dev-renderer` option.
- `packages/studyloop/src/studyloop/web/app.py` — renderer-aware injection.
- `packages/studyloop/src/studyloop/web/static/vendor/js/` — ghostty-web
  assets added.
- `packages/studyloop/src/studyloop/tui/sidebar.py` — replace `_tmux()`
  private import with protocol call.
- `packages/studyloop/src/studyloop/web/routes/session/_start.py` — protocol.
- `packages/studyloop/src/studyloop/web/routes/session/_ipc.py` — protocol.
- `packages/studyloop/src/studyloop/doctor/config.py` — conditional check.
- Tests: new journey test files + updated harness.

## Non-Goals

- Hard-delete tmux support (kept as fallback).
- Replace xterm.js in production mode (only `--dev` is affected).
- N+2 herdr features (plugins, notification sounds, integration manifests).
- Web dashboard session-start via herdr (that path uses PTY/ACP transports,
  not the multiplexer).

## Risks / Trade-offs

- **herdr is preview-channel (0.7.4)** — API surface may shift. Mitigation:
  pin version, own both sides, protocol abstraction absorbs changes.
- **AGPL-3.0 licensing** — subprocess invocation (no linking, no
  distribution). Same pattern as tmux (ISC). Legal question is out of scope
  of this technical design.
- **CI has no herdr binary** — herdr journey tests are `skipif not
  shutil.which("herdr")`. A nightly job can provision it; the protocol test
  suite (mocked) runs everywhere.
- **Bundle size increase for ghostty-web** — 448 KB vs wterm's 70 KB.
  Acceptable: dev-mode only, still smaller than xterm.js (730 KB).
- **WASM init race** — mitigated by eager init + Alpine `$nextTick` natural
  delay. Guard in bootstrap defers `window.Terminal` patch to `.then()`.

## Migration Plan

No user-facing migration. Backend auto-selection means existing tmux users
see zero change until they install herdr. The `--dev` renderer switch is
backwards-compatible: `--dev-renderer wterm` restores prior behaviour.

Session state keys: a one-time read migration reads `tmux_session` and writes
`mux_session` (read both, prefer new). No schema version bump (JSON file, not
SQLite).

Rollback: each track is independently revertible — revert the protocol
extraction leaves tmux direct-calls intact; revert the herdr backend leaves
tmux-only; revert ghostty-web leaves wterm as `--dev` default.
