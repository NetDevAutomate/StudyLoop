## ADDED Requirements

### Requirement: Session purpose
A web session start (`POST /api/session/start`) SHALL carry a *purpose* —
`focus` (the default) or `planning` — validated structurally by
`StartSessionRequest` (`purpose: Literal["focus", "planning"] = "focus"`), so
any other value is refused with `422` before the handler runs. A `focus` start
SHALL be indistinguishable from a start that names no purpose: the same
persona, the same `persona_hash`, the same session-state `mode`. A `planning`
start SHALL launch the study-plan architect: the persona is the
`plan-architect` mode carrying a `## Planning brief` section (the interview
questions, the learner's history evidence and the existing plans), and the
session's topic is the learner's subject when one was supplied, else the fixed
label `Study plan` — the same label `studyloop plan architect` pins. The start
SHALL NOT create a plan and SHALL NOT store a plan id anywhere; the architect
creates plans through the plan tools during the session. The only planning
fact the live-session state carries is `purpose`, written on every start
(never inherited through the state file's read-merge-write), and
`GET /api/session/state` SHALL expose it for the reconnect label with one
precedence on every path it answers from — the live-slot overlay and the
file-only path a CLI-started session takes: an explicitly persisted
`purpose` wins; otherwise a state whose persisted `mode` is the planning
persona's (`persona_mode_for("planning")`, the mode `studyloop plan
architect` writes without a `purpose` key) reports `planning`; anything else
— a state that predates the key, or an overlay that rebuilt the payload —
reports `focus`. The topic string SHALL never determine the purpose. If the
planning brief cannot be built, the start SHALL refuse with a
structured error (`error`, `purpose`, `repair`; HTTP 500) and leave the
single-session slot free — no reservation, no live slot, no study row. Both
transports (`pty` and `acp`) SHALL follow this requirement identically.

#### Scenario: Planning start launches the architect with a brief
- **WHEN** `POST /api/session/start` is called with `{"purpose": "planning", "topic": "", ...}`
- **THEN** the response is `201`, the persona the agent receives has
  `**Mode:** plan-architect`, contains the plan-architect persona body and a
  `## Planning brief` section naming the interview questions and every existing
  plan by id and title, contains no `Resuming Previous Session` section, and
  the session topic is `Study plan`

#### Scenario: Planning start keeps a supplied subject
- **WHEN** `POST /api/session/start` is called with `{"purpose": "planning", "topic": "Spark", ...}`
- **THEN** the persona and the session state both carry the topic `Spark`

#### Scenario: Default purpose is focus and unchanged
- **WHEN** `POST /api/session/start` is called with no `purpose`
- **THEN** the persona is byte-identical to `build_canonical_persona("focus", topic, energy)`,
  the `persona_hash` is unchanged from before the purpose existed, the state's
  `mode` is `focus` and its `purpose` is `focus`

#### Scenario: Unknown purpose is refused structurally
- **WHEN** `POST /api/session/start` is called with `{"purpose": "revision", ...}`
- **THEN** the response is `422` and no session slot is held

#### Scenario: Planning start creates no plan and stores no plan id
- **WHEN** one plan exists and `POST /api/session/start` is called with `purpose: planning`
- **THEN** the set of plan ids on disk is unchanged, the `201` body has no
  `plan_id`, and the session state has no `plan_id` key

#### Scenario: Purpose is persisted for the reconnect label
- **WHEN** a `planning` session has started
- **THEN** the session state's `purpose` is `planning` and
  `GET /api/session/state` reports `purpose == "planning"` alongside the live
  session's id and topic

#### Scenario: A CLI-started architect is labelled from its persisted mode
- **WHEN** the state file was written by `studyloop plan architect` (`mode ==
  "plan-architect"`, no `purpose` key) and `GET /api/session/state` is called
- **THEN** the body reports `purpose == "planning"`; a file with `mode ==
  "focus"` and topic `Study plan` reports `focus`; a file carrying `purpose ==
  "focus"` beside `mode == "plan-architect"` reports `focus`

#### Scenario: Brief failure releases the session claim
- **WHEN** `PlanApplication.prepare_planning` raises during a `planning` start
- **THEN** the response is `500` with an `error` naming the brief and
  `purpose == "planning"`, the session state file is empty, no in-process
  session is held, no study row was created, and a following `focus` start
  succeeds with `201`

#### Scenario: PTY and ACP resolve the mode through one resolver
- **WHEN** a `planning` start is made over `transport: pty` and, separately,
  over `transport: acp`
- **THEN** each start calls `agent_launcher.persona_mode_for` exactly once
  with `planning`, each persona has `**Mode:** plan-architect` and a
  `## Planning brief` section, and each state records its own `transport`
  with `purpose == "planning"`
