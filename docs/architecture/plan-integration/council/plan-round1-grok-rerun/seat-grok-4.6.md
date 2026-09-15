## 1. High-level plan

Phases follow the ticket graph, not #7’s six-step monolith. Working branch `fix/plan-integration-bugs` @ `3a4f6b01` is the Bug A/B contract; stacked feature branches fork from it (except §5, which forks `main`).

| Phase | Goal | Tickets | Closes |
|---|---|---|---|
| 0 | Domain Bug B + kick §5 measurement | — | Bug B |
| 1 | Seam: views, errors, browse/inspect/prepare, activation-capable `apply` | #8 | Bug A |
| 2 | Remaining intents + `assess` + adapter→store ban | #9 | — |
| 3 | Now ranking **and** six MCP authoring tools | #10 ∥ #11 | — |
| 4 | Three MCP progression tools **and** `planning` purpose | #12 ∥ #13 | — |
| 5 | Web “Plan with architect” journey | #14 | — |
| 6 | Specs/docs/installer/Archify agree; full suite | #15 | — |

**Parallelisation.** §5 (`plan_prose_query`) vs all of #8–#14: no shared files, run now. After #9 lands, #10 (`decision.py`, `cli/_now.py`, `web/routes/now.py`) and #11 (`mcp/tools.py` new tools only) run concurrently. After #11, #12 (same `tools.py` + stdio inventory) and #13 (`web/routes/session/_start.py`, `agent_launcher`) run concurrently; #12 and #11 must not overlap on `tools.py`. #14 waits for #13. #15 waits for #10, #12, #14.

**Critical path.** #8 → #9 → #11 → #13 → #14 → #15 (six serial gates). #10 is off that path but on #15. Bug B is off the path (Phase 0, hours). Bug A is on it (Phase 1).

**Deviations from #7’s delivery order.**

1. Close Bug B in `planning/evaluation.py` *before* the seam, not in #9. It is not a route bug; the committed test already names the contract; CLI `plan evaluate` calls this function today.
2. Ship `CreatePlan`, `ReplaceDocument`, and `TransitionLifecycle` in #8, not #9. #8’s own DoD demands “identical readiness on create-and-activate / transition / imported active doc”, and the two RED tests in `tests/test_web_plans.py` *are* those doors. #9’s mutation taxonomy split the invariant in half. Do not leave POST `/api/plans` and PATCH `markdown` ungated for a whole ticket.
3. Do not implement all six operations before any adapter migration. #8 migrates list/inspect/activate/create/replace; #9 migrates the rest. Matches the ticket edges; contradicts #7 step (1) then (2).
4. `get_next_action`’s `interleave` patch is the *last* commit of #10, after #11, so only one writer owns `mcp/tools.py` at a time. #7 step (3) then (4) would serialize Now behind a tool that does not need it.
5. §5 is not serialized onto #7 at all. #15 does not wait for the lexical adopt/reject.
6. No new ADR for the seam: the invariant belongs in `openspec/specs/active-learning-decisions/spec.md` and `openspec/specs/mcp-server/spec.md`. ADR only if `planning` purpose changes session identity (it must not).

## 2. Implementation plan

### Phase 0 — Bug B (not a route patch)

RED already committed: `tests/test_planning_evaluation.py::test_failed_checkpoint_db_write_is_reported_as_a_warning` asserts `any("database" in w for w in result.warnings)` when `record_checkpoint` returns `False`.

Change only `packages/studyloop/src/studyloop/planning/evaluation.py` `evaluate_and_record`: honor the bool (and a raised exception) by appending the existing warning string `"checkpoint not saved to the database"`. Do not wrap a second `except` around a callee that swallows. Leave `index.record_checkpoint`’s swallow+`False` as the index’s best-effort policy.

Done: that test plus `test_successful_checkpoint_db_write_adds_no_warning` pass; `uv run --group dev pytest tests/test_planning_evaluation.py` exits 0.

### Phase 1 — #8 seam, Bug A closed by the seam

New files:

- `packages/studyloop/src/studyloop/planning/errors.py`
- `packages/studyloop/src/studyloop/planning/views.py`
- `packages/studyloop/src/studyloop/planning/intents.py`
- `packages/studyloop/src/studyloop/planning/application.py`

