# Task 4 report — central planning lifecycle

## Outcome

Implemented the release-one `PlanningLifecycle` as the authoritative application
seam for agentic plan preparation, proposal review, learner decisions, trusted
evidence/checkpoints, milestone outcomes, status transitions, and draft import.
The repository remains a generic filesystem transaction boundary: lifecycle
policy is evaluated by a guard over the validated `PlanSnapshot` and journal
events while the root lock is held.

The implementation deliberately keeps authority outside model-authored payloads.
`ActorContext` is trusted adapter context paired with the closed command union;
models may prepare, submit and inspect, learners decide/import/transition/attest,
and the trusted StudyLoop recorder records evidence and checkpoints.

## Delivered contract

- Exact raw brain dumps are persisted as immutable private mode-0600 artifacts
  before model work. Journal events contain only an artifact reference and
  digest, and journal folding reconstructs runs and proposals after restart.
- Create/revise briefs bind the exact learner input, every current canonical
  plan, active stable goal identities, offered evidence provenance, selected
  source content digests, and lifecycle/schema policy versions.
- Revise briefs expose the target canonical plan plus known resources, topics,
  unresolved gaps and invariants. Existing goal/concept/milestone identities
  can only be referenced from that brief; new aliases receive fresh IDs once at
  submission.
- Proposal submission is private-artifact/journal-only. It assigns immutable
  IDs, emits canonical Markdown/Mermaid preview, supersedes an older open
  proposal from the run, and cannot mutate canonical Markdown.
- Proposal digests bind structural assigned content, aliases, target CAS,
  evidence dispositions, explicit typed concept relations with provenance,
  next action, resulting active goal set, and an override request/reason. Audit
  timestamps and free-form review prose are excluded.
- Approval/rejection revalidate authority, proposal state, complete CAS,
  included context and current active-goal state under the repository lock.
  Repository idempotent replay returns before evaluating the guard.
- Rule-of-Three overrides require an explicit learner reason and are journal
  authoritative, mirrored to a readable `DecisionRecord`, and valid only while
  the exact sorted active-goal digest still matches.
- The evidence catalogue owns IDs, source tiers and provenance. Tier 1 alone
  verifies completion; tier 3 produces a visibly distinct learner attestation;
  tier 2 can inform adaptation; tier 4 is context only. Checkpoints never infer
  completion, and rejected/unresolved evidence cannot prove an outcome.
- Import is learner-only, create-only and locked-capacity checked. Foreign IDs,
  digests, evidence authority, goal/milestone completion and Mermaid are
  discarded; fresh IDs, draft status, incomplete milestones, active draft goals,
  regenerated Mermaid and tier-4 import context are issued instead.
- `next_action` is first-class schema-v2 Mission Markdown and part of the
  structural digest. It is no longer hidden in free-form notes.

## TDD evidence

### RED

1. Initial lifecycle collection:

   ```text
   rtk uv run --group dev pytest packages/studyloop/tests/test_planning_lifecycle_*.py -q
   ```

   All four new lifecycle modules failed collection because `ActorContext` and
   the lifecycle API did not exist.

2. Durable direct-command replay initially produced two
   `IdempotencyConflictError` failures after constructing a new lifecycle
   instance. The journal fold did not yet project direct command keys.

3. Immutable private-artifact test initially failed with `DID NOT RAISE`; a
   changed payload could replace a private run artifact.

4. Proposal privacy test found the proposed title in `planning-journal.jsonl`.
   Proposal payloads were then moved to immutable digest-checked private
   artifacts, leaving only authoritative references in the journal.

5. First-class next-action contract:

   ```text
   rtk uv run --group dev pytest \
     packages/studyloop/tests/test_planning_markdown.py::test_next_action_is_canonical_mission_structure \
     packages/studyloop/tests/test_planning_digests.py::test_each_structural_change_changes_structure_digest \
     packages/studyloop/tests/test_planning_lifecycle_commands.py::test_submission_assigns_ids_and_persists_no_canonical_markdown -q
   ```

   Result: 13 failures (`StudyPlan` rejected/omitted `next_action`). After the
   schema, parser/renderer, digest and lifecycle changes: 13 passed.

6. Proposal-digest normalization test failed because changing audit timestamps
   and free-form notes changed the proposal digest. It passed after replacing
   whole-model serialization with the structural assigned-plan projection.

7. Imported foreign goal completion test failed (`complete != active`) and now
   passes after import strips the foreign completion claim.

