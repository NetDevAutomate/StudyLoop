## Purpose

Expose StudyLoop's study/review state to any MCP-compatible client (desktop
apps, other agent CLIs) as a set of stdio tools, independent of the browser
UI. Backed by `FastMCP` (`mcp[cli]` SDK) with lifespan-managed DB/settings
access. This is one of two MCP servers in the repo; `session-db-mcp`
(cross-agent session memory, documented in `agents/mcp/README.md` and
`docs/session-memory.md`) is
separate and out of scope for this capability.

## Requirements

### Requirement: studyloop-mcp registers a fixed set of study tools
The system SHALL register exactly 32 tools via `register_tools(mcp)`
(`mcp/tools.py`), each under its own name: the 23 study, review, lifecycle
and course-explorer tools — `list_courses`, `get_study_context`,
`record_study_progress`, `generate_flashcards`, `generate_quiz`,
`get_chapter_text`, `get_study_backlog`, `get_topic_suggestions`,
`get_study_history`, `list_session_options`, `end_session`,
`record_topic_progress`, `log_topic`, `get_due_cards`, `log_review_outcome`,
`get_next_action`, `get_active_topics`, `log_struggle`, `get_lesson_tree`,
`read_lesson`, `search_lessons`, `get_concept_context`,
`record_plan_learning` — plus the nine study-plan lifecycle tools of the two
study-plan requirements in this specification, exactly
`studyloop.mcp.inventory.PLAN_TOOL_NAMES`. The published inventory is the
table in `agents/mcp/README.md` (see "The studyloop-mcp inventory is
published where the harness registration is").

#### Scenario: Client lists available tools
- **WHEN** an MCP client connects to the `studyloop-mcp` stdio server and
  requests its tool list
- **THEN** exactly these 32 tools are returned, each once, matching the table
  in `agents/mcp/README.md`; the full stdio handshake + tools/list +
  tools/call round-trip is locked by `tests/test_mcp_stdio_smoke.py`
  (integration-marked), which pins the count, the nine plan tools and the
  core names

### Requirement: Review-loop tools enable a complete quiz cycle without the browser
`get_due_cards(course=None, limit=20)` SHALL return real serialized
`CardProgress` entries (per-course via `get_due(course)`, or aggregated
across `list_course_summaries()` when no course is given);
`log_review_outcome(course, card_type, card_hash, correct, ...)` SHALL
delegate to `record_review()` and reject `card_type` outside
`{"flashcard","quiz"}` with `ToolError`; `get_next_action(...)` SHALL
delegate to `learning.decision.build_now_plan()` (the same engine as
`/api/now`); `get_active_topics()` SHALL split pending backlog items at
`MAX_ACTIVE_TOPICS`; `log_struggle(...)` SHALL park with
`source="struggled"`.

#### Scenario: Desktop client runs a full review loop
- **WHEN** an MCP client calls `get_due_cards` → presents cards →
  `log_review_outcome` per answer → `get_next_action`
- **THEN** each outcome is persisted through the same SM-2 path the web UI
  uses, and the next-action recommendation comes from the shared decision
  engine, not a hardcoded string

### Requirement: Course paths are validated against traversal
The system SHALL resolve any tool-supplied `course` argument through
`_safe_course_dir(base, course, subdir)` (`mcp/tools.py:26`), which
resolves the joined path and rejects it via `ToolError` if the result is
not `is_relative_to(base.resolve())`.

#### Scenario: Tool called with a traversal-shaped course argument
- **WHEN** a tool such as `get_chapter_text` is called with
  `course: "../../etc"`
- **THEN** `_safe_course_dir` raises `ToolError("Invalid course path: ...")`
  before any filesystem read occurs

### Requirement: get_study_context aggregates review state for one course
`get_study_context(course)` SHALL call `get_due()` and `get_stats()`
(`services/review.py`) and return `due_cards`, `total_reviews`,
`unique_cards`, `mastered`, and `due_today` — a summary, not the card
content itself.

#### Scenario: Agent checks a course before starting a session
- **WHEN** an MCP client calls `get_study_context("python")`
- **THEN** the response contains counts only (no card front/back text);
  retrieving actual due-card content requires a separate, currently
  unimplemented tool (tracked as the highest-value desktop-MCP gap in
  `docs/audit/2026-07-11-comprehensive-review.md` §6)

### Requirement: Generation tools save agent-authored content, not pipeline output
`generate_flashcards(course, chapter, content)` and
`generate_quiz(course, chapter, content)` SHALL persist LLM-agent-supplied
JSON directly to disk; they SHALL NOT invoke the provider pipeline in
`content/generators/` (that pipeline is triggered only via the CLI and the
web Generate panel).

#### Scenario: MCP client calls generate_flashcards
- **WHEN** an MCP client calls `generate_flashcards` with a `content`
  payload it authored itself
- **THEN** that payload is written to the course's flashcards directory
  as-is; no Bedrock/OpenAI/Anthropic/Ollama/Stub provider call occurs

### Requirement: Desktop MCP clients can serve due-card content for review
The system SHALL add a `get_due_cards(course, limit, kind)` tool returning
full card front/back content (joining `get_due()` with the review loader),
and a `submit_card_answer(course, card_hash, correct)` tool that records
the SM-2 outcome and returns the card's updated next-review interval, so
an MCP client can run a complete quiz turn without the browser.

#### Scenario: Desktop agent runs a review turn
- **WHEN** a Claude Desktop or Codex client calls `get_due_cards` for a
  course, presents a card to the user in chat, judges the user's answer,
  and calls `submit_card_answer`
- **THEN** the response includes the updated next-review interval so the
  agent can tell the user when the card returns — the same outcome a
  browser review session produces

### Requirement: Desktop MCP clients have Course Explorer read parity
The system SHALL add `get_lesson_tree(provider?, course?)`,
`read_lesson(lesson_id)`, and `search_lessons(query)` tools that are pure
wrappers over the existing `web/routes/explorer.py` internals, reusing the
same traversal guard as `_safe_course_dir` / the explorer's
`is_relative_to(base)` check.

#### Scenario: Desktop agent browses course material
- **WHEN** a desktop MCP client calls `get_lesson_tree` then
  `read_lesson(lesson_id)` for a specific lesson
- **THEN** the returned tree and lesson content match what
  `GET /api/explorer/tree` and `GET /api/explorer/lesson/{id}/content`
  would return in the browser, including the traversal guard rejecting
  any `lesson_id` containing `../` segments

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
refusal SHALL be a `ToolError` mapped by the same `_plan_tool_error` helper the
nine plan lifecycle tools use (before this fold the tool mapped inline, without
a kind prefix): `PlanNotReady` SHALL render as `not_ready:
plan is not ready to activate: <blocker>; <blocker>…` (with the already-active
"pause it or repair" suffix when the plan was active) so the agent can tell
the learner what to repair (the plan-application-seam design, §2: "ToolError
containing blockers");
`PlanNotFound`, `InvalidPlanId` and `InvalidField` (the store's title/heading
rule) SHALL render as `not_found: …`, `invalid_id: …` and `invalid: …`
followed by their message, with the domain error chained as `__cause__`. The
success shape is unchanged by the fold.

The six read/write plan tools are the requirement "Study-plan discovery and
authoring tools"; the three progression tools (`set_study_plan_milestone`,
`evaluate_study_plan`, `delete_study_plan`) are "Study-plan progression and
deletion tools". The stdio smoke test pins the exact production inventory (32
unique names), the nine plan tools and the core names.

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
- **THEN** a `ToolError` is raised whose message starts with `not_ready: plan
  is not ready to activate: `, contains each blocker string from the
  `ReadinessView` and the "already active … pause it or repair" hint, and
  chains the `PlanNotReady` as its cause

