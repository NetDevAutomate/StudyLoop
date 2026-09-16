# Design — PlanApplication seam and plan integration

Decisions are cited as D-n from the council arbitration
(`docs/architecture/plan-integration/council/arbitration-plan-round1-2026-09-15.md`). Where this document
and the arbitration disagree, the arbitration wins and this document is wrong.

## 1. Module layout (D-3)

```
packages/studyloop/src/studyloop/planning/
    errors.py        PlanError(Exception) and six subclasses — no CLI/HTTP/MCP types
    views.py         frozen dataclasses, tuples only, to_json_dict() returns fresh containers
    intents.py       closed union of frozen intent dataclasses
    application.py   class PlanApplication — the only writer adapters may use
    store.py / index.py / authoring.py / evaluation.py / markdown.py / models.py — unchanged roles, now
                     internal to the seam (adapters may not import them: D-6)
```

### Errors

```python
class PlanError(Exception): ...
class PlanNotFound(PlanError): ...
class InvalidPlanId(PlanError): ...
class PlanConflict(PlanError): ...          # duplicate id without overwrite
class InvalidField(PlanError): ...          # bad status, empty title, unconfirmed delete, bad phase
class PlanNotReady(PlanError):              # carries the ReadinessView
    readiness: ReadinessView
class InvalidMilestone(PlanError): ...
```

### Views

Field sets mirror today's `StudyPlan.summary()` and `authoring.readiness()` keys exactly, so the existing
REST bodies and `tests/test_web_plans.py` stay behaviour-identical (D-3).

```python
@dataclass(frozen=True) class ReadinessView: ready: bool; blockers: tuple[str, ...]; nudges: tuple[str, ...]
@dataclass(frozen=True) class MilestoneView: index: int; title: str; concepts: tuple[str, ...]; done: bool
@dataclass(frozen=True) class CheckpointView: ...                      # from Checkpoint.to_dict()
@dataclass(frozen=True) class PlanSummary: ...                          # = summary() keys
@dataclass(frozen=True) class PlanDetail:
    summary: PlanSummary; mission: MissionView; milestones: tuple[MilestoneView, ...]
    readiness: ReadinessView; markdown: str | None = None; checkpoints: tuple[CheckpointView, ...] | None = None
@dataclass(frozen=True) class PlanningBrief:
    interview: tuple[InterviewItemView, ...]; evidence_seed: Mapping[str, object]; existing_plans: tuple[PlanSummary, ...]
@dataclass(frozen=True) class AssessmentResult:
    evaluation: PlanEvaluationView; db_write: Literal["not_requested","saved","failed"]
    document_write: Literal["not_requested","saved","failed"]; warnings: tuple[str, ...]
    @property recording_complete -> bool   # every requested sink saved
@dataclass(frozen=True) class ActivePlanGuidance:        # one per active plan (Phase 2, consumed by #10)
    plan: PlanSummary; next_milestone: MilestoneView | None; match_keys: frozenset[str]
    target_urgency: Literal["overdue","soon","later","undated"]; energy_floor: int
    completion_action: str | None; warnings: tuple[str, ...]
@dataclass(frozen=True) class ActiveGuidance: plans: tuple[ActivePlanGuidance, ...]; warnings: tuple[str, ...]
```

### Intents (D-2, D-4)

```python
CreatePlan(title, answers, plan_id=None, status="draft", overwrite=False)   # overwrite: Web/CLI only, never MCP
ReplaceDocument(plan_id, markdown)                                            # preserves plan_id + created
TransitionLifecycle(plan_id, status)
RevisePlan(plan_id, title=None, topics=None, target_date=None, energy_floor=None,
           review_cadence_days=None, notes=None, milestones=None, learning_record=None)  # explicit fields
SetMilestone(plan_id, index, done: bool)                                      # idempotent
DeletePlan(plan_id, confirmed: bool = False)
AssessPlan(plan_id, phase, study_id="", record=True, append_to_plan=True)
```

### Application

