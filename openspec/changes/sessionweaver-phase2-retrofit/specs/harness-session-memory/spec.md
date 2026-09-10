## ADDED Requirements

### Requirement: The canonical skill names memory_recall as the preferred concept-first path when exposed
The `studyloop-session-memory` skill SHALL name `memory_recall` as the
preferred retrieval path whenever the connected harness's MCP server
exposes it, describing it as concept-first (concepts, then deduplicated
sessions), before falling back to plain `session_search`. It SHALL NOT
claim `memory_recall` is available on a harness that has not registered
`session-db-mcp`.

#### Scenario: Harness exposes session-db-mcp
- **GIVEN** an agent has read the canonical skill
- **AND** its harness has `session-db-mcp` registered and reachable
- **WHEN** the agent needs prior-session context
- **THEN** it calls `memory_recall` before falling back to `session_search`

#### Scenario: Harness has no MCP connection
- **GIVEN** an agent has read the canonical skill
- **AND** no MCP server is reachable from its harness
- **WHEN** the agent needs prior-session context
- **THEN** it uses `session-query` per the skill's existing fallback, and the
  skill never implies `memory_recall` exists without an MCP connection

### Requirement: Wind-down is code-enforced and produces citation-bound concepts
`session-context winddown` and the `memory_winddown` MCP tool SHALL validate
a wind-down document, assign concept and event identities, bind each
concept's citations to captured evidence, and write both the database and
the Markdown projection in one operation. A wind-down document that fails
validation SHALL return field-level errors and SHALL NOT write any concept,
citation, or projection change. StudyLoop SHALL NOT accept a hand-written
Markdown concept file as an alternative to this path.

#### Scenario: Valid wind-down document
- **GIVEN** a wind-down document naming one or more concepts with exact
  quoted citations into the current session's captured evidence
- **WHEN** `memory_winddown` is called with that document
- **THEN** each concept is written as a citation-bound `context_assertion`
  with a `proposed` lifecycle event
- **AND** the Markdown projection reflects the new concept on its next
  rebuild

#### Scenario: Malformed wind-down document
- **GIVEN** a wind-down document whose citation quote does not appear at
  the stated offset in the captured evidence
- **WHEN** `memory_winddown` is called with that document
- **THEN** the call returns a field-level error naming the failing citation
- **AND** no concept, event, or projection file is written

### Requirement: Legacy-imported concepts are visibly labelled and cannot be promoted without a bind
Concepts imported from the legacy OKF Markdown store SHALL carry
`binding_state = legacy-unbound` and an explicit `legacy-unbound` label
wherever they appear in recall or the projection. A legacy-unbound concept
SHALL NOT be accepted (`legacy_unbound_requires_bind`) until a bind
operation creates a normal, citation-bound `context_assertion` for it. An
unparseable legacy file SHALL be reported, never silently dropped.

#### Scenario: Legacy-unbound concept appears in recall
- **GIVEN** a concept imported from the legacy OKF store with no bind
  applied
- **WHEN** it is returned by a recall surface
- **THEN** its `legacy-unbound` label and session-level provenance are
  present and distinguishable from a bound concept's citations

#### Scenario: Accepting a legacy-unbound concept without a bind
- **GIVEN** a legacy-unbound concept
- **WHEN** an `accepted` transition is attempted on it directly
- **THEN** the transition is refused with a `legacy_unbound_requires_bind`
  error
- **AND** the concept's standing is unchanged

### Requirement: Retiring a concept or forgetting a session removes it from recall and the projection
Retiring a concept, or forgetting the whole session that is its source,
SHALL remove that concept from recall results and from the next Markdown
projection rebuild, while leaving sibling concepts and the source session's
other data untouched.

#### Scenario: Retire one concept among several from the same session
- **GIVEN** a session that produced three concepts via wind-down
- **WHEN** one of those concepts is retired
- **THEN** recall no longer returns the retired concept
- **AND** the other two concepts and the source session remain unchanged

#### Scenario: Forget the source session
- **GIVEN** a bound concept whose source session is later forgotten
- **WHEN** the forgetting policy processes that session
- **THEN** the concept is excluded from recall and from the projection
- **AND** the exclusion is scope-aware, matching the session's own
  forgetting state

### Requirement: Concept trust language distinguishes model-proposed content from execution-confirmed content
Every concept surfaced to a learner or another agent SHALL label its
authorship as `model-proposed` (unreviewed) rather than
`machine-confirmed`, unless a bound concept's citation is itself the
confirming evidence — in which case the citation binding, not the
concept's authorship, is what is labelled confirmed.

#### Scenario: A freshly wound-down concept is surfaced
- **GIVEN** a concept just written by `memory_winddown`
- **WHEN** it is returned by any recall surface or projection
- **THEN** its trust label reads `model-proposed`, never
  `machine-confirmed`

#### Scenario: A bound concept's citation is inspected
- **GIVEN** a bound concept with an exact citation into captured evidence
- **WHEN** the citation is inspected
- **THEN** the citation is labelled `citation_binding: machine-confirmed`
- **AND** the concept's own authorship label remains `model-proposed`
