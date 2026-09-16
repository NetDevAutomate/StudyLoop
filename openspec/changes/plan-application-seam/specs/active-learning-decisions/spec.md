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
before `InvalidField`).

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

#### Scenario: Document failure reported independently
- **WHEN** the document save raises
- **THEN** `document_write == "failed"`, `db_write == "saved"`, the log holds
  the row, and the document is unchanged

### Requirement: Active-plan guidance is a deterministic read (not yet consumed)
`get_active_guidance(*, today=None)` SHALL return a frozen `ActiveGuidance`
holding one `ActivePlanGuidance` per plan whose status is `active`, ordered by
`plan_id`, with: the `PlanSummary`; `next_milestone` (the first unchecked
milestone, or `None`); `match_keys`, a `frozenset` of `normalise_match_key`
over the topics and every milestone's concepts (casefold, punctuation replaced
by spaces, whitespace collapsed — matching is equality on the key, never a
substring test); `target_urgency` in `overdue` (days until target `< 0`),
`soon` (`0..7`), `later` (`> 7`) or `undated`; `energy_floor`; a
`completion_action` string only when the plan has milestones and every one is
done; and per-plan `warnings` for defects worked around (no milestones, a
target date that is not a date). Documents the store could not parse SHALL be
named in the collection's `warnings`. Non-active plans are skipped. `today`
pins the urgency computation for frozen-clock callers and defaults to the UTC
date.

This view exists so that the `now` decision engine (issue #10, Phase 3) has
one plan-static read to consume. **Nothing consumes it yet**: `studyloop now`
and the Today card are unchanged by this phase, and `docs/study-plans.md`'s
"does not do yet" list stays as it is until #10 ships.

#### Scenario: One entry per active plan, ordered, others skipped
- **WHEN** plans `zeta` (active), `alpha` (active), `mid` (active) and one
  plan in each of `draft`, `paused`, `complete`, `abandoned` exist
- **THEN** `get_active_guidance().plans` has three entries in the order
  `alpha`, `mid`, `zeta`, and repeated calls return equal views

#### Scenario: Match keys and next milestone
- **WHEN** an active plan has topics `["SQL", "Data-Engineering"]` and
  milestones with concepts `["Window-Function"]` (done) and `["RANK vs
  DENSE_RANK", "dense rank"]`, `["window frame"]`
- **THEN** `match_keys == {"sql", "data engineering", "window function",
  "rank vs dense rank", "dense rank", "window frame"}` and `next_milestone`
  is index `1`

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

### Requirement: Adapters reach study plans only through the seam
No module under `studyloop/cli`, `studyloop/web/routes` or `studyloop/mcp`
SHALL import `studyloop.planning.store`, `.index`, `.authoring` or
`.evaluation` (directly, relatively, as a whole-package handle, or by name
through `from studyloop.planning import …` for the names those modules
contribute). `tests/test_architecture_plan_seam.py` SHALL enforce this by
parsing every adapter module, SHALL reject a planted bypass in a temp copy of
an adapter, and SHALL check its explicit name list against what
`studyloop.planning` actually re-exports from the four modules.

#### Scenario: Planted bypass is rejected
- **WHEN** `from studyloop.planning.store import save_plan` is appended to a
  copy of `web/routes/plans.py` and the checker runs on the copy
- **THEN** the checker reports a violation; on the real tree it reports none

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
