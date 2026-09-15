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
