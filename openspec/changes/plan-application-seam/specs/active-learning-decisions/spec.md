## ADDED Requirements

### Requirement: Activation is readiness-gated on every entry path
The study-plan domain SHALL expose one application seam,
`studyloop.planning.PlanApplication`, and it SHALL be the only writer any
adapter (Web routes, CLI commands, MCP tools) uses for study plans. `apply`
SHALL evaluate readiness whenever the *resulting* document would be `active` —
create with `status="active"` (`CreatePlan`), import of a document whose
frontmatter says `active` (`ImportDocument`), replacement of an existing
document with one whose frontmatter says `active` (`ReplaceDocument`), and a
lifecycle transition to `active` (`TransitionLifecycle`) — and SHALL raise
`PlanNotReady` carrying a `ReadinessView` **before any canonical write** when
the plan has no mission `why`, no success criteria, or no milestones. Readiness
SHALL be computed by exactly one function (`authoring.readiness`), reached only
through the seam; no adapter SHALL carry a readiness check of its own.

The seam's read side (`browse`, `inspect`, `prepare_planning`) SHALL return
frozen, tuple-only views whose `to_json_dict()` returns a fresh container on
every call and serialises `PlanSummary` and `ReadinessView` to exactly the
`StudyPlan.summary()` and `authoring.readiness()` key sets. Domain failures
SHALL be exceptions with no CLI, HTTP or MCP vocabulary: `PlanNotFound`,
`InvalidPlanId`, `PlanConflict`, `InvalidField`, `PlanNotReady`,
`InvalidMilestone`.

#### Scenario: Create with status active on an unready plan
- **WHEN** `apply(CreatePlan(title="Vague", answers={}, status="active"))` is
  called
- **THEN** `PlanNotReady` is raised, its `readiness.ready` is `false` with a
  non-empty `blockers` tuple, and no document exists afterwards

#### Scenario: Whole-document replacement whose frontmatter says active
- **WHEN** `apply(ReplaceDocument(plan_id, markdown))` is called with a
  document whose frontmatter says `active` and which has no milestones
- **THEN** `PlanNotReady` is raised and the stored document is byte-identical
  to what it was before the call

#### Scenario: Status transition to active on an unready plan
- **WHEN** `apply(TransitionLifecycle(plan_id, "active"))` is called for a
  draft whose readiness reports blockers
- **THEN** `PlanNotReady` is raised and `inspect(plan_id).summary.status` is
  still `draft`

#### Scenario: Every door raises the same refusal
- **WHEN** the same unready document is refused via `CreatePlan`,
  `TransitionLifecycle`, `ReplaceDocument` and `ImportDocument`
- **THEN** the four `ReadinessView` payloads are equal apart from `plan_id`,
  and `str(exc)` is `plan is not ready to activate` for each

#### Scenario: Replacement keeps identity
- **WHEN** `apply(ReplaceDocument(plan_id, markdown))` is called with a
  document whose frontmatter names a different `id` and `created`
- **THEN** the persisted plan keeps the original `plan_id` and `created`, the
  content edits are applied, and no second document appears

#### Scenario: Several ready plans may be active
- **WHEN** two ready plans are created with `status="active"` and a third
  ready plan is transitioned to `active`
- **THEN** all three succeed and `browse(status="active")` returns all three

#### Scenario: Duplicate id without overwrite
- **WHEN** `apply(CreatePlan(..., plan_id="demo"))` is called and `demo`
  already exists with `overwrite=False`
- **THEN** `PlanConflict` is raised and the existing plan is unchanged; with
  `overwrite=True` the plan is replaced

#### Scenario: Browse order is the store's and is deterministic
- **WHEN** `browse()` is called over active and draft plans
- **THEN** active plans come first, then ascending `updated`, ties broken by
  plan id, and repeated calls return equal tuples

