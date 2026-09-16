## Purpose

Serve a local-first, no-build-step web dashboard (Alpine.js + HTMX,
FastAPI backend, `index.html` ~3.4k lines + `components.js` modules) for
starting study sessions, chatting live with the agent, reviewing generated
flashcards/quizzes, browsing course source material, tracking mastery, and
managing LLM provider credentials.

## Requirements

### Requirement: The PWA owns all chat-surface rendering
The server SHALL NOT send server-rendered HTML for ACP chat bubbles; it
forwards only raw ACP `session/update` events over the session WebSocket.
Markdown rendering (`marked`), sanitization (`DOMPurify`), and syntax
highlighting (`hljs`) all happen client-side.

#### Scenario: Agent response contains a script tag payload
- **WHEN** an agent-authored chat message contains
  `<script>`/`onerror=`/`javascript:` content
- **THEN** the marked → DOMPurify → hljs pipeline strips the executable
  payload before the message is inserted into the DOM (verified against a
  jsdom simulation with these three payload classes)

### Requirement: Explorer content routes are read-only and traversal-guarded
`GET /api/explorer/tree`, `.../courses/{id}/lessons`, and
`.../lesson/{id}/content` (`web/routes/explorer.py`) SHALL never write to
`content.base_path`, SHALL resolve every path with
`resolve().is_relative_to(base)`, and SHALL restrict readable suffixes to
`.md`, `.markdown`, `.txt`.

#### Scenario: Lesson ID crafted to escape the content base
- **WHEN** `GET /api/explorer/lesson/{lesson_id}/content` is called with a
  `lesson_id` containing `../` segments
- **THEN** the traversal guard rejects the resolved path before any file
  read occurs

### Requirement: Course Explorer tree is cached by a visible-source fingerprint
`GET /api/explorer/tree` SHALL cache the built provider/course tree on
`app.state` keyed by `_tree_fingerprint(base)`, which stats visible
providers/courses/source files while skipping dot-directories and
generated output subdirectories. Adding or deleting a nested course
invalidates the cache; writing a generated deck does not.

#### Scenario: A generated flashcard deck is written mid-session
- **WHEN** a new flashcard JSON file is written under an existing course's
  output directory
- **THEN** the Explorer tree cache is unaffected (the fingerprint ignores
  output subdirectories), and no unnecessary tree rebuild occurs

### Requirement: Explorer full-text search is a derived, rebuildable cache
`GET /api/explorer/search` SHALL query a separate SQLite FTS5 database
(`explorer_fts.db`, porter unicode61 tokenizer) that is lazily built and
incrementally refreshed on search, independent of `sessions.db`'s
migration system. Deleting `explorer_fts.db` SHALL NOT require a
migration to recover — it rebuilds on the next search call.

#### Scenario: explorer_fts.db is deleted while the server is running
- **WHEN** `explorer_fts.db` is deleted from disk and a search request
  arrives
- **THEN** `_run_fts_search` rebuilds the index from `content.base_path`
  before answering the query, with no migration step involved

### Requirement: Struggle marking writes lesson provenance for later scoped generation
`POST /api/history/struggling-topics` SHALL write `source_course`,
`source_section`, `source_publisher`, and `created_by='web'` onto
`study_progress` (migration v22), using the same `record_progress()` /
`get_struggling_topics()` helpers the agent session path uses, so the
Generate panel's "topic I'm struggling on" scope can resolve back to the
specific lesson.

#### Scenario: User marks a lesson as struggling from Course Explorer
- **WHEN** a user clicks "mark struggling" while reading a lesson in the
  Explorer panel
- **THEN** the write includes the lesson's course/section/publisher, and a
  subsequent Generate-panel request scoped to "struggling topics" can
  target that specific lesson rather than only a generic topic string

### Requirement: Generation progress streams over a per-job WebSocket
`POST /api/content/generate` SHALL return `202 {job_id, plan}` and start
`run_job` as a background asyncio task; `WS /api/content/generate/ws?job_id=...`
SHALL stream `started`, `task_complete` (per source×kind), and `all_done`
frames so a client can reconnect and resubscribe to a job in progress
without losing events already queued for it.