8. Normalized prepare replay failed when the same evidence/source sets arrived
   in a different order. It now replays after canonical sorting while still
   binding the exact raw brain dump.

### GREEN

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_lifecycle_*.py \
  packages/studyloop/tests/test_planning_repository.py -q
# 67 passed in 1.33s

rtk uv run --group dev pytest packages/studyloop/tests/test_planning_*.py -q
# 253 passed in 2.36s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_store.py -q
# 84 passed, 1 pre-existing Starlette TestClient deprecation warning

rtk uv run --group dev pyright \
  packages/studyloop/src/studyloop/planning/contracts.py \
  packages/studyloop/src/studyloop/planning/evidence.py \
  packages/studyloop/src/studyloop/planning/lifecycle.py \
  packages/studyloop/src/studyloop/planning/lifecycle_journal.py \
  packages/studyloop/src/studyloop/planning/lifecycle_proposals.py \
  packages/studyloop/src/studyloop/planning/models.py \
  packages/studyloop/src/studyloop/planning/markdown.py \
  packages/studyloop/src/studyloop/planning/digests.py \
  packages/studyloop/src/studyloop/planning/authoring.py
# 0 errors, 0 warnings, 0 informations
```

The focused suite includes a real cross-process race through public lifecycle
status commands: two different plans attempt activation against two existing
active goals, exactly one succeeds, and the final locked snapshot contains
three active stable goal IDs.

## Files and boundaries

Public lifecycle contracts live in `planning/contracts.py`; trusted evidence
policy in `planning/evidence.py`; orchestration in `planning/lifecycle.py`;
journal folding/private proposal rehydration in `planning/lifecycle_journal.py`;
and proposal validation/identity/digest/readiness rules in
`planning/lifecycle_proposals.py`. This keeps `PlanningLifecycle` as the public
deep seam without shipping a single task-shaped implementation module.

Repository changes are limited to a generic locked projection/guard API and
immutable private artifact behavior. Existing CLI/REST/browser writers are not
migrated in this task.

## Honest limitations and deferrals

- Existing adapters/writers still bypass this lifecycle until Task 5. No claim
  is made that the current CLI or web plan form is agentic yet.
- The production evidence catalogue adapter is not wired here. The injected
  catalogue is deterministic and enforces the normative contract; Task 5/10
  must project real StudyLoop/session sources into it.
- Harness installation, workspace/ACP transport, HTTP routes, browser UI,
  stewardship and release-gate certification belong to Tasks 6–11.
- The repository-wide `just typecheck` is not currently a green baseline: it
  reports 360 errors, including pre-existing web/test typing debt and existing
  repository rehydration typing. The new lifecycle source modules pass a
  targeted Pyright run with zero errors; this report does not misrepresent the
  broad gate as passing.
- Private artifacts are payload storage, not an independent index. Missing or
  digest-mismatched artifacts make journal projection fail closed rather than
  inventing run/proposal state.
- Import rejects executable Markdown patterns and never dereferences user text
  as a filesystem path. Browser-side rendering sanitization and accessible
  Mermaid fallback remain Task 9 concerns.

## Fix round 1 — atomic semantic retries and stale rejection

### Review findings resolved

The repository now keeps two independent digests for each transaction:

- `idempotency_digest` represents trusted caller + key + normalized semantic
  command input and decides whether a concurrent attempt is a replay or a
  conflict;
- `payload_digest` continues to bind the complete generated transaction and
  still rejects reuse of an `intent_id` for different bytes.

Lifecycle commands supply their existing normalized request/command digest as
the semantic digest. A losing concurrent attempt receives the journal-folded
winning run, proposal, decision, import, or direct-command result, including
the winner's IDs, revisions, digests and status.

Brain dumps and proposal payloads are now transactional private artifacts.
The repository checks semantic replay while holding the root lock before it
writes either artifact, so a normal losing race creates no private data. The
journal intent records only artifact path and content digest; if a process dies
after an artifact write but before the terminal event, recovery verifies the
digest, removes the uncommitted artifact and narrowly matched temporary, fsyncs
the directory, and removes the empty run directory. It refuses unknown paths,
symlinks, non-regular files, or digest mismatches rather than deleting them.

Revision rejection now validates the complete target CAS before dispatch and
recomputes brief context inside its repository guard. Checkpoint, trusted
evidence, canonical document, evidence provenance, capacity/context, or newer
proposal changes therefore make rejection stale without appending a terminal
`proposal_decided` event. A fresh revision rejection remains journal-only and
idempotent.

### RED evidence

The first public-lifecycle run synchronized two spawned processes inside
`PlanningRepository.commit()`, after both lifecycle pre-reads and generated
candidate state:

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_lifecycle_commands.py::test_checkpoint_makes_revision_rejection_stale_without_terminal_decision \
  packages/studyloop/tests/test_planning_lifecycle_commands.py::test_trusted_evidence_makes_revision_rejection_stale_without_terminal_decision \
  packages/studyloop/tests/test_planning_lifecycle_commands.py::test_canonical_transition_makes_revision_rejection_stale_without_terminal_decision \
  packages/studyloop/tests/test_planning_lifecycle_capacity.py::test_concurrent_identical_prepare_replays_one_captured_run \
  packages/studyloop/tests/test_planning_lifecycle_capacity.py::test_concurrent_identical_submission_replays_one_proposal \
  packages/studyloop/tests/test_planning_lifecycle_capacity.py::test_concurrent_identical_approval_replays_one_canonical_decision \
  packages/studyloop/tests/test_planning_lifecycle_capacity.py::test_concurrent_identical_import_replays_one_canonical_plan \
  packages/studyloop/tests/test_planning_lifecycle_capacity.py::test_concurrent_identical_checkpoint_replays_one_canonical_append -q
# 8 failed: three stale rejections did not raise; every spawned race returned one ok + one error
```