Public signatures (immutable, no CLI/HTTP/MCP types):

```python
class PlanError(Exception): ...
class PlanNotFound(PlanError): ...
class InvalidPlanId(PlanError): ...
class PlanConflict(PlanError): ...
class InvalidField(PlanError): ...
class PlanNotReady(PlanError):
    readiness: ReadinessView
class InvalidMilestone(PlanError): ...

@dataclass(frozen=True)
class ReadinessView:
    ready: bool
    blockers: tuple[str, ...]
    nudges: tuple[str, ...]

@dataclass(frozen=True)
class PlanSummary:  # fields = today's plan.summary() keys
    plan_id: str
    title: str
    status: str
    milestone_total: int
    # remaining keys copied from existing summary(), not invented

@dataclass(frozen=True)
class PlanDetail:
    summary: PlanSummary
    readiness: ReadinessView
    markdown: str | None = None
    checkpoints: tuple[CheckpointView, ...] | None = None

@dataclass(frozen=True)
class PlanningBrief:
    interview: tuple[InterviewItem, ...]   # shaped from authoring.interview_spec
    evidence_seed: Mapping[str, object]    # shaped from authoring.seed_from_history
    existing_plans: tuple[PlanSummary, ...]

@dataclass(frozen=True)
class CreatePlan:
    title: str
    answers: Mapping[str, object]
    plan_id: str | None = None
    status: str = "draft"
    overwrite: bool = False

@dataclass(frozen=True)
class ReplaceDocument:
    plan_id: str
    markdown: str

@dataclass(frozen=True)
class TransitionLifecycle:
    plan_id: str
    status: str

class PlanApplication:
    def __init__(self, *, plans_dir: Path | None = None) -> None: ...
    def browse(self, *, status: str | None = None) -> tuple[PlanSummary, ...]: ...
    def inspect(self, plan_id: str, *, include_markdown: bool = False,
                include_history: bool = False) -> PlanDetail: ...
    def prepare_planning(self) -> PlanningBrief: ...
    def apply(self, intent: CreatePlan | ReplaceDocument | TransitionLifecycle) -> PlanDetail: ...
```

`apply` is the only writer. `_assert_can_be_active(plan)` runs iff `plan.status == "active"` (create and replace) or `intent.status == "active"` (transition), calls existing `authoring.readiness`, raises `PlanNotReady`. Preserve `plan_id` + `created` on replace; application sets `updated`. `create` uses `authoring.draft_plan` + `store.create_plan`; duplicate id without `overwrite=True` → `PlanConflict`. Markdown remains authoritative via existing `store.save_plan` atomic replace. Index refresh stays best-effort inside the store/index layer.

Adapters this phase (thin; no `readiness(` call in the route):

- `web/routes/plans.py`: GET list/detail, POST create, PATCH status, PATCH markdown all go through `PlanApplication`. Map `PlanNotReady` → HTTP 422 `detail={"message": "plan is not ready to activate", "ready": False, "blockers": ..., "nudges": ...}` — the shape `test_create_refuses_an_active_status_on_an_unready_plan` and `test_markdown_replacement_refuses_an_unready_active_document` already lock. Map `PlanConflict` → 409, `InvalidField` → 400, `PlanNotFound` → 404.
- `cli/_plan.py`: `list`, `show`, `status` go through the seam. `plan status X active` on an unready plan must refuse (see contradiction below). `_print_readiness` consumes `ReadinessView`.

Do **not** add a third copy of the gate in `web/routes/plans.py`. The PATCH-status gate already there is deleted when the route delegates.

Specs/docs this slice: `openspec/changes/plan-application-seam/{proposal,design,tasks}.md`; delta + normative `openspec/specs/web-ui/spec.md`, `openspec/specs/cli-surface/spec.md`, `openspec/specs/active-learning-decisions/spec.md`; `docs/study-plans.md` §activation.

### Phase 2 — #9 mutations + assess

Add to `intents.py` / `application.py`:

