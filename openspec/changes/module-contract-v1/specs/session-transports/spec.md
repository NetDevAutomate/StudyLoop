## ADDED Requirements

### Requirement: A drill check result is delivered to the live mentor as one bounded, labelled envelope
When a drill phase completes inside a claimed session, core SHALL deliver one typed
`PracticeCheckEnvelope` to the session's mentor transport: drill identity (module id, module
digest, deck id, task id), phase, exit class, bounded redacted output, and the fact that the
learner triggered it. The envelope SHALL be size-bounded, labelled as data (never as an
instruction), and delivered on both the PTY and the ACP transports per ADR 0012.

#### Scenario: delivery on PTY
- **GIVEN** a PTY-transport session with a fake mentor
- **WHEN** a check exits `1`
- **THEN** the fake mentor receives exactly one envelope carrying the identity and exit class, framed as the ADR specifies

#### Scenario: delivery on ACP does not interleave with a learner turn
- **GIVEN** an ACP-transport session with a learner prompt turn in flight
- **WHEN** a check completes
- **THEN** the envelope is delivered after that turn completes and never inside it

### Requirement: Delivery failure is learner-visible
If the envelope cannot be delivered (transport closed, size exceeded, serialisation refused),
core SHALL surface the failure to the learner in the session and SHALL NOT silently drop it.

#### Scenario: a closed transport is reported
- **GIVEN** a session whose transport has closed
- **WHEN** a check completes
- **THEN** the learner sees a message naming the undelivered result and the reason