```python
class PlanApplication:
    def __init__(self, *, plans_dir: Path | None = None) -> None
    def browse(self, *, status: str | None = None) -> tuple[PlanSummary, ...]
    def inspect(self, plan_id, *, include_markdown=False, include_history=False) -> PlanDetail
    def prepare_planning(self) -> PlanningBrief
    def get_active_guidance(self) -> ActiveGuidance                    # Phase 2
    def apply(self, intent: PlanIntent) -> PlanDetail                   # the only writer
    def assess(self, intent: AssessPlan) -> AssessmentResult
```

`apply` runs `_assert_can_be_active(plan)` whenever the *resulting* document would be active — create with
`status="active"`, replace whose frontmatter says active, transition to active — and raises `PlanNotReady`
before any canonical write. Markdown stays authoritative through the existing `store.save_plan` atomic
replace; index refresh stays best-effort inside the store/index layer. `assess` calls the Phase-0
`evaluate_and_record` for `record=True` and `evaluate_plan` for preview, and reports both sinks (D-1, D-3).

## 2. Adapter mapping

| Domain error | Web | CLI | MCP |
|---|---|---|---|
| `PlanNotFound` | 404 | exit 1, message | ToolError |
| `InvalidPlanId`, `InvalidField` | 400 | exit 1 | ToolError |
| `PlanConflict` | 409 | exit 1 | ToolError |
| `PlanNotReady` | 422 `{"message": "plan is not ready to activate", "ready": false, "blockers": [...], "nudges": [...]}` | exit 1 + `_print_readiness` | ToolError containing blockers |
| `InvalidMilestone` | 404 (existing toggle behaviour) | exit 1 | ToolError |

The Web PATCH-status gate is deleted when the route delegates (D-2). CLI `plan status` already gates
(`_plan.py:336-341`); it migrates to the seam and keeps the same exit code and output.

## 3. Plan-aware `now` (D-5)

`decision.py` remains the only ranker. Order of operations inside `build_now_plan`:

1. `guidance = PlanApplication().get_active_guidance()` (cheap, plan-static; no session-history scan).
2. Existing candidate collection unchanged.
3. Energy capability `low|medium|high → 3|6|10`; below a plan's `energy_floor`, new-milestone work is
   *deferred* (listed in `energy_deferred`), plan-related due recall / struggle repair stays eligible.
4. Match: `casefold` + strip punctuation; equality on topic/course **or** on named milestone concepts. No
   substring.
5. Score as today; within an urgency class, plan-related beats unrelated; a globally more-urgent unrelated
   candidate still wins (bias, not filter).
6. If no candidate represents an eligible next milestone, synthesise one.
7. `_dedupe`, then attach every matching `PlanRef`, ordered by target urgency → most recent update → plan id.
8. Guarantee ≥ 1 eligible plan-backed action in primary + alternates when time/energy permit.
9. Fully-checked active plan → `completion_actions`, never a study candidate.

```python
@dataclass(frozen=True) class PlanRef: plan_id: str; milestone_index: int | None = None
LearningRecommendation.plan_refs: tuple[PlanRef, ...] = ()
NowPlan.active_plans: tuple[ActivePlanSummary, ...] = ()
NowPlan.energy_deferred: tuple[DeferredMilestone, ...] = ()
NowPlan.completion_actions: tuple[CompletionAction, ...] = ()
NowPlan.warnings: tuple[str, ...] = ()
```

`to_json_dict()` omits each additive key when empty and omits `plan_refs` when empty. Golden
`tests/golden/now_plan_no_active.json` is captured on `main` **before** any #10 change.

## 4. MCP tools (D-8, D-9)

| Tool | Seam call |
|---|---|
| `list_study_plans(status=None)` | `browse` |
| `get_study_plan(plan_id, include_markdown=False, include_history=False)` | `inspect` |
| `get_planning_interview()` | `prepare_planning` |
| `create_study_plan(title, answers, plan_id=None, status="draft")` | `apply(CreatePlan(overwrite=False))` |
| `update_study_plan(plan_id, **explicit fields)` | `apply(RevisePlan)` |
| `set_study_plan_status(plan_id, status)` | `apply(TransitionLifecycle)` |
| `set_study_plan_milestone(plan_id, index, done)` | `apply(SetMilestone)` |
| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | `assess` |
| `delete_study_plan(plan_id, confirmed=False)` | `apply(DeletePlan)` |

