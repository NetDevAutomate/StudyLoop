## ADDED Requirements

### Requirement: record_plan_learning writes through the plan seam
The `record_plan_learning(plan_id, title, body="", status="active")` tool
SHALL apply one `RevisePlan(plan_id, learning_record=LearningRecordSpec(title,
body, status))` through `studyloop.planning.PlanApplication` and SHALL import
no storage module (`studyloop.planning.store` or the store's `record_learning`
/ error family) and make no preliminary read. Its response SHALL keep the
pre-seam keys `{"plan_id", "number", "title", "status", "created"}`; `created`
SHALL be the mutation's own outcome — `PlanDetail.learning_record_outcome`,
the store's `append_learning_record` verdict relayed by the seam — never
inferred from an `inspect` taken before the revision, so a retry with the same
title and body reports `created: false` with the original `number`, and so
does a record another writer filed just before the mutation ran. Every seam
refusal SHALL be a `ToolError`: `PlanNotReady` SHALL
render as `plan is not ready to activate: <blocker>; <blocker>…` so the agent
can tell the learner what to repair (design §2, "ToolError containing
blockers"); `PlanNotFound`, `InvalidPlanId` and `InvalidField` (the store's
title/heading rule) SHALL render as their message.

This was the **only** change to `mcp/tools.py` in Phase 2. The six read/write
plan tools of design §4 are registered in Phase 3 (#11, the requirement
below); the three of Phase 4 (`set_study_plan_milestone`, `evaluate_study_plan`,
`delete_study_plan`) are **not yet registered**. The stdio smoke test pins a
lower bound and the core-tool names, not an exact count, and is retargeted to
the full inventory in #12 (D-9).

#### Scenario: One revision through the seam
- **WHEN** `record_plan_learning("decorators", "MCP insight", body="prose")`
  is called on a ready active plan
- **THEN** exactly one `RevisePlan` whose `learning_record` carries that title
  and body is applied, the response is `{"plan_id": "decorators", "number": 1,
  "title": "MCP insight", "status": "active", "created": true}`, and the plan
  document holds the record

#### Scenario: Retry is one seam call and reports created false
- **WHEN** the same call is repeated
- **THEN** one `RevisePlan` is applied, the response has `created: false` and
  `number: 1`, and the plan still holds one record

#### Scenario: A record filed by another writer just before the mutation
- **WHEN** the same record is written through the store immediately before
  the tool's `RevisePlan` runs
- **THEN** the response has `created: false` and `number: 1`, the tool made no
  `inspect` call, and the plan holds one record

#### Scenario: Not-ready refusal names the blockers
- **WHEN** the seam raises `PlanNotReady` for the revision (the plan is active
  but has no mission, success criteria or milestones)
- **THEN** a `ToolError` is raised whose message contains `not ready` and each
  blocker string from the `ReadinessView`

#### Scenario: Store rule and id refusals are tool errors
- **WHEN** the title is blank, or the body contains a `###` line, or the plan
  id is unknown or malformed
- **THEN** a `ToolError` is raised carrying the seam's message and no record is
  added


### Requirement: Study-plan discovery and authoring tools
`register_tools(mcp)` SHALL register six study-plan tools in the production
inventory, each a thin adapter that makes exactly one
`studyloop.planning.PlanApplication` call and imports no storage, index,
authoring or evaluation module (D-6):

| Tool | Seam call |
|---|---|
| `list_study_plans(status=None)` | `browse(status=)` → `{"plans": [PlanSummary.to_json_dict()…], "count": N}` |
| `get_study_plan(plan_id, include_markdown=False, include_history=False, history_limit=20)` | `inspect(...)` → `PlanDetail.to_json_dict()` (the `GET /api/plans/{id}` body) |
| `get_planning_interview()` | `prepare_planning()` → `PlanningBrief.to_json_dict()` (`questions`, `seed`, `existing_plans`) |
| `create_study_plan(title, answers, plan_id=None, status="draft")` | `apply(CreatePlan(...))` with `overwrite` always `False` → `PlanDetail.to_json_dict()` |
| `update_study_plan(plan_id, title=None, topics=None, target_date=None, energy_floor=None, review_cadence_days=None, notes=None, milestones=None, status=None)` | `apply(RevisePlan(...))` — one intent, judged as one document → `PlanDetail.to_json_dict()` |
| `set_study_plan_status(plan_id, status)` | `apply(TransitionLifecycle(...))` → `PlanDetail.to_json_dict()` |

Every response SHALL be the seam view's `to_json_dict()` built on that call —
fresh containers, never a cached or shared dict. The adapter SHALL carry no
plan policy: the readiness gate, the lifecycle status list, the id rules and
the conflict check are the seam's, and the adapter forwards its arguments
unchanged (an omitted `update_study_plan` field SHALL reach the seam as `None`,
"leave as is", never as `""` or `[]`).

