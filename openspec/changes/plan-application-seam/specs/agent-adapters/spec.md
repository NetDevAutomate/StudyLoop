## ADDED Requirements

### Requirement: Persona resolution by purpose
`studyloop.agent_launcher` SHALL expose one resolver,
`persona_mode_for(purpose: str) -> str`, mapping a session purpose to the
persona mode that serves it: `planning` → `plan-architect`, anything else →
`focus`. Every web start path (PTY and ACP alike) SHALL obtain its mode
through this resolver; no route SHALL name a persona mode as a literal
(`rg 'build_canonical_persona\("focus"' packages/studyloop/src/studyloop/web` → 0).
`build_canonical_persona(mode, topic, energy, *, previous_notes=None,
brief=None)` SHALL accept the planning brief through the `brief` keyword and
render it as its own `## Planning brief` section — introduced as data about
the learner, not instructions — placed with the other context sections ahead
of the persona body. The brief SHALL NOT be carried through `previous_notes`
(which renders `Resuming Previous Session`, the framing for a resumed study
session) and SHALL NOT be folded into `topic`. With `brief=None` the output
SHALL be byte-identical to the pre-`brief` output, so no existing session's
`persona_hash` changes.

#### Scenario: Resolver maps the two purposes
- **WHEN** `persona_mode_for("planning")` and `persona_mode_for("focus")` are called
- **THEN** they return `plan-architect` and `focus` respectively

#### Scenario: Brief renders as its own section
- **WHEN** `build_canonical_persona("plan-architect", "Study plan", 5, brief="- item")` is called
- **THEN** the result contains `## Planning brief`, contains `- item`, contains
  the plan-architect persona body, and does not contain `Resuming Previous Session`

#### Scenario: No brief, no section
- **WHEN** `build_canonical_persona("focus", "Python", 5)` is called
- **THEN** the result contains no `## Planning brief` section and is
  byte-identical to the output before the `brief` keyword existed

### Requirement: Architect persona prefers the MCP plan tools
The canonical study-plan-architect persona (`agents/shared/personas/plan-architect.md`,
the body every harness projection carries verbatim after its own header) SHALL
carry one tooling section that introduces the plan tools over MCP **before** the
CLI fallback. The MCP subsection SHALL name the nine plan lifecycle tools (the
plan-application-seam design, §4) — `list_study_plans`, `get_study_plan`, `get_planning_interview`,
`create_study_plan`, `update_study_plan`, `set_study_plan_status`,
`set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan` — in
lifecycle order (discover → interview → create as `draft` → revise → activate →
tick → evaluate → delete), and SHALL state the three guards the plan
application layer enforces: activation only once `readiness` reports ready
(never creating as `active` to skip the gate), `evaluate_study_plan` with
`record=False` as a preview that writes nothing versus `record=True` to
persist a checkpoint, and `delete_study_plan` only with `confirmed=True` after
the learner has explicitly confirmed. The CLI fallback subsection SHALL give
the `studyloop plan` command for every lifecycle step that has one
(`interview`, `list`, `show`, `new`, `status`, `milestone`, `evaluate`,
`record`) and SHALL say plainly which steps the CLI cannot perform (revising an
existing plan's fields; deletion) rather than inventing a command. A tool
missing from the connected server's inventory SHALL route to that step's CLI
fallback where one exists; for the two steps with no CLI command (revising an
existing plan's fields, deletion) the persona SHALL have the architect say so
to the learner and stop, never improvise a shell edit of the document. The
interview protocol (one question per turn) SHALL be unchanged,
and the `focus` persona SHALL be byte-identical before and after this change.

#### Scenario: Planning persona names the nine tools before the fallback
- **WHEN** `build_canonical_persona(persona_mode_for("planning"), "Study plan", 5, brief="- item")` is rendered
- **THEN** the result names all nine lifecycle tool names inside the MCP
  subsection, the MCP subsection precedes the `CLI fallback` subsection and
  closes before it, no `studyloop plan` recipe appears inside the MCP
  subsection, and the `CLI fallback` subsection names `studyloop plan
  interview`, `list`, `show`, `new`, `status`, `milestone`, `evaluate` and
  `record` and no `studyloop plan delete`

#### Scenario: Focus persona untouched
- **WHEN** `build_canonical_persona("focus", "Python", 5)` is rendered with the
  three session paths fixed
- **THEN** its SHA-256 digest equals the digest recorded at `205819c7`

#### Scenario: Projections and manifest regenerate byte-identically
- **WHEN** `agents/claude/study-plan-architect.md`, `agents/opencode/study-plan-architect.md`
  and `agents/kiro/study-plan-architect/persona.md` are read
- **THEN** each body after its harness header equals the canonical persona
  byte-for-byte, and `agents/manifest.json` carries the generator's own hash
  for every architect projection it tracks
