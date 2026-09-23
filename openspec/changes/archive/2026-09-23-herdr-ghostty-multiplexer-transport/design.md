## Context

StudyLoop orchestrates live study sessions by composing panes in a terminal
multiplexer (tmux today) with an AI agent in the main pane and a Textual
sidebar in a right split. The coupling is deep: 21 functions in `tmux.py`,
12 production files importing them, 2 files bypassing the module with raw
subprocess calls, and 20 test files. The `--dev` terminal renderer (wterm)
requires a 200-line adapter shim because its API differs from xterm.js.

This design introduces a `Multiplexer` Protocol (backend-agnostic), two
implementations (`TmuxBackend`, `HerdrBackend`), a renderer selector for
`--dev`, and a simulated-user journey test matrix.

## Goals / Non-Goals

**Goals:**

- Extract a Protocol so production code is multiplexer-agnostic.
- Implement herdr backend using the workspace-per-study model.
- Auto-select herdr when available, fall back to tmux.
- Replace wterm with ghostty-web as the `--dev` default renderer.
- Preserve wterm behind `--dev-renderer wterm`.
- Cover both changes with simulated-user journey tests.

**Non-Goals:**

- Delete tmux support.
- Touch production xterm.js path.
- Implement herdr popup/notification features.
- Change the web session-start path (PTY/ACP transports are unaffected).

## Decisions

| ID | Decision | Rationale |
|---|---|---|
| D1 | Protocol, not ABC | `typing.Protocol` + `@runtime_checkable` — no inheritance coupling, duck-typing friendly, pytest can verify at runtime. |
| D2 | Workspace-per-study, not named sessions | herdr's default session is already running; workspaces provide isolation without server lifecycle management. Fall back to named sessions only if workspace ID stability proves insufficient. |
| D3 | `get_backend()` factory with env → config → availability cascade | `STUDYLOOP_MULTIPLEXER=herdr\|tmux` env var (override) → `config.yaml` `multiplexer:` key → `shutil.which("herdr")` → tmux. Default: tmux (until herdr journey suite is green). |
| D4 | Session state key migration via dual-read | Read `mux_session` first, fall back to `tmux_session`. Write only `mux_session` + `mux_main_pane` + `mux_sidebar_pane`. No version field needed — JSON file, not schema'd. |
| D5 | `--dev-renderer {ghostty,wterm}` with ghostty default | Preserves wterm path and its test suite. Selector stored as `<meta name="studyloop-dev-mode" content="ghostty-web\|wterm">`. |
| D6 | No adapter shim for ghostty-web | ghostty-web IS the xterm.js API. A ~30-line bootstrap script handles WASM init + global patching. `liveAgentConsole()` unchanged. |
| D7 | `display_popup` → accept-loss | herdr has no popup/overlay. Replace with: notification for break reminders, dedicated pane for interactive UIs, web dashboard for pickers. No protocol method for popup. |
| D8 | `set_option` → `configure_session_defaults()` | Backend-specific defaults encapsulated in a single method. tmux backend sets `remain-on-exit`, `detach-on-destroy`, `window-size`. herdr backend uses workspace labels + pane report-metadata. |
| D9 | `set_environment` → creation-time env only | herdr supports `--env` at workspace/pane creation, not mutation. StudyLoop already knows all env vars upfront. Mutable state uses IPC files (existing pattern). |

## Component Design

### `multiplexer.py` (NEW)

```python
from typing import Protocol, runtime_checkable
from pathlib import Path

@runtime_checkable
class Multiplexer(Protocol):
    """Backend-agnostic terminal multiplexer for study sessions."""

    # Detection
    def is_available(self) -> bool: ...
    def is_inside_session(self) -> bool: ...
    def is_server_running(self) -> bool: ...

    # Session lifecycle
    def session_exists(self, name: str) -> bool: ...
    def create_session(self, name: str, *, command: str | None = None,
                       cwd: str | None = None,
                       env: dict[str, str] | None = None) -> str: ...
    def kill_session(self, name: str) -> bool: ...
    def list_study_sessions(self) -> list[str]: ...
    def kill_all_study_sessions(self, current_session: str | None = None) -> None: ...

    # Pane management
    def split_pane(self, target: str, *, direction: str = "right",
                   size: int = 30, percentage: bool = False,
                   command: str | None = None,
                   env: dict[str, str] | None = None) -> str: ...
    def send_keys(self, target: str, keys: str, *, enter: bool = True) -> None: ...
    def select_pane(self, target: str) -> None: ...

    # Session configuration (backend-specific semantics)
    def configure_session_defaults(self, session: str) -> None: ...

    # Client/attach
    def switch_client(self, name: str) -> None: ...
    def attach(self, name: str) -> None: ...  # replaces current process (os.execvp)

    # Process introspection
    def pane_has_child_process(self, pane_id: str) -> bool: ...
    def is_zombie_session(self, name: str, min_age_seconds: float = 60.0) -> bool: ...

    # Test harness support
    def capture_pane(self, pane_id: str, lines: int = 50) -> str: ...
    def wait_for_content(self, pane_id: str, pattern: str,
                         timeout_ms: int = 10000) -> str: ...


class TmuxBackend:
    """Wraps existing tmux.py functions into Multiplexer protocol."""
    ...

def get_backend() -> Multiplexer:
    """Factory: env → config → availability → default (tmux)."""
    ...
```