### Requirement: Partial checkpoint recording is reported, never silent
`evaluate_and_record` SHALL treat a `False` return from
`index.record_checkpoint` exactly as it treats a raised failure: by appending
`checkpoint not saved to the database` to the evaluation's `warnings`. The
index's swallow-and-return-`False` remains its best-effort policy; the caller
SHALL honour the answer. A successful database write SHALL add no warning.

#### Scenario: Database write reports failure by returning False
- **WHEN** `record_checkpoint` returns `False` during `evaluate_and_record`
- **THEN** the returned evaluation's `warnings` contains an entry mentioning
  `database`, and the evaluation is still returned with a valid verdict

#### Scenario: Database write succeeds
- **WHEN** `record_checkpoint` returns `True`
- **THEN** no warning mentioning `database` is present


### Requirement: Milestone set is idempotent and refuses indices the plan lacks
`apply(SetMilestone(plan_id, index, done))` SHALL set — not toggle — one
milestone's `done` state on a loaded candidate, judge the resulting document
with the same readiness gate every write uses when the plan is active, and
save once when the state changed. Applying the same intent twice SHALL leave
the same document *byte for byte*: a retry that asks for the state the
milestone already has writes nothing and leaves `updated` untouched (the
gate still runs first).
`index` is a 0-based position: an index past the end **or negative** SHALL
raise `InvalidMilestone` before any write. A plan that does not exist SHALL
raise `PlanNotFound` before the index is judged.

#### Scenario: Set is idempotent
- **WHEN** `SetMilestone(plan_id, 0, done=True)` is applied twice
- **THEN** the first application saves exactly once and the second saves
  nothing (document bytes and `updated` unchanged), the milestone is done
  after both, and `SetMilestone(plan_id, 0, done=False)` undoes it

#### Scenario: Negative index
- **WHEN** `SetMilestone(plan_id, -1, done=True)` is applied
- **THEN** `InvalidMilestone` is raised and the document is byte-identical

#### Scenario: Ticking a milestone on an unready active document
- **WHEN** `SetMilestone` is applied to a hand-edited active plan that has no
  mission
- **THEN** `PlanNotReady` is raised — the resulting document would be
  active-but-unready — and nothing is written

### Requirement: Deletion is confirmed and retains the checkpoint log
`apply(DeletePlan(plan_id, confirmed))` SHALL raise `InvalidField` unless
`confirmed` is `True` (after `PlanNotFound` for an unknown id), remove the
canonical document and its derived index row, retain every row of the durable
checkpoint log for that id, and return a frozen `DeleteResult(plan_id)` whose
`to_json_dict()` is `{"deleted": true, "plan_id": "<id>"}` — `apply` returns a
`DeleteResult` for this intent and a `PlanDetail` for every other, because a
detail cannot describe a plan that no longer exists.

#### Scenario: Unconfirmed delete
- **WHEN** `DeletePlan(plan_id)` is applied with `confirmed` left `False`
- **THEN** `InvalidField` is raised and the document is unchanged

#### Scenario: Confirmed delete keeps history
- **WHEN** a plan with one recorded checkpoint is deleted with `confirmed=True`
- **THEN** a `DeleteResult` is returned, `inspect(plan_id)` raises
  `PlanNotFound`, the derived index no longer lists the plan, and
  `checkpoint_history(plan_id)` still returns the row

### Requirement: Assessment reports each recording sink independently
`assess(AssessPlan(plan_id, phase, study_id, record, append_to_plan))` SHALL
return a frozen `AssessmentResult` carrying a `PlanEvaluationView` (whose
`to_json_dict()` equals `PlanEvaluation.to_dict()` key for key and whose
`markdown` is the rendered checkpoint block), `db_write` and `document_write`
each in `not_requested | saved | failed`, and the evaluation's `warnings`.
`record=False` SHALL call `evaluate_plan` and write to neither sink;
`record=True` SHALL call the Phase-0 `evaluate_and_record` — the seam adds no
second checkpoint writer — and read its two recording warnings back into the
sink fields. A failed sink SHALL be a reported outcome on the result, never an
exception (no `PartialRecording`), because the evaluation succeeded.
`recording_complete` is `True` when no requested sink failed — vacuously true
for a preview. The plan SHALL be found before the phase is judged (`PlanNotFound`
before `InvalidField`). Because appending the checkpoint re-saves the plan
document, `record=True, append_to_plan=True` on an *active* plan SHALL run the
same readiness gate every other write runs — before either sink is touched —
and raise `PlanNotReady` (with `already_active=True`) for an active-but-unready
document; a preview or a database-only recording persists no document and is
not gated.

