## ADDED Requirements

### Requirement: Live agent consoles are addressed by origin, never broadcast
`liveAgentConsole(origin)` SHALL accept an origin identifier and SHALL ignore
`study-session-start` / `study-session-stop` window events whose
`detail.origin` (defaulting to `'study'` when absent) does not match its own.
Every dispatcher of those events SHALL set `origin`. Alpine initialises
`x-data` on elements hidden by `x-show`, so multiple console instances are
live simultaneously — visibility is not liveness, and an unaddressed broadcast
would mount a second xterm and open a second WebSocket to the same PTY
session. (ADR-0002)

#### Scenario: Body Double session starts while the study console exists
- **WHEN** a `study-session-start` event with `origin: 'body-double'` is
  dispatched and both consoles are initialised
- **THEN** only the `body-double` console leaves `terminalMode: null`, and
  exactly one WebSocket is constructed

#### Scenario: Study session starts while the Body Double console exists
- **WHEN** a `study-session-start` event with `origin: 'study'` is dispatched
- **THEN** the Body Double console remains idle (`terminalMode: null`) and
  opens no WebSocket

#### Scenario: Stop is likewise addressed
- **WHEN** a `study-session-stop` event carrying `origin: 'study'` is
  dispatched while a Body Double session is live
- **THEN** the Body Double console does not tear down its terminal or socket

### Requirement: The Study Session picker has no session-type selector
The study-session picker SHALL NOT render a session-type control, and the
frontend SHALL NOT carry a `sessionType` state field or a `sessionType` key in
the `study-session-start` event detail. Session mode is determined by which
view the learner is in, not by a dropdown value. `GET /api/session/options`
and the `list_session_options` MCP tool SHALL continue to publish a
`session_types` key (contract shape asserted by
`test_mcp_session_parity.py`) containing the single `study` entry.

Rationale: the former `body_double` option was written in three places and
read in none — `StartSessionRequest` has no such field, so selecting it
changed nothing and left the learner on the Study Session view. Body Double is
now a first-class view with its own picker (capability `body-double-session`).

#### Scenario: Rendering the study-session picker
- **WHEN** the study-session picker is rendered with no session active
- **THEN** no session-type `<select>` is present, and `sessionType` appears
  nowhere in `index.html` or `components.js`

#### Scenario: MCP and web option payload shape
- **WHEN** `GET /api/session/options` or the `list_session_options` MCP tool
  is called
- **THEN** the response still contains a `session_types` key, and its only
  entry is `{"label": "Study Session", "value": "study", ...}`

## MODIFIED Requirements

### Requirement: Starting a 4th topic requires parking one first
When `GET /api/backlog` reports `active_count >= max_active` and the learner
starts a **study** session on a topic NOT in the active set, the start SHALL
be intercepted by an in-page `.park-first-overlay` (never a native dialog)
listing the active topics; choosing one calls `POST /api/backlog/demote`
(which makes the row the oldest pending entry — re-parking the same
question is an INSERT OR IGNORE no-op and would not free the slot) and then
proceeds with the start. Escape or "Keep all" cancels without starting.

Body Double starts are exempt: they SHALL NOT query `GET /api/backlog` and
SHALL NOT render the overlay, because body doubling is not a new study thread
(ADR-0003).

#### Scenario: Fourth topic blocked until one is parked
- **WHEN** three topics are active and the learner starts a new, fourth
  topic from the study-session picker
- **THEN** the park-first overlay appears in-page, and the session only
  starts after one active topic is demoted to the parking lot

#### Scenario: Body Double start with three topics already active
- **WHEN** three topics are active and the learner starts a Body Double
  session
- **THEN** no `/api/backlog` request is issued and the session starts without
  the overlay
