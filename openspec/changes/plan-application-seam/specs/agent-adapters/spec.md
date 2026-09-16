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