#### Scenario: Preview writes neither sink
- **WHEN** `assess(AssessPlan(id, "mid", record=False))` is called
- **THEN** both sink fields are `not_requested`, no checkpoint row exists in
  the log or the document, and `recording_complete` is `True`

#### Scenario: Both sinks saved
- **WHEN** `assess(AssessPlan(id, "end", study_id="s1"))` is called and both
  writes succeed
- **THEN** both sink fields are `saved`, `recording_complete` is `True`, and
  the row is present in the log (with `study_id == "s1"`) and in the document

#### Scenario: Database failure reported, document still written
- **WHEN** the log write returns `False` or raises
- **THEN** `db_write == "failed"`, `document_write == "saved"`,
  `recording_complete` is `False`, `warnings` contains `checkpoint not saved
  to the database`, and the evaluation carries a valid verdict

#### Scenario: Recording onto an unready active document is refused first
- **WHEN** `assess(AssessPlan(id, "start"))` is called for a hand-edited active
  plan with no mission
- **THEN** `PlanNotReady` is raised before the checkpoint log is written, the
  document is byte-identical, and the same call with `record=False` or
  `append_to_plan=False` succeeds

#### Scenario: Document failure reported independently
- **WHEN** the document save raises
- **THEN** `document_write == "failed"`, `db_write == "saved"`, the log holds
  the row, and the document is unchanged

### Requirement: Active-plan guidance is a deterministic read
`get_active_guidance(*, today=None)` SHALL return a frozen `ActiveGuidance`
holding one `ActivePlanGuidance` per plan whose status is `active`, ordered by
`plan_id`, with: the `PlanSummary`; the plan's `ReadinessView` (`readiness`) —
the same view every write is judged by, so an active-but-unready document (a
hand edit or pre-gate import with no mission) is still listed but its entry
says that every `SetMilestone`, `RevisePlan` or recorded assessment on it will
be `PlanNotReady` until it is paused or repaired, with no second `inspect` per
plan; `next_milestone` (the first unchecked
milestone, or `None`); `match_keys`, a sorted, de-duplicated `tuple` of
`normalise_match_key`
over the topics and every milestone's concepts (casefold, punctuation replaced
by spaces, whitespace collapsed — matching is equality on the key, never a
substring test; a tuple, not a `frozenset`, because D-3 binds every view to
tuples and a consumer that wants a set builds one); `target_urgency` in `overdue` (days until target `< 0`),
`soon` (`0..7`), `later` (`> 7`) or `undated`; `energy_floor`; a
`completion_action` string only when the plan has milestones and every one is
done; and per-plan `warnings` for defects worked around (no milestones, a
target date that is not a date). Every document SHALL be enumerated by its
storage id and loaded through the identity-pinning seam path, so an entry's
id is the file's, never an untrusted frontmatter `id`; documents that cannot
be read or parsed SHALL be named in the collection's `warnings`, in id order.
Non-active plans are skipped. `today`
pins the urgency computation and the nested summary's `days_until_target` —
one effective date for the whole payload — for frozen-clock callers and
defaults to the UTC
date.