```python
@dataclass(frozen=True)
class RevisePlan:
    plan_id: str
    title: str | None = None
    answers: Mapping[str, object] | None = None
    # explicit fields only — not a free dict

@dataclass(frozen=True)
class SetMilestone:
    plan_id: str
    milestone_id: str
    complete: bool

@dataclass(frozen=True)
class DeletePlan:
    plan_id: str
    confirmed: bool = False

@dataclass(frozen=True)
class AssessPlan:
    plan_id: str
    phase: Literal["start", "mid", "end"]
    study_id: str = ""
    record: bool = True
    append_to_plan: bool = True

@dataclass(frozen=True)
class AssessmentResult:
    evaluation: PlanEvaluationView
    warnings: tuple[str, ...]  # independent flags for DB vs markdown

class PlanApplication:
    def apply(self, intent: CreatePlan | RevisePlan | ReplaceDocument
              | TransitionLifecycle | SetMilestone | DeletePlan) -> PlanDetail: ...
    def assess(self, intent: AssessPlan) -> AssessmentResult: ...
    def get_active_guidance(self, *, energy: str) -> ActiveGuidance: ...
```

`SetMilestone` is an explicit boolean, idempotent (second `complete=True` is a no-op success). `DeletePlan(confirmed=False)` → `InvalidField`; confirmed delete calls `store.delete_plan` and **does not** DELETE FROM `study_plan_checkpoints`. `assess` calls the Phase-0 `evaluate_and_record` when `record=True`, or `evaluate_plan` when preview; copies whatever warnings that function already set; never claims a complete recording if either write failed. Do not raise a `PartialRecording` exception (see underspec).

Rewire remaining CLI (`plan new|interview|evaluate|milestone|architect`) and remaining Web mutation paths. `get_active_guidance` is implemented here so #10 consumes it; ranking stays in `decision.py`.

Architecture test lands here (mechanism in §3).

### Phase 3a — #10 NowPlan additive

`packages/studyloop/src/studyloop/learning/decision.py` is the only ranker. It calls `PlanApplication.get_active_guidance`, then biases `_score_candidates` output. Matching: `casefold` + strip punctuation, equality on topic/course **or** named milestone concepts — no substring. Energy map `low|medium|high → 3|6|10` compared to plan `energy_floor`; below floor, drop *new* milestone work, keep due-recall / struggle-repair. Plan-related due/struggle outrank unrelated of the same urgency class; globally more-urgent unrelated may still win. If no candidate represents an eligible next milestone, synthesize one. After `_dedupe`, attach every matching plan ref (order: target urgency, most recent update, plan id). Fully-checked active plan contributes lifecycle/completion actions, not a study candidate. Guarantee ≥1 eligible plan-backed action in `primary+alternates` when time/energy permit. Zero active plans: existing fields and JSON keys byte-identical to today.

```python
@dataclass(frozen=True)
class PlanRef:
    plan_id: str
    milestone_id: str | None = None

# LearningRecommendation: add plan_refs: tuple[PlanRef, ...] = ()
# NowPlan: add, all default empty
#   active_plans: tuple[ActivePlanSummary, ...] = ()
#   energy_deferred: tuple[DeferredMilestone, ...] = ()
#   completion_actions: tuple[CompletionAction, ...] = ()
#   warnings: tuple[str, ...] = ()
```

`NowPlan.to_json_dict()` **omits** the four additive keys when all empty, and omits `plan_refs` on a recommendation when empty. That is the only reading of “No active plans → output byte-identical to today” that is not self-contradictory.

Consumers stay delegates: `cli/_now.py`, `web/routes/now.py`, `mcp/tools.py:get_next_action`. Last #10 commit: add optional `interleave` to `get_next_action` (same default as `build_now_plan`; default **not established by the brief** — copy the function default, do not invent).

`energy_floor` on the plan/milestone schema is **not established by the brief**. If parse/render does not already have it, #10 adds it to `planning/models.py` + `planning/markdown.py` with a RED parse/render test *before* ranking work. Do not silently default a floor.

### Phase 3b / 4a — nine MCP tools → six operations

Thin adapters in `packages/studyloop/src/studyloop/mcp/tools.py`. No policy. Register via the existing `@tool()` decorator.

