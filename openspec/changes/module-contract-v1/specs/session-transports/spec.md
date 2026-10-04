## ADDED Requirements

### Requirement: A drill check result is delivered to the live mentor as one bounded, labelled envelope
When a drill phase completes, core SHALL deliver one typed `practice_check` envelope to the
session's mentor transport: drill identity (module id, module digest, deck id, task id), attempt
id, phase, exit class and code, duration, bounded redacted stdout and stderr tails, and the fact
that the learner triggered it. The envelope SHALL be rendered and bounded **by core in the web
server process** from typed fields — never from text a CLI rendered — with control bytes stripped,
the whole rendering ≤ 8 KiB, every header field bounded by construction, and the stdout tail cut
first and the stderr tail second when the bound is exceeded. It SHALL be labelled as data (never
as an instruction) and delivered on both the PTY and the ACP transports per ADR 0012.

#### Scenario: delivery on PTY
- **GIVEN** a PTY-transport session with a fake mentor that has enabled bracketed paste
- **WHEN** a check exits `1`
- **THEN** the fake mentor receives exactly one bracketed-paste block, sentinel-delimited, carrying the identity and exit class, submitted once

#### Scenario: a learner keystroke cannot land inside the block
- **GIVEN** a PTY-transport session
- **WHEN** learner input and an envelope are sent concurrently
- **THEN** the envelope's bytes are contiguous in the child's input and the learner's bytes precede or follow the whole block

#### Scenario: bracketed paste off falls back to one line
- **GIVEN** a PTY-transport session whose child never enabled DEC mode 2004
- **WHEN** an envelope is delivered
- **THEN** it arrives as exactly one printable line (output newlines escaped) followed by one CR, or the outcome is `unsupported_framing`

#### Scenario: oversize input is truncated to a valid bounded envelope
- **GIVEN** a check whose stdout is 10 MiB
- **WHEN** the envelope is rendered
- **THEN** it is ≤ 8 KiB, the header is intact, the stdout tail is marked as truncated, and delivery proceeds

#### Scenario: delivery on ACP does not interleave with a learner turn
- **GIVEN** an ACP-transport session with a learner prompt turn in flight
- **WHEN** a check completes
- **THEN** the envelope is delivered after that turn completes and never inside it; concurrent deliveries queue in order

### Requirement: Delivery reports one of six outcomes and no learner observation
Delivery SHALL return exactly one of `delivered`, `no_active_session`, `transport_closed`,
`timed_out`, `unsupported_framing`, `error`, and the surface that ran the phase SHALL show it to
the learner (`Mentor told.` / `Mentor not told: <reason>`). A closed transport SHALL be detected
from the write itself, not from a pre-flight liveness check alone. An ACP delivery SHALL be
awaited up to 120 seconds; on timeout the outcome is `timed_out`, the turn is cancelled, the
prompt serialiser is held until the agent confirms the cancellation by answering the cancelled
prompt. The wait is bounded; when the agent never confirms, the transport is marked wedged and
every later prompt fails fast with a clear error (a delivery reports `transport_closed`) rather
than overlap a turn that may still be running — the learner restarts the session. The envelope
is never retried. Prompts SHALL go to the agent in the order their callers asked,
learner input and deliveries alike. The
transient `practice_check` event SHALL record the outcome; nothing SHALL be written to learner
history.

#### Scenario: a closed transport is reported
- **GIVEN** a session whose transport has closed
- **WHEN** a check completes
- **THEN** the outcome is `transport_closed` and the learner sees a message naming the undelivered result and the reason

#### Scenario: a hung ACP turn times out once
- **GIVEN** an ACP-transport session whose fake agent never answers `session/prompt`
- **WHEN** an envelope is delivered
- **THEN** after 120 seconds the outcome is `timed_out`, exactly one envelope was sent, and a later learner prompt does not overlap the cancelled turn

### Requirement: A drill run outside the web server process reaches the mentor through an authenticated loopback hop
Because the MVP executes phases from `studyloop drill` in a separate process, core SHALL expose
one loopback-only route that accepts the **typed fields** of a check result and performs the
delivery above in the web server process. The route SHALL require a per-session capability token
minted when the web process claims the session and written to the owner-only session state file
beside the web port; SHALL bind the request to the active session and an open attempt; SHALL
deduplicate on `(attempt id, phase)`; SHALL rate-limit; and SHALL reject any request that is not
from the loopback address. The CLI SHALL read the port and token from the state file and never
render the envelope itself.

#### Scenario: no token, no delivery
- **GIVEN** a request to the route without the session's capability token
- **WHEN** it arrives
- **THEN** it is refused with 401 and nothing reaches the mentor

#### Scenario: a replayed result is delivered once
- **GIVEN** the same `(attempt id, phase)` posted twice
- **WHEN** both arrive
- **THEN** exactly one envelope is delivered and the second request is acknowledged as a duplicate

#### Scenario: no running server is learner-visible
- **GIVEN** no session state file or no web process listening
- **WHEN** `studyloop drill check` completes
- **THEN** the learner sees `Mentor not told: no_active_session` and the check result itself is still printed