#### Scenario: Client disconnects and reopens the progress WebSocket mid-job
- **WHEN** the browser tab reloads while a generation job is still running
- **THEN** reopening the WS with the same `job_id` resumes receiving
  `task_complete`/`all_done` frames from the per-job queue rather than
  missing events emitted during the gap

### Requirement: Session picker vendors are content sources, not study topics
`GET /api/session/options` SHALL list a directory as a Course Vendor only
when it is a child of a courses root AND is not a configured topic's
`obsidian_path` (topics are session *targets*, never vendors). Vendors
sharing a name across multiple course roots SHALL render once in the
picker, while course discovery SHALL walk every same-name vendor
directory so no courses are lost.

#### Scenario: Topic directories live at vendor level under a study root
- **WHEN** configured topics (e.g. `Python`, `DevOps`) have note dirs
  directly under a study root that also holds vendor dirs
- **THEN** the `vendors` list contains only real vendors — no topic names,
  no duplicate entries — and `courses` includes courses from every
  same-name vendor directory across roots

### Requirement: Ending a session is confirmed in-page, never via native dialogs
The session stop control SHALL open an in-page confirm dialog
(`.end-confirm-overlay`) rather than a native `confirm()`; only the
explicit confirm action POSTs `/api/session/end`. Native dialogs are
banned on this path because Chrome auto-dismisses them in some focus
states (e.g. while the embedded ttyd terminal iframe holds focus), which
previously made agent sessions impossible to end.

#### Scenario: User cancels the end-session dialog
- **WHEN** the user clicks the stop button and then "Keep going" (or
  presses Escape)
- **THEN** no request is sent to `/api/session/end` and the session
  remains active

### Requirement: Review list mode-splits Flashcards and Quizzes from one shared component
The `reviewApp('flashcards' | 'quiz')` Alpine factory SHALL be
instantiated once per mode; `filteredCourses` gates the list on the
matching card-type count before applying the search filter, and
`groupedCourses` groups by the API's `publisher` field with collapsible
headers. `name` (not `publisher`) SHALL be the identity key for
`/api/cards`, config lookups, and the SM-2 review DB.

#### Scenario: Same course name exists under two publishers
- **WHEN** two distinct publisher-scoped course directories happen to
  share a display `name`
- **THEN** review/SM-2 state keys on `name`, so the two are treated as the
  same reviewable course even though `publisher` differs (a known
  identity-key choice, not a bug)

### Requirement: Settings → LLM Providers only persists verified credentials
The Settings panel SHALL call `GET /api/content/providers` to render one
row per provider by `auth_kind`, and SHALL only call
`POST/DELETE /api/content/secrets` to store a credential after
`POST /api/content/providers/<slug>/test` succeeds (api_key: live auth
call; Bedrock: AWS-cred check; Ollama: real generation call).

#### Scenario: Test-and-save with an invalid API key
- **WHEN** a user submits an invalid API key and clicks Test & Save
- **THEN** the live verification call fails and the key is never written
  to `secrets.bin`

### Requirement: The app lands on the Today one-next-action view
The nav store's default view SHALL be `today`, rendering exactly one
primary recommendation from `GET /api/now` (concept, estimated minutes,
action type, reason, one Start button), a collapsible alternates list, a
context-aware resume shortcut (live-session rejoin > `GET /api/session/last`
topic > last review deck from `GET /api/history`), and parked-topic pickup
chips from `GET /api/backlog`. Hash links to other views (`#flashcards`,
`#quizzes`, …) SHALL keep working via `nav.init()`.

#### Scenario: Open the app with no hash
- **WHEN** the learner opens `/` with no location hash
- **THEN** `Alpine.store('nav').current` is `today` and one next-action
  card is visible — the learner never has to decide "what now" unaided

### Requirement: Starting a 4th topic requires parking one first
When `GET /api/backlog` reports `active_count >= max_active` and the learner
starts a **study** session on a topic NOT in the active set, the start SHALL
be intercepted by an in-page `.park-first-overlay` (never a native dialog)
listing the active topics; choosing one calls `POST /api/backlog/demote`
(which makes the row the oldest pending entry — re-parking the same
question is an INSERT OR IGNORE no-op and would not free the slot) and then
proceeds with the start. Escape or "Keep all" cancels without starting.