### `herdr.py` (NEW)

```python
class HerdrBackend:
    """herdr workspace-per-study implementation of Multiplexer."""

    def __init__(self) -> None:
        self._session_name: str | None = None  # HERDR_SESSION if using named sessions
        # Prefer default session + workspace isolation (D2)

    def _herdr(self, *args: str, json_output: bool = True) -> dict | str:
        """Run herdr CLI, parse JSON output."""
        ...

    def create_session(self, name: str, *, command=None, cwd=None, env=None) -> str:
        """Create a workspace labelled `name`, return workspace_id."""
        # herdr workspace create --label {name} --cwd {cwd} --no-focus [--env K=V ...]
        ...

    def wait_for_content(self, pane_id: str, pattern: str, timeout_ms=10000) -> str:
        """herdr wait output <pane_id> --match <pattern> --regex --timeout <ms>"""
        ...

    def is_zombie_session(self, name: str, min_age_seconds: float = 60.0) -> bool:
        """Check agent_status + process-info; age from StudyLoop DB."""
        ...
```

### Renderer injection (`app.py` changes)

```python
def _dev_renderer_scripts(renderer: str) -> list[str]:
    """Return <script>/<link> tags for the selected dev renderer."""
    if renderer == "ghostty-web":
        return [
            '<meta name="studyloop-dev-mode" content="ghostty-web">',
            '<script src="/vendor/js/ghostty-web-0.4.0.umd.cjs"></script>',
            '<script src="/vendor/js/ghostty-web-bootstrap-0.4.0.js"></script>',
        ]
    elif renderer == "wterm":
        return [
            '<meta name="studyloop-dev-mode" content="wterm">',
            '<link rel="stylesheet" href="/vendor/css/wterm-0.3.0.css">',
            '<script defer src="/vendor/js/wterm-0.3.0.js"></script>',
            '<script defer src="/vendor/js/wterm-adapter-0.3.0.js"></script>',
        ]
    return []
```

### Bootstrap script (`ghostty-web-bootstrap-0.4.0.js`)

~30 lines. Reads `<meta name="studyloop-dev-mode" content="ghostty-web">`,
calls `GhosttyWeb.init('/vendor/js/ghostty-vt-0.4.0.wasm')`, patches
`window.Terminal` and `window.FitAddon` inside the `.then()` callback, nulls
`window.WebglAddon` and `window.ClipboardAddon`.

### Test harness evolution

```python
# tests/harness/multiplexer.py (NEW)
class MultiplexerHarness:
    """Backend-agnostic test harness wrapping Multiplexer protocol."""

    def __init__(self, backend: Multiplexer): ...
    def session_exists(self, name: str) -> bool: ...
    def capture_pane(self, pane_id: str, lines: int = 50) -> str: ...
    def wait_for_pane_content(self, pane_id: str, pattern: str, timeout: int = 10) -> str: ...
    def send_keys(self, pane_id: str, keys: str, *, enter: bool = True) -> None: ...
    def cleanup_all(self) -> None: ...
```

Existing `TmuxHarness` is retained for the tmux-specific integration tests
that remain. New journey tests use `MultiplexerHarness` parameterised by
backend.

## Error Handling

