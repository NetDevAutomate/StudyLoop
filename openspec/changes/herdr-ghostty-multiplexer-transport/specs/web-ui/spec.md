## MODIFIED Requirements

### Requirement: --dev flag supports a renderer selector
`studyloop web --dev` SHALL accept an optional `--dev-renderer` argument with
values `ghostty` (default) and `wterm`. The selected renderer determines which
vendor scripts are injected into the page and which `<meta name="studyloop-dev-mode">`
content value is set. Passing `--dev-renderer` without `--dev` SHALL imply
`--dev=True`.

#### Scenario: Default dev mode uses ghostty-web
- **WHEN** `studyloop web --dev` is run without `--dev-renderer`
- **THEN** the served page contains
  `<meta name="studyloop-dev-mode" content="ghostty-web">`,
  a `<script>` tag for `ghostty-web-0.4.0.umd.cjs`, and a `<script>` tag
  for `ghostty-web-bootstrap-0.4.0.js`. No wterm scripts are injected.

#### Scenario: Explicit wterm renderer
- **WHEN** `studyloop web --dev-renderer wterm` is run
- **THEN** the served page contains
  `<meta name="studyloop-dev-mode" content="wterm">`,
  the wterm-0.3.0.js script, the wterm-adapter-0.3.0.js script, and the
  wterm-0.3.0.css stylesheet. No ghostty-web scripts are injected.

#### Scenario: Production mode is unaffected
- **WHEN** `studyloop web` is run without `--dev` or `--dev-renderer`
- **THEN** the served page contains no dev-mode meta tag, no ghostty-web
  scripts, and no wterm scripts. The production xterm.js stack is served
  as normal.

### Requirement: ghostty-web bootstrap patches globals only after WASM init
The vendored `ghostty-web-bootstrap-0.4.0.js` SHALL call
`GhosttyWeb.init('/vendor/js/ghostty-vt-0.4.0.wasm')` eagerly on page load
and SHALL only patch `window.Terminal` and `window.FitAddon` inside the
`.then()` resolution callback. This prevents `liveAgentConsole()` from
constructing a terminal before the WASM engine is ready. If WASM init fails,
`window.Terminal` remains the production xterm.js `Terminal` (graceful
degradation).

#### Scenario: WASM loads successfully
- **WHEN** the page loads in `--dev-renderer ghostty` mode and
  `ghostty-vt-0.4.0.wasm` fetches successfully
- **THEN** `window.Terminal` is ghostty-web's Terminal class and
  `liveAgentConsole()` creates a ghostty-web terminal instance

#### Scenario: WASM load fails (network error, corrupt file)
- **WHEN** `GhosttyWeb.init()` rejects
- **THEN** `window.Terminal` remains the original xterm.js Terminal,
  a console.error is logged, and `liveAgentConsole()` falls back to the
  production renderer with no user-visible error

## ADDED Requirements

### Requirement: Existing wterm path is preserved behind explicit selector
The vendored wterm-0.3.0.js, wterm-adapter-0.3.0.js, and wterm-0.3.0.css
files SHALL NOT be deleted. They are served when `--dev-renderer wterm` is
selected. The existing `test_web_wterm_dev_mode.py` test suite SHALL
continue to pass when invoked against a server started with
`--dev-renderer wterm`.

#### Scenario: wterm dev mode still works
- **WHEN** `studyloop web --dev-renderer wterm` serves the page
- **THEN** the wterm adapter is loaded, `window.Terminal` is the
  WTermAdapter class, and the existing wterm e2e test assertions pass

### Requirement: WASM binary is served as a separate static file
The `ghostty-vt-0.4.0.wasm` file SHALL be served at
`/vendor/js/ghostty-vt-0.4.0.wasm` as a static file with MIME type
`application/wasm`. It SHALL NOT be base64-inlined into the JavaScript
bundle. This keeps transfer size minimal for dev mode (where a live server
is always present) and avoids the 37% size overhead of base64 encoding.

#### Scenario: Browser fetches WASM file
- **WHEN** the bootstrap script calls
  `GhosttyWeb.init('/vendor/js/ghostty-vt-0.4.0.wasm')`
- **THEN** the browser fetches the .wasm file via a same-origin request and
  the Content-Type response header is `application/wasm`
