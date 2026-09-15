# 1. High-level plan

**Phase 0 – Bug triage seam prep (parallelizable)**
- **Goal:** Close Bugs A and B by moving activation-readiness and checkpoint-write reporting into a shared seam that every adapter must call.
- **Tickets:** #8 (reduced scope: only activation-readiness and create/replace paths, no full multiplexer migration yet).
- **Parallel work:** #5.2 (plan_prose_query measurement) can run in parallel; no code touches plans.

**Phase 1 – Core PlanApplication seam (critical path)**
- **Goal:** Introduce `PlanApplication` with six operations, immutable views, domain errors; migrate CLI and Web list/inspect/activate to use it.
- **Tickets:** #8 (full), #9 (create/revise/replace/milestone/delete), #13 (planning-purpose wiring), #14 (Web launch wiring).
- **Parallel work:** #11 (MCP discovery + authoring) can start after #9 is API-stable; #10 (Now plan-aware) can start after #9's guidance operation is implemented.

**Phase 2 – Recommendation engine integration**
- **Goal:** Wire `PlanApplication.get_active_guidance()` into `build_now_plan`, extend `NowPlan` fields, update MCP `get_next_action` with `interleave`.
- **Tickets:** #10 (engine changes), #12 (MCP evaluate/delete tools).
- **Parallel work:** #15 (doc reconciliation) starts here, runs alongside #12.

**Phase 3 – Final integration and docs**
- **Goal:** MCP stdio list shows nine tools, Web architect journey E2E test green, ADR-0011 amended, full suite passes, no adapter imports store.
- **Tickets:** #15 (final verification).
- **Parallel work:** None; this is the merge gate.

**Deviation from #7 order:**
- **Run #13 (planning-purpose) in Phase 1** instead of waiting for #11. The persona resolver change (`build_canonical_persona`) is a five-line delta in `web/routes/session/_start.py` and `agents/shared/personas/plan-architect.md` already exists; it does not depend on MCP tools. Delaying it adds no safety and blocks #14 Web journey tests.
- **Run #10 (Now plan-aware) in parallel with #11–#12** after #9. The spec says "once in the engine" – the engine's ranking logic is isolated in `decision.py`; it can be implemented and unit-tested without MCP tools or Web architect UI. Parallelizing reduces critical path by ~1 day.

**Critical path:** #8 → #9 → (#10 || #11) → (#12 || #13) → #14 → #15.

---

# 2. Implementation plan per phase

## Phase 0 – Bug triage seam prep

**File changes:**
- `packages/studyloop/src/studyloop/planning/application.py` (new):
  ```python
  class ActivationReadinessError(DomainError): ...
  class CheckpointPartialWriteWarning(DomainError): ...

  def check_activation_readiness(plan: StudyPlan) -> Union[Literal[True], ActivationReadinessError]: ...
  def record_checkpoint_checked(evaluation: PlanEvaluation, *, study_id: str) -> Union[Literal[True], CheckpointPartialWriteWarning]: ...
  ```
- `packages/studyloop/src/studyloop/web/routes/plans.py`:
  Replace `readiness(plan)` call with `check_activation_readiness` in POST and PATCH markdown paths; raise 422 if error returned.
- `packages/studyloop/src/studyloop/planning/evaluation.py`:
  Replace `record_checkpoint` call with `record_checkpoint_checked`; if it returns a warning, append to `evaluation.warnings`.

**Public signatures introduced:**
Only the two helper functions above; full `PlanApplication` interface is deferred to Phase 1.

**Bug closure rationale:**
Both bugs are **closed by the seam** because the seam owns the invariant (readiness on activation, partial-write warning). Patching routes directly would duplicate policy and leave the MCP door (which also activates plans) still broken. The seam helpers are unit-tested; routes delegate.

---

## Phase 1 – Core PlanApplication seam

