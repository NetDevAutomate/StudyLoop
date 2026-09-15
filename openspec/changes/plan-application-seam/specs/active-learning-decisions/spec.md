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