| Tool | Operation | Intent / call |
|---|---|---|
| `list_study_plans` | Browse | `browse(status=)` |
| `get_study_plan` | Inspect | `inspect(..., include_markdown=, include_history=)` |
| `get_planning_interview` | Prepare planning | `prepare_planning()` |
| `create_study_plan` | Apply | `CreatePlan` |
| `update_study_plan` | Apply | `RevisePlan` (structured; **not** raw markdown) |
| `set_study_plan_status` | Apply | `TransitionLifecycle` |
| `set_study_plan_milestone` | Apply | `SetMilestone` |
| `evaluate_study_plan` | Assess | `AssessPlan` (`record` flag = preview vs record) |
| `delete_study_plan` | Apply | `DeletePlan` (`confirmed` required) |

Get-active-guidance is **not** a tenth tool; it rides `get_next_action` / `NowPlan`. Raw replacement stays Web/CLI import. Keep existing `record_plan_learning` (`mcp/tools.py:129`); the brief does not retire it. Inventory 26 → 35; `tests/test_mcp_stdio_smoke.py::test_full_handshake_list_tools_and_call` is updated in #12 when all nine are present (not in #11).

### Phase 4b / 5 — `planning` purpose

```python
# web/routes/session/_start.py
class StartSessionRequest:
    topic: str
    energy: str
    agent: ...
    transport: Literal["pty", "acp"]
    purpose: Literal["focus", "planning"] = "focus"   # additive

# single resolver, used by PTY and ACP
def persona_mode_for(purpose: str) -> str:
    return "plan-architect" if purpose == "planning" else "focus"
```

`_start.py` after the one-session claim: `mode = persona_mode_for(body.purpose)`; if `planning`, `brief = PlanApplication().prepare_planning()` and pass a rendered brief as `previous_notes` into the existing `agent_launcher.build_canonical_persona(mode, body.topic, body.energy, previous_notes=...)`. That is the one function that already resolves `agents/shared/personas/{mode}.md` (`plan-architect.md` exists; `"focus"` already falls through to `_default_persona`). Persist **only** `purpose` on session state for label/reconnect. Create **no** plan. No plan id on the live session (spec out of scope). Architect then uses the #11 tools, CLI as harness fallback — same as today’s `studyloop plan architect` / `studyloop study --mode plan-architect`.

#14: Plans view gains “Plan with architect” beside manual New Plan; hits the same start endpoint with `purpose="planning"`. One console, one WebSocket, existing conflict/reconnect. Manual form retained. Topic for an architect launch is **not established by the brief** — use the user-supplied subject if present, else a fixed `"Planning"` label, and lock it with a test so it cannot drift.

### Specs that are under-specified or self-contradictory

- **#8 vs #9 split** (contradiction). #8 DoD includes create-and-activate and imported active docs; #9 owns create/replace. Resolved by deviation 2.
- **`PartialRecording` listed as a domain error** vs “result reports either failure” and the existing return-with-warnings API. Raising would prevent returning the evaluation. Surface is `AssessmentResult.warnings`. Do not add the exception.
- **“byte-identical” vs additive JSON.** Omit empty additive keys (above).
- **“behaviour-preserving” CLI/Web migration vs readiness on every path.** CLI `plan status X active` gating is *not established by the brief*. The invariant wins: CLI must start refusing. That is an intentional behavior change, RED-tested in Phase 1.
- **`energy_floor`, match normalization, target-urgency enum, `RevisePlan` field list, interview item schema, evidence-seed shape, `interleave` default, architect launch `topic`, how the brief is injected (I chose `previous_notes`), overwrite “privilege”, malformed-plan listing policy, `multiplexer.py`’s role.** None established. Do not invent schema beyond what parse/render already emit; any new field gets a parse/render RED test first.
- **ADR-0011 vs reality** — handled in §4, not here.
- **#13 “uses MCP lifecycle tools”** but is blocked only by #11 (six tools), not #12 (milestone/evaluate/delete). Accept that: authoring is enough to start. Do not block #13 on #12.
- **“Do not expose mutable domain objects” vs current REST bodies.** Views must serialize to the existing summary/readiness keys or `tests/test_web_plans.py` (minus the two RED cases going green) will not stay behaviour-identical.

## 3. Test plan

TDD order is fixed: named RED, assertion, then the production edit. Isolated `PLANS_DIR_ENV` + temp index DB for every seam test.

### Phase 0

