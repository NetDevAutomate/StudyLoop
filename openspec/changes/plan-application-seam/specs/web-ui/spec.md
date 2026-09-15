## ADDED Requirements

### Requirement: Activation is readiness-gated on every entry path
Every Web API write that can leave a study plan in the `active` state —
create-with-status, raw-Markdown import, whole-document replacement, status
transition, and in-place revision of fields or milestones (including a body
that combines a status change with field edits) — SHALL delegate to
`PlanApplication.apply` as a single intent and SHALL be refused by the seam's
single readiness gate when the *resulting* document — the document as it
would be saved, after every supplied field is applied — has no mission `why`,
no success criteria, or no milestones. The gate judges the resulting document
whether the request makes the plan active or the plan already is. The routes
in `web/routes/plans.py` SHALL hold no readiness check and perform no store
write of their own (`rg 'readiness\(|save_plan' web/routes/plans.py` → 0
hits). A refusal SHALL be `422` whose response body is
`{"detail": {"message": "plan is not ready to activate", "plan_id": "<id>",
"ready": false, "blockers": [...], "nudges": [...]}}` — `detail` is the same
object the `PATCH` status path has always returned, `plan_id` included — and
SHALL persist nothing: no document is created, replaced or re-saved before the
gate runs, and a compound request is one write or none.

#### Scenario: Create with status active on an unready plan
- **WHEN** `POST /api/plans` is called with `{"title": "Vague", "status": "active", "answers": {}}`
- **THEN** the response is `422` whose `detail.ready` is `false` and
  `detail.blockers` is non-empty, no document is written, and
  `GET /api/plans?status=active` reports `count == 0`

#### Scenario: Whole-document replacement whose frontmatter says active
- **WHEN** `PATCH /api/plans/{id}` is called with `{"markdown": ...}` where the
  document's frontmatter has `status: active` and the Milestones section is
  empty
- **THEN** the response is `422` with `detail.ready == false`, and the stored
  document is byte-identical to what it was before the request (status still
  `draft`, milestone count unchanged)

#### Scenario: Status transition to active on an unready plan
- **WHEN** `PATCH /api/plans/{id}` is called with `{"status": "active"}` on a
  plan whose readiness reports blockers
- **THEN** the response is `422` with `detail.ready == false`, and
  `GET /api/plans/{id}` still reports `status == "draft"`

#### Scenario: Raw-markdown import whose frontmatter says active
- **WHEN** `POST /api/plans` is called with `{"markdown": ...}` whose
  frontmatter has `status: active` and which has no milestones
- **THEN** the response is `422` with `detail.ready == false` and no document
  is written

#### Scenario: Compound PATCH is judged as one resulting document
- **WHEN** `PATCH /api/plans/{id}` is called on a ready draft with
  `{"status": "active", "milestones": []}`
- **THEN** the response is `422` with `detail.ready == false`, the stored
  document is byte-identical to what it was before the request, and
  `GET /api/plans/{id}` still reports `status == "draft"` with its original
  milestone count — the status change is not saved before the edit is judged

#### Scenario: Compound PATCH that supplies what was missing activates
- **WHEN** `PATCH /api/plans/{id}` is called on a draft whose only blocker is
  "no milestones" with `{"status": "active", "milestones": [{"title": "First",
  "concepts": ["a"]}]}`
- **THEN** the response is `200`, the plan's `status` is `active`,
  `readiness.ready` is `true`, and the document was written exactly once

#### Scenario: Field-only edit cannot make an active plan unready
- **WHEN** `PATCH /api/plans/{id}` is called on an already-active plan with
  `{"milestones": []}` (no `status` in the body)
- **THEN** the response is `422` with `detail.ready == false`, and the stored
  document is byte-identical to what it was before the request

#### Scenario: Every door returns the same refusal
- **WHEN** the same unready document is refused via create-with-status, status
  transition, document replacement and raw-markdown import
- **THEN** the four `422` bodies are equal apart from `detail.plan_id`, with
  the same blockers and nudges in the same order

#### Scenario: A ready plan still activates on every door
- **WHEN** a plan with a mission `why`, at least one success criterion and at
  least one milestone is created with `status: active`, or transitioned to
  `active`, or replaced by a document whose frontmatter says `active`, or
  imported as raw Markdown whose frontmatter says `active`
- **THEN** the response is `201` (create, import) or `200` (patch) and the
  plan's `status` is `active`; several plans MAY be active at once

### Requirement: Plan routes map seam errors to HTTP status codes in one place
`web/routes/plans.py` SHALL translate `PlanError` subclasses exactly once:
`PlanNotFound` → `404`, `InvalidPlanId` and `InvalidField` → `400`,
`PlanConflict` → `409`, `PlanNotReady` → `422` (body above),
`InvalidMilestone` → `404`. Field validation for the in-place PATCH (empty
title, non-list milestones, non-integer `energy_floor` /
`review_cadence_days`, unknown `status`) SHALL be the seam's `InvalidField`
with the messages the route used before it delegated. Response bodies for
list, detail, create, patch and interview SHALL be unchanged from the
pre-seam routes: summaries carry the `StudyPlan.summary()` key set and
readiness blocks carry the `authoring.readiness()` key set.

#### Scenario: Duplicate id without overwrite
- **WHEN** `POST /api/plans` names a `plan_id` that already exists and does
  not set `"overwrite": true`
- **THEN** the response is `409` and the existing plan is unchanged

#### Scenario: Conflict is judged before readiness
- **WHEN** `POST /api/plans` names a `plan_id` that already exists, does not
  set `"overwrite": true`, and would also have failed the readiness gate
  (`"status": "active"` with empty `answers`)
- **THEN** the response is `409`, not `422`, and the existing plan is
  byte-identical to what it was before the request — identity and conflict
  are settled before the incoming document is judged, on every create door

#### Scenario: Unknown plan on a write
- **WHEN** `PATCH /api/plans/{id}` is called for an id with no document
- **THEN** the response is `404` before any field of the body is validated

#### Scenario: A bad field beside a status change writes nothing
- **WHEN** `PATCH /api/plans/{id}` is called with `{"status": "active",
  "title": "   "}` on a ready draft
- **THEN** the response is `400` and `GET /api/plans/{id}` still reports
  `status == "draft"` — the transition is not committed before the field is
  refused