**File changes:**
- `packages/studyloop/src/studyloop/planning/application.py`:
  ```python
  @dataclass(frozen=True) class PlanSummaryView: plan_id, title, status, created, updated, milestone_total, ready, blockers_count
  @dataclass(frozen=True) class PlanDetailView: plan_id, title, status, created, updated, milestones, readiness, markdown
  @dataclass(frozen=True) class PlanningBriefView: interview_questions, seed_evidence, existing_summaries
  @dataclass(frozen=True) class ActivePlanGuidance: plans: list[ActivePlanGuide]
  @dataclass(frozen=True) class ActivePlanGuide: plan_id, next_milestone_id, match_keys, urgency_sec, energy_floor, completion_actions, malformed_warnings
  @dataclass(frozen=True) class PlanChangeIntent: op: Literal["create","revise","replace","lifecycle","milestone","delete"]; plan_id: str; ...
  @dataclass(frozen=True) class PlanAssessmentView: evaluation: PlanEvaluation; warnings: list[str]

  class PlanApplication:
      def browse_plans(self, filter_status: Optional[str]) -> list[PlanSummaryView]: ...
      def inspect_plan(self, plan_id: str, *, include_markdown: bool = False) -> Union[PlanDetailView, DomainError]: ...
      def prepare_planning(self) -> PlanningBriefView: ...
      def get_active_guidance(self) -> ActivePlanGuidance: ...
      def apply_change(self, intent: PlanChangeIntent) -> Union[PlanDetailView, DomainError]: ...
      def assess_plan(self, plan_id: str, phase: str, *, study_id: str = "", record: bool = True) -> Union[PlanAssessmentView, DomainError]: ...
  ```
- `packages/studyloop/src/studyloop/cli/_plan.py`:
  Replace all calls to `store.create_plan`, `save_plan`, `delete_plan` with `PlanApplication.apply_change`; replace `list_plans` with `browse_plans`; replace `load_plan` + `readiness` with `inspect_plan`.
- `packages/studyloop/src/studyloop/web/routes/plans.py`:
  Replace all store calls with `PlanApplication` methods; raise 422/404/409 based on domain error types.
- `packages/studyloop/src/studyloop/web/routes/session/_start.py`:
  Add `purpose: Optional[Literal["focus","planning"]] = "focus"` to `StartSessionRequest`; set `persona_mode = "plan-architect" if body.purpose == "planning" else "focus"`.

**NowPlan additive extension (Phase 2 prep):**
- `packages/studyloop/src/studyloop/learning/decision.py`:
  ```python
  @dataclass(frozen=True) class NowPlan:
      # existing fields unchanged
      active_plan_summaries: list[ActivePlanSummary]
      energy_deferred_milestones: list[DeferredMilestone]
      completion_actions: list[CompletionAction]
      warnings: list[str]

  @dataclass(frozen=True) class LearningRecommendation:
      # existing fields unchanged
      plan_ref: Optional[tuple[str, str]] = None  # (plan_id, milestone_id)
  ```

**MCP tool mapping (nine → six operations):**
- `list_study_plans` → `PlanApplication.browse_plans(filter_status)`
- `get_study_plan` → `PlanApplication.inspect_plan(plan_id, include_markdown=...)`
- `get_planning_interview` → `PlanApplication.prepare_planning()`
- `create_study_plan` → `PlanApplication.apply_change(create-intent)`
- `update_study_plan` → `PlanApplication.apply_change(revise-intent)`
- `set_study_plan_status` → `PlanApplication.apply_change(lifecycle-intent)`
- `set_study_plan_milestone` → `PlanApplication.apply_change(milestone-intent)`
- `evaluate_study_plan` → `PlanApplication.assess_plan(record=True)`
- `delete_study_plan` → `PlanApplication.apply_change(delete-intent)`