This view is the one plan-static read the `now` decision engine consumes
(issue #10, next requirement).

#### Scenario: One entry per active plan, ordered, others skipped
- **WHEN** plans `zeta` (active), `alpha` (active), `mid` (active) and one
  plan in each of `draft`, `paused`, `complete`, `abandoned` exist
- **THEN** `get_active_guidance().plans` has three entries in the order
  `alpha`, `mid`, `zeta`, and repeated calls return equal views

#### Scenario: Match keys and next milestone
- **WHEN** an active plan has topics `["SQL", "Data-Engineering"]` and
  milestones with concepts `["Window-Function"]` (done) and `["RANK vs
  DENSE_RANK", "dense rank"]`, `["window frame"]`
- **THEN** `match_keys == ("data engineering", "dense rank", "rank vs dense
  rank", "sql", "window frame", "window function")` — sorted, de-duplicated —
  and `next_milestone` is index `1`

#### Scenario: Urgency buckets
- **WHEN** the target date is 30 or 1 day(s) ago, today, 1, 7, 8 or 90 days
  ahead, or unset
- **THEN** `target_urgency` is `overdue`, `overdue`, `soon`, `soon`, `soon`,
  `later`, `later`, `undated` respectively

#### Scenario: Every milestone done
- **WHEN** an active plan's milestones are all `done`
- **THEN** `next_milestone` is `None` and `completion_action` is a non-empty
  string naming the plan

#### Scenario: Malformed documents become warnings
- **WHEN** an active plan has no milestones and `target_date: someday`, and an
  unreadable file sits beside it
- **THEN** the guidance is returned; the plan's entry has `next_milestone ==
  None`, `completion_action == None`, `target_urgency == "undated"` and
  warnings naming the milestones and the date; the collection's `warnings`
  name the unreadable file

#### Scenario: Identity is the file, not the frontmatter
- **WHEN** `alpha.md` carries frontmatter `id: beta` beside a real `beta.md`,
  and two unreadable files sit beside a healthy plan
- **THEN** the entries are `alpha`, `beta` (and `healthy`) with unique ids and
  their own titles — never two `beta` entries; `readiness.plan_id` matches
  the entry id; the collection's `warnings` name exactly the unreadable files
  in id order and never the readable mismatched one; `inspect(<entry id>)`
  resolves to the same document

#### Scenario: An unready active plan is listed with its blockers
- **WHEN** an active document has topics and milestones but no mission `why`
  and no success criteria, beside a ready active plan
- **THEN** both appear in `.plans`; the husk's `readiness.ready` is `false`
  and its `readiness.blockers` name the missing why and success criteria; the
  ready plan's `readiness.ready` is `true`; `load_plan` ran once per document;
  and `to_json_dict()` carries the `readiness` block per entry

### Requirement: The now engine is plan-aware with tested ranking rules
`studyloop.learning.decision.build_now_plan` SHALL remain the only ranker of
study actions and SHALL consume active plans through exactly one call to
`PlanApplication().get_active_guidance(today=…)`, where `today` is the date
of the same instant `generated_at` records. It SHALL apply these rules, in
this order (design §3, D-5):

1. Candidates are collected as before; a failure to read plans at all SHALL
   degrade to a `warnings` entry, never a failed recommendation.
2. The energy capability is `low|medium|high → 3|6|10`. For an active plan
   whose `energy_floor` exceeds it, the next milestone SHALL be listed in
   `energy_deferred` and SHALL NOT become a candidate; plan-related due recall
   and struggle repair stay eligible and plan-related.
3. A candidate is plan-related when `normalise_match_key` of its concept,
   topic or course **equals** one of the plan's `match_keys`; no substring
   test. It names the plan's next milestone (`milestone_index`) only when the
   key equals one of that milestone's concepts **and** the plan is eligible —
   ready and within the energy capability; a topic or finished-milestone
   match, or any match on an energy-deferred or active-but-unready plan,
   carries `milestone_index = None` (plan-related repair), so a payload never
   names a milestone it also reports as deferred or that the seam would
   refuse to tick.
4. Scoring is today's scoring plus one bounded bias for plan-related
   candidates: within one urgency class plan-related beats unrelated, and a
   globally more-urgent unrelated candidate still wins — a bias, not a filter.
5. When no collected candidate represents an eligible (ready, energy-permitted)
   plan's next milestone, one `conversation` candidate SHALL be synthesised
   for it (source `study_plan:<plan_id>:<index>`, concept = the milestone's
   first concept or its title, topic = the plan's first topic), scored below
   every due and repair class. A learner with an active plan and no evidence
   is therefore sent to the plan, and `starter` is `false`.
6. After de-duplication every matching `PlanRef(plan_id, milestone_index)`
   SHALL be attached to each ranked action, ordered by target urgency
   (`overdue`, `soon`, `later`, `undated`) → most recent `updated` → `plan_id`,
   keeping the most specific milestone per plan.
7. When primary + alternates hold no plan-backed action and an eligible one
   whose estimate fits the requested time exists further down, it SHALL
   replace the last alternate only; the primary is never re-ranked by plans.
8. A fully-checked active plan SHALL appear in `completion_actions` and SHALL
   be neither matched nor synthesised. An active-but-unready plan SHALL be
   listed and matched (bias and a `milestone_index = None` reference) but
   never synthesised and never named as a milestone, with a warning naming
   its blockers.

`NowPlan` gains `active_plans` (ordered as rule 6), `energy_deferred`,
`completion_actions` and `warnings`; `LearningRecommendation` gains
`plan_refs: tuple[PlanRef, ...] = ()`. `to_json_dict()` SHALL omit each of
these when empty, so a learner with no active plan receives the pre-#10
payload **byte for byte** — pinned by `tests/golden/now_plan_no_active.json`,
captured before any of this shipped. Renderers (`studyloop now`, `GET
/api/now`, the Today card, the daily recap) SHALL show plan relevance and
energy deferral from these fields and SHALL NOT re-rank. Ranking tests prove
ranking compliance, not learner benefit (D-16); a five-scenario human rubric
receipt accompanies the change.

#### Scenario: No active plan is byte-identical to the golden
- **WHEN** no active plan exists (an empty plans directory, or only a draft)
  and `build_now_plan()` runs with a frozen clock in an empty world
- **THEN** the serialised `to_json_dict()` equals
  `tests/golden/now_plan_no_active.json` byte for byte, and no
  `active_plans`, `energy_deferred`, `completion_actions`, `warnings` or
  `plan_refs` key is present

#### Scenario: Matching due concept outranks unrelated of the same urgency
- **WHEN** an active plan's milestone names `window function` and two due
  items are two points apart, `decorators` (unrelated) ahead
- **THEN** `window function` is primary with `plan_refs == (PlanRef(plan, 0),)`
  and `decorators` is the first alternate with no refs

#### Scenario: A more-urgent unrelated item still wins
- **WHEN** the only collected candidate is an unrelated due item and the
  plan's next milestone is unrepresented
- **THEN** the due item is primary and the synthesised milestone
  (`study_plan:<id>:0`) is an alternate with a lower score

#### Scenario: Energy below the floor defers the milestone, keeps repair
- **WHEN** energy is `low` (3/10), the plan's `energy_floor` is 5, its next
  milestone is `Frames` and a struggle repair on a finished milestone's
  concept is collected
- **THEN** the repair is primary with `PlanRef(plan, None)`,
  `energy_deferred` names `(plan, 1, 5, 3)`, and no `study_plan:` candidate
  exists; at `medium` energy nothing is deferred and the milestone is
  synthesised

#### Scenario: A deferred milestone is never named by a reference
- **WHEN** energy is `low`, the plan's `energy_floor` is 5 and the only
  collected candidate's concept equals the next milestone's concept
- **THEN** the candidate is primary with `PlanRef(plan, None)` while
  `energy_deferred` names that milestone; at `medium` energy the same
  candidate carries `PlanRef(plan, 0)` and nothing is deferred

#### Scenario: An unready active plan is matched but never named
- **WHEN** an active plan has no mission and no success criteria (unready)
  and a collected candidate equals its next milestone's concept
- **THEN** the candidate is primary with `PlanRef(plan, None)`, no
  `study_plan:` candidate exists, the plan's `active_plans` entry has
  `ready == False` and `eligible == False`, and one warning names the plan,
  its blockers and "pause or repair"

#### Scenario: No substring matching
- **WHEN** a milestone titled `Window functions deep dive` has no concepts
  and candidates `window functions deep dive tutorial`, `window` and
  `joins`/`SQL` are collected
- **THEN** only `joins` is plan-related (`PlanRef(plan, None)` via the topic
  `sql`, casefolded); the other two carry no refs

#### Scenario: Every matching plan is referenced, in order
- **WHEN** six active plans (overdue, soon, later, three undated with
  distinct and tied `updated`) all name the primary's concept
- **THEN** `plan_refs` lists all six ordered overdue → soon → later → undated
  by latest `updated` then `plan_id`, and `active_plans` is in the same order

#### Scenario: A plan-backed action is preserved when energy allows
- **WHEN** four unrelated due items outrank everything and the plan's
  `energy_floor` is 5
- **THEN** at `medium` energy the synthesised milestone replaces the second
  alternate (the primary and first alternate are unchanged); at `low` energy
  the alternates are the unrelated items and `energy_deferred` names the
  milestone

#### Scenario: Fully-checked plan emits a completion action
- **WHEN** an active plan's every milestone is done and an unrelated due item
  is collected
- **THEN** `completion_actions` names the plan, the due item is primary with
  no refs, no `study_plan:` candidate exists, and the plan's `active_plans`
  entry has `next_milestone_index == None`

#### Scenario: Renderers show, never re-rank
- **WHEN** `studyloop now --energy low`, `GET /api/now?energy=low` and the
  daily recap run against the energy-deferral fixture
- **THEN** each names the primary the engine chose, the plan it advances, and
  the deferred milestone; with no plan the CLI panel prints no plan lines,
  `GET /api/now` equals the golden, and the recap's `plan_context` is absent

### Requirement: Adapters reach study plans only through the seam
No module under `studyloop/cli`, `studyloop/web/routes` or `studyloop/mcp`
SHALL import `studyloop.planning.store`, `.index`, `.authoring` or
`.evaluation` (directly, relatively, as a whole-package handle, by wildcard
`from studyloop.planning import *`, by a literal string naming a forbidden
module or the whole package, by name through `from studyloop.planning import …`
for the names those modules contribute, or transitively through one of the
four allowed seam modules — `from studyloop.planning.application import
store`). `tests/test_architecture_plan_seam.py` SHALL enforce this by
parsing every adapter module, SHALL reject each planted bypass in a temp copy
of an adapter, and SHALL check its explicit name list against what
`studyloop.planning` actually re-exports from the four modules.

#### Scenario: Planted bypass is rejected
- **WHEN** `from studyloop.planning.store import save_plan`, `from
  studyloop.planning import *`, `importlib.import_module("studyloop.planning")`
  or `from studyloop.planning.application import store` is appended to a copy
  of `web/routes/plans.py` and the checker runs on the copy
- **THEN** the checker reports a violation for each; on the real tree it
  reports none

### Requirement: The learning-record rule has one copy
Learning-record validation (non-empty title; no H1–H3 lines in the body) and
idempotent numbering SHALL live in one function,
`studyloop.planning.store.append_learning_record(plan, title, body=, status=)`,
applied to an in-memory plan. The store's `record_learning` SHALL wrap it
(load → append → save only when created, so a duplicate leaves the file's
bytes untouched) and the seam's `RevisePlan(learning_record=…)` SHALL call it
on the revision candidate, translating its `ValueError` to `InvalidField`.
A revision whose only content is a learning record that already exists SHALL
write nothing (no save, bytes and `updated` untouched — the guarantee the
store's `record_learning` always gave); a duplicate record beside another
field change SHALL still be one save, and an empty revision remains the
Phase-1 "touch".

#### Scenario: The seam follows the store's rule
- **WHEN** `store.append_learning_record` is replaced by a function that
  raises `ValueError("the store said no")` and `RevisePlan(learning_record=…)`
  is applied
- **THEN** `InvalidField` carrying that message is raised and no record is
  added
