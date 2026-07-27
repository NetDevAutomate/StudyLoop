## Why

The Body Double tab cannot start an agent session. Its terminal is the
deprecated `terminalPanel()` ttyd iframe, gated on `x-show="available"`,
which reads `state.ttyd_port` — a field only the legacy `transport: "ttyd"`
path ever writes (`session/orchestrator.py:451`). Since `pty` is the
resolved default, `ttyd_port` is never set, `available` stays `false`, and
the entire panel — including its own "terminal unavailable" fallback — is
hidden. The learner sees blank space with no error. Meanwhile the
`body_double` option in the Study Session picker is a no-op label:
`sessionType` is written in three places and read in none, and
`StartSessionRequest` has no such field, so choosing it changes nothing and
leaves the learner on the Study Session view.

Body doubling is a first-class AuDHD support mode — presence and a running
clock while you do your own work. It needs its own start surface, not a
dead dropdown value in someone else's picker.

## What Changes

- **Add** a start picker to the Body Double view: agent dropdown, detected-
  agents card grid, transport selector (pty / acp / ttyd), an energy slider,
  and a single freeform "What are you working on?" text field in place of
  the Study Session topic/vendor/course/lesson cascade. Reuses the existing
  `.session-start-picker` / `.picker-field` / `.picker-select` /
  `.agent-choice-grid` / `.start-session-btn` CSS classes.
- **Add** a live agent terminal to the Body Double view using the modern
  `liveAgentConsole()` component (xterm.js for pty, ACP chat for acp,
  same-origin iframe for ttyd) instead of the legacy `terminalPanel()`.
- **Add** an `origin` field to the `study-session-start` /
  `study-session-stop` window events so the two `liveAgentConsole()`
  instances (Study Session, Body Double) each only respond to their own
  view's start. Without this, one start mounts two xterms and opens two
  WebSockets to the same PTY. See ADR-0002.
- **Keep** the existing Pomodoro timer, `.body-double-header`, and
  `.body-double-controls` selectors — three test suites and one e2e journey
  depend on them.
- **BREAKING (internal frontend contract)**: **remove** the Session Type
  dropdown from the Study Session picker, the `sessionType` component state,
  and the `sessionType` field from the `study-session-start` event detail.
  No backend or persisted data depends on any of them.
- **Remove** the `body_double` entry from `session_types` in
  `web/routes/session/_options.py`. The `session_types` key itself stays —
  `list_session_options` (MCP) publishes it and `test_mcp_session_parity.py`
  asserts its presence.
- **Remove** the Body Double view's dependency on `terminalPanel()` and on
  `splitLayout()`'s `terminal-ready` gating. `terminalPanel()` itself is
  **retained but no longer mounted anywhere** pending an explicit retirement
  change (ADR-0004).
- **No backend changes to session start.** Body Double reuses
  `POST /api/session/start` with the freeform text as `topic` (ADR-0001).
- Body Double starts are **exempt** from the park-first 3-topic friction
  (ADR-0003).

## Capabilities

### New Capabilities
- `body-double-session`: the Body Double view as a first-class session
  surface — its own agent/transport/freeform-activity picker, its own live
  agent console, the retained Pomodoro timer, and its relationship to the
  single-active-session slot.

  *Ownership note*: `docs/openspec.md` maps all of `web/` (including
  `static/index.html`) to `web-ui`, so a new capability sharing that file
  needs justifying. Two reasons it is the right split: (1) the baseline
  already carves static files out of `web-ui` by behaviour rather than by
  file — `voice-tts` owns `web/static/tts-engine.js`; (2) `web-ui` already
  carries 14 requirements against the contract's 5–9 guidance, and the
  contract's own remedy for that is to split. Body doubling is a distinct
  user-facing mode, not another web-ui surface detail. The boundary is:
  anything specific to the `#body-double` view belongs to
  `body-double-session`; shared picker/console/nav machinery stays in
  `web-ui`.

### Modified Capabilities
- `web-ui`: the park-first 3-topic friction requirement narrows to
  study-session starts only (Body Double is exempt); a new requirement
  governs origin-scoped addressing of the shared `liveAgentConsole()`
  component; the Study Session picker loses its Session Type field.

## Impact

- `packages/studyloop/src/studyloop/web/static/index.html` — Body Double
  view (`1142-1191`) rebuilt; Session Type field removed (`1516-1519`);
  `sessionType` state (`2497`) and event field (`2640`) removed;
  `liveAgentConsole()` (`2951`) gains an `origin` parameter and event filter;
  new `bodyDoubleSession()` component.
- `packages/studyloop/src/studyloop/web/static/style.css` — minor;
  `.body-double-*` rules (`337-365`) and the `main:has(.split-container)`
  override (`1570`) must keep working alongside the picker.
- `packages/studyloop/src/studyloop/web/routes/session/_options.py` — drop
  the `body_double` entry (`91-94`).
- Tests: `test_web_session_lifecycle.py:71` (stubbed `body_double` type),
  `test_web_terminal.py:154-270,409,426,531-535` (body-double
  `terminalPanel()` iframe), `test_web_layout_regression.py:203-211`
  (`.body-double-header` geometry — must keep passing),
  `test_terminal_proxy.py:153-157` (source-string assertion on
  `:src="activeTtydUrl || 'about:blank'"` — **will fail**, `activeTtydUrl`
  exists only in the iframe being removed),
  `test_web_navigation.py:74-77,123-132,159-160` (`[x-show*="body-double"]`),
  `e2e/test_representative_user_journey.py:93-108`
  (`.body-double-controls` Pomodoro selectors — must keep passing).
- Decisions recorded as ADR-0001 … ADR-0004 in `docs/adr/`.
