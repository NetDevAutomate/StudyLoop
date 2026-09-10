## ADDED Requirements

### Requirement: New checkers cover ontology freshness, concept-sidecar consistency, and MCP registration
The `harness` category SHALL gain checkers verifying: the tier-1 ontology's
build state is fresh relative to the sessions table; the concept sidecar's
schema fingerprint and FTS-consistency digest match; and each supported
harness's MCP registration (Claude Code `~/.claude.json`, Kiro
`~/.kiro/settings/mcp.json`, Codex `~/.codex/config.toml`) is present. Each
checker SHALL produce a `CheckResult` using the existing category/status/
fix-metadata contract.

#### Scenario: Ontology is stale relative to captured sessions
- **GIVEN** sessions have been captured since the last ontology build
- **WHEN** `studyloop doctor --category harness` runs
- **THEN** the ontology-freshness checker returns a `warn` result naming
  the staleness

#### Scenario: MCP registration is missing for a detected harness
- **GIVEN** Claude Code is detected but `session-db-mcp` is absent from
  `~/.claude.json`
- **WHEN** `studyloop doctor --category harness` runs
- **THEN** the MCP-registration checker returns a result naming Claude
  Code and the missing registration

#### Scenario: Concept sidecar has drifted from its pinned fingerprint
- **GIVEN** the installed concept sidecar's schema fingerprint does not
  match the fingerprint `context_concept_schema` records
- **WHEN** `studyloop doctor --category harness` runs
- **THEN** the sidecar-consistency checker returns a result naming the
  fingerprint mismatch

### Requirement: Ontology, concept-sidecar, and MCP-registration checks are classified report-only, never fatal
None of the checkers added by this change SHALL cause
`_compute_exit_code()` to return exit 2, and none SHALL be required for a
representative end-to-end workflow test to pass. Their `CheckResult`
SHALL be `warn` or `info` only, and documentation SHALL state explicitly
which harness-category checks are fatal versus report-only.

#### Scenario: Missing MCP registration does not fail doctor
- **GIVEN** no harness has MCP registration configured
- **WHEN** `studyloop doctor` runs
- **THEN** the exit code is 0 or 1, never 2, solely due to the
  registration checks
- **AND** a representative workflow test that never registers MCP still
  passes

#### Scenario: Documentation states the fatal/report-only split
- **GIVEN** a contributor reads the harness-category checker
  documentation
- **WHEN** they look for which checks can fail a release gate
- **THEN** the ontology, sidecar, and MCP-registration checks are
  explicitly listed as report-only, distinct from any fatal `core` check
