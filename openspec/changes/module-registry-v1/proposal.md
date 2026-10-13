## Why

Optional modules need a discoverable, reviewable source of versioned
metadata without turning StudyLoop into a topic-specific application or
making catalogue inclusion an execution permission. The existing
`module-contract-v1` proposal defines a module; this companion defines
the registry, its governance and its interface to a future consumer.

## What Changes

- Specify a GitHub-hosted, reviewed metadata catalogue. Modules remain
  in their authors' repositories; the registry never runs their code.
- Define registry identities, immutable version entries, source pins,
  archive checksums, compatibility, conformance evidence and lifecycle
  states, with deterministic validation and catalogue generation.
- Define an explicit-refresh, fail-closed resolution interface for a
  later StudyLoop consumer. Discovery neither installs nor executes.
- Define submission, review, ownership transfer, withdrawal and security
  handling, with untrusted-PR CI separated from privileged publication.
- Supply staged implementation tasks, release gates, test scenarios
  and a handoff checklist for subsequent user/contributor documentation.

This is a planning-only change. Phase 1 is the registry repository and
offline tooling; phase 2 integrates resolution with the separate module
runtime only after that runtime is ready. Phase 3 publishes verified
usage and contribution documentation. No registry, command, module
installer or trust grant exists merely because this spec is written.

## Capabilities

### New Capabilities

- `module-registry`: reviewed, versioned catalogue, governance, safe
  validation, reproducible publication and lifecycle management.
- `module-registry-resolution`: explicit metadata refresh, exact-version
  resolution, compatibility/integrity checks and offline behaviour.

### Modified Capabilities

None in this planning change. Existing session authority, consent,
configuration and learning-record contracts remain authoritative.
Any future CLI/Web bindings must add deltas to their owning capabilities
in the implementation change; no command spelling is claimed here.

## Impact

- Planning home: `openspec/changes/module-registry-v1/` in StudyLoop.
- Proposed implementation home: a separate GitHub registry repository,
  provisionally `StudyLoop-Modules`; exact owner/name and creation need
  maintainer approval. Do not create or publish it from this handoff.
- Dependency: `openspec/changes/module-contract-v1/proposal.md` is an
  existing draft, not a completed runtime. It is left unchanged.
- Phase 1 needs Python/uv, JSON Schema validation, pytest and GitHub CI;
  no cluster, model credentials, learner database or new core dependency.
- Public StudyLoopSite usage/contribution documentation is deferred
  until release evidence and real command/UI contracts are available.
- No application runtime, public navigation, existing schemas or
  learner data change in this spec-only task.
