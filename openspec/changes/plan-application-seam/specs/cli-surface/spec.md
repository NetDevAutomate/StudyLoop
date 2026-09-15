## ADDED Requirements

### Requirement: Activation is readiness-gated on every entry path
`studyloop plan status <id> active` SHALL apply a `TransitionLifecycle` intent
through `PlanApplication` rather than checking readiness itself, so the refusal
a learner sees in the terminal is produced from the same `ReadinessView` the
Web API turns into its `422` body. A refused activation SHALL exit `1`, print
`Cannot activate '<id>' — the plan is incomplete.` followed by the blockers and
then the nudges as `•` bullets, print no traceback, and leave the document on
disk byte-identical. `studyloop plan list` and `studyloop plan show` SHALL
read through the seam (`browse` / `inspect`) with their `--json` shapes
unchanged: `list --json` emits the `StudyPlan.summary()` key set per plan;
`show --json` emits `{"plan", "mission", "milestones": [{"title", "done",
"concepts"}], "readiness"}`.

#### Scenario: Status transition to active on an unready plan
- **WHEN** `studyloop plan status vague-plan active` is run for a draft with
  no mission, success criteria or milestones
- **THEN** the exit code is `1`, the output contains `Cannot activate` and the
  word `Mission`, contains no `Traceback`, and `studyloop plan show
  vague-plan --json` still reports `"status": "draft"`

#### Scenario: The CLI refusal and the Web refusal are the same refusal
- **WHEN** the same unready draft is refused via `studyloop plan status <id>
  active` and via `PATCH /api/plans/{id}` with `{"status": "active"}`
- **THEN** the CLI's `•` bullets, in order, equal the Web `detail.blockers`
  followed by `detail.nudges`, and neither surface has written to the document

#### Scenario: Create with --activate on an unready plan
- **WHEN** `studyloop plan new --title Empty --activate` is run
- **THEN** the exit code is `1` and the output contains `Cannot activate`;
  no active plan is created

#### Scenario: A ready plan activates
- **WHEN** `studyloop plan status <id> active` is run for a plan with a
  mission `why`, a success criterion and a milestone
- **THEN** the exit code is `0`, the output is `<id> → active`, and `plan
  show <id> --json` reports `"status": "active"`

#### Scenario: Unknown id on the seam-backed commands
- **WHEN** `studyloop plan show nope` or `studyloop plan status nope paused`
  is run
- **THEN** the exit code is `1`, the output contains `No study plan with id`
  and no `Traceback`


### Requirement: The CLI maps every seam refusal to one line and exit 1
Every `studyloop plan` command that reads or writes through `PlanApplication`
SHALL catch `PlanError` and map it in one place (`_fail_for`): `PlanNotFound`
→ `No study plan with id '<id>'. Try: studyloop plan list`; `PlanNotReady` →
`Cannot activate '<id>' — the plan is incomplete.` followed by the blockers
and nudges; `PlanConflict` → `A study plan with id '<id>' already exists.
Choose another id.`; `InvalidPlanId` → `Invalid plan id '<id>': <reason>`;
`InvalidField` → `Invalid value: <reason>`; `InvalidMilestone` → `No such
milestone on '<id>': <reason>`. Every mapping SHALL exit `1` and print no
traceback. `studyloop plan list` SHALL route a `browse` refusal through the
same mapping.

#### Scenario: A refusal reaching plan list is a message, not a traceback
- **WHEN** `studyloop plan list --status draft` is run and the seam refuses the
  filter with `InvalidField`
- **THEN** the exit code is `1`, the output contains the seam's reason and no
  `Traceback`

#### Scenario: Each refusal has its own line
- **WHEN** `studyloop plan status <id> active` is refused with `PlanConflict`,
  `InvalidField`, `InvalidPlanId`, `InvalidMilestone` or `PlanNotReady`
- **THEN** the exit code is `1` in every case, the output contains the
  mapping's distinguishing text (`already exists`, `Invalid value:`, `Invalid
  plan id`, `No such milestone`, `Cannot activate '<id>'`), and no `Traceback`
