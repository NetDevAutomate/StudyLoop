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

## Gate status as of 2026-09-06 (close-out update ~17:15 UTC)

Tracked against `reviews/sessionweaver-plans/PLAN-phase-0-stabilise.md`;
evidence lives under `reviews/2026-09-06-sessionweaver-phase0/evidence/`.
Definitive close-out test results: `evidence/gate1/TEST-RESULTS-closeout.md`.
"Candidate" wording elsewhere in this file and in `docs/session-memory.md`
stays until the §7 council validation gate and the human review pass.

0. **Production pin — DONE except two HUMAN steps.** Wheel from
   `codex/session-memory-mvp @ 5dfe0f9b88f9a0c93069a05a1f707bc6e74caecc`
   (SHA-256 `6ef71b21…3412`) installed via `uv tool install --force`; the uv
   receipt names the pinned wheel path; `which` ×6 verified; all 11 symlinks
   relinked into the pin checkout with before/after evidence
   (`evidence/pin/symlinks.before.txt`, `symlinks.txt`); one Stop-hook-path
   write observed end-to-end through the pinned binary
   (`evidence/pin/claude-hook.*`, caveat in `hook-observation-notes.md`);
   `provenance.md` completed. **Remaining HUMAN:** open Codex/Kiro/OpenCode/pi
   once to confirm skill loads; rotate the ambient API key named in this file.
1. **Gate 1 — regression, lint, typecheck, docs, spec, SAST, pre-commit —
   PASSED (agent-run).** Workspace `4884 passed / 0 failed`; package
   `1126 passed, 1 xfailed`; ruff clean; pyright 0/0/0; spec-check 25/25;
   pip-audit clean; bandit passed; pre-commit 13/14 with the sole failure
   being detect-secrets' "baseline unstaged" (clears on `git add
   .secrets.baseline`; decision in `evidence/gate1/secret-hooks-decision.md`).
   Evidence: `evidence/gate1/`.
2. **Gate 2a — loopback sync integration — PASSED with one recorded
   limitation.** `test_sync_integration.py` + `test_sync_all_default.py`:
   5 passed, 1 xfailed(strict) on Python 3.12 and 3.13
   (`evidence/gate2/loopback-closeout.txt`). The strict xfail is the
   incremental-mode non-convergence documented under Known limitations.
   **Gate 2b (two-Mac) — RUN AND PASSED 2026-09-06** at the user's direction against
   Andys-Mac-Mini (192.168.125.12): all four runbook scenarios pass on disposable
   DBs over the real ssh/scp transport with both Macs on the identical pinned
   wheel; the divergence pre-check found Mac B's production DB populated and
   non-subset (5521 sessions / 223449 messages), so real-DB merging stays
   deferred to Phase 2 (BL-1) and Mac B was backed up read-only first. Evidence:
   `evidence/gate2-two-mac.md`.
3. **Gate 3 — repair rehearsal — DONE, HUMAN sign-off PENDING.** Full
   inspect → apply → re-inspect → rollback on an Online-Backup copy of
   `sessions.db.bak-2026-09-02` (v27→v30; integrity checks clean twice;
   rollback verified two ways). Re-inspect anomaly for opencode/pi recorded
   under Known limitations. Report: `evidence/gate3-repair.md`.
4. **Sentinel + installed-wheel verifier extension — DONE.** Sentinel test
   passes; verifier extended for Claude + Kiro native repair; close-out run
   against the pinned wheel in a fresh py3.12 venv: **17 PASS, 0 FAIL**
   (`evidence/wp8/verify-closeout.txt`).
5. **main dirty-tree reconciliation (WP-2) — DONE.** main's 26 dirty
   entries under `packages/agent-session-tools/` were discarded after a
   preserved, human-approved packet;
   `git status --porcelain -- packages/agent-session-tools` on main is now
   empty. Evidence:
   `~/.local/share/sessionweaver/main-dirty-reconciliation/20260906T155542Z/`.
6. **Grok decision and spec/doc correction (WP-7) — DONE.** Grok is
   recorded as a capture-only decision
   (`docs/adr/0011-grok-is-capture-only.md`, status Proposed); the
   `session-export` spec now names exactly the six exporter modules that
   exist. Evidence: `just spec-check` / `just docs` output filed under
   `reviews/2026-09-06-sessionweaver-phase0/evidence/wp7/`.

### Known limitations (Phase 0 findings, accepted 2026-09-06; fix scheduled for Phase 2)

Both findings were reproduced on disposable copies, are recorded with full repro
evidence, and were deliberately **not** patched in Phase 0 (zero-source-edit rule).
Each is a Phase 2 backlog item.

1. **Incremental sync cannot converge a both-sides-divergent session in one pass.**
   Under `session-sync all --incremental`, a session present on both endpoints with
   divergent messages will not converge: push requires `local_ts > remote_ts` and
   pull requires `remote_ts > local_ts` — mutually exclusive for the same pair
   (`sync.py:872-877`, `1239-1254`, `785-802`). Reconcile mode (the `sync all`
   default, asserted by `tests/test_sync_all_default.py`) does converge.
   Workaround: use reconcile mode when endpoints may have diverged. Repro:
   `reviews/2026-09-06-sessionweaver-phase0/evidence/gate2/REPRO.md`.
   Phase 2 backlog: per-machine `machine_id` + `seq` LWW tiebreak (decision #3 in
   `reviews/sessionweaver-plans/HANDOFF-2026-09-06.md` §2) makes incremental
   convergence decidable.

2. **`session-repair` re-inspect is not idempotent for the `opencode` and `pi` sources.**
   On the gate-3 rehearsal copy, a second inspect after apply reported
   `changed_sessions: 4, missing_messages: 11`; opencode (+4) and pi (+3) `added`
   counts repeat identically on every subsequent inspect — their native matching
   re-proposes the same rows on this DB shape. Data is not corrupted (quick_check,
   FK and FTS checks all clean twice); the counts are a dedup defect in inspect
   matching. Repro and escalation note:
   `reviews/2026-09-06-sessionweaver-phase0/evidence/gate3-repair.md` §6.
   **Severity bounded 2026-09-06 by a second-apply idempotence test: the apply write
   path deduplicates correctly — zero opencode/pi rows written on re-apply, no growth,
   no duplicates; the defect is reporting-only**
   (`evidence/gate3-bl2-idempotence.md`). Interim mitigations until the fix: omit
   opencode/pi from live applies (`--source claude --source codex --source kiro
   --source grok`) so summaries stay trustworthy, and treat per-source row counts —
   not the summary's `added` field — as the authoritative change signal.
   Phase 2 backlog: repair dedup keys for opencode/pi native matchers.

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