**Under-specified areas (flagged):**
- **Revision idempotency:** Spec says "preserve id + created, app owns updated" but does not define concurrency control (ETag, version). Implementation will add `updated: datetime` to views and trust last-write-wins; no 409 conflict on concurrent edit until a future ADR.
- **Deletion confirmation:** Spec requires explicit confirmation but MCP `delete_study_plan` has no `confirmed: bool` parameter. Implementation adds `require_confirmation: bool = True` to intent; MCP adapter must pass `True` after client confirms.
- **Match normalization:** "normalized topic/course equality or named milestone concepts" is not defined. Implementation uses lowercase alphanumeric slug matching; spec should be updated in #15 slice.

---

# 3. Test plan per phase

## Phase 0 – Bug triage seam prep

**Test module:** `tests/test_planning_application_basics.py` (new)
**RED tests:**
```python
def test_activation_readiness_helper_returns_error_on_unready():
    # Given unready plan, check_activation_readiness returns ActivationReadinessError with blockers
def test_activation_readiness_helper_returns_true_on_ready():
    # Given ready plan, returns True
def test_record_checkpoint_checked_returns_warning_on_db_failure(monkeypatch):
    # Mock conn.execute to raise; assert returned CheckpointPartialWriteWarning
def test_record_checkpoint_checked_returns_true_on_success():
    # Normal path returns True
```

**Existing suite delta:**
`tests/test_web_plans.py::test_create_refuses_an_active_status_on_an_unready_plan` remains RED until Phase 1 routes are migrated; Phase 0 only tests the helper.

**Architecture test:** Not yet; Phase 0 is pre-seam.

---

## Phase 1 – Core PlanApplication seam

**Test modules:**
- `tests/test_planning_application_interface.py` (isolated unit tests for each operation)
- `tests/test_cli_plan_migration.py` (CLI parity)
- `tests/test_web_plan_migration.py` (Web parity, includes Bug A RED tests now passing)
- `tests/test_architecture_forbidden_imports.py` (architecture test)

**RED test list (one-line assertions):**
```python
# test_planning_application_interface.py
def test_browse_plans_returns_immutable_summaries():  # List[PlanSummaryView], no mutable plan objects
def test_inspect_plan_returns_detail_or_not_found():  # DomainError.NotFound on missing id
def test_inspect_plan_include_markdown_true_includes_canonical_doc():  # markdown field populated
def test_prepare_planning_brief_includes_interview_and_seed():  # interview_questions non-empty, seed_evidence keyed
def test_get_active_guidance_multiple_active():  # two active plans → two ActivePlanGuide entries
def test_apply_change_create_active_unready_refuses():  # ActivationReadinessError returned, not raised
def test_apply_change_create_active_ready_succeeds():  # PlanDetailView with status active
def test_apply_change_replace_preserves_id_created():  # id and created timestamp unchanged, updated changes
def test_apply_change_delete_requires_confirmation_true():  # intent with require_confirmation=False → DomainError.Invalid
def test_assess_plan_partial_checkpoint_returns_warning():  # CheckpointPartialWriteWarning in warnings list
def test_assess_plan_record_false_no_db_write():  # warnings empty, no INSERT attempted

# test_cli_plan_migration.py (existing suite must remain byte-identical)
def test_plan_list_shows_same_output_as_before():  # stdout snapshot == main@a0272a52 snapshot
def test_plan_show_readiness_same_as_before():  # _print_readiness output unchanged

# test_web_plan_migration.py (Bug A closure)
def test_create_refuses_an_active_status_on_an_unready_plan():  # 422, readiness blockers, 0 active count
def test_markdown_replacement_refuses_an_unready_active_document():  # 422, status remains draft

# test_architecture_forbidden_imports.py
def test_cli_plan_module_does_not_import_store_directly():  # inspect.getsource(cli._plan) contains no "from .store import"
def test_web_plans_module_does_not_import_store_directly():  # inspect.getsource(web.routes.plans) contains no "from ...store import"
def test_mcp_tools_module_does_not_import_store_directly():  # inspect.getsource(mcp.tools) contains no "from ...planning.store import"
```

**Data/fixtures:**
- `tests/fixtures/plans/unready.yaml` (plan with 3 blockers)
- `tests/fixtures/plans/ready.yaml` (plan with 0 blockers)
- `tests/fixtures/plans/active_two.yaml` (two active plans for guidance tests)

