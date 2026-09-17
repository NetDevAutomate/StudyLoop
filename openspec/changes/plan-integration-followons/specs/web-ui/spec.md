## MODIFIED Requirements

### Requirement: Plan with architect journey
The Study Plans view SHALL offer a **Plan with architect** control beside
**New plan** (button name `Plan with architect`, `data-testid="plan-architect"`)
with an optional subject field (`data-testid="plan-architect-subject"`, labelled
for assistive technology), an optional brain-dump textarea
(`data-testid="plan-architect-braindump"`, labelled, `maxlength` equal to the
server's `BRAIN_DUMP_MAX_CHARS`) and a live status region
(`data-testid="plan-architect-status"`, `role="status"`, `aria-live="polite"`).
One activation SHALL cause exactly one `POST /api/session/start` carrying
`purpose: "planning"`, `topic: <the subject, trimmed, or "">` (never omitted;
the server resolves `""` to the fixed label `Study plan`), `brain_dump: <the
textarea's text, trimmed>` **only when it is non-blank** (a blank dump sends no
key, so the server's "no dump" and "empty dump" are one case), `origin:
"study"` and the start picker's own `energy`, `agent` and `transport`. The
brain dump SHALL never be folded into `topic` and SHALL never ride a `focus`
start. The Plans view SHALL NOT post, open a WebSocket, mount a terminal or
listen for the console's `study-session-start` event: it dispatches one
`plan-architect-request` window event (detail `{purpose, topic, brainDump}`)
and the Study Session view's session timer — the one owner of the start POST,
the 409 handling and the `study-session-start` event the live console mounts on
— starts the session and navigates the learner to the existing console
(`#study-session`), then reports the outcome back with exactly one
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

Abandoning a launch is the console's existing End control (the ■ button, then
the in-page confirmation — never a native dialog): fired as soon as the launch
has been accepted, it SHALL leave no live slot, no plan document, no
`plan_id`, no planning label, and at most one WebSocket ever opened.
Navigating away is **not** the abandon path: a closed socket detaches with a
grace period by design, so an accidental reload cannot kill a live session.

The architect's one-question-at-a-time protocol is asserted as persona text
(owner decision D-B): the browser and unit tests prove the brief — including
the brain dump — is delivered to the agent process; no test asserts how a live
model behaves with it, and the docs say so.

#### Scenario: One click, one POST, the existing console
- **WHEN** the learner types `SQL window functions` into the subject field and activates **Plan with architect**
- **THEN** exactly one `POST /api/session/start` is made, with `purpose == "planning"`, `topic == "SQL window functions"`, `origin == "study"` and no `brain_dump` key
- **AND** the response is `201` with `purpose == "planning"` and a `ws_url`
- **AND** the page navigates to `#study-session`, exactly one `study-session-start` event fires with `purpose == "planning"`, exactly one WebSocket is opened, one console is visible and nothing is mounted in the Plans view

#### Scenario: The brain dump reaches the architect
- **WHEN** the learner types a multi-line brain dump into the textarea, leaves the subject blank and activates the control
- **THEN** the one POST carries `brain_dump` equal to the trimmed text and `topic == ""`, the `201` names the topic `Study plan`
- **AND** the persona the fake agent received contains `### Learner's brain dump` with every dump line quoted (`> …`), `**Topic:** Study plan`, and `GET /api/session/state` carries neither the key nor the text

#### Scenario: No subject
- **WHEN** the learner activates the control with an empty subject
- **THEN** the request carries `topic == ""` and the `201` body's `topic` is `Study plan`

#### Scenario: Label survives a reload
- **WHEN** a planning session is running and the learner reloads the page
- **THEN** the console shows exactly one visible purpose label reading "planning" both before and after the reload

#### Scenario: CLI-started architect is labelled from its persisted mode
- **WHEN** the session state file carries `mode == "plan-architect"` and no `purpose` key
- **THEN** `GET /api/session/state` reports `purpose == "planning"`; a file with `mode == "focus"` and topic `Study plan` reports `focus`

#### Scenario: The brief's structure, never its wording
- **WHEN** a planning launch reaches the fake PTY agent
- **THEN** the persona it received contains, in order, `## Planning brief`, `### Interview`, `### Evidence from the learner's history`, `### Existing plans`, `## Tooling`, with `**Mode:** plan-architect` and no `Resuming Previous Session`

#### Scenario: Nothing is created by the launch
- **WHEN** the control is activated and the console mounts
- **THEN** `GET /api/plans` is unchanged, the plans directory holds no new document, and the session state carries no `plan_id`

#### Scenario: Abandoning a launch mid-flight leaves no session and no plan
- **WHEN** the learner activates the control and, as soon as the `201` arrives, uses the console's End control and confirms
- **THEN** `GET /api/session/state` has no `study_session_id` and no planning purpose, `GET /api/plans` and the plans directory are unchanged, exactly one `study-session-start` fired, at most one WebSocket was opened, and no purpose label is visible

#### Scenario: Conflict is the existing shape with a reattach lever
- **WHEN** a session is already running and the learner activates the control
- **THEN** the POST returns the existing `409` body and the picker's recovery block appears with the reattach lever; no second console mounts

#### Scenario: Manual New plan is unchanged
- **WHEN** the learner uses **New plan**, fills the form and submits
- **THEN** the plan is created and listed and no session is started

## ADDED Requirements

### Requirement: Plan list rows carry readiness and the sidebar marks a husk
Every row of `GET /api/plans` SHALL be `PlanSummary.to_json_dict()` and SHALL
carry `ready` — the same verdict the readiness gate judges every write by —
as its eighteenth key, so a client can tell an active-but-unready plan (a
"husk", item 3 / D-C) from the list alone, with no per-row round-trip. The
Plans sidebar SHALL render one mark (`data-testid="sidebar-plan-husk"`, the
glyph `!`, `role="img"` with an `aria-label` and a `title` naming the
condition and both exits) inside `.sidebar-plan-meta` for a row whose
`status` is `active` and whose `ready` is `false`, and SHALL render it for no
other row. The mark is computed from the row's own `ready`; the sidebar
SHALL make no further request to decide it. Colour SHALL come from the theme's
own tokens and SHALL not be the only carrier of the information.

#### Scenario: List payload carries ready
- **WHEN** `GET /api/plans` is served for one ready active plan and one active
  document with no mission
- **THEN** every row has 18 keys, the ready plan's row has `ready: true`, the
  husk's row has `ready: false`, and `?status=active` returns both

#### Scenario: Sidebar marks the husk and only the husk
- **WHEN** the Plans sidebar renders those rows
- **THEN** exactly one `sidebar-plan-husk` mark is present, on the husk's row,
  and the ready plan's row has none

### Requirement: PATCH carries the mission to the one RevisePlan
`PATCH /api/plans/{id}` SHALL accept `why`, `success`, `constraints` and
`out_of_scope` beside the fields it already carries (item 3b, design §3b), and
SHALL translate them onto the same single `RevisePlan` — the route validates
and writes nothing itself. An absent key is `None` ("leave as is"); a
supplied list replaces the whole list. The seam's refusals map as they always
have: a bare string where a list belongs is the seam's `InvalidField` → `400`
naming the field; a write whose resulting document would be active but not
ready is `422` with the `readiness` body and nothing written. The `PATCH`
response is the write receipt (`updated`, `plan`, `readiness`); the mission is
read back from `GET /api/plans/{id}`. With this the Web UI's whole-document
`PATCH markdown` is no longer the only mission writer.

#### Scenario: Partial mission on a husk is 422; the whole mission lands and the row flips to ready
- **WHEN** `PATCH /api/plans/husk` is sent `{"why": "…"}` on an active plan
  with no mission, and then `{"why": "…", "success": ["…"], "constraints":
  ["…"], "out_of_scope": ["…"]}`
- **THEN** the first is `422` with `detail.ready == false` and
  `detail.blockers == ["No observable success criteria."]` and the document
  is unchanged; the second is `200` with `plan.status == "active"`,
  `plan.ready == true` and `readiness.blockers == []`, `GET /api/plans/husk`
  returns the four mission values, and the `GET /api/plans` row for `husk`
  has `ready: true`

#### Scenario: A string where a list belongs is the seam's 400
- **WHEN** `PATCH /api/plans/{id}` is sent `{"success": "one string"}`
- **THEN** the response is `400` naming `success` and the document is
  unchanged
