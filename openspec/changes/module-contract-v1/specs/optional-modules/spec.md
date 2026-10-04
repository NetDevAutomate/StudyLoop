## ADDED Requirements

### Requirement: A module is a directory of data that core validates and never imports
A StudyLoop module SHALL be a directory holding `module.yaml` (validated by a Pydantic model
with `extra: forbid`: `id`, `contract`, `version`, `title`, `topic`, `license`, `maintainers`,
`prerequisites`, `capabilities`, `target`), drills as `PracticeDeck` JSON under `decks/`, an
optional `mentor/brief.md`, and executables under `scripts/`. Core SHALL NOT import, `exec` or
evaluate any file a module ships; module text is untrusted data. A module declaring a `contract`
core does not speak SHALL be refused.

#### Scenario: a manifest with an unknown key is refused
- **GIVEN** a `module.yaml` carrying a key the manifest model does not declare
- **WHEN** `studyloop module check <path>` runs
- **THEN** it fails with the unknown key named (rule MC001)

#### Scenario: an unsupported contract version is refused
- **GIVEN** a manifest with `contract: 99`
- **WHEN** `module check` runs
- **THEN** it fails naming the contract versions core speaks

### Requirement: Prerequisites and capabilities are declared from closed enums and enforced by core
`prerequisites` SHALL be drawn from a core-owned enum (`docker`, `kind`, `kubectl` in v1) with an
optional minimum version; the probe for each lives in core's `doctor/` and never runs module text.
`capabilities` SHALL be drawn from `terminal`, `setup`, `check`, `cleanup`; a deck phase whose
capability is not declared SHALL fail conformance.

#### Scenario: an undeclared capability is caught
- **GIVEN** a deck task carrying `setupCommand` and a manifest whose `capabilities` omit `setup`
- **WHEN** `module check` runs
- **THEN** it fails (rule MC005) naming the task and the missing capability

#### Scenario: doctor reports only installed modules' prerequisites
- **GIVEN** no module is installed
- **WHEN** `studyloop doctor` runs
- **THEN** no module prerequisite probe runs and no cluster or context is created or switched

### Requirement: `studyloop module check` applies conformance rules MC001–MC016 with stable ids
`module check <path>` SHALL evaluate every rule in `proposal.md` §6, report each failure with its
rule id, file and line, support `--json`, and exit non-zero on any failure. Every rule SHALL have a
fixture that fails it and a repaired twin that passes.

#### Scenario: the scaffold passes every rule
- **GIVEN** the output of `studyloop module new <id>`
- **WHEN** `module check` runs on it
- **THEN** it passes with zero findings

#### Scenario: each rule has a failing fixture
- **GIVEN** fixture `tests/fixtures/modules/mc0NN/`
- **WHEN** `module check` runs on it
- **THEN** exactly rule `MC0NN` is reported, and its repaired twin passes

### Requirement: Modules are installed from a local path into an immutable snapshot recorded in a lockfile
`studyloop module add <path>` SHALL run `module check` first and refuse on any finding; copy the
module into an immutable snapshot keyed by content digest; and record `id`, `version`, digest and,
when the path is a git checkout, the remote URL and HEAD sha read locally with no fetch, into
`modules.lock.json`. `module list` and `module remove` SHALL operate on the lockfile only. No
network access SHALL occur in v1.

#### Scenario: an unconforming module is not installed
- **GIVEN** a module directory that fails one conformance rule
- **WHEN** `module add` runs
- **THEN** nothing is written to the snapshot store or the lockfile and the finding is shown

#### Scenario: git provenance is recorded without a fetch
- **GIVEN** a conforming module in a git checkout with a remote
- **WHEN** `module add` runs offline
- **THEN** the lockfile entry carries the remote URL and HEAD sha and the snapshot digest
