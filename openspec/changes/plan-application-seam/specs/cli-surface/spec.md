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
milestone on '<id>': <reason>`. When the refused `PlanNotReady` carries
`already_active` (the stored plan was active and incomplete before the write —
a `record`, `milestone` or `evaluate --record` on a hand-edited document), the
mapping SHALL add a line telling the learner to pause the plan
(`studyloop plan status <id> paused`) or repair the blockers, then retry.
Every mapping SHALL exit `1` and print no traceback. `studyloop plan list` SHALL route a `browse` refusal through the
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


### Requirement: Every plan command reads and writes through the seam
`studyloop plan new|interview|evaluate|milestone|record|reindex` SHALL
delegate to `PlanApplication` like `list|show|status` already do, and
`cli/_plan.py` SHALL import no storage, index, authoring or evaluation module
(the architecture guard `tests/test_architecture_plan_seam.py` fails
otherwise). `plan new` SHALL be one `CreatePlan` whose `status` is `"active"`
with `--activate` and `"draft"` without; the `--activate` refusal SHALL be the
seam's `PlanNotReady` reached through `_fail_for` — the command holds no
readiness decision of its own — and a refused create SHALL write nothing.
`plan new --json` SHALL keep `{"plan", "readiness", "path"}`. `plan interview`
SHALL be `prepare_planning` and SHALL keep emitting `{"questions", "seed"}`
(no `existing_plans` key is added here). `plan reindex` SHALL call
`PlanApplication.reindex()`. The other CLI readers of plans — `exercise
from-milestone` and `brain publish`'s plan selection — SHALL read through
`inspect` / `browse`.

#### Scenario: Create with --activate on a ready plan
- **WHEN** `studyloop plan new --title "Glue ETL" --why … --success …
  --milestone … --activate` is run
- **THEN** exactly one `CreatePlan(status="active")` is applied, the exit
  code is `0`, and the stored plan's status is `active`

#### Scenario: Create with --activate on an unready plan writes nothing
- **WHEN** `studyloop plan new --title Empty --activate` is run
- **THEN** the exit code is `1`, the output contains `Cannot activate 'empty'`
  and the blockers, and the plans directory holds no document

### Requirement: The CLI milestone command is an idempotent set
`studyloop plan milestone <id> <index> [--done|--undone]` SHALL apply one
`SetMilestone`. With a flag the state is set as asked, so running the same
command twice is safe; without a flag the current state is read through the
seam and its opposite is set. A negative index SHALL be refused exactly like
one past the end (`No milestone at index -1 …`, exit `1`, document unchanged).

#### Scenario: Set twice stays set, no flag toggles
- **WHEN** `plan milestone <id> 0 --done` is run twice and then `plan
  milestone <id> 0` once
- **THEN** the outputs report `1/2`, `1/2`, `0/2`, and the three applied
  intents were `SetMilestone(done=True)`, `SetMilestone(done=True)`,
  `SetMilestone(done=False)`

### Requirement: Recorded checkpoints report a complete, partial or absent recording
`studyloop plan evaluate <id> --record` SHALL call `assess(record=True)`,
print the evaluation Markdown, and then print `Checkpoint recorded.` only when
every requested sink was saved. When a sink failed the command SHALL exit `0`
— the evaluation succeeded — and name each sink: `Checkpoint partially
recorded — database: <state>, document: <state>` when at least one sink
saved, and `Checkpoint not recorded — database: failed, document: <state>`
when none did ("partially" is only honest when something landed). Without
`--record` the command is `assess(record=False)` and writes nothing; `--json`
keeps emitting the evaluation dict unchanged.

#### Scenario: Database sink fails
- **WHEN** the checkpoint log write returns `False` during `plan evaluate <id>
  --record`
- **THEN** the exit code is `0`, the output contains `partially recorded`,
  `database: failed` and `document: saved`, and the plan document carries
  the checkpoint

#### Scenario: Both sinks fail
- **WHEN** the checkpoint log write returns `False` and the document save
  raises during `plan evaluate <id> --record`
- **THEN** the exit code is `0`, the output contains `Checkpoint not recorded`,
  `database: failed` and `document: failed`, never `partially recorded`, and
  the plan document carries no checkpoint

### Requirement: Learning records are one revision through the seam
`studyloop plan record <id> --title T [--body B]` SHALL apply one
`RevisePlan(learning_record=LearningRecordSpec(...))` and no preliminary read.
`created` in the `--json` output SHALL be the mutation's own outcome —
`PlanDetail.learning_record_outcome.created`, the store's
`append_learning_record` verdict relayed by the seam — never inferred from an
`inspect` taken before the revision (a record another writer files in that
window must be reported `created: false`), and the command carries no copy of
the store's identity rule. A retry with the same title and body SHALL report
`created: false` with the original `number`. An empty title SHALL be the
seam's `Invalid value: …` refusal, exit `1`.

#### Scenario: Retry reports created false
- **WHEN** `plan record <id> --title Insight --body prose --json` is run twice
- **THEN** both exit `0`; the first reports `created: true, number: 1`; the
  second reports `created: false, number: 1`; the plan holds one record

#### Scenario: A record filed by another writer just before the mutation
- **WHEN** the same record is written through the store immediately before
  the command's `RevisePlan` runs
- **THEN** the command exits `0` with `created: false, number: 1`, made no
  `inspect` call, and the plan holds one record