Writers to `mcp/tools.py` are serialised: #11 → #12 → #10's `interleave` commit. The stdio smoke test's
inventory assertion is retargeted in #12 to the real count: the production registry had **23** tools at
`0a20a796` (D-9's "26 → 35" counted from a stale inventory), 29 after #11, and **32** once #12's three land —
`record_plan_learning` is among the original 23 (council review 3).

## 5. `planning` purpose (D-10, D-11)

```python
class StartSessionRequest: ...; purpose: Literal["focus", "planning"] = "focus"
def persona_mode_for(purpose: str) -> str: return "plan-architect" if purpose == "planning" else "focus"
def build_canonical_persona(mode, topic, energy, *, previous_notes=None, brief: str | None = None) -> str
```

`_start.py` (and the ACP path) call `persona_mode_for(body.purpose)`; for `planning`, render
`PlanApplication().prepare_planning()` to Markdown and pass it as `brief=` (a new "Planning brief" persona
section — not `previous_notes`, which renders "Resuming Previous Session"). Persist only `purpose` on
session state for label/reconnect. No plan is created; no plan id is stored. Topic for an architect launch:
the user-supplied subject if present, else the fixed label `"Study plan"` (matches `776a9dc0`).

## 6. Architecture guard (D-6)

`tests/test_architecture_plan_seam.py`: `ast.parse` every `.py` under `studyloop/cli/`,
`studyloop/web/routes/`, `studyloop/mcp/`; resolve relative imports; fail on `Import`/`ImportFrom` rooted at
`studyloop.planning.store|index|authoring|evaluation`; allow `studyloop.planning.application|views|errors|
intents` (and `studyloop.planning` itself only for the re-exported view/intent/error names). A second test
plants `from studyloop.planning.store import save_plan` into a temp copy of an adapter and asserts the
checker rejects it.

## 7. §5 stream (D-12, D-13) — separate branch `feat/lexical-or-fallback` off `main`

Candidate: replace only the OR-*widen* construction in `query_planner.plan()` with `plan_prose_query`'s
quoted-token OR; the AND arm, STOP set and `len(token) > 2` filter stay; `retrieval.plan_query`'s explicit
door stays in front. Arms (planner variants in `eval/arms.py`, orthogonal to `mcp|cli|hybrid|frozen`):
`shipped`, `or_first_filtered`, `and_first_unfiltered`, `or_only_unfiltered`, `and_then_prose_or` (the
candidate). Pre-registration receipt written **before** any run:
`docs/architecture/session-memory/receipts/lexical/preregistration-2026-09-15.md` with corpus sha256, gold
sha256, seed, arms, metrics, thresholds. Adopt `and_then_prose_or` iff: DEV recall@5 paired-bootstrap CI95
lower bound > 0; precision@5 drop ≤ 0.05 absolute; explicit-door tests pass; `session_search_pre_planner.json`
unchanged. Measurement receipt at `receipts/lexical/or-fallback-dev-2026-09-15.json` (+ `.md` reading).
ADR-0011 amended per D-13 regardless of adopt/reject.

## 8. Verification receipt (D-15)

`scripts/verify/plan_integration.py --out docs/architecture/plan-integration/receipts/verify-<sha>.json`
runs: the full suite; `ruff check`; `ruff format --check`; `pyright`; the named Bug A/B node ids; the
architecture guard; the no-active golden; the stdio inventory; the `rg` invariants (`PlanApplication` used by
all three adapters; zero adapter imports of `planning.store|index`; zero `build_canonical_persona("focus"`
literals under `web/routes/session`). Records exit codes and node counts. A missing check is a failure.

## 9. Diagram

When the seam lands, author `docs/architecture/plan-integration/plan-integration.architecture.json`
(Archify, showcase quality) showing adapters → `PlanApplication` → store/index and the `now` consumer,
deliver the HTML beside it, and record the delivery receipt in the tasks file.