- Module: `tests/test_planning_evaluation.py` (already committed).
- RED: `test_failed_checkpoint_db_write_is_reported_as_a_warning` — `"database"` appears in `warnings` when the bool is `False`.
- Must stay green: `test_successful_checkpoint_db_write_adds_no_warning`.

### Phase 1

New: `tests/test_plan_application.py` (highest seam = `PlanApplication`, no private helpers).

| RED test | Assertion |
|---|---|
| `test_browse_filters_by_status_deterministically` | ordered tuple; same inputs → same ids |
| `test_inspect_unknown_id_raises_plan_not_found` | `PlanNotFound` |
| `test_create_unready_active_raises_plan_not_ready` | `PlanNotReady`, `ready is False`, `blockers` non-empty; `browse(status="active")` empty |
| `test_transition_unready_to_active_raises_plan_not_ready` | same exception/detail; status remains `draft` |
| `test_replace_unready_active_document_raises_and_does_not_persist` | status + milestone_total unchanged |
| `test_create_activate_transition_replace_refusal_payload_is_identical` | same `ReadinessView` fields/values for one unready fixture via all three intents |
| `test_replace_preserves_id_and_created` | those two fields equal pre-replace |
| `test_multiple_ready_active_plans_are_valid` | two actives list |
| `test_create_duplicate_id_without_overwrite_raises_conflict` | `PlanConflict` |
| `test_prepare_planning_returns_interview_seed_and_summaries` | three sections populated from existing `interview_spec` / `seed_from_history` / `browse` |

Existing RED, now expected green via delegation (do not rewrite assertions):

- `tests/test_web_plans.py::test_create_refuses_an_active_status_on_an_unready_plan` — 422, `detail["ready"] is False`, `detail["blockers"]`, GET `?status=active` `count == 0`
- `tests/test_web_plans.py::test_markdown_replacement_refuses_an_unready_active_document` — 422, status stays `draft`, `milestone_total == 2`

New CLI RED: `tests/test_cli_plan.py::test_status_active_refuses_unready` (module name inferred — if the CLI plan tests live elsewhere, put it next to them) — non-zero exit, stdout/stderr contains a blocker, store still `draft`.

Must remain behaviour-identical: the rest of `tests/test_web_plans.py` including `test_patch_refuses_to_activate_an_incomplete_plan`; existing CLI plan suite; Now/Today/recap suites; `tests/test_mcp_stdio_smoke.py` (still 26 tools).

Fixtures: the “Vague” empty-answers plan from the committed tests; one ready plan built via `draft_plan` + enough answers to pass current `readiness()`.

### Phase 2

Same module, plus `tests/test_planning_evaluation.py` for the assess wrapper.

| RED test | Assertion |
|---|---|
| `test_set_milestone_complete_is_idempotent` | two applies, same `PlanDetail`, one checked milestone |
| `test_set_unknown_milestone_raises_invalid_milestone` | `InvalidMilestone` |
| `test_delete_without_confirm_raises_invalid_field` | plan still loadable |
| `test_delete_retains_checkpoint_history` | `index.checkpoint_history(plan_id)` non-empty after delete |
| `test_assess_preview_does_not_write_db_or_markdown` | history length and checkpoint count unchanged |
| `test_assess_partial_db_failure_warns_and_does_not_claim_complete` | `"database"` in `warnings`; result still returned |
| `test_assess_partial_markdown_failure_warns_independently` | markdown warning present, DB warning absent when DB wrote |
| `test_malformed_plan_browse_matches_store_list` | same ids as `list_plans` (policy: do not invent a new skip rule) |

Architecture test: `tests/test_architecture_plan_seam.py`. Mechanism: `ast.parse` every module under `studyloop/cli/`, `studyloop/web/routes/`, `studyloop/mcp/` (not runtime import graphs — those pull the store transitively through `application`). Fail on `ast.Import` / `ast.ImportFrom` whose root is `studyloop.planning.store`, `studyloop.planning.index`, `studyloop.planning.authoring`, or `studyloop.planning.evaluation`. Allow only `studyloop.planning.application`, `.views`, `.errors`, `.intents`. No extra dependency (`grimp` not required). Done: `pytest tests/test_architecture_plan_seam.py` fails on a planted `from studyloop.planning.store import save_plan` in a temp adapter copy, passes on the real tree.

