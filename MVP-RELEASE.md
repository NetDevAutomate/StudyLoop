# Session memory: bounded reliability release

Date: 2026-09-06. Decision: prepare an improved release of the existing tools.
Do not merge the evidence-context research branch as the MVP.

## Why this release

The user needs a usable release and a finite delivery boundary after an expensive
research/implementation run. The early capture/repair/sync fixes are separable:
three existing commits apply cleanly to current main. They address missing or
damaged conversation imports and make configured peer reconciliation usable
without introducing a new context schema or distributed permission protocol.

The research branch contains useful source-grounded retrieval, interpretations,
scope controls and lifecycle work, but also unfinished recovery and integration
paths. Selecting an arbitrary later stage would inherit those dependencies.
Disabling their safeguards to make a release would not resolve that problem.

This is deliberately a **reliability release**, not completion of the richer
shared-memory product. Its value is recovering and retrieving conversation
history with the existing StudyLoop integration. The rich-context work and its
independently runnable lessons remain preserved on their separate branch.

## Exact candidate

- Branch: `codex/session-memory-mvp`.
- Base: current main at `f945d057`.
- Existing changes: `90869332`, `ebd71d49`, `66907922`, cherry-picked as
  `b08d4f06`, `a5304d1c`, `9e979e53`.
- Runtime/test/documentation change from those commits: 31 files, 3,568 additions
  and 199 deletions. This includes substantial tests and documentation; it is not
  a count of production code alone.
- No new runtime implementation in this audit. The additional verification script
  exercises the installed wheel; this file defines the release boundary. One
  existing five-line test-isolation fix was also copied from the research branch
  after the full regression exposed ambient credential fallback in secret tests.
- Existing schema version remains 30. No new context migrations are included.
- The main checkout's uncommitted work was not copied, changed or discarded.
- The research branch and its unfinished reconciliation changes remain intact.

## Included and excluded behaviour

| Area | Included in this candidate | Explicit limit |
|---|---|---|
| Capture | Existing parser fixes for Codex, Claude Code and Kiro; Grok exporter; stable conversation updates | Supported local transcript formats, not every desktop/cloud conversation or all native tool events |
| Repair | Inspect by default, explicit apply, consistent backup, transactional merge, retained history, repeatable reconciliation | Cannot recover missing original transcripts; no universal completeness guarantee |
| Retrieval | Existing session search/inspection and configured project aliases | Conversation retrieval, not proof that an agent's advice or validation claim is correct |
| Sync | Configured `session-sync all`, pushes before pulls, per-peer failure reporting, preserved message content and archived learner variants | Existing trusted whole-database transport; conflicting databases are not promised to become identical |
| StudyLoop | Current main's installer, skill and doctor integration retained | No new standalone setup owner or comprehensive runtime capture-health system |
| Scope | Existing project filters | Filters are not enforced work/personal authorization; no per-peer scope protection |
| Forgetting | No new distributed forgetting claim | Deleted data may return through legacy sync/restore; no tombstone guarantee |
| Decisions | Original conversations can inform the agent | No automatic arbitration, source-bound decision acceptance or semantic truth certification |

Only use the legacy sync path where every participant is permitted to receive the
entire selected database. This candidate is unsuitable for syncing a mixed
work/personal store to a destination allowed to receive only one part. Preserving
the current transport does not satisfy the richer product's scope requirements.

Do not install this schema-30 candidate against a database upgraded by the
research branch. It is not a downgrade tool and does not preserve the modern
scope/retirement contract. Rehearse upgrades on a copy of an existing supported
database. No owner database or real peer was modified by this audit.

## Verification recorded in this audit

- Locked workspace dependency setup succeeded.
- Memory package and selected StudyLoop installer/harness/doctor tests:
  1,182 passed, one failure caused by setting `CLAUDE_CONFIG_DIR` while a default
  constructor test expects that variable to be absent. That exact test passed
  separately with the override unset. No runtime or test change was needed.
- Workspace source and test type checking: zero errors/warnings.
- Memory package lint and format checks passed.
- Memory wheel built and installed in a fresh environment with StudyLoop absent.
- Installed-wheel verification: seven checks passed, covering native capture,
  continued conversation/idempotence, non-mutating repair preview, repair with
  pre-change backup, repeat repair, CLI retrieval, and database/source integrity.
- Full StudyLoop regression: 3,760 passed, four skipped, 704 deselected, two
  failures in secret-store tests due to ambient credential fallback. The existing
  fixture fix clears provider fallback variables at each secret test; all 41
  secret-store tests then passed. The full suite was not repeated after this
  test-only change. Runtime code did not change.
- Memory package SAST passed with the repository's configured exclusions.
- All pre-commit checks on the three imported commits passed, including secrets,
  SAST, formatting, and workspace source/test type checking.

Operational notice: the secret-test failure printed an ambient API key in tool
output. Rotate that credential. Its value is not included in this document or the
verification script. Startup-only environment removal did not prevent its later
presence during the suite; test-local isolation now covers the observed failures.

The installed check uses fictional native-format records and real installed
package entry points. It does not launch a coding harness or exercise SSH.
The audit made no model-provider or council calls.

Reproduce the small installed check after building/installing the memory wheel:

```sh
/path/to/fresh-memory-only-venv/bin/python scripts/verify-session-memory-mvp.py
```

## Fixed remaining release gates

1. Complete the default regression suite and normal release/CI checks on this
   candidate. Record failures explicitly; don't replace failing checks with a
   growing feature project.
2. Exercise the existing installed StudyLoop/harness workflow and actual
   two-endpoint sync against disposable, same-trust databases. Include a continued
   conversation, repeat sync, a conflicting message and an unavailable peer.
   Existing local/helper tests do not replace this transport acceptance.
3. Rehearse upgrade/repair on a disposable copy of a supported pre-research
   database, confirm retained history and backup recovery, then review the exact
   changes and release notes. Reconcile overlapping main-checkout work before
   merge. Use the normal version/release process only after acceptance.

These are acceptance gates for the frozen candidate, not permission to implement
the deferred product. The candidate is not published and is not yet declared
production-ready. If a gate reveals an architectural change rather than a bounded
fix, stop and report the failed gate with a smaller alternative before spending
more on implementation. No unbounded goal run, additional research stage, council
loop or database redesign is authorized by this checklist.

## Deferred separately

The broader SessionWeave product remains a separate decision: explicit boundaries,
code-owned provenance, rich source explanations, reviewed conflicts, forgetting
across sync and restore, and shared installer/doctor ownership. Its existing
implementation and lessons are retained for later selection. This reliability
release neither discards them nor claims to deliver them.

See [repair instructions](packages/agent-session-tools/docs/session-repair.md)
and [sync instructions](packages/agent-session-tools/docs/sync-after-repair.md).
The [user-facing conversation memory guide](docs/session-memory.md), setup,
CLI reference, agent installation guide, shared session-memory skill and
Unreleased changelog now describe this same candidate boundary. These source
documentation updates do not publish a release or update installed user skills.
