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

This is the **only** change to `mcp/tools.py` in this phase. The six read/
write plan tools of design §4 (`list_study_plans` … `set_study_plan_status`)
and the three of Phase 4 (`set_study_plan_milestone`, `evaluate_study_plan`,
`delete_study_plan`) are **not yet registered**; the stdio inventory is
unchanged at this phase.

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