Cross-surface: `tests/test_plan_surface_parity.py` — create-via-CLI then inspect-via-Web then browse-via-`PlanApplication` yield the same `plan_id/status/readiness.ready`.

### Phase 3 (#10 / #11)

New: `tests/test_now_plan_guidance.py`. Golden: `tests/golden/now_plan_no_active.json` pinning today’s `to_json_dict()` with no active plans.

| RED test | Assertion |
|---|---|
| `test_no_active_plans_json_byte_identical_to_golden` | `to_json_dict() == golden` (no extra keys) |
| `test_matching_due_concept_outranks_unrelated_same_urgency` | `primary.plan_refs[0].plan_id` == the matching plan |
| `test_unrelated_more_urgent_due_outranks_new_milestone` | primary is the urgent due, not the synthesized milestone |
| `test_one_action_keeps_every_matching_plan_ref_ordered` | refs sorted urgency → updated → plan id |
| `test_milestone_without_concepts_does_not_substring_match` | short name ≠ unrelated card text |
| `test_energy_below_floor_defers_new_milestone_keeps_repair` | deferred listed; struggle/recall still eligible |
| `test_fully_checked_active_plan_emits_completion_not_candidate` | completion_actions non-empty; primary is not that milestone |
| `test_synthesizes_milestone_when_no_candidate_represents_it` | primary or an alternate carries that `milestone_id` |
| `test_preserves_one_plan_backed_action_when_energy_allows` | any(ref) across primary+alternates |
| `test_additive_keys_present_only_when_active_plans_exist` | keys appear iff `browse(status="active")` non-empty |

#11: `tests/test_mcp_plan_tools.py` — schema present, delegates to `PlanApplication` (monkeypatch the application, not the store), `PlanNotReady` → tool error containing blockers, create+create same id without overwrite → conflict, idempotent `set_status` retry. Do **not** retarget the stdio inventory yet.

Must stay delegates: Web Now/Today/recap tests still only call `build_now_plan(...).to_json_dict()`.

### Phase 4 (#12 / #13)

- `tests/test_mcp_stdio_smoke.py::test_full_handshake_list_tools_and_call` RED first: asserted tool name set includes the nine strings; then implement #12 tools. Also: confirmed delete required; preview vs record on `evaluate_study_plan`; idempotent `set_study_plan_milestone` retry.
- #13: `tests/test_session_start_purpose.py` — `purpose="planning"` → `build_canonical_persona` called with `"plan-architect"` and non-empty `previous_notes`; `purpose` omitted → `"focus"` (today’s path); no `create_plan` / `CreatePlan` call; conflict response unchanged; reconnect payload contains `purpose`. Fake agent, no paid model.

### Phase 5 (#14)

Browser journey module (name not established — put next to existing web session browser tests): fake agent, one “Plan with architect” click, console labeled planning, brief text present (assert structure: interview / existing plans — **not** exact wording), refresh/reconnect keeps the label, manual New Plan still works, one WebSocket, no second listener, no plan row created. Structured error on conflict.

### Suites that must stay byte-identical through #8/#9

`tests/test_web_plans.py` (except the two committed RED going green), the existing CLI plan suite, `tests/test_planning_evaluation.py` after Phase 0, all Now/Today/recap tests until #10, `tests/test_mcp_stdio_smoke.py` until #12, `tests/golden/session_search_pre_planner.json` forever (that is §5’s pin, not this programme’s).

## 4. §5 plan

Independent branch from `main`, not from `fix/plan-integration-bugs`. Do not touch planning files.

**Protect the explicit door and the golden first** (RED, then code):

- `tests/test_query_planner.py::test_explicit_fts_prefix_is_verbatim` — `fts:foo AND bar` equals the raw string in `QueryPlan`.
- `tests/test_query_planner.py::test_uppercase_operator_outside_quotes_is_verbatim` — `TERM AND OTHER` unchanged.
- `tests/golden/session_search_pre_planner.json` remains the pin of `agent_session_tools/query_planner.py` as shipped; any candidate arm that changes those outputs is rejected before recall is even scored.

