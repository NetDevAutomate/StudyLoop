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

- Deprecated `studyloop plan new` creates a typed draft proposal but cannot
  approve it in the same invocation. `--confirm` is refused; a separate
  interactive-only `plan decide <proposal-id> <proposal-digest>` action
  redisplays the proposal and prompts for the decision and confirmation. It
  cannot activate or bypass three-plan capacity.
- Structured `POST /api/plans` returns an exact proposal preview with HTTP 202
  for every structured creation request. A later request can approve/reject
  only that persisted proposal ID and displayed digest; same-request approval
  is refused.
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

- `plan new` never approves in the same command; deprecated `--confirm` and
  `--activate` are refused. `plan decide` is interactive-only with no JSON or
  flag-based approval surface.
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
- CLI compatibility approval is deliberately a TTY-only, prompted,
  digest-bound command. Agent conversation and onboarding installation belong
  to Task 6.
- Planning workspace/ACP transport, new planning HTTP/WebSocket routes, browser
  Markdown/Mermaid rendering, stewardship, and aggregate release gates remain
  Tasks 7-12.

## Independent-review fix round 1

The first implementation passed its Task 5 suite but an independent adversarial
review found three Critical and five Important boundary defects. This round
closed all eight without beginning Task 6 or later transport/workspace work:

- Creation approval is now necessarily two-phase in CLI and REST. Both paths
  require the persisted proposal ID and exact displayed digest; the CLI
  `--confirm` shortcut and structured same-request REST decision are rejected.
- Structural revisions merge lifecycle-owned state by stable ID. Plan status,
  existing goal status, and verified milestone completion survive title-only
  and full structural proposals; completed/abandoned plans cannot be revised.
- CLI and browser learner input can record only explicit tier-3 attestation,
  never mint recorder authority. Internal verified completion additionally
  requires selected tier-1 evidence with a completion claim whose subject
  matches the target milestone (or its named concept).
- PATCH decisions inspect the persisted proposal before dispatch and reject a
  creation proposal or a revision targeting a different route plan.
- Raw imports reject foreign Mermaid fences, all raw HTML, HTML comments, and
  concealed markup before any recognised Mission/Milestone field is accepted.
  Canonical Mermaid remains renderer-generated. Ambiguous duplicate normalised
  legacy concept labels are refused rather than cross-linked.
- The architecture gate scans the real `session/`, `session_runtime/`, root
  session/agent modules, adapters, and MCP tree. Self-tests cover dynamic
  `importlib`, `__import__`, string `getattr`, aliases, nested calls, qualified
  calls, and public re-exports.
- Every plan-agent harness invocation receives a fresh private scratch root;
  caller-selected directories and their existing Markdown are never unlinked.
- Checkpoint DB history uses the same lifecycle command key with a partial
  unique index, so lifecycle replay cannot append a second history row. Both
  CLI and REST now surface the helper's `False` result as a warning.

### Fix-round RED evidence

The added regression slices reproduced each defect before production changes,
including immediate approval (`201` instead of `400`), state regression
(`active`/`paused` previewed as `draft`), cross-plan PATCH returning `200`,
irrelevant tier-1 evidence being accepted, concealed import markup returning
`201`, dynamic-writer self-tests returning no violation, the harness helper
being absent while direct unlink remained, and a replay producing two DB
history rows.

### Fix-round final verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_architecture.py \
  packages/studyloop/tests/test_plan_agent_harness.py -q
# 112 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 299 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 620 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pyright <changed Task 5 source and harness files>
# 0 errors, 0 warnings, 0 informations
```

Ruff check, Ruff formatting, Python compilation, the expanded AST architecture
gate, and `git diff --check` also passed on the final formatted tree.

## Independent-review fix round 2

The second adversarial review correctly identified that exact proposal IDs and
digests are CAS values, not learner authentication. It also found a remaining
legacy progress-loss case plus two identity/parser edge cases. All four are now
closed:

- CLI proposal decisions are unavailable to non-TTY and JSON/flag invocation.
  The command redisplays the exact proposal, prompts for approve/reject, and
  requires a second explicit confirmation. `plan new` shows the review values
  but never prints an immediately executable approval command.
- The web app now mints an expiring, bounded, application-local learner session
  only during same-site browser navigation. Authority-bearing plan writes
  require the HttpOnly session cookie, exact same Origin, `Sec-Fetch-Site:
  same-origin`, and a double-submit CSRF token tied to server-side session
  state. Configured HTTP Basic authentication remains the outer identity
  boundary; no learner session is minted until it succeeds.
- Proposal decisions, raw imports, status transitions, milestone outcomes, and
  abandonment all construct learner `ActorContext` only from that trusted
  browser boundary. Default/direct HTTP clients receive 403. Proposal
  preparation remains model-authorised and does not mint learner authority.
- Structural revision of a tolerated legacy plan with blank stable entity IDs
  is refused before any proposal or canonical write. Completed milestones and
  active/non-default plan state therefore remain intact until an explicit
  lossless identity repair exists.
- Import scans CommonMark backtick and tilde Mermaid fence openers across valid
  fence lengths, spacing, indentation, and case. Only renderer-generated
  canonical Mermaid is accepted.
- Tier-1 relevance contains no title/substring heuristic. Evidence must name
  the exact milestone ID or an exact canonical concept label/stable concept ID
  explicitly attached to that milestone; SQL/NoSQL and nested-label cases are
  rejected.

### Round-2 RED evidence

Before implementation, noninteractive CLI decisions succeeded, direct REST
approval returned 201, browser navigation minted no trusted session, tilde
Mermaid imports returned 201, the legacy completed-milestone PATCH returned
202, and SQL/NoSQL evidence completed the wrong milestone. Each regression now
fails closed at its public boundary.

### Round-2 final verification

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli_plan.py \
  packages/studyloop/tests/test_web_plans.py \
  packages/studyloop/tests/test_planning_evaluation.py \
  packages/studyloop/tests/test_planning_architecture.py \
  packages/studyloop/tests/test_plan_agent_harness.py -q
# 129 passed, one pre-existing Starlette/httpx deprecation warning

rtk uv run --group dev pytest packages/studyloop/tests/test_planning*.py -q
# 301 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_web*.py -q
# 637 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_e2e_coverage_gate.py \
  packages/studyloop/tests/test_e2e_coverage_gate_selftest.py -q
# 27 passed

rtk uv run --group dev pyright <changed round-2 source files>
# 0 errors, 0 warnings, 0 informations
```

Ruff check, Ruff formatting, Python compilation, architecture tests, and
`git diff --check` passed on the final round-2 tree.