| Scenario | Handling |
|---|---|
| herdr binary not found | `get_backend()` returns `TmuxBackend`. Logged at DEBUG. |
| herdr server not running | `HerdrBackend.create_session()` auto-starts via `herdr workspace create` (herdr auto-starts its server on first command). |
| herdr command timeout | `subprocess.run(timeout=30)` → `MultiplexerError`. Caller retries once. |
| herdr workspace create fails | Raise `MultiplexerError` with stderr. `session/start.py` catches and falls back to tmux if `STUDYLOOP_MULTIPLEXER != "herdr"` (explicit selection = no fallback). |
| WASM init fails (ghostty-web) | Bootstrap logs error. `window.Terminal` remains unpatched → `liveAgentConsole()` uses the xterm.js `Terminal` already loaded by the page (graceful degradation to non-dev mode). |
| Pane ID format differences | IDs are opaque strings in the protocol. No test asserts on format. |

## Testing Strategy

### Unit tests (mocked, run in CI always)

- `test_multiplexer_protocol.py`: verify `TmuxBackend` and `HerdrBackend` are
  `isinstance(Multiplexer)` at runtime.
- `test_tmux_backend.py`: existing `test_tmux.py` reworked to test through
  `TmuxBackend` class (mock subprocess).
- `test_herdr_backend.py`: mock `subprocess.run` → verify correct CLI args,
  JSON parsing, error handling.
- `test_backend_selection.py`: mock `shutil.which`, env vars, config → verify
  `get_backend()` returns correct type.
- `test_ghostty_web_vendor.py`: file existence + size assertions for vendored
  assets.

### Integration tests (real multiplexer, `pytest -m integration`)

- `test_herdr_integration.py`: real herdr binary, parameterised journey tests
  (T1-T11 from impact map). Marked `skipif not shutil.which("herdr")`.
- `test_tmux_integration.py`: existing tests, parameterised through
  `MultiplexerHarness(TmuxBackend())`.

### E2E browser tests (Playwright, `pytest -m e2e`)

- `test_web_ghostty_dev_mode.py`: journeys B1-B7 from impact map.
- `test_web_wterm_dev_mode.py`: retained, runs under `--dev-renderer wterm`.

### Journey test parameterisation

```python
@pytest.fixture(params=["tmux", "herdr"])
def mux_harness(request):
    backend = request.param
    if backend == "herdr" and not shutil.which("herdr"):
        pytest.skip("herdr not available")
    if backend == "tmux" and not shutil.which("tmux"):
        pytest.skip("tmux not available")
    impl = TmuxBackend() if backend == "tmux" else HerdrBackend()
    return MultiplexerHarness(impl)
```

## Sequence: Session Start (herdr path)

```
User                  CLI                    HerdrBackend              herdr server
  │                    │                         │                         │
  │─studyloop study──▶│                         │                         │
  │                    │─get_backend()──────────▶│                         │
  │                    │◀─HerdrBackend───────────│                         │
  │                    │─create_session(name)───▶│                         │
  │                    │                         │─workspace create───────▶│
  │                    │                         │◀─{workspace_id,pane_id}─│
  │                    │◀─workspace_id───────────│                         │
  │                    │─split_pane(ws:p1)──────▶│                         │
  │                    │                         │─pane split─────────────▶│
  │                    │                         │◀─{sidebar_pane_id}──────│
  │                    │◀─sidebar_pane_id────────│                         │
  │                    │─send_keys(sidebar, cmd)▶│                         │
  │                    │                         │─pane run───────────────▶│
  │                    │─configure_defaults()───▶│                         │
  │                    │                         │─pane report-metadata───▶│
  │                    │─attach(workspace_id)───▶│                         │
  │                    │                         │─os.execvp("herdr")──────│
  │◀─────────────────TUI client takes over──────────────────────────────│
```

## Gaps Carried as Explicit Decisions

| Gap | tmux function | herdr status | Decision |
|---|---|---|---|
| `display_popup` | Floating overlay for topic picker, park prompt | No equivalent (API has `popup.close` but no CLI `popup.open`) | **Accept-loss (D7)**. Use notifications for alerts, web dashboard for pickers, dedicated pane for interactive UIs. |
| `set_option` | Runtime session options (status bar, pane borders) | No runtime options — config.toml only | **Encapsulate (D8)**. `configure_session_defaults()` sets backend-specific defaults. herdr uses workspace labels + pane report-metadata. |
| `set_environment` | Mutable session env vars | `--env` at creation only, not mutable after | **Accept (D9)**. All vars known at creation time. Mutable state via IPC files. |
| `load_config` | Source arbitrary tmux.conf | `herdr server reload-config` (main config only) | **tmux-only**. herdr backend's `configure_session_defaults()` skips this. |
| `is_zombie_session` (age) | `#{session_created}` timestamp | No creation timestamp exposed | **Workaround**. Track creation time in StudyLoop DB (already done for session tracking). |