#### Scenario: Store rule and id refusals are tool errors
- **WHEN** the title is blank, or the body contains a `###` line, or the plan
  id is unknown or malformed
- **THEN** a `ToolError` is raised reading `invalid: …`, `not_found: …` or
  `invalid_id: …` followed by the seam's message, and no record is added

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

### Requirement: Study-plan progression and deletion tools
`register_tools(mcp)` SHALL register three further study-plan tools in the
production inventory — completing the nine plan lifecycle tools — each a thin adapter
that makes exactly one `studyloop.planning.PlanApplication` call, imports no
storage, index, authoring or evaluation module (D-6), and maps every seam
refusal through the same `<kind>: <message>` `ToolError` mapping as the six
above (the domain error chained as `__cause__` — an in-process requirement on
the adapter, checked by the delegation tests; the stdio transport carries the
prefixed refusal text only, since JSON-RPC does not serialise an exception
chain):

| Tool | Seam call |
|---|---|
| `set_study_plan_milestone(plan_id, index, done)` | `apply(SetMilestone(plan_id, index, done))` → `PlanDetail.to_json_dict()` |
| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | `assess(AssessPlan(plan_id, phase, study_id, record))` → `AssessmentResult.to_json_dict()` |
| `delete_study_plan(plan_id, confirmed=False)` | `apply(DeletePlan(plan_id, confirmed))` → `DeleteResult.to_json_dict()` (`{"deleted": true, "plan_id": "<id>"}`) |

