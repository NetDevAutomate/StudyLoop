## Purpose

Resolve reviewed module versions for a later StudyLoop installer without
implicit installation, execution, trust escalation or network dependency
for ordinary studying. These proposed phase-2 requirements depend on
the module runtime; they do not describe an existing CLI or Web UI.

## ADDED Requirements

### Requirement: Registry refresh is explicit and preserves last-good state

The consumer SHALL refresh only on an explicit user operation, authenticate
the configured registry identity, fetch metadata at one full commit and
replace its versioned cache atomically after validation. Ordinary startup
and core study flows SHALL NOT contact or depend on the registry.

#### Scenario: A learner studies without installed modules or network access
- **WHEN** StudyLoop starts and opens its normal study workflow
- **THEN** no registry request is made and core study remains available

#### Scenario: Refresh fails or returns an unknown schema
- **WHEN** retrieval, identity or schema verification fails
- **THEN** the last-good cache is preserved, failure is reported and the
  freshness clock is not extended

### Requirement: Snapshot history cannot silently roll back known state

The consumer SHALL reject decreasing sequences, equal sequences with
different bytes and removal of known revocations. It SHALL bind index
and lifecycle metadata to a single verified revision, retaining repository
identity, commit, sequence, checksum and successful-fetch time.

#### Scenario: A server returns an older snapshot
- **WHEN** its sequence precedes the last accepted sequence
- **THEN** refresh refuses it without losing any known revoked identity

#### Scenario: Index and status come from different revisions
- **WHEN** a response mixes catalogue state across commits
- **THEN** it is not accepted as a resolution source

### Requirement: Resolution returns an exact eligible version or an explicit refusal

Resolution SHALL apply qualified identity, exact SemVer, supported contract,
application constraint, prerelease opt-in and lifecycle checks. Success
SHALL return the immutable receipt in design.md, without downloading or
executing module content. It SHALL NOT silently substitute another version.

#### Scenario: An active release matches all consumer constraints
- **WHEN** the learner explicitly selects its coordinate and exact version
- **THEN** resolution returns its pinned receipt and declared permissions
- **AND** performs no installation or command execution

#### Scenario: A release is incompatible, revoked, yanked or not found
- **WHEN** the learner selects that release
- **THEN** resolution returns the specific refusal without fallback

#### Scenario: Two publishers use the same manifest module ID
- **WHEN** the current installer cannot preserve distinct qualified identities
- **THEN** the conflicting installation is refused rather than overwritten

### Requirement: Offline browsing reports uncertainty and cannot authorize stale mutations

Cached browsing SHALL report its last verified fetch and stale/unavailable
state. New install/update/rollback SHALL require status verified against
the registry head within 24 hours. Previously installed modules may run
offline under existing consent if no revocation is known; this SHALL NOT
be represented as proof of current remote safety status.

#### Scenario: The registry is unavailable and cached status is stale
- **WHEN** the learner browses then requests a new installation
- **THEN** browsing remains available with stale labels
- **AND** installation is refused without changing local modules

#### Scenario: A known revoked module is encountered offline
- **WHEN** the learner tries to launch it after learning of revocation
- **THEN** launch is refused even if the cache is now stale
- **AND** learner records are preserved and no running terminal is killed

### Requirement: Installation consumes a verified receipt without inheriting execution trust

The module installer SHALL recheck receipt identity, eligibility and artifact
integrity before atomic activation. Registry review SHALL NOT bypass the
existing runtime's consent, target ownership or session-authority contracts.
Updates SHALL expose permission changes and require renewed installation
consent; command execution needs its separate existing consent path.

#### Scenario: Content changes between selection and activation
- **WHEN** downloaded bytes, receipt metadata or lifecycle no longer match
- **THEN** activation is refused and the previous installation is intact

#### Scenario: An update expands capabilities
- **WHEN** an eligible new version declares additional permissions
- **THEN** the difference is shown and fresh consent is required
- **AND** no command or setup script runs as part of discovery or approval

#### Scenario: An explicit rollback targets a withdrawn version
- **WHEN** that version is yanked or revoked
- **THEN** rollback is refused without rewinding learner data

### Requirement: Consumer integration proves optionality and supplies documentation evidence

Phase 2 SHALL provide tests through the shared resolution/installer interface
and any introduced public surface, using synthetic data and isolated state.
It SHALL supply real commands, UI states and failure evidence before public
usage guides are written. Any new UI SHALL include keyboard, narrow-screen,
failure/recovery and clean browser/server diagnostic checks.

#### Scenario: A release candidate is handed to the documentation owner
- **WHEN** implementation and release gates pass
- **THEN** the handoff identifies published versions, supported contracts,
  actual commands, installation/refusal/revocation behaviour and reviewed
  synthetic examples, with limitations and skipped checks explicit
- **AND** it does not claim support based solely on this specification