Repository tracer tests then covered semantic replay without weakened payload
integrity, transactional artifact winner-only behavior, and crash cleanup.

### GREEN evidence

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_lifecycle_*.py \
  packages/studyloop/tests/test_planning_repository.py \
  packages/studyloop/tests/test_planning_repository_crash.py -q
# 96 passed in 2.51s

rtk uv run --group dev pytest packages/studyloop/tests/test_planning_*.py -q
# 265 passed in 3.07s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_store.py -q
# 84 passed, 1 pre-existing Starlette TestClient deprecation warning in 1.42s

rtk uv run --group dev pyright \
  packages/studyloop/src/studyloop/planning/contracts.py \
  packages/studyloop/src/studyloop/planning/evidence.py \
  packages/studyloop/src/studyloop/planning/lifecycle.py \
  packages/studyloop/src/studyloop/planning/lifecycle_journal.py \
  packages/studyloop/src/studyloop/planning/lifecycle_proposals.py \
  packages/studyloop/src/studyloop/planning/models.py \
  packages/studyloop/src/studyloop/planning/markdown.py \
  packages/studyloop/src/studyloop/planning/digests.py \
  packages/studyloop/src/studyloop/planning/authoring.py
# 0 errors, 0 warnings, 0 informations
```

Ruff formatting/checks and `git diff --check` passed. Changed-input controls
remain green for prepare, proposal submission, approval, import and checkpoint;
the semantic replay path does not turn a changed command into a replay.

### Compatibility note

`idempotency_digest` is additive and optional at the generic repository seam.
Existing callers and older journal events fall back to the complete payload
digest, preserving their prior byte-identical replay behavior. Lifecycle
callers opt into semantic replay explicitly because their candidate payloads
contain server-generated IDs and audit timestamps.

## Fix round 2 — recovered-before semantic retry history

### Review finding resolved

Journal validation now models each `(caller, idempotency_key)` as an explicit
semantic state machine. The first intent binds the semantic digest and
transaction operation. An exactly matched recovered-before terminal moves that
lineage to `retryable`, allowing a later intent to carry regenerated IDs,
timestamps, private-artifact paths and therefore a different raw payload
digest. A committed or recovered-after terminal moves it permanently to
`completed`.

Every terminal still has to match its own intent byte-for-byte across the
complete transaction fields. Validation continues to fail closed when a retry
changes semantic digest or operation, follows a terminal-after outcome, or is
appended while another intent is pending. Older events without an explicit
semantic digest still fall back to their raw payload digest, so their historical
byte-identical contract is unchanged.

Public lifecycle crash tests cover preparation and proposal submission at both
`after_journal_intent` and `after_private_artifacts`. Recovery classifies the
failed attempt before, removes any uncommitted private artifact, and an exact
retry deliberately using a different clock and ID generator commits a new
winner. A third lifecycle instance can inspect and replay that winner, only the
winner's referenced private artifact remains, and changed semantic input still
conflicts. Direct tamper controls cover committed, recovered-after, changed
semantic digest, changed operation and parallel-intent histories.

### RED evidence

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_repository_crash.py \
  -k 'recovered_before_semantic_lineage or semantic_payload_change or different_semantic_digest' -q
# 8 failed, 18 deselected in 0.25s
# Four lifecycle retries returned successfully but the next read raised:
# JournalCorruptionError: idempotency tuple has conflicting payload digests
# Four tamper controls were rejected only by that blanket payload check rather
# than the required semantic-lineage transition.
```

