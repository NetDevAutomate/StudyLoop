# e2e-representative-journey Specification

## Purpose
TBD - created by archiving change complete-e2e-harness-and-desktop-mcp. Update Purpose after archive.
## Requirements
### Requirement: The journey test runs against a subprocess-hosted server
The e2e harness SHALL launch the StudyLoop web server as a real subprocess
whose main thread owns the asyncio event loop (via `create_app()` +
`uvicorn.run()` in a dedicated runner script, not a thread inside the
pytest process), so `PTYTransport`'s `SIGCHLD` handler installation
succeeds.

#### Scenario: Journey test starts a PTY session
- **WHEN** the representative journey test posts
  `transport: "pty"` to a subprocess-hosted server
- **THEN** `loop.add_signal_handler(SIGCHLD, ...)` succeeds because the
  subprocess's main thread owns the loop, and the session starts without
  a 500 error

### Requirement: The journey covers the full study loop, not just session start
The representative journey test SHALL exercise, in one continuous flow:
session start, real flashcard/quiz generation (Stub provider for
determinism), at least one study block, a break, flashcard/quiz review,
and session end with export assertions.

#### Scenario: Full journey run
- **WHEN** the representative journey test runs
- **THEN** it completes start → generate → study → break → review → end
  without manual intervention, and asserts that generated decks exist on
  disk and that session end recorded progress in `sessions.db`

### Requirement: Socratic steering is validated behaviorally, not by persona-text inspection
The journey SHALL include an LLM-judge assertion that scores real mentor
output from the session against "did the mentor ask guiding questions
rather than give the full answer," using a judge model distinct from the
mentor model (via the LiteLLM gateway), because static persona-text checks
cannot catch drift in actual agent behavior.

#### Scenario: Mentor gives a direct answer instead of a Socratic question
- **WHEN** the fake-agent (or a live-marker real-agent variant) response
  under test states the answer directly rather than probing
- **THEN** the LLM-judge assertion fails the journey, distinguishing this
  from a transport/plumbing failure

