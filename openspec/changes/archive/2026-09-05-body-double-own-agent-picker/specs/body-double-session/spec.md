## ADDED Requirements

### Requirement: Body Double has its own start picker
The Body Double view SHALL render its own start picker while no session is
active and no start is in flight, containing: an agent `<select>`, a
transport `<select>` (`pty` | `acp`, with `acp` carrying its own hint when
the selected agent supports it), and a single freeform text input labelled
for the current activity, plus a start button. It SHALL NOT render the
study-target cascade (target kind, topic, vendor, course, lesson) and SHALL
NOT render a session-type selector. While a start is in flight the view
SHALL show a starting spinner in place of the picker.

(As shipped, the picker uses the Body Double view's own `bd-`-prefixed
markup — `#bd-activity-input`, `#bd-agent-select`, `#bd-transport-select`,
`#bd-start-session` — sharing `.picker-select` / `.picker-hint` /
`.picker-error` atoms with the Study picker rather than the full
`.session-start-picker` block originally proposed. The `ttyd` transport
option was removed by ADR-0008 before this spec was synced.)

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
`liveAgentConsole('body-double')` — a terminal (xterm.js, or the ghostty
canvas renderer under `--dev`) for `pty`, and the ACP chat surface for
`acp`. The console SHALL exist in the DOM only while the Body Double view is
current (`x-if` on nav, not `x-show`), so a hidden mount can never shadow
the Study console's selectors. (ADR-0004; the interim "unmount
`terminalPanel()`, don't delete it" state was later superseded by ADR-0008,
which retired ttyd — and `terminalPanel()`, `_mountLegacyIframe()` and the
`/terminal/` iframe with it.)

#### Scenario: PTY session started from Body Double
- **WHEN** a Body Double session starts on the `pty` transport
- **THEN** a terminal mounts in the Body Double terminal pane with a
  non-zero bounding box and connects to the returned `ws_url`

#### Scenario: The console is absent outside the Body Double view
- **WHEN** any other view is current
- **THEN** no Body Double console element exists in the DOM, so global
  terminal selectors (e.g. `.xterm-mount`) cannot silently address a hidden
  Body Double mount

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