`plan_prose_query` (from the archived branch) may run **only** as the widen step inside the existing AND-then-OR planner, and only after `retrieval.py:plan_query` has classified the string as natural language. It must not see `fts:` / uppercase-operator inputs. Stop-word and `len<=2` behaviour of the shipped AND arm stay; the OR widen replaces the current OR construction with `plan_prose_query`’s quoted-token OR. That is the lift the semantic-layer plan-brief actually asked for (“OR arm as the fallback”), not a wholesale swap.

**Pre-registered measurement** (write the receipt command and thresholds *before* looking at numbers):

- Harness: `packages/agent-session-tools` `eval/` — `gold.py` 91-item DEV, `census.py`, `metrics.py`, `receipt.py`.
- Arms (new planner arms, not the session `mcp|cli|hybrid|frozen` arms): `shipped` = current `query_planner.py`; `or_fallback` = shipped AND + `plan_prose_query` widen; optional `or_only` as a diagnostic, not an adopt candidate.
- Primary metric: recall@5. Secondary: precision@5 (must be reported; not optional).
- Adopt `or_fallback` iff DEV recall@5 lift vs `shipped` has CI95 lower bound **> 0** **and** precision@5 does not drop by more than 0.05 absolute. Otherwise reject. Historical +0.142/+0.168 is **not** evidence: different baseline, pre-SEALED-on-main; remeasure.
- If a SEALED set is still loadable on `main`, run it as confirmation only; it cannot flip an adopt (DEV-registered). If it is not loadable, say so on the receipt — do not reconstruct it.
- Receipt path: `packages/agent-session-tools/eval/receipts/lexical-or-fallback-YYYYMMDD.json` (+ `.md`) produced by the eval command, committed. Prose is not a receipt.

On adopt: one logical commit swapping only the OR widen, golden file updated only if the widen path is separately golden’d (`tests/golden/session_search_or_fallback.json`); the pre-planner golden stays the shipped-AND pin. On reject: commit the receipt and leave the planner alone.

**ADR-0011 amendment outline** (`docs/adr/0011-retire-okf-ontology-and-concept-sidecar.md`):

- Add `Amended: 2026-09-15`.
- Strike “stands and will be renumbered when merged” (lines 6–7). Replace with: PR #19 is closed; tip tagged `archive/feat-knowledge-proof-2026-09-15`; primary receipts remain reachable via that tag; the claim-centric learning-memory decision is **not** merged.
- Strike / footnote lines 51–52. The semantic-layer programme on `main` sealed on 2026-09-15 without that store. Branch Stage F measured a fused claims arm at −0.140 recall. It is not a prerequisite.
- Residual work: the lexical OR-fallback evaluation above, tracked outside the plan-integration programme.
- Do not renumber a never-merged ADR from that branch.

## 5. Definition of done

A reviewer ticks from command output only. Working tree clean (no temp artefacts) before each tick.