Body Double starts are exempt: they SHALL NOT query `GET /api/backlog` and
SHALL NOT render the overlay, because body doubling is not a new study thread
(ADR-0003).

#### Scenario: Fourth topic blocked until one is parked
- **WHEN** three topics are active and the learner starts a new, fourth
  topic from the study-session picker
- **THEN** the park-first overlay appears in-page, and the session only
  starts after one active topic is demoted to the parking lot

#### Scenario: Body Double start with three topics already active
- **WHEN** three topics are active and the learner starts a Body Double
  session
- **THEN** no `/api/backlog` request is issued and the session starts without
  the overlay

### Requirement: Quick-park captures a tangent without leaving the current view
A globally visible "Park a thought" control (and the `p` shortcut outside
input fields) SHALL open an in-page input overlay that POSTs to
`/api/backlog/park` and confirms via the shared toast; `nav.current` SHALL
NOT change (flow protection).

#### Scenario: Parking a tangent mid-review
- **WHEN** the learner quick-parks "how do generators pause?" while on the
  flashcards view
- **THEN** the thought lands in the parking lot, a toast confirms it, and
  the flashcards view stays active

### Requirement: Course lists never flash a false empty state
The review course list SHALL render a loading indicator ("Checking your
content…") while `/api/courses` is in flight and SHALL only show "No
courses found" after the fetch resolves empty (`coursesLoading` tri-state
in `reviewApp()`).

#### Scenario: Switching to Flashcards with slow content discovery
- **WHEN** the learner switches to the Flashcards tab while the course scan
  is still running
- **THEN** they see the loading line, never a transient "No courses found"
  that self-replaces seconds later

### Requirement: Live agent consoles are addressed by origin, never broadcast
`liveAgentConsole(origin)` SHALL accept an origin identifier and SHALL ignore
`study-session-start` / `study-session-stop` window events whose
`detail.origin` (defaulting to `'study'` when absent) does not match its own.
Every dispatcher of those events SHALL set `origin`. Alpine initialises
`x-data` on elements hidden by `x-show`, so multiple console instances are
live simultaneously — visibility is not liveness, and an unaddressed broadcast
would mount a second xterm and open a second WebSocket to the same PTY
session. (ADR-0002)

#### Scenario: Body Double session starts while the study console exists
- **WHEN** a `study-session-start` event with `origin: 'body-double'` is
  dispatched and both consoles are initialised
- **THEN** only the `body-double` console leaves `terminalMode: null`, and
  exactly one WebSocket is constructed

#### Scenario: Study session starts while the Body Double console exists
- **WHEN** a `study-session-start` event with `origin: 'study'` is dispatched
- **THEN** the Body Double console remains idle (`terminalMode: null`) and
  opens no WebSocket

#### Scenario: Stop is likewise addressed
- **WHEN** a `study-session-stop` event carrying `origin: 'study'` is
  dispatched while a Body Double session is live
- **THEN** the Body Double console does not tear down its terminal or socket

### Requirement: The Study Session picker has no session-type selector
The study-session picker SHALL NOT render a session-type control, and the
frontend SHALL NOT carry a `sessionType` state field or a `sessionType` key in
the `study-session-start` event detail. Session mode is determined by which
view the learner is in, not by a dropdown value. `GET /api/session/options`
and the `list_session_options` MCP tool SHALL continue to publish a
`session_types` key (contract shape asserted by
`test_mcp_session_parity.py`) containing the single `study` entry.

Rationale: the former `body_double` option was written in three places and
read in none — `StartSessionRequest` has no such field, so selecting it
changed nothing and left the learner on the Study Session view. Body Double is
now a first-class view with its own picker (capability `body-double-session`).

#### Scenario: Rendering the study-session picker
- **WHEN** the study-session picker is rendered with no session active
- **THEN** no session-type `<select>` is present, and `sessionType` appears
  nowhere in `index.html` or `components.js`

#### Scenario: MCP and web option payload shape
- **WHEN** `GET /api/session/options` or the `list_session_options` MCP tool
  is called
- **THEN** the response still contains a `session_types` key, and its only
  entry is `{"label": "Study Session", "value": "study", ...}`

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
