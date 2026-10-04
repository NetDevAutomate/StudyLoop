## ADDED Requirements

### Requirement: Drill phases run as argv without a shell, in a clean environment, inside an immutable snapshot
Each drill phase (`setup`, `check`, `cleanup`) SHALL name one executable under the module
snapshot's `scripts/` plus literal arguments; the runner SHALL execute it with `shell=False` from
the snapshot, in an environment built from scratch (a scratch `HOME`, a per-attempt working
directory, `STUDYLOOP_DRILL_ID` from the deck and task ids, the target's injected variables) and
never the caller's inherited environment. A phase whose command contains shell tokens, resolves
outside `scripts/`, or follows a symlink out of the snapshot SHALL be refused before any process
starts.

#### Scenario: a shell token is refused
- **GIVEN** a check phase whose argv contains `;`, `|`, `&&` or `$(`
- **WHEN** `studyloop drill check <module>/<deck>/<task>` runs
- **THEN** it refuses before spawning and names the token

#### Scenario: the environment is not inherited
- **GIVEN** the caller's environment carries `STUDYLOOP_SECRET_PROBE=1`
- **WHEN** a check phase runs a script that prints its environment
- **THEN** the variable is absent from the captured output

### Requirement: Every phase is consented to on its exact argv and script digest, each time
Before each phase the runner SHALL show the phase, target, exact argv and the content digest of
the script, require an explicit confirmation, and re-check the digest at spawn; a change between
confirmation and spawn SHALL abort. Setup and cleanup SHALL each be consented to separately from
check. The web surface SHALL expose no `--yes` equivalent in v1.

#### Scenario: a modified script does not run
- **GIVEN** consent given on digest `A`
- **WHEN** the script's content changes before spawn
- **THEN** the phase aborts and reports the digest mismatch

### Requirement: Exit classes, per-phase timeouts and streamed caps are the runner's, not the module's
Exit `0` SHALL mean passed; `1` SHALL mean "failed, task not complete"; `≥ 2` SHALL mean the
check could not run. `timeoutSeconds` SHALL bound each phase separately and a timeout SHALL be an
error, never a fail. Output SHALL be streamed with a byte cap and a line cap enforced while the
process runs, redacted by the existing secret detector, and kept only as transient evidence.

#### Scenario: output is capped while streaming
- **GIVEN** a check script that prints 10 MiB
- **WHEN** it runs
- **THEN** the captured output stops at the cap, the process is terminated, and the result is an error naming the cap

### Requirement: A passing check records no learner observation
A drill check result SHALL be recorded as a transient `practice_check` event only; it SHALL NOT
write a `confident` or `struggling` observation into learner history. Mastery still comes from
teach-back.

#### Scenario: no observation after a passing check
- **GIVEN** an empty learner history
- **WHEN** a check phase exits `0`
- **THEN** `study_progress` and the observation store are unchanged and one `practice_check` event exists

### Requirement: `studyloop drill` is the MVP's only execution surface
`studyloop drill <setup|check|cleanup> <module>/<deck>/<task>` SHALL be the only way a module phase
is executed in v1; the web UI SHALL list and start drills but SHALL NOT execute a phase. The drill
SHALL run inside the learner's one claimed session.

#### Scenario: the scaffold's offline drill runs end to end
- **GIVEN** the module `studyloop module new` produces, installed with `module add`
- **WHEN** `drill setup`, `drill check` and `drill cleanup` run with consent
- **THEN** each exits `0` without Docker, kind or network
