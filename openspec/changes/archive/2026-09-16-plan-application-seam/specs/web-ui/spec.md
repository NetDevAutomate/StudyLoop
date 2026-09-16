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


### Requirement: The milestone checkbox is one SetMilestone; the toggle request is not replay-safe
`POST /api/plans/{id}/milestones/{index}/toggle` SHALL read the milestone's
current state through the seam and apply one `SetMilestone(plan_id, index,
done=<opposite>)` intent — never a route-side write and never the full-list
`RevisePlan` substitute the review-1 corrections used in the interim. The
seam's `SetMilestone` is a *set*, not a toggle: applying the same intent twice
leaves the same document. The legacy no-body toggle *request* is
read-invert-write and therefore **not** retry-idempotent: replaying it flips
the box again, and two concurrent toggles can collapse into one update — the
contract this checkbox has always had, acceptable for a checkbox, and no claim
of replay safety SHALL be made for it (council review 2, F3). A caller that
needs replay safety SHALL state the desired state (`PATCH` with `milestones`,
or the CLI's `--done`/`--undone`). An
index the plan does not have — past the end **or negative** — SHALL be the
seam's `InvalidMilestone`, mapped to `404`, with the document byte-identical
afterwards. The response body SHALL keep its pre-seam keys: `{"updated": true,
"index": <i>, "done": <bool>, "plan": <summary>}`.

#### Scenario: Toggle flips and flips back
- **WHEN** the toggle is posted twice for milestone `0` of a two-milestone plan
- **THEN** the first response has `done == true` and `plan.milestone_done ==
  1`; the second has `done == false` and `plan.milestone_done == 0`; each
  request applied exactly one `SetMilestone` whose `done` was the opposite of
  the state it read — a replayed request is not a no-op

#### Scenario: Out-of-range and negative indices
- **WHEN** the toggle is posted for index `42` or `-1`
- **THEN** the response is `404` and `GET /api/plans/{id}/markdown` is
  unchanged

### Requirement: Delete is confirmed by the verb and retains checkpoint history
`DELETE /api/plans/{id}` SHALL apply `DeletePlan(plan_id, confirmed=True)` —
the HTTP verb is the confirmation this route contract has always had — and
return `200` with `{"deleted": true, "plan_id": "<id>"}`. The canonical
document and its derived index row are removed; the durable checkpoint log
(`study_plan_checkpoints`) is retained. An unknown id SHALL be `404` and a
malformed id `400`, both before anything is removed.

#### Scenario: Delete removes the document and keeps the log
- **WHEN** a plan with one recorded checkpoint is deleted
- **THEN** the response is `200` with `deleted == true`; `GET /api/plans/{id}`
  is `404`; a second `DELETE` is `404`; the checkpoint log for that id still
  holds the row; the derived index no longer lists the plan

### Requirement: Checkpoint recording reports each sink
`POST /api/plans/{id}/evaluate` SHALL call `PlanApplication.assess` with
`record=True` and return `201` with `recorded`, `db_write`, `document_write`,
`evaluation` and `markdown`. `db_write` and `document_write` are each
`"not_requested"`, `"saved"` or `"failed"`; `recorded` SHALL be `true` only
when no requested sink failed. A failed sink is a reported outcome, not an
error response: the evaluation succeeded and the client is entitled to it, so
the status stays `201`. `GET /api/plans/{id}/evaluate` SHALL be
`assess(record=False)` and write to neither sink. The route SHALL hold no
phase check of its own: an unknown phase on `POST` is the seam's
`InvalidField` → `400`, judged after the plan is found (`404` first).

#### Scenario: Both sinks saved
- **WHEN** `POST /api/plans/{id}/evaluate` is called with `{"phase": "start"}`
  and both writes succeed
- **THEN** the body has `recorded == true`, `db_write == "saved"`,
  `document_write == "saved"`

#### Scenario: Database write fails
- **WHEN** the checkpoint log write returns `False` or raises during
  `POST /api/plans/{id}/evaluate`
- **THEN** the response is still `201`; `recorded == false`, `db_write ==
  "failed"`, `document_write == "saved"`; `evaluation.warnings` contains
  `checkpoint not saved to the database`; and the plan document carries the
  checkpoint row

#### Scenario: Document sink not requested
- **WHEN** the body has `"append_to_plan": false`
- **THEN** `document_write == "not_requested"`, `recorded == true`, the
  document has no new checkpoint and the log has the row

#### Scenario: Both sinks fail
- **WHEN** both writes fail during `POST /api/plans/{id}/evaluate`
- **THEN** the response is still `201` with `recorded == false`, `db_write ==
  "failed"`, `document_write == "failed"`; the plans panel shows `Not recorded
  <phase> checkpoint — database: failed, document: failed`, never "Partially
  recorded" — "partially" is shown only when at least one sink saved

#### Scenario: Preview writes nothing
- **WHEN** `GET /api/plans/{id}/evaluate?phase=end` is called
- **THEN** neither the checkpoint log nor the document gains a row

#### Scenario: Recording onto an unready active document
- **WHEN** `POST /api/plans/{id}/evaluate` is called for a hand-edited active
  plan with no mission
- **THEN** the response is the seam's `422` readiness refusal, the document is
  byte-identical, the checkpoint log has no row, and `GET
  /api/plans/{id}/evaluate` (preview) is still `200`


### Requirement: Plan with architect journey
The Study Plans view SHALL offer a **Plan with architect** control beside
**New plan** (button name `Plan with architect`, `data-testid="plan-architect"`)
with an optional subject field (`data-testid="plan-architect-subject"`, labelled
for assistive technology) and a live status region
(`data-testid="plan-architect-status"`, `role="status"`, `aria-live="polite"`).
One activation SHALL cause exactly one `POST /api/session/start` carrying
`purpose: "planning"`, `topic: <the subject, trimmed, or "">` (never omitted;
the server resolves `""` to the fixed label `Study plan`), `origin: "study"`
and the start picker's own `energy`, `agent` and `transport`. The Plans view
SHALL NOT post, open a WebSocket, mount a terminal or listen for the console's
`study-session-start` event: it dispatches one `plan-architect-request` window
event and the Study Session view's session timer — the one owner of the start
POST, the 409 handling and the `study-session-start` event the live console
mounts on — starts the session and navigates the learner to the existing
console (`#study-session`), then reports the outcome back with exactly one
`plan-architect-result` event. A second activation while a launch is in flight
SHALL be a no-op. The Study Session view's `init()` SHALL register its window
listeners once even when called twice (Alpine auto-init plus `x-init`).

The live console SHALL carry a purpose label (`data-testid="console-purpose-label"`,
`role="status"`, `aria-live="polite"`) that is rendered only for a planning
session, read from `purpose` on the `201` body on a fresh start and from `GET
/api/session/state` on load-time adoption; a focus console SHALL render as
before. `GET /api/session/state` SHALL report `purpose` for every session it
describes — on the live-slot overlay and on the file-only path a CLI session
takes — with an explicit persisted `purpose` winning, a file whose persisted
`mode` is the planning persona's (`persona_mode_for("planning")`) reporting
`planning`, and anything else `focus`; the topic string SHALL never be
consulted. The launch SHALL create no plan and store no plan id (D-11). A
launch refused with the existing `409` conflict shape (`error`,
`study_session_id`, `topic`, `agent`, `detached`, `reattach_url`) SHALL land
the learner on the picker's recovery block with the reattach lever, not on a
second console. The manual **New plan** path SHALL be unchanged.

#### Scenario: One click, one POST, the existing console
- **WHEN** the learner types `SQL window functions` into the subject field and
  activates **Plan with architect**
- **THEN** exactly one `POST /api/session/start` is made with `purpose ==
  "planning"`, `topic == "SQL window functions"`, `origin == "study"`; the
  response is `201` with `purpose == "planning"` and a `ws_url`; the page
  navigates to `#study-session`; exactly one `study-session-start` event with
  `purpose == "planning"` is dispatched; exactly one WebSocket to the `ws_url`
  opens; exactly one console is visible and nothing is mounted in the Plans view

#### Scenario: No subject
- **WHEN** the subject field is empty and **Plan with architect** is activated
- **THEN** the request carries `topic == ""` and the `201` body's `topic` is
  `Study plan`

#### Scenario: Label survives a reload
- **WHEN** a planning session is live and the page is reloaded
- **THEN** the console re-adopts the session from `GET /api/session/state`,
  whose body has `purpose == "planning"`, and exactly one visible
  `console-purpose-label` reads as a planning session, before and after the
  reload

#### Scenario: CLI-started architect is labelled from its persisted mode
- **WHEN** the session state file was written by `studyloop plan architect`
  (`mode == "plan-architect"`, no `purpose` key) and `GET /api/session/state`
  is called
- **THEN** the body has `purpose == "planning"`; a file with `mode == "focus"`
  and `topic == "Study plan"` reports `focus`; a file carrying `purpose ==
  "focus"` beside `mode == "plan-architect"` reports `focus`

#### Scenario: The brief's structure, never its wording
- **WHEN** the fake PTY agent receives the persona of a Web-launched planning
  session
- **THEN** it contains, in order, `## Planning brief`, `### Interview`,
  `### Evidence from the learner's history`, `### Existing plans` and the
  architect body's `## Tooling` section, with `**Mode:** plan-architect` and no
  `Resuming Previous Session` section

#### Scenario: Nothing is created by the launch
- **WHEN** **Plan with architect** is activated
- **THEN** `GET /api/plans` is unchanged, the plans directory holds no new
  document, and the session state carries no `plan_id`

#### Scenario: Conflict is the existing shape with a reattach lever
- **WHEN** a session is live and `POST /api/session/start` is called again with
  `purpose: "planning"`
- **THEN** the response is `409` with `error`, `study_session_id`, `topic`,
  `agent`, `detached` and `reattach_url == <the live session's ws_url>`; and a
  Plans-view launch that meets that `409` shows the picker's `.picker-error`
  with the body's `error` and the `Reattach to this session` control, with no
  terminal mounted

#### Scenario: Manual New plan is unchanged
- **WHEN** the learner uses **New plan**, fills the form and creates the plan
- **THEN** the reader shows the plan, `GET /api/plans` counts one more, and no
  session was started
