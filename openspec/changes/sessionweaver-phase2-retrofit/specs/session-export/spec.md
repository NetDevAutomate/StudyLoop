## ADDED Requirements

### Requirement: Every export run triggers an incremental ontology refresh after committing captured sessions
`export_sessions._run_export` SHALL call a named, separately identifiable
ontology-refresh hook after its per-source export loop commits captured
session and message rows. The refresh SHALL be scoped to the sessions this
run touched (or the whole corpus on a full run) and SHALL run after, never
inside, the transaction that commits captured data.

#### Scenario: Incremental export refreshes only touched sessions
- **GIVEN** an incremental `session-export` run that adds or updates a
  subset of sessions
- **WHEN** the run's per-source export loop commits
- **THEN** the ontology refresh hook is invoked for that run
- **AND** the refresh is scoped to the sessions added or updated in this
  run

#### Scenario: A full export run refreshes the whole corpus
- **GIVEN** a `session-export --full` run
- **WHEN** the run's per-source export loop commits
- **THEN** the ontology refresh hook is invoked for the entire corpus,
  not only a per-run delta

### Requirement: An ontology-refresh failure never rolls back captured sessions and is recoverable
A failure raised by the ontology-refresh hook SHALL NOT roll back or
otherwise affect the session and message rows already committed by this
export run. The failure SHALL surface as a structured warning on a named,
stable channel/field rather than a bare exception or silent drop, and a
subsequent `session-maint ontology-rebuild` SHALL converge the ontology to
the same state a failure-free run would have reached.

#### Scenario: Ontology refresh raises after a successful capture
- **GIVEN** an export run whose session/message capture commits
  successfully
- **WHEN** the ontology-refresh hook then raises
- **THEN** the committed session and message rows are unchanged
- **AND** a structured warning is surfaced on the named channel/field
- **AND** the process exits reporting the export's capture results, not a
  fatal error

#### Scenario: Maintenance sweep recovers from a refresh failure
- **GIVEN** an export run that left the ontology stale after a refresh
  failure
- **WHEN** `session-maint ontology-rebuild` is run afterward
- **THEN** the ontology reaches full coverage for the corpus
- **AND** its build-state record reports a healthy status
