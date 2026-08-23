# Task 5 report — lifecycle-only product writers

## Outcome

Migrated every normal CLI and existing REST plan mutation through
`PlanningLifecycle`. The legacy file store is now read-oriented in the public
package API; its three raw write implementations remain underscore-prefixed for
explicit maintenance/test fixtures only and are not imported, called, or
re-exported by normal product code.

One production factory now derives the repository root, lock, journal, private
run storage, and canonical Markdown directory from the same configured plans
directory. In particular, `STUDYLOOP_PLANS_DIR` remains the document directory;
the runtime never silently writes to `<configured-dir>/plans`.

## Delivered behavior

- Deprecated `studyloop plan new` creates a typed draft proposal and requires
  `--confirm`; it cannot activate or bypass three-plan capacity.
- Structured `POST /api/plans` returns an exact proposal preview with HTTP 202
  when no decision is supplied. A trusted learner decision can approve/reject
  that exact proposal, or an explicit same-request approval can apply it.
  Request JSON cannot select `ActorContext` and overwrite is refused.
- Raw Markdown POST is learner-only `ImportPlanDraft`: fresh IDs, draft status,
  incomplete milestones, regenerated Mermaid, canonical tier-4 import context,
  and no foreign evidence/completion/Mermaid or generic unknown-section notes.
- Structural and whole-Markdown PATCH return a revision proposal with exact
  target digests/revisions and do not mutate canonical Markdown. A later exact
  learner decision applies it; stale decisions conflict.
- Status-only PATCH/CLI status and normal DELETE use
  `TransitionPlanStatus`. DELETE now records terminal abandonment while keeping
  the Markdown and checkpoint history. Public hard deletion is absent.
- Evaluation computes first, records the checkpoint through
  `RecordCheckpoint`, then independently records DB history. A repository
  conflict has no raw fallback; DB failure still produces a visible warning.
- Milestone CLI/REST writes use `RecordMilestoneOutcome`. Bare toggle is gone;
  verified completion needs selected canonical tier-1 evidence, learner
  attestation needs selected canonical tier-3 evidence plus a milestone-specific
  reason and the exact confirmation sentence, and attestation remains visibly
  non-verified and does not check the milestone.
- Compatibility revision translation refuses more than three goals, duplicate
  identities, ambiguous goal/milestone links, and unresolved concept relations
  rather than truncating or cross-linking. Stable goal/concept/milestone IDs and
  explicit concept relations are preserved when the legacy structure is safe.
- Production evidence catalogues are built from evidence already carried by the
  canonical plan. JSON cannot supply source tiers or mint trusted evidence.
- An AST architecture test catches nested/top-level imports, aliases, direct or
  qualified calls/references, and public re-exports of all six raw writer names
  across CLI, web, MCP, session, agent, evaluation, and package public API code.

## TDD evidence

### RED

1. The new architecture/path test initially failed collection because the
   production runtime factory did not exist:

   ```text
   ModuleNotFoundError: No module named 'studyloop.planning.runtime'
   ```

2. After adding the AST gate it reported the public `create_plan`, `save_plan`,
   and `delete_plan` re-exports. Those exports and public wrappers were removed;
   normal adapters now contain no raw calls.

3. Compatibility regression tests initially found silent structural loss:

   ```text
   DID NOT RAISE LifecycleValidationError  # four goals were sliced to three
   assert 1 == 2                           # blank goal IDs collapsed in a dict
   ```

   Translation now preserves unambiguous blank identities and refuses
   over-limit, duplicate, or ambiguous structures with no canonical write.

4. The first migrated focused run exposed eight expected compatibility changes:
   old bare milestone toggles, immediate structural PATCH, hard deletion, and
   activation error shapes no longer matched the safe lifecycle contract. Tests
   were updated to assert proposals, evidence-backed outcomes, abandonment, and
   conflict semantics.

5. A strengthened import test caught forged Evidence prose surviving through
   generic parsed notes:

   ```text
   assert "forged" not in imported["markdown"].lower()
   # forged tier-1 evidence table was still rendered
   ```

   Import now canonicalises only recognised typed fields and clears generic
   notes/unknown sections, closing the evidence and foreign-Mermaid smuggling
   path.

### GREEN

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_architecture.py -q
# 87 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 292 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 601 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pyright \
  packages/studyloop/src/studyloop/planning/runtime.py \
  packages/studyloop/src/studyloop/planning/compat.py \
  packages/studyloop/src/studyloop/planning/lifecycle.py \
  packages/studyloop/src/studyloop/planning/evaluation.py \
  packages/studyloop/src/studyloop/planning/store.py \
  packages/studyloop/src/studyloop/planning/__init__.py \
  packages/studyloop/src/studyloop/cli/_plan.py \
  packages/studyloop/src/studyloop/web/routes/plans.py
# 0 errors, 0 warnings, 0 informations
```

Ruff checks, Ruff formatting, Python compilation, the AST architecture gate,
and `git diff --check` also pass.

## Compatibility changes

- `plan new` requires `--confirm`; `--activate` is refused.
- New structured REST plans default to draft, cannot overwrite, and require an
  explicit learner decision. Unconfirmed requests return 202 proposal previews.
- Structural PATCH is asynchronous proposal creation (202), not an immediate
  write. Mixed structural/status/completion authority is rejected.
- Bare milestone toggle and completion without evidence/attestation are gone.
- DELETE means audited abandonment, not file removal.
- `create_plan`, `save_plan`, and `delete_plan` are no longer public planning
  imports. Test/maintenance fixtures use underscore-prefixed helpers explicitly.
- `evaluate_and_record` no longer appends Markdown and emits a warning if an old
  caller requests that behavior; normal adapters use `RecordCheckpoint`.

## Honest limitations and deferrals

- The existing browser wizard/store has not yet been adapted to the proposal
  preview/decision DTO. The compatibility API is correct, but the end-to-end
  browser planning experience remains deliberately incomplete until Tasks 8-9;
  this task does not claim the old wizard works with the new 202 flow.
- The production evidence catalogue projects canonical plan evidence only.
  Sessions DB identity-bearing evidence integration belongs to Task 10; no
  Task-5 command claims notes, checkpoints, or arbitrary JSON as tier 1.
- Top-level free-form notes cannot be represented by the current typed proposal
  contract. Direct notes PATCH is refused, and raw import generic notes are
  stripped rather than silently trusted or lost during approval.
- CLI compatibility approval is a single command with `--confirm`; interactive
  agent conversation, safe harness tools, and onboarding installation belong to
  Task 6.
- Planning workspace/ACP transport, new planning HTTP/WebSocket routes, browser
  Markdown/Mermaid rendering, stewardship, and aggregate release gates remain
  Tasks 7-12.
