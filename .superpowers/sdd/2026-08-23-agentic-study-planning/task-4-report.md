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