The `create_study_plan` schema SHALL NOT expose `overwrite` (D-4); an agent
cannot replace an existing plan by picking its id, and a taken id is a
conflict. One argument is normalised rather than forwarded unchanged: an
empty `plan_id` string is treated as omitted, so the seam allocates the
unique title slug instead of refusing `""` as a malformed id (council review
3). `update_study_plan` SHALL NOT expose `learning_record`:
`record_plan_learning` remains the one record writer (D-9).

`get_study_plan` SHALL refuse a `history_limit` outside `1..200` — the range
the Web history route accepts — with `invalid: history_limit must be between 1
and 200, got <n>` **before** calling the seam, so a refused limit performs no
database query.

Every seam refusal SHALL be one `ToolError` whose message is
`<kind>: <the seam's message>`, where `kind` is machine-readable:
`PlanNotFound` → `not_found`, `InvalidPlanId` → `invalid_id`, `PlanConflict` →
`conflict`, `InvalidField` → `invalid`, `PlanNotReady` → `not_ready` (rendered
`not_ready: plan is not ready to activate: <blocker>; <blocker>…`, with the
suffix `— the plan is already active; pause it or repair the blockers before
writing` when the plan was already active), `InvalidMilestone` →
`invalid_milestone`, and `plan_error` for any `PlanError` subclass this mapping
has not met. The `ToolError` SHALL chain the domain error as its cause.

#### Scenario: Discover, inspect, create, revise, activate
- **WHEN** an agent calls `get_planning_interview()` (no plans exist), then
  `create_study_plan("Python Decorators", {"why": …, "success": […],
  "topics": ["python"]})`, then `list_study_plans()`, then
  `update_study_plan(<id>, topics=[…], milestones=[{"title": …, "concepts":
  […]}])`, then `set_study_plan_status(<id>, "active")`, then
  `get_study_plan(<id>, include_markdown=True)`
- **THEN** the interview lists the `why`, `success` and `milestones` keys with
  `existing_plans: []`; the create returns a `draft` plan whose id is the
  unique title slug and whose `readiness.ready` is `false` (no milestones yet);
  the list shows that one plan; the revision returns `readiness.ready: true`
  with the new topics and milestone concepts; the transition returns status
  `active`; the inspection returns the active plan with its Markdown document,
  and `list_study_plans(status="active")` counts it while
  `list_study_plans(status="draft")` does not

#### Scenario: Refused activation carries the blockers and writes nothing
- **WHEN** `set_study_plan_status("husk", "active")` — or
  `create_study_plan("Husk", {}, plan_id="husk", status="active")`, or an
  `update_study_plan` whose resulting document would be active — is called
  for a plan with no mission, success criteria or milestones
- **THEN** a `ToolError` is raised whose message starts with `not_ready: plan
  is not ready to activate: ` and contains every blocker string the plan's
  `readiness` reports, the existing document is byte-identical afterwards
  (still `draft`), and no document is created for the refused create

#### Scenario: No overwrite through the MCP door
- **WHEN** `create_study_plan` is called with a `plan_id` that already exists
- **THEN** a `ToolError` starting `conflict: ` is raised, the existing
  document is byte-identical afterwards, and the tool's input schema has no
  `overwrite` property to ask for otherwise

#### Scenario: Every refusal is one prefixed ToolError
- **WHEN** the seam raises `PlanNotFound`, `InvalidPlanId`, `PlanConflict`,
  `InvalidField`, `InvalidMilestone`, or an unmapped `PlanError` from
  `browse`, `inspect`, `prepare_planning` or `apply`
- **THEN** the tool raises exactly one `ToolError` reading `not_found: …`,
  `invalid_id: …`, `conflict: …`, `invalid: …`, `invalid_milestone: …` or
  `plan_error: …` respectively, followed by the seam's message, with the
  domain error chained as `__cause__`

#### Scenario: A retried status transition is not refused
- **WHEN** `set_study_plan_status("decorators", "paused")` is called twice
- **THEN** both calls apply the same `TransitionLifecycle`, both return the
  plan with status `paused`, and neither raises

#### Scenario: history_limit is bounded before any read
- **WHEN** `get_study_plan("decorators", include_history=True,
  history_limit=0)` (or `-1`, `201`, `10000`) is called
- **THEN** a `ToolError` reading `invalid: history_limit must be between 1 and
  200, got <n>` is raised and `PlanApplication.inspect` is never called; `1`
  and `200` are accepted and forwarded unchanged

#### Scenario: Responses are fresh containers
- **WHEN** a response from any of the six tools is mutated by the caller and
  the same call is repeated
- **THEN** the second response is equal to an untouched first response and is
  not the same object
