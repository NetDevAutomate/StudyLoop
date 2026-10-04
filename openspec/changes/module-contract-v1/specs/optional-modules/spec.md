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
The probe argv is `<bin> --version` unless core's per-tool table names another — as it does for
kubectl, which has no `--version` flag: `kubectl version --client --output=json`. An installed tool
whose version output cannot be parsed is reported as a warning ("version unknown"), never as a pass
or a failure.
`capabilities` SHALL be drawn from `terminal`, `setup`, `check`, `cleanup`; a deck phase whose
capability is not declared SHALL fail conformance (MC006), and a declared `setup`, `check` or
`cleanup` that no deck uses SHALL fail MC016. `terminal` names the learner's session itself and is
always in use: declaring it never fails MC016.

#### Scenario: an undeclared capability is caught
- **GIVEN** a deck task carrying `setupCommand` and a manifest whose `capabilities` omit `setup`
- **WHEN** `module check` runs
- **THEN** it fails (rule MC006) naming the task and the missing capability

#### Scenario: doctor reports only installed modules' prerequisites
- **GIVEN** no module is installed
- **WHEN** `studyloop doctor` runs
- **THEN** no module prerequisite probe runs and no cluster or context is created or switched

### Requirement: `studyloop module check` applies conformance rules MC001–MC016 with stable ids
`module check <path>` SHALL evaluate every rule in `proposal.md` §6, report each failure with its
rule id, file and line (line `None` when the fault is file-level), support `--json`, and exit
non-zero on any failure. When one fault could satisfy several rules the most specific wins: a bad
`contract` is MC002 and a bad `prerequisites[].id` is MC005, never MC001; a deck that `PracticeDeck`
rejects (missing field, malformed or duplicate id, unknown field) is MC004; MC010 fires only for a
`solution` without a `scaffolding` level. MC009 SHALL run the secret detector's keyword detector
with its heuristic filters disabled, so a fixture secret the commit hook ignores is still caught.
MC011's required brief headings are the `##` headings `proposal.md` §5.1 lists. Every rule SHALL have a
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
`studyloop module add <path>` SHALL first copy the module into a private staging area (regular
files only — a symlink, hard link or special file anywhere in the tree is refused by name, never
skipped), run `module check` on the staged copy and refuse on any finding, digest the staged copy,
and publish it atomically as an immutable snapshot keyed by that digest (an existing snapshot at
that digest is re-digested and refused on mismatch); and record `id`, `version`, digest and,
when the path is a git checkout, the remote URL and HEAD sha read locally with no fetch, into
`modules.lock.json`. `module add` of an id that is already installed SHALL replace its lock entry
and remove the orphaned snapshot; the lockfile records the new digest. `module list` and
`module remove` SHALL operate on the lockfile only. No
network access SHALL occur in v1.

#### Scenario: an unconforming module is not installed
- **GIVEN** a module directory that fails one conformance rule
- **WHEN** `module add` runs
- **THEN** nothing is written to the snapshot store or the lockfile and the finding is shown

#### Scenario: git provenance is recorded without a fetch
- **GIVEN** a conforming module in a git checkout with a remote
- **WHEN** `module add` runs offline
- **THEN** the lockfile entry carries the remote URL and HEAD sha and the snapshot digest
