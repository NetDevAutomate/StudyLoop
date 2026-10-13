# StudyLoop module registry — implementation handoff

**Status: proposed specification, not implemented or published.**
Prepared 4 October 2026 against StudyLoop commit
`75bab230d52e7e3dfb29992a2bbb911dbd330285`.

## Start here

Build a reviewed catalogue of optional, independently maintained learning
modules. StudyLoop stays topic-agnostic: Kubernetes drills are one module,
not a Kubernetes mode embedded throughout the core. A second unrelated
topic must demonstrate that the contract is genuinely reusable.

The first delivery is registry tooling that works offline. Do not make
core studying depend on GitHub, install modules during discovery, execute
submission code during review, or advertise registry usage before the
consumer is implemented and released.

Read these in order:

1. [Proposal](proposal.md): scope, motivation and three delivery phases.
2. [Design](design.md): data contract, trust boundaries, lifecycle,
   consumer interface and eighteen user stories.
3. [Tasks](tasks.md): dependency-ordered work with verification per task.

The normative acceptance scenarios are in
[module-registry](specs/module-registry/spec.md) for phase 1 and
[module-registry-resolution](specs/module-registry-resolution/spec.md)
for phase 2.

## Relationship to the module runtime

This is a companion to the existing
[module-contract-v1 proposal](../module-contract-v1/proposal.md), not a
replacement. That workstream owns the module manifest, PracticeDeck
extensions, conformance checker, local installation/inventory, Labs and
execution. This workstream owns reviewed discovery, release identity,
publication and later resolution into that installer.

Neither proposal proves those capabilities are shipped. In particular,
the proposed additional PracticeTask fields are not accepted by the
current strict content schemas. Phase-one fixtures can model a labelled
draft contract; publishing real entries requires an implemented released
checker. Registry review is never a host sandbox or command approval.

## Delivery boundaries

| Phase | Work and owner role | Completion means | Does not mean |
| --- | --- | --- | --- |
| 1: registry | Registry implementer, with maintainer review | Schemas, offline validator, deterministic catalogue, trusted CI design, lifecycle and governance pass the gates below | StudyLoop can install registry modules or the public repository exists |
| 2: integration | Core/module-runtime owner plus registry implementer | Exact-version resolution, cache, provenance and installer/runtime gates work through one shared interface | Every CLI, browser or MCP surface must acquire an installer |
| 3: documentation | Contributor/site documentation owner | Verified usage and authoring guides reflect released commands and tested workflows | A design draft is evidence of released behaviour |

Roles are responsibilities, not assignments to particular people. The
maintainer confirms the implementation checkout and external repository
before work that provisions or publishes it. `StudyLoop-Modules` is a
provisional name. Existing contributor-handbook work can continue without
waiting for this registry; using/contributing-to-the-registry guides wait.

## Phase-one definition of done

Phase 1 is **tooling-ready** only when all these statements are evidenced:

- **Reproducible start:** a clean checkout can install locked tooling and
  run validation/build/tests with network denied after dependency setup;
  no Docker, kind, model subscription, credentials or learner data needed.
- **Unambiguous records:** strict schemas reject malformed/unknown input;
  publisher identity, qualified module ID, exact version, contract and
  application compatibility are independently checked. Published release
  entries cannot be overwritten.
- **Content provenance:** full source commit, repository/asset numeric
  IDs, archive checksum and normalized content digest agree. Golden digest
  vectors and changed/missing/extra-file cases pass.
- **Hostile input:** traversal, links, path collisions, archive bombs,
  resource limits and disallowed redirects are tested. Marker-writing
  module code demonstrably does not execute during validation or build.
- **Stable publication:** two clean builds of identical inputs produce
  identical bytes. Trusted validation rechecks the merge result; a
  submission cannot replace its validator or obtain privileged execution.
- **Withdrawal and ownership:** lifecycle transitions, immutable history,
  tombstones, namespace claims/transfers and emergency review have tests
  or explicit governance evidence. Recovery never erases known revocation.
- **Two topics:** Kubernetes and one unrelated topic pass the same data
  path with synthetic fixtures; no technology-specific registry logic.
- **Usable maintenance:** local check instructions, submission/update/
  withdrawal templates, actionable diagnostics, security contact policy
  and publication/recovery runbook are included in the registry checkout.
- **Traceability:** every phase-one requirement/scenario maps to a test
  or review record; commands, versions, results, skips and limitations are
  recorded. No checkbox is closed solely because a file was scaffolded.

**Public release is a separate gate.** It additionally requires explicit
maintainer approval, actual responsible reviewers/security contact,
verified GitHub protections, an implemented released module checker,
real two-topic conformance evidence and a published immutable registry
revision. Until then report “tooling-ready, publication pending”. Do not
archive phase-two requirements into the shipped baseline at this point.

The concrete limits and policy defaults in the design—such as 24-hour
metadata freshness and review quorum—are proposed v1 decisions, not
claims about current infrastructure. Review changes explicitly and update
the contract/tests together instead of quietly relaxing them in code.

## Copyable implementer handoff

> Implement phase 1 of `module-registry-v1` in the maintainer-provided
> registry checkout. Read this README, proposal, design, both capability
> specs and tasks first, along with that checkout's local instructions.
> Preserve the existing `module-contract-v1` proposal and coordinate its
> checker/schema dependency rather than implementing competing formats.
> Keep submitted content as data: do not execute its scripts, tests or
> workflows. Use isolated synthetic fixtures and prove both a Kubernetes
> and unrelated-topic path. Report acceptance evidence and dependency
> blockers. Stop at tooling-ready unless the maintainer has explicitly
> authorized external provisioning/publication. Do not change StudyLoop
> runtime code or public website usage docs as part of phase 1. Propose
> any required contract changes for review before expanding scope.

## Documentation handoff after implementation

Send the documentation owner one evidence packet containing:

1. **What is available:** published StudyLoop, registry, module-contract
   and checker versions/commits; actual repository URL and catalogue
   revision; supported platforms and which CLI/Web/MCP surfaces exist.
2. **Verified happy paths:** exact discovery, refresh, selection,
   installation, update, disable/remove and author submission commands
   that actually exist. Include prerequisites and expected outputs;
   label unsupported operations rather than inventing commands.
3. **Safety and recovery:** permission prompts, capability changes,
   cancellation, incompatible/missing versions, offline/stale state,
   corrupted downloads, yanked/revoked releases and cleanup ownership.
   State what review checks and what it cannot guarantee.
4. **Teaching assets:** synthetic Kubernetes and unrelated-topic examples,
   licensed/redacted screenshots if a UI exists, and an isolated capture
   recipe. No personal paths, real session history, credentials or private
   security reports in public examples.
5. **Contributor evidence:** working module template, current schema and
   checker invocation, representative good/bad fixtures, test results,
   support/review process and known limitations.

Then create separate low-friction guides for learners and module authors,
link them from the contributor handbook, and validate both repository
documentation and the website. Local tests, merged code, released tooling
and deployed pages must remain separately reported milestones.

## Specification checks

From the StudyLoop checkout:

```sh
openspec validate module-registry-v1 --strict --no-interactive
openspec status --change module-registry-v1
```

These validate planning artifacts, not implementation or runtime safety.