### GREEN evidence

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_lifecycle_*.py \
  packages/studyloop/tests/test_planning_repository.py \
  packages/studyloop/tests/test_planning_repository_crash.py -q
# 105 passed in 2.57s

rtk uv run --group dev pytest packages/studyloop/tests/test_planning_*.py -q
# 274 passed in 2.88s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_store.py -q
# 84 passed, 1 pre-existing Starlette TestClient deprecation warning

rtk uv run --group dev pyright \
  packages/studyloop/src/studyloop/planning/contracts.py \
  packages/studyloop/src/studyloop/planning/evidence.py \
  packages/studyloop/src/studyloop/planning/lifecycle.py \
  packages/studyloop/src/studyloop/planning/lifecycle_journal.py \
  packages/studyloop/src/studyloop/planning/lifecycle_proposals.py \
  packages/studyloop/src/studyloop/planning/models.py \
  packages/studyloop/src/studyloop/planning/markdown.py \
  packages/studyloop/src/studyloop/planning/digests.py \
  packages/studyloop/src/studyloop/planning/authoring.py \
  packages/studyloop/src/studyloop/planning/journal.py
# 0 errors, 0 warnings, 0 informations
```

Ruff formatting/checks and `git diff --check` passed. No repository or
lifecycle interface changed; this round only corrects validation of durable
history already emitted by the semantic-idempotency contract.

## Fix round 3 — reject invalid semantic retries before append

### Review finding resolved

`validate_event_sequence()` now returns the same authoritative semantic retry
projection used by the repository's locked idempotency check. The projection
binds each `(caller, idempotency_key)` to its semantic digest, mutation
operation and pending/retryable/completed state. Repository commit validates a
candidate against that projection before guards, artifact writes, canonical
plan replacement or journal append. Journal sequence validation uses the same
projection while folding durable history, so the pre-append and restart rules
cannot diverge.

An operation-incompatible retry now raises deterministic
`IdempotencyConflictError` without changing journal bytes, private artifacts or
canonical plans. Parameterized public repository tests cover recovered-before
lineages for create, update, record and journal operations; their otherwise
valid retries attempt upsert, upsert, journal and record respectively. Each
rejection is followed by successful recovery/projection of the unchanged
history. Controls prove that a compatible regenerated raw payload still
commits and replays, while a changed semantic digest still conflicts before
mutation.

### RED evidence

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_repository_crash.py \
  -k 'commit_rejects_operation_incompatible or commit_accepts_compatible or commit_rejects_changed_semantics' -q
# 4 failed, 2 passed, 27 deselected in 0.14s
# Every create/update/record/journal incompatible retry returned instead of
# raising IdempotencyConflictError.
```

### GREEN evidence

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_lifecycle_*.py \
  packages/studyloop/tests/test_planning_repository.py \
  packages/studyloop/tests/test_planning_repository_crash.py -q
# 111 passed in 3.26s

rtk uv run --group dev pytest packages/studyloop/tests/test_planning_*.py -q
# 280 passed in 3.55s

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_store.py -q
# 84 passed, 1 pre-existing Starlette TestClient deprecation warning in 1.69s

rtk uv run --group dev pyright \
  packages/studyloop/src/studyloop/planning/contracts.py \
  packages/studyloop/src/studyloop/planning/evidence.py \
  packages/studyloop/src/studyloop/planning/lifecycle.py \
  packages/studyloop/src/studyloop/planning/lifecycle_journal.py \
  packages/studyloop/src/studyloop/planning/lifecycle_proposals.py \
  packages/studyloop/src/studyloop/planning/models.py \
  packages/studyloop/src/studyloop/planning/markdown.py \
  packages/studyloop/src/studyloop/planning/digests.py \
  packages/studyloop/src/studyloop/planning/authoring.py \
  packages/studyloop/src/studyloop/planning/journal.py
# 0 errors, 0 warnings, 0 informations
```

All previous Task 3 corruption and Task 4 crash/race tests remain green. Ruff
format/check and staged/unstaged diff checks passed. No lifecycle or repository
public command shape changed, and no Task 5 adapter migration was started.
