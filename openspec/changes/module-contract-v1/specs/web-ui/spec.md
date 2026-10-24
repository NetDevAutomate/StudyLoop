## ADDED Requirements

### Requirement: One generic Labs entry lists installed modules' drills and starts them in the claimed session
The web UI SHALL show a single **Labs** entry only when `modules.lock.json` lists at least one
module; it SHALL list drills grouped by module from the installed snapshots; starting a drill
SHALL happen inside the learner's one claimed session and SHALL be cancellable.

#### Scenario: Labs is hidden with an empty lockfile
- **GIVEN** no installed module
- **WHEN** the session options are fetched
- **THEN** no Labs entry is present

#### Scenario: Labs lists drills after `module add`
- **GIVEN** one conforming module installed
- **WHEN** the session options are fetched
- **THEN** Labs is present and lists that module's decks and tasks by their ids and prompts

#### Scenario: list, start, cancel journey
- **GIVEN** the e2e hermetic world with one installed module
- **WHEN** the learner opens Labs, starts a drill and cancels it
- **THEN** the session returns to its prior state and no phase was executed

### Requirement: Labs shows the learner a task's prompt and success criteria only, and the browser executes no phase
The learner SHALL
see a task's `prompt` and `successCriteria` only — `hint`, `solution` and `mentorNotes` reach the
learner through the mentor alone. The browser SHALL NOT execute a drill phase in v1 (deferred to
v1.1 with its own consent surface).

#### Scenario: the learner never sees the solution in the UI
- **GIVEN** a task carrying `hint`, `solution` and `mentorNotes`
- **WHEN** the drill is started from Labs
- **THEN** the rendered page contains the prompt and success criteria and none of the three mentor-side fields
