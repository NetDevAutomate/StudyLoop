## ADDED Requirements

### Requirement: Body Double has its own start picker
The Body Double view SHALL render its own start picker while no session is
active, containing: an agent `<select>`, the detected-agents card grid, a
transport `<select>` (`pty` | `acp` | `ttyd`, with `acp` shown only when the
selected agent reports `supports_acp` and `available`), an energy slider, a
single freeform text input labelled for the current activity, and a start
button. It SHALL NOT render the study-target cascade (target kind, topic,
vendor, course, lesson) and SHALL NOT render a session-type selector.

The picker SHALL reuse the existing `.session-start-picker`, `.picker-field`,
`.picker-select`, `.picker-input`, `.picker-hint`, `.agent-choice-grid`, and
`.start-session-btn` classes so Body Double and Study Session are visually
identical surfaces.

#### Scenario: Opening Body Double with no active session
- **WHEN** the learner navigates to `#body-double` with no session active
- **THEN** the picker is visible with an agent pre-selected (first detected
  available agent), transport defaulted to `pty`, an empty freeform activity
  field, and the start button disabled

#### Scenario: Selected agent does not support ACP
- **WHEN** the learner selects a PTY-only agent (e.g. Claude Code) in the
  Body Double picker
- **THEN** the `acp` transport option is not offered

#### Scenario: Picker fields occupy real layout boxes
- **WHEN** the Body Double picker is rendered at desktop and narrow widths
- **THEN** every `.picker-field` and the start button have non-zero bounding
  boxes and do not overlap each other or the Pomodoro timer panel

### Requirement: The freeform activity is the session topic
The Body Double start SHALL be gated on non-empty freeform activity text and
a selected agent, and SHALL POST that text as `topic` to
`POST /api/session/start` together with `energy`, `agent`, and `transport`.
No new endpoint and no session-type field SHALL be introduced. (ADR-0001)

#### Scenario: Start with an empty activity field
- **WHEN** the learner clicks start with the freeform field blank
- **THEN** the button is disabled, no request is issued, and a hint explains
  what is missing

#### Scenario: Start with an activity and an agent
- **WHEN** the learner enters "unblock the Glue job", picks an agent, and
  starts
- **THEN** exactly one `POST /api/session/start` is issued with
  `topic: "unblock the Glue job"` and the chosen `agent`/`transport`/`energy`

#### Scenario: A study session is already active
- **WHEN** the learner starts a Body Double session while a study session
  holds the single-active-session slot
- **THEN** the server's HTTP 409 is surfaced as a visible picker error, not
  swallowed silently

### Requirement: Body Double uses the modern live agent console
The Body Double view SHALL render the agent surface via
`liveAgentConsole('body-double')` — xterm.js for `pty`, ACP chat for `acp`,
and the same-origin `/terminal/` iframe via `_mountLegacyIframe()` for
`ttyd`. It SHALL NOT mount `terminalPanel()`, and its terminal pane SHALL NOT
be gated on `state.ttyd_port` or on a `terminal-ready` event. (ADR-0004)

#### Scenario: PTY session started from Body Double
- **WHEN** a Body Double session starts on the `pty` transport
- **THEN** an xterm.js terminal mounts in the Body Double terminal pane with a
  non-zero bounding box and connects to the returned `ws_url`

#### Scenario: Legacy ttyd forced by the operator
- **WHEN** `STUDYLOOP_TRANSPORT=ttyd` is set and a Body Double session starts
- **THEN** the console mounts the `/terminal/` iframe through
  `_mountLegacyIframe()`, not through `terminalPanel()`

#### Scenario: No session has been started
- **WHEN** the app is loaded and no session has been started
- **THEN** every ttyd iframe `src` in the page is bound to a state field that
  is empty until `_mountLegacyIframe()` runs, so no `/terminal/` request is
  issued at page load (the lazy-load invariant currently asserted against
  `activeTtydUrl` in `test_terminal_proxy.py`, re-expressed against
  `legacyTtydUrl`)

### Requirement: Body Double starts skip the park-first friction
A Body Double start SHALL NOT query `GET /api/backlog` and SHALL NOT render
`.park-first-overlay`, regardless of how many topics are active. Body
doubling is not a new study thread. (ADR-0003)

#### Scenario: Three topics already active
- **WHEN** `GET /api/backlog` would report `active_count >= max_active` and
  the learner starts a Body Double session on new activity text
- **THEN** the session starts immediately, no backlog request is issued, and
  no park-first overlay appears

### Requirement: The Pomodoro timer and header survive the rebuild
The Body Double view SHALL retain `.body-double-header` (with its `h2` and
`p`), the timer display, and `.body-double-controls` containing the focus /
break / long-break number inputs and a "Start Pomodoro" button, driven by
`$store.pomodoro`. These selectors are load-bearing for existing layout and
e2e tests and SHALL NOT be renamed by this change.

#### Scenario: Pomodoro started without an agent session
- **WHEN** the learner clicks "Start Pomodoro" in Body Double without
  starting an agent session
- **THEN** the timer runs, independent of session state

#### Scenario: Existing geometry assertions
- **WHEN** the layout regression suite measures `.body-double-header h2` and
  `.body-double-header p`
- **THEN** the existing assertions pass unchanged against the rebuilt view