**Byte-identical suites:**
`tests/test_cli_now.py`, `tests/test_web_now.py`, `tests/test_mcp_stdio_smoke.py` must not change – no plan awareness yet.

---

## Phase 2 – Recommendation engine integration

**Test modules:**
- `tests/test_now_plan_active_guidance.py` (new)
- `tests/test_mcp_get_next_action_interleave.py` (new)

**RED test list:**
```python
# test_now_plan_active_guidance.py
def test_now_plan_includes_active_plan_summaries_when_active_exists():  # NowPlan.active_plan_summaries length > 0
def test_now_plan_energy_deferred_milestones_filtered_by_floor():  # energy=low defers plan with floor=high
def test_now_plan_recommendation_includes_plan_ref_when_matching_milestone():  # LearningRecommendation.plan_ref == (plan_id, milestone_id)
def test_now_plan_unrelated_urgent_due_outranks_new_milestone():  # primary rec from due card, not milestone
def test_now_plan_action_matching_multiple_plans_keeps_all_refs():  # plan_ref list length > 1, ordered by urgency
def test_now_plan_no_active_plans_byte_identical_to_main():  # to_json_dict() == golden from main@a0272a52

# test_mcp_get_next_action_interleave.py
def test_get_next_action_accepts_interleave_parameter():  # Tool schema includes interleave: bool, no error
def test_get_next_action_interleave_true_modifies_candidates():  # interleave_ratio != 1.0 when interleave=True
```

**Data/fixtures:**
- `tests/fixtures/now/golden_main_no_plans.json` (committed receipt from main)
- `tests/fixtures/now/active_with_due_card.json` (session state: one active plan + one globally urgent due review)

---

## Phase 3 – Final integration and docs

**Test modules:**
- `tests/test_mcp_stdio_tool_list.py` (new)
- `tests/test_web_architect_journey.py` (browser test)

**RED test list:**
```python
# test_mcp_stdio_tool_list.py
def test_stdio_tool_list_includes_all_nine_plan_tools():  # test_full_handshake_list_tools_and_call returns 9 plan-tool names

# test_web_architect_journey.py
def test_plan_with_architect_button_starts_planning_purpose_session():  # POST /api/session/start with purpose="planning" → persona="plan-architect"
def test_planning_session_brief_visible_in_console():  # WebSocket message contains "Planning brief delivered" substring
def test_manual_fallback_form_still_works():  # Manual plan creation form POST still 201
```

**Architecture test (mechanical enforcement):**
```python
# tests/test_architecture_forbidden_imports.py
import sys, importlib
def test_no_adapter_imports_mutable_store():
    banned = {"studyloop.planning.store": ["create_plan", "save_plan", "delete_plan"]}
    for mod_name in ["studyloop.cli._plan", "studyloop.web.routes.plans", "studyloop.mcp.tools"]:
        mod = importlib.import_module(mod_name)
        src = inspect.getsource(mod)
        for banned_mod, banned_funcs in banned.items():
            assert not any(f"from {banned_mod}" in src and f in src for f in banned_funcs), f"{mod_name} imports mutable store"
```

---

# 4. §5 plan for `plan_prose_query`

## Pre-registered measurement protocol

**Evaluation harness:** `packages/agent-session-tools/eval/` arms `mcp|cli|hybrid|frozen` already exists; add `plan_prose` arm.

**Arms:**
- **control:** `main@a0272a52` shipped planner (`agent_session_tools/query_planner.py`)
- **experimental:** `plan_prose_query` from PR #19 tip (`learning_memory/store.py`)

**Gold sets:**
- **DEV:** 91-item set committed at `gold.py` (DEV)
- **SEALED:** Stage 5 outcome set from semantic-layer programme (CI95 lower bound +0.076 receipt)

**Census:** Full `sessions.db` snapshot from `main@a0272a52` (read-only copy in `tests/fixtures/sessions.db.census`)

