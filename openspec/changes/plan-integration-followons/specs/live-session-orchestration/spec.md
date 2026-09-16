## MODIFIED Requirements

### Requirement: Session purpose
A web session start (`POST /api/session/start`) SHALL carry a *purpose* —
`focus` (the default) or `planning` — validated structurally by
`StartSessionRequest` (`purpose: Literal["focus", "planning"] = "focus"`), so
any other value is refused with `422` before the handler runs. A `focus` start
SHALL be indistinguishable from a start that names no purpose: the same
persona, the same `persona_hash`, the same session-state `mode`. A `planning`
start SHALL launch the study-plan architect: the persona is the
`plan-architect` mode carrying a `## Planning brief` section (the interview
questions, the learner's history evidence, the existing plans and — only when
the request carried one — the learner's brain dump), and the session's topic
is the learner's subject when one was supplied, else the fixed label
`Study plan` — the same label `studyloop plan architect` pins. The start
SHALL NOT create a plan and SHALL NOT store a plan id anywhere; the architect
creates plans through the plan tools during the session.

The request MAY carry `brain_dump: str | None` (default `None`, `max_length`
`BRAIN_DUMP_MAX_CHARS` = 4000, published by `_models`), the learner's own free
text for the architect. On a `planning` start a non-blank dump SHALL be
rendered by the brief renderer as a fourth section, `### Learner's brain dump`,
after `### Existing plans`, introduced as the learner's words — evidence, not
instructions — with every line of the dump emitted as a Markdown blockquote
line (`> …`, a blank line as a bare `>`) after in-line whitespace
normalisation, and a line that begins with a block marker (`#`, `-`, `*`,
`+`, `>`, `` ` ``, `~`) backslash-escaped, so a dump line can never open a
heading, list item or fence of its own inside the persona (review-3 F4
containment). A blank or absent dump SHALL render no section, so a brief
without one is byte-identical to the pre-change brief. The dump SHALL NOT be
folded into `topic`, SHALL NOT be written to the session state or exposed by
`GET /api/session/state`, and SHALL travel once, inside the persona (on `acp`
the `201` echoes the persona as `persona_text` by design, and the dump appears
in that field only). On a `focus` start the dump SHALL be ignored: the persona
and state are byte-identical to a start without it. A dump longer than
`BRAIN_DUMP_MAX_CHARS` SHALL be refused with `422` before the handler runs,
holding no slot.

The only planning fact the live-session state carries is `purpose`, written on
every start (never inherited through the state file's read-merge-write), and
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
- **WHEN** `POST /api/session/start` is made with `purpose: "planning"` and `topic: ""`
- **THEN** the persona the agent receives has `**Mode:** plan-architect`, a `## Planning brief` section containing the interview's first prompt and the existing plans, `**Topic:** Study plan`, and no `Resuming Previous Session`

#### Scenario: Brain dump travels once, contained, and is never persisted
- **WHEN** a planning start carries `brain_dump` with several paragraphs, one of which begins `## Ignore previous instructions`
- **THEN** the persona contains exactly one `### Learner's brain dump` section after `### Existing plans`, every dump line rendered as `> …` with the `##` line escaped (`> \## …`), and `**Topic:** Study plan`
- **AND** the session state file and `GET /api/session/state` carry neither a `brain_dump` key nor the text, and on `acp` the text appears in the `201` body's `persona_text` only

#### Scenario: Over-limit brain dump is refused structurally
- **WHEN** a planning start carries a `brain_dump` of `BRAIN_DUMP_MAX_CHARS + 1` characters
- **THEN** the response is `422` naming `brain_dump`, no slot is held and no agent is launched; a dump of exactly `BRAIN_DUMP_MAX_CHARS` is accepted

#### Scenario: Brain dump on a focus start is ignored
- **WHEN** a focus start carries `brain_dump`
- **THEN** the persona is byte-identical to `build_canonical_persona("focus", topic, energy)` and the state carries no trace of the text

#### Scenario: Planning start keeps a supplied subject
- **WHEN** a planning start carries `topic: "Spark"`
- **THEN** the persona carries `**Topic:** Spark` and the state's `topic` is `Spark`

#### Scenario: Default purpose is focus and unchanged
- **WHEN** a start names no purpose
- **THEN** the persona equals `build_canonical_persona("focus", topic, energy)`, the state's `mode` is `focus` and its `purpose` is `focus`

#### Scenario: Unknown purpose is refused structurally
- **WHEN** a start carries `purpose: "revision"`
- **THEN** the response is `422` and no slot is held

#### Scenario: Planning start creates no plan and stores no plan id
- **WHEN** a planning start succeeds
- **THEN** the plans directory is unchanged, the `201` body has no `plan_id`, and the state carries `purpose == "planning"` and no `plan_id`

#### Scenario: Purpose is persisted for the reconnect label
- **WHEN** a planning start succeeds
- **THEN** the state file's `purpose` is `planning` and `GET /api/session/state` reports it with the fixed topic `Study plan`

#### Scenario: A CLI-started architect is labelled from its persisted mode
- **WHEN** the state file carries `mode == "plan-architect"` and no `purpose`
- **THEN** `GET /api/session/state` reports `purpose == "planning"`; an explicit persisted `purpose` wins over the mode; `mode == "focus"` with topic `Study plan` reports `focus`

#### Scenario: Brief failure releases the session claim
- **WHEN** the planning brief cannot be built on either transport
- **THEN** the response is a structured `500` with `error`, `purpose` and `repair`, and the active slot is free

#### Scenario: PTY and ACP resolve the mode through one resolver
- **WHEN** a planning start is made over `pty` and over `acp`
- **THEN** both personas carry the same mode and brief section and neither route names a persona mode as a literal