`set_study_plan_milestone` SHALL take `done` as a required boolean with no
default and forward it as given — set, not toggle: the tool SHALL make no
preliminary read and compute no opposite, so a second identical call returns
the same plan, raises nothing and rewrites nothing. An index the plan does
not have (past the end or negative) is the seam's `InvalidMilestone`,
rendered `invalid_milestone: …`; a set on an active-but-unready document is
the seam's `PlanNotReady`, rendered `not_ready: … — the plan is already
active; pause it or repair the blockers before writing`, and nothing is
written in either case.

`evaluate_study_plan` SHALL call `assess`, never `apply` (`AssessPlan` is not
a `PlanIntent`), SHALL default `record` to `False`, and SHALL NOT expose
`append_to_plan` (the seam's default, `True`, applies when recording). The
response SHALL be the `AssessmentResult` view — `evaluation`, `markdown`,
`db_write`, `document_write`, `recording_complete`, `warnings` — with each
sink reported **as the seam reports it** (`not_requested`, `saved`, `failed`),
never flattened to a boolean and never an invented `saved`. A preview
(`record=False`) SHALL write to neither sink: the document is byte-identical
afterwards and the checkpoint log is unchanged. With `record=True` a failed
sink SHALL surface as `failed` with `recording_complete: false` and the seam's
warning string in `warnings` — a reported outcome, never an exception and
never a bare success. Recording on an active plan that is unready SHALL be
refused (`not_ready: …`) before either sink is touched; an unknown `phase`
is the seam's `invalid: phase must be one of …`, judged after the plan
exists (`not_found:` first).

`delete_study_plan` SHALL keep `confirmed` as an ordinary boolean defaulting
to `False` in its schema — not required, not constrained to a literal `true`
— and SHALL forward it unchanged: an unconfirmed call is the seam's
`InvalidField`, rendered `invalid: deleting '<id>' requires confirmed=True`,
and the plan still exists byte-identical afterwards. A confirmed delete
removes the document and its derived index row and SHALL leave the plan's
checkpoint history in the sessions database readable. A missing plan is
`not_found:` before the confirmation is judged.

The production inventory SHALL be exactly 32 unique tool names — 23 at
`0a20a796` plus the nine design-§4 plan tools, `record_plan_learning` being
one of the 23 — and the stdio smoke test SHALL assert that exact count, the
nine plan names, `record_plan_learning` and the core names over the real
transport.

#### Scenario: A retried milestone set is a no-op
- **WHEN** `set_study_plan_milestone(<id>, 0, true)` is called twice on a
  ready plan with two milestones, then `set_study_plan_milestone(<id>, 0,
  false)`
- **THEN** the first call returns the plan with `milestones[0].done: true` and
  `plan.milestone_done: 1`; the second returns an equal response, raises
  nothing and leaves the document byte-identical; the third reopens the
  milestone (`done: false`, `milestone_done: 0`)

#### Scenario: Milestone set on an active-but-unready document is refused
- **WHEN** `set_study_plan_milestone("husk", 0, true)` is called for an active
  document with a milestone but no mission or success criteria
- **THEN** a `ToolError` is raised starting `not_ready: plan is not ready to
  activate: `, naming every blocker and containing `already active` and
  `pause it or repair`, and the document is byte-identical afterwards; an
  index the plan does not have (`2`, `9`, `-1`) is `invalid_milestone: No
  milestone at index …` with nothing written

#### Scenario: Evaluate preview writes nothing
- **WHEN** `evaluate_study_plan(<id>, "mid")` is called (the default
  `record=False`) on an active plan
- **THEN** the response carries the evaluation (`phase: "mid"`, a verdict, a
  non-empty `markdown`) with `db_write` and `document_write` both
  `not_requested` and `recording_complete: true`; the plan document is
  byte-identical afterwards; `get_study_plan(<id>, include_history=True)`
  returns an empty `history` and an empty `checkpoints` table

#### Scenario: Evaluate record reports both sinks
- **WHEN** `evaluate_study_plan(<id>, "end", study_id="sess-9", record=True)`
  is called on an active plan
- **THEN** `db_write` and `document_write` are `saved`, `recording_complete`
  is `true`, the checkpoint log holds one `end` row attributed to `sess-9`
  (visible through `get_study_plan(include_history=True)`), and the
  document's `checkpoints` table holds one `end` row

#### Scenario: A failed sink is a warning, not a success and not an error
- **WHEN** the checkpoint log write fails during
  `evaluate_study_plan(<id>, "start", record=True)`
- **THEN** the tool returns (no `ToolError`) with `db_write: "failed"`,
  `document_write: "saved"`, `recording_complete: false` and `checkpoint not
  saved to the database` in `warnings`; the document holds the checkpoint and
  the log does not

#### Scenario: Recording on an active-but-unready plan is refused before either sink
- **WHEN** `evaluate_study_plan("husk", "start", record=True)` is called for
  an active document that is unready
- **THEN** a `ToolError` starting `not_ready: ` with the "pause it or repair"
  hint is raised, the document is byte-identical and the log unchanged; the
  same call with `record=False` succeeds with both sinks `not_requested`

#### Scenario: Delete requires confirmation
- **WHEN** `delete_study_plan(<id>)` or `delete_study_plan(<id>,
  confirmed=False)` is called
- **THEN** a `ToolError` reading `invalid: deleting '<id>' requires
  confirmed=True` is raised, the document exists byte-identical afterwards
  and `list_study_plans()` still counts it; the tool's schema has
  `confirmed` as a boolean defaulting to `false`

#### Scenario: Confirmed delete keeps the checkpoint history
- **WHEN** a checkpoint has been recorded for `<id>` and
  `delete_study_plan(<id>, confirmed=True)` is called
- **THEN** the response is `{"deleted": true, "plan_id": "<id>"}`, the
  document is gone, `list_study_plans()` is empty, `get_study_plan(<id>)` is
  `not_found: …`, and the checkpoint history for `<id>` still holds the
  recorded row; `delete_study_plan("ghost")` is `not_found:` whether or not
  confirmed, and a traversal id is `invalid_id:`

#### Scenario: Every refusal of the three is one prefixed ToolError
- **WHEN** the seam raises `PlanNotFound`, `InvalidPlanId`, `PlanConflict`,
  `InvalidField`, `InvalidMilestone`, or an unmapped `PlanError` from
  `apply` (milestone, delete) or `assess` (evaluate)
- **THEN** the tool raises exactly one `ToolError` reading `not_found: …`,
  `invalid_id: …`, `conflict: …`, `invalid: …`, `invalid_milestone: …` or
  `plan_error: …` followed by the seam's message, with the domain error
  chained as `__cause__`; responses of the three are fresh containers on
  every call

#### Scenario: The production inventory is exactly 32 with the nine plan tools
- **WHEN** a stdio client performs the handshake and `tools/list` against
  `python -m studyloop.mcp.server` (no `--dev`)
- **THEN** exactly 32 unique names are advertised, including
  `list_study_plans`, `get_study_plan`, `get_planning_interview`,
  `create_study_plan`, `update_study_plan`, `set_study_plan_status`,
  `set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan`,
  `record_plan_learning` and the core tools

### Requirement: The studyloop-mcp inventory is published where the harness registration is
The full `studyloop-mcp` tool list SHALL be published in `agents/mcp/README.md`
under "studyloop-mcp (Study tools)" — the same page that carries every
harness's registration snippet (Claude Code `mcp.json`, Kiro `study-mentor.json`,
Codex `~/.codex/config.toml`, OpenCode, Grok Build `~/.grok/config.toml`) — as
one table equal to the production registry, with the count stated in prose.
Both SHALL be pinned to the registry by
`tests/test_docs_plan_integration_contract.py`, so a tool added to or removed
from `mcp/tools.py` fails a test rather than leaving a stale page. The
learner-facing reach of the study-plan tools per harness (which harness
definitions attach the server; the Kiro/Claude CLI fallback) SHALL be stated
in `docs/agent-install.md`, "Study-plan tools over MCP". No other page SHALL
carry a second copy of the inventory or a tool count.

#### Scenario: A new contributor reads the inventory
- **WHEN** someone reads `agents/mcp/README.md` to decide what an agent can do
  through `studyloop-mcp`
- **THEN** they find every registered tool in one table (32 rows), the stated
  count, and the registration snippet for their harness — and the contract
  test fails if the table or the count ever disagrees with `register_tools`