**Adopt/reject criteria:**
- Reject if experimental arm **degrades recall@5** on either DEV or SEALED by any amount.
- Reject if experimental arm **hurts precision@5** (measured by human-labeled true positives) by >0.05.
- Reject if **explicit FTS door breaks** (test `test_explicit_fts_routes_around_planner` fails).
- Adopt only if **recall@5 improves ≥0.05 on DEV and lower CI on SEALED stays ≥0.076** and explicit door intact.

**Explicit door protection:**
- `tests/test_query_planner.py::test_explicit_fts_routes_around_planner` asserts that a query `"fts:term1 AND term2"` is passed verbatim without tokenization.
- Golden file `tests/golden/session_search_pre_planner.json` is pinned; test `test_planner_output_matches_golden` diffs JSON and fails on any delta.

**Command chain (receipt-producing):**
```bash
uv run --group eval python -m agent_session_tools.eval.arms --arm plan_prose --gold DEV --receipt out/plan_prose_dev.json
uv run --group eval python -m agent_session_tools.eval.arms --arm plan_prose --gold SEALED --receipt out/plan_prose_sealed.json
uv run pytest tests/test_query_planner.py::test_explicit_fts_routes_around_planner --tb=short
```

**Decision point:** If adopt, merge only the `plan_prose_query` function and its eval receipt; do not merge any other PR #19 code. Tag PR tip `archive/feat-knowledge-proof-2026-09-15` and close.

---

## ADR-0011 amendment text outline

**File:** `docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md`
**Amendment section (after line 7):**
```markdown
## Disposition of the knowledge-proof branch

The `feat/knowledge-proof` programme concluded on 2026-09-15. The claim-centric learning-memory decision referenced in lines 6–7 was **not merged**; Stage F evaluation showed the fused claims arm reduced recall (−0.140). The surviving result is the `plan_prose_query` phrase-token OR planner, which was independently measured against the shipped planner. Based on eval outcome [receipt-id], it was [adopted|rejected] and merged in commit [hash] or archived. The branch tip is tagged `archive/feat-knowledge-proof-2026-09-15` for historical reference.
```

---

# 5. Definition of done – whole programme checklist

Reviewer runs these commands and ticks each box:

- [ ] `uv run --group dev pytest tests/test_planning_application_basics.py -q` → **4 passed** (Phase 0 helpers)
- [ ] `uv run --group dev pytest tests/test_planning_application_interface.py -q` → **11 passed** (six operations)
- [ ] `uv run --group dev pytest tests/test_cli_plan_migration.py -q` → **existing CLI suite green, snapshots match main**
- [ ] `uv run --group dev pytest tests/test_web_plan_migration.py -q` → **Bug A tests pass (2 x 422)**
- [ ] `uv run --group dev pytest tests/test_planning_evaluation.py::test_failed_checkpoint_db_write_is_reported_as_a_warning -q` → **1 passed** (Bug B closed)
- [ ] `uv run --group dev pytest tests/test_architecture_forbidden_imports.py -q` → **3 passed** (CLI, Web, MCP import bans)
- [ ] `uv run --group dev pytest tests/test_now_plan_active_guidance.py -q` → **6 passed** (guidance rules)
- [ ] `uv run --group dev pytest tests/test_mcp_get_next_action_interleave.py -q` → **2 passed** (interleave parity)
- [ ] `uv run --group dev pytest tests/test_mcp_stdio_tool_list.py -q` → **9 tools listed in handshake**
- [ ] `uv run --group dev pytest tests/test_web_architect_journey.py -q` → **3 passed** (purpose wiring)
- [ ] `uv run --group eval python -m agent_session_tools.eval.arms --arm plan_prose --gold DEV --receipt out/plan_prose_dev.json` → **receipt written**
- [ ] `uv run --group eval python -m agent_session_tools.eval.arms --arm plan_prose --gold SEALED --receipt out/plan_prose_sealed.json` → **receipt written**
- [ ] `uv run pytest tests/test_query_planner.py::test_explicit_fts_routes_around_planner` → **passed** (explicit door intact)
- [ ] `uv run pytest tests/golden/session_search_pre_planner.json` → **byte-identical to main snapshot**
- [ ] `ruff check` → **0 errors**
- [ ] `ruff format --check` → **0 diff**
- [ ] `pyright` → **0 errors in changed files**
- [ ] `git diff openspec/specs/` → **specs updated** (active-learning-decisions, mcp-server, web-ui, cli-surface)
- [ ] `git diff docs/` → **public docs updated** (study-plans.md, cli.md, mcp.md)
- [ ] `git diff *.architecture.json` → **Archify specs updated** if structure changes (e.g., new module)
- [ ] `git tag archive/feat-knowledge-proof-2026-09-15 3a4f6b01` → **tag pushed**

