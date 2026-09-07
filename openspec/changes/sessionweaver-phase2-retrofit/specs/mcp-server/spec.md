## ADDED Requirements

### Requirement: session-db-mcp registers memory_recall implementing the frozen RecallReport contract
`agent_session_tools.mcp_server` SHALL register a `memory_recall` tool
returning the frozen `RecallReport` shape (`concepts[]` with citations and
provenance, deduplicated `sessions[]` with a ≤300-character preview, and
the query `plan`), matching `docs/data/recall-contract.json` byte for byte.
`memory_recall` SHALL NOT execute any query against
`message_embeddings` or call `semantic_search.hybrid_search`, and this
SHALL be verified behaviourally, not only by static import inspection.

#### Scenario: Recall returns concepts before sessions
- **GIVEN** a database with both matching concepts and matching plain
  sessions for a question
- **WHEN** `memory_recall` is called
- **THEN** the response's `concepts[]` are ranked ahead of `sessions[]`
- **AND** any session already cited by a returned concept is excluded from
  `sessions[]`

#### Scenario: No embedding query runs during recall
- **GIVEN** a database with `message_embeddings` rows present
- **WHEN** `memory_recall` executes a query
- **THEN** no SQL statement issued during that call references
  `message_embeddings` or invokes `semantic_search.hybrid_search`

### Requirement: session-db-mcp registers memory_winddown with field-level validation
`agent_session_tools.mcp_server` SHALL register a `memory_winddown` tool
that validates its document argument, and on failure returns field-level
errors as the MCP tool error payload rather than raising an unhandled
exception or writing a partial concept.

#### Scenario: Wind-down tool call with an invalid document
- **GIVEN** a wind-down document missing a required citation
- **WHEN** `memory_winddown` is called with that document
- **THEN** the tool call returns an error result naming the missing field
- **AND** no concept or event row is written

### Requirement: session_search's planner falls back from AND to OR without changing the preview contract
`session_search` SHALL apply an AND→OR query planner: a multi-term query
first attempts an FTS AND match, and only when that returns no rows does
it retry as an OR match. The existing ≤300-character preview contract on
each returned row SHALL be unchanged by this planner.

#### Scenario: Multi-word query with no exact AND match
- **GIVEN** a multi-word query whose terms never co-occur in any single
  indexed row
- **WHEN** `session_search` runs that query
- **THEN** the AND attempt returns no rows, the OR attempt returns at
  least one row, and the OR results are what the caller receives

#### Scenario: Preview contract is unchanged
- **GIVEN** any row returned by `session_search`, under either the AND or
  the OR branch
- **WHEN** the row is rendered
- **THEN** its preview text is truncated to the existing ≤300-character
  contract exactly as before the planner was added

### Requirement: Every MCP tool call returns one structured diagnostic on a missing or invalid scope
Both `studyloop-mcp` and `session-db-mcp` SHALL catch `ScopeError` at every
tool-call boundary and return one structured diagnostic shape as the tool
error payload, never an unhandled exception or bare traceback.
`session-db-mcp`'s `open_context()` on a database that does not exist yet
SHALL return this same diagnostic shape rather than a distinct
file-not-found error.

#### Scenario: A scope-dependent tool is called with no classified scope
- **GIVEN** a fresh installation with no project-root or default scope
  configured
- **WHEN** any scope-dependent tool on either MCP server is called
- **THEN** the call returns the structured scope diagnostic as its error
  result
- **AND** the underlying process does not crash or print a traceback

#### Scenario: session-db-mcp opens a missing database
- **GIVEN** no database file exists yet at the resolved path
- **WHEN** `open_context()` is invoked by any tool
- **THEN** the same structured diagnostic shape is returned
- **AND** no distinct "file not found" error shape leaks to the caller