- [ ] `uv run --group dev pytest` exit 0 (`just test`).
- [ ] `just lint` (`ruff check` + `ruff format --check`) exit 0.
- [ ] `just typecheck` (`pyright`) exit 0.
- [ ] pre-commit hook set green on the tip commit (detect-secrets, bandit included).
- [ ] `pytest tests/test_web_plans.py::test_create_refuses_an_active_status_on_an_unready_plan tests/test_web_plans.py::test_markdown_replacement_refuses_an_unready_active_document` — both pass (Bug A).
- [ ] `pytest tests/test_planning_evaluation.py::test_failed_checkpoint_db_write_is_reported_as_a_warning` — pass (Bug B).
- [ ] `pytest tests/test_architecture_plan_seam.py` — pass (no adapter import of `store`/`index`/`authoring`/`evaluation`).
- [ ] `pytest tests/test_now_plan_guidance.py::test_no_active_plans_json_byte_identical_to_golden` — pass.
- [ ] `pytest tests/test_mcp_stdio_smoke.py::test_full_handshake_list_tools_and_call` — pass, and the printed/asserted inventory contains exactly these nine names: `list_study_plans`, `get_study_plan`, `get_planning_interview`, `create_study_plan`, `update_study_plan`, `set_study_plan_status`, `set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan` (26 + 9 = 35).
- [ ] `pytest tests/test_session_start_purpose.py` — pass; planning purpose creates no plan.
- [ ] Browser architect journey module exit 0 (fake agent; no paid calls).
- [ ] `rg -n "PlanApplication" packages/studyloop/src/studyloop/cli packages/studyloop/src/studyloop/web packages/studyloop/src/studyloop/mcp` — hits in all three adapters.
- [ ] `rg -n "from studyloop.planning.store|from studyloop.planning.index" packages/studyloop/src/studyloop/cli packages/studyloop/src/studyloop/web packages/studyloop/src/studyloop/mcp` — zero hits.
- [ ] `rg -n "build_canonical_persona\\(\"focus\"" packages/studyloop/src/studyloop/web/routes/session` — zero hits (hard-code gone).
- [ ] Normative specs updated in the same commits as the slice they describe: `openspec/specs/active-learning-decisions/spec.md`, `mcp-server`, `web-ui`, `cli-surface`, `agent-adapters`, `live-session-orchestration`.
- [ ] `docs/study-plans.md` no longer lists the three “does not do yet” items in §2 of this brief (bias `now`/Today; Web planning agent; single plan-write MCP tool).
- [ ] Archify spec + sibling HTML updated if a `*.architecture.json` for planning exists (path **not established by the brief** — if absent, tick is N/A and recorded as such, not invented).
- [ ] Nested-event-loop regression test in the #15 suite exit 0 (name **not established by the brief**; the #15 commit must add one that starts a planning-purpose web session and calls an MCP plan tool without raising a nested-loop error).
- [ ] §5 receipt committed at the path in §4, with an `adopt` or `reject` field; `tests/golden/session_search_pre_planner.json` still passing; ADR-0011 amendment merged.
- [ ] `git status --porcelain` empty; each tip commit is conventional, one logical change, body states *why*.

## 6. Risks and pushback

**#7 is over-built in one place and under-built in another.** Nine MCP tools over one seam is the right shape for an agent architect — do not cut those. #14 (browser journey, second affordance, reconnect labeling) is UX sugar on top of a CLI that already launches `plan-architect` (`776a9dc0`). If the critical path slips, ship #13’s purpose param + CLI and move #14 behind #15. Do not cut #8/#9: the two bugs exist *because* policy lived in one route door.

**#7 is wrong about “partial-recording” as an exception type** and about bundling create-and-activate into a later mutation ticket. Both called out above. It is also wrong to imply a new ADR is likely; the load-bearing rules are activation gating, independent checkpoint writes, and “no plan id on a live session” — all spec text, not architecture-decision text.

**Fan-out merge pain is `mcp/tools.py`.** #10 (interleave), #11 (six tools), #12 (three tools + inventory) all touch it. Serialize that file: #11 → #12 → #10’s last commit. `decision.py` is #10-only; `_start.py` is #13-only. Do not let a #10 agent “helpfully” register tools. Stacked branches, rebase onto #9; no long-lived forks off #8 once #9 exists.

**Architecture-test brittleness.** Forbidding `authoring`/`evaluation` imports is correct post-#9 and will fail any leftover `_print_readiness` that still calls `readiness(` directly — good. It will also fail a well-meaning debug print. Keep the allow-list tiny.

**Plan-aware `now` can pass every test in §3 and still nag.** The suite encodes the spec’s ranking story, not learner value. Measure, post-#10, a committed receipt from a 5-scenario human rubric on frozen fixtures (matching due; urgent-unrelated-wins; energy-deferred; fully-checked; no-plan identical) scored “would I do the primary?”. After ship, log accept/skip of `primary` tagged `plan_backed|not` for two weeks; if plan-backed accept rate is not higher than the no-plan baseline, revert the bias and keep the summaries. The failure mode is a stale active plan burying an exam-due card — the “globally urgent still outranks” rule is the safety valve; the rubric must include that case or it is theatre.

**`energy_floor` may not exist.** If #10 invents it without a markdown parse/render test, every existing plan silently becomes floor-less and the energy rule is dead code. Confirm on the fixture set before ranking.

**Do not merge §5 into this programme.** A planner swap that moves recall will churn `tests/golden/session_search_pre_planner.json` and look like a plan-integration regression. Separate PR, separate receipt, ADR amendment only.