---

# 6. Risks and pushback

## Where #7–#15 is wrong, over-built, or should be cut

1. **“No operation binds a live study session to a plan” is contradictory.**
   The Web architect launch (#13–#14) sends a planning brief *into* a live session; if the user creates a plan, the session console shows plan ID. The seam is correct, but the spec should admit that `purpose=planning` sessions are implicitly bound to the plan created during that session. **Pushback:** Update spec in #15 to state session-purpose logs plan ID for reconnect, but no automatic plan selection at future session start.

2. **MCP nine tools vs six operations is over-built.**
   `update_study_plan` (revise) and `set_study_plan_status` (lifecycle) could be one tool with a discriminated union. The extra surface increases test burden. **Cut:** Merge into `mutate_study_plan` with `mutation: Union[ReviseIntent, LifecycleIntent, MilestoneIntent]`; reduces tools to seven, still meets parity. Do this in #11 slice; update spec.

3. **Active-plan guidance ranking is under-specified and likely over-fitted.**
   The rule “unrelated more-urgent due outranks new milestone” is sensible, but “plan-related due review outranks unrelated work in same urgency class” requires a non-existent urgency-class categorizer in the retrieval layer. **Risk:** Implementing this requires leaking plan concepts into `learning_memory/retrieval.py`, coupling layers. **Mitigation:** Start with simple plan-id tagging; measure if recall@1 actually improves on a held-out set before adding complex urgency-class logic.

## Fan-out merge pain points

- **`NowPlan` JSON schema change touches three renderers:** Web `/api/now`, MCP `get_next_action`, and CLI `studyloop now`. If #10 and #12 run in parallel, they will conflict on the `to_json_dict()` signature. ** Mitigation:** #10 owns `NowPlan` dataclass and its JSON schema; #12 must branch from #10's head and only update MCP tool schema to match, not the dataclass.
- **`PlanningBriefView` interview questions may drift between #11 (MCP tool) and #14 (Web console).** **Mitigation:** Both adapters must assert against the same golden brief JSON in `tests/fixtures/planning/brief_golden.json`; brief generation is owned by #11, #14 is read-only.

## What to measure to know plan-aware `now` helps learners

- **Metric:** `recall@1-plan-matched` – proportion of sessions where the top recommendation matches a plan milestone and the learner accepts it (clicks start, completes >5 min).
- **Instrumentation:** Add `plan_ref` to `learning_record` table; `agent_session_tools/eval/receipt.py` computes acceptance rate per plan vs non-plan recs.
- **A/B gate:** expose `now_plan_aware` flag in user config; run 50/50 for 2 weeks; require **+0.10 acceptance-rate lift** with p<0.05 to keep enabled by default. Receipt command:
  ```bash
  uv run python -m agent_session_tools.eval.receipt --cohort now_plan_aware --metric acceptance_rate --receipt out/now_ab.json
  ```
- **Qualitative:** Sample 20 plan-matched sessions; human label if milestone was actually the right next step; require ≥80% concordance.

Without this measurement, the feature risks adding complexity for no learner benefit even if all tests pass.
