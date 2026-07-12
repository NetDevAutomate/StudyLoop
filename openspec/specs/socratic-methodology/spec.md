## Purpose

Deliver a consistent, AuDHD-aware Socratic mentoring persona to every
supported agent CLI regardless of transport, so the same teaching
methodology (energy-adaptive, break-science-aware, teach-back scoring)
governs a session whether it's PTY or ACP.

## Requirements

### Requirement: One canonical persona builder feeds every agent
The system SHALL generate persona text via
`build_canonical_persona()` (`agent_launcher.py:299`) parameterized by
topic and energy level, drawing on shared methodology docs under
`agents/shared/` (currently `agents/shared/personas/study.md` and
`co-study.md`) as the single source of truth referenced by all
per-agent definitions.

#### Scenario: Same topic started with two different agents
- **WHEN** a session is started with the same topic and energy level, once
  with Kiro and once with Claude Code
- **THEN** both receive persona text derived from the same
  `build_canonical_persona()` call and the same shared methodology
  content, differing only in the transport-specific delivery mechanism

### Requirement: Persona delivery mechanism is transport-specific
The system SHALL deliver persona text to a PTY-transported agent via a
temp file referenced in the launch command's argv (never sent as a
runtime message), and to an ACP-transported agent via the first
`session/prompt` sent immediately after the session WebSocket opens
(added `2026-05-28`, commit `bfe9210`) — because ACP agents have no
argv/env hook for system context and the prompt channel is the only
injection point.

#### Scenario: ACP agent persona turn is hidden from the user
- **WHEN** the invisible persona `session/prompt` triggers `agent_chunk`,
  `tool_call`, `plan`, or `request_permission` frames on the wire
- **THEN** none of them render in the chat UI (dropped or auto-allowed)
  until that turn's `turn_end`, at which point the setup banner clears and
  the first user-visible turn begins

### Requirement: Persona effectiveness is trackable per version
The system SHALL compute a SHA-256[:16] `persona_hash` at session start and
store it on `study_sessions` (migration v20), alongside structured
`win_count`/`struggle_count` extracted at session end, so
`get_persona_effectiveness()` can report win rate per persona version via
`studyloop session effectiveness`.

#### Scenario: Persona text changes between two sessions
- **WHEN** the shared persona content changes and a new session starts
- **THEN** the new session records a different `persona_hash`, and
  `studyloop session effectiveness` can distinguish outcomes attributable
  to the old vs. new persona version
