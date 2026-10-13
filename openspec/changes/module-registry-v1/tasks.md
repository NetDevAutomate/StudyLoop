## 1. Phase 1 — establish the registry boundary

- [ ] 1.1 Confirm the maintainer-provided local registry checkout and record the proposed GitHub owner/repository, reviewers and security contact; verify a handoff decision record exists without provisioning or publishing anything implicitly.
- [ ] 1.2 Agree the dependency boundary with module-contract-v1 owners: manifest/checker ownership, qualified identity and installer provenance; verify a written compatibility matrix distinguishes draft fixtures from released contracts.
- [ ] 1.3 Scaffold the registry layout and locked development environment described in design.md; verify a clean checkout can install tooling and run its offline smoke test without Docker, kind, model access or StudyLoop learner data.

## 2. Phase 1 — strict records and deterministic catalogue

- [ ] 2.1 Implement versioned publisher, release, lifecycle and catalogue schemas; verify valid fixtures and rejection tests for unknown fields, text limits, bad coordinates, SemVer, compatibility constraints and unsupported schemas.
- [ ] 2.2 Implement immutable-release and publisher-identity comparison against the previous snapshot; verify changed digests, permissions, repository identities and reused coordinates cannot replace existing releases.
- [ ] 2.3 Implement lifecycle validation and append-only history; verify every allowed transition and every disallowed reversal, deletion and revoked-tombstone omission.
- [ ] 2.4 Implement deterministic generation with explicit sequence/time inputs; verify byte-identical output across two clean runs, SemVer ordering, final newline and rejection of sequence rollback or equal-sequence changed bytes.
- [ ] 2.5 Provide thin validation/build command adapters with stable JSON diagnostics and exit codes; verify captured stdout/stderr and codes for success, invalid input and infrastructure failure.

## 3. Phase 1 — source, artifact and conformance verification

- [ ] 3.1 Implement bounded archive inspection in temporary storage without extracting unsafe entries; verify traversal, links, devices, duplicate paths, Unicode/case collisions, unsupported modes and compressed/expanded/file-count limits are rejected.
- [ ] 3.2 Implement sha256-tree-v1 with published golden vectors; verify file order, raw content, executable modes and non-ASCII paths produce the specified digest while empty directories do not change it.
- [ ] 3.3 Implement allowlisted, timeout-bounded source/artifact retrieval behind an injectable transport; verify numeric repository/asset IDs, full commit pins, checksums, byte sizes, redirect limits, blocked private destinations and no cross-origin credential forwarding with offline transport fixtures.
- [ ] 3.4 Compare the pinned source subtree with the archive tree; verify matching trees pass and changed/omitted/extra files, unresolved LFS pointers and submodules fail without executing hooks or filters.
- [ ] 3.5 Integrate the trusted pinned module checker through an adapter; verify manifest metadata agrees with registry declarations, evidence binds the checked digest, and unsupported or unreleased contracts cannot publish real entries.
- [ ] 3.6 Add hostile fixtures containing marker-writing scripts and author tests; verify validation/build never execute them, never alter non-test files and pass with network denied after tooling installation.

## 4. Phase 1 — governance and trusted publication

- [ ] 4.1 Supply submission, update, deprecation, withdrawal and ownership-transfer templates plus a review checklist; verify each requires exact versions, pinned evidence, ownership checks and applicable independent approval.
- [ ] 4.2 Write the maintainer/security runbook and configure proposed CODEOWNERS coverage; verify a tabletop exercise covers namespace theft, abandoned modules, compromised assets and emergency revocation with two-working-day follow-up.
- [ ] 4.3 Implement the untrusted-PR lane using trusted validator code and least privilege; verify its workflow cannot execute submitted module code or use secrets, privileged caches or self-hosted runners, and refuses combined entry/trusted-tooling changes.
- [ ] 4.4 Implement protected-branch publication that revalidates the merge result and rebuilds the committed catalogue; verify concurrent-PR conflicts and tampered generated output prevent publication in a test repository or non-publishing rehearsal.
- [ ] 4.5 Add recovery instructions and tests for unavailable assets, failed builds and revoked releases; verify recovery produces a higher sequence retaining history rather than a rewritten or older snapshot.

## 5. Phase 1 — acceptance and release gate

- [ ] 5.1 Add synthetic Kubernetes and unrelated-topic module fixtures; verify one schema/checker adapter handles both without topic-specific registry branches or a core topic enum.
- [ ] 5.2 Map every module-registry requirement/scenario to a test or recorded governance check; verify the phase-one definition of done in README.md has no unexplained gaps and report skipped checks explicitly.
- [ ] 5.3 Reproduce offline checks and deterministic builds from a clean environment; verify the acceptance record includes exact tooling/module-contract versions, commands, results and known limitations without private session data.
- [ ] 5.4 Review the completed tooling with the module-contract owner; verify draft-only fixtures remain labelled and public publication remains blocked until an implemented released checker, real two-topic evidence and governance approvals exist.
- [ ] 5.5 Only with explicit maintainer approval, provision/configure the public registry and branch protections; verify required checks, reviewer policy, security contact and the first published immutable revision. If approval/dependencies are absent, stop at tooling-ready and record the blocker rather than marking publication done.

## 6. Phase 2 — shared resolution and local state

- [ ] 6.1 Confirm the module runtime/checker and installer seam are implemented and add owning CLI/Web/MCP spec deltas for surfaces actually introduced; verify no proposed command or permission is treated as already shipped.
- [ ] 6.2 Implement the single resolution interface and immutable receipt with exact coordinate/version, compatibility, contract and prerelease checks; verify active/deprecated outcomes, precise refusals, duplicate bare-ID handling and no silent substitution or artifact download.
- [ ] 6.3 Implement explicit refresh against the approved repository identity and one full commit; verify mixed revisions, repository substitution, unknown schemas and failed retrieval preserve the last-good cache and do not extend freshness.
- [ ] 6.4 Implement versioned atomic cache/provenance migrations; verify corrupt/old/unknown versions, sequence rollback, equal-sequence changed content and revoked-tombstone removal fail safely with known revocations retained.
- [ ] 6.5 Implement cached discovery and the 24-hour verified-fetch policy; verify stale/absent status is labelled, new install/update/rollback is refused when stale, and normal core startup/study performs no registry requests.

## 7. Phase 2 — runtime integration and regression proof

- [ ] 7.1 Hand the verified receipt to the core-owned installer and record provenance there; verify rechecked bytes, identities and eligibility precede atomic activation, and failures preserve the previous installation and learner records.
- [ ] 7.2 Require renewed installation consent for updates and show capability differences; verify registry approval never substitutes for the existing exact-command execution consent or session/target ownership gates.
- [ ] 7.3 Gate future launch of known revoked versions without deleting data or killing active terminals; verify offline behaviour, retained revocations, explicit eligible rollback and refusal of withdrawn rollback targets.
- [ ] 7.4 Test each introduced public surface through the shared interface; verify its success, refusal and recovery paths rather than mocking away the policy under test. Add isolated Playwright tests only for UI actually introduced, including keyboard/narrow-screen behaviour and clean browser/server diagnostics.
- [ ] 7.5 Run focused tests, required coverage gates and the current repository preflight/regression suites; verify no-module/offline study remains unchanged and report unrelated failures, skips and live-environment prerequisites honestly.
- [ ] 7.6 Validate real Kubernetes and one unrelated-topic workflow against the released module contract; verify installation, explicit execution consent, progress boundaries, cleanup ownership and recovery evidence before calling the ecosystem ready.

## 8. Phase 3 — documentation handoff, not speculative documentation

- [ ] 8.1 Deliver the documentation evidence packet in README.md; verify it names published registry/runtime/checker/module revisions, actual commands and supported surfaces, synthetic examples, limitations and acceptance results.
- [ ] 8.2 After the implementation and publication gates pass, update repository and website guides for discovering/using modules and authoring/submitting them; verify every example against released behaviour and do not imply a browser installer or sandbox that is not implemented.
- [ ] 8.3 Run documentation links/build, site checks and relevant browser/accessibility checks for the new pages; verify screenshots contain synthetic data and the deployed/publication state is reported separately from local results.
- [ ] 8.4 Review the full change against both normative capability specs before archiving; verify completed planning, phase-one tooling, phase-two integration and public release are recorded as distinct states rather than equated.
