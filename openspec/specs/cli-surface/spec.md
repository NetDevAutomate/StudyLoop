## Purpose

Define the observable contract of the `studyloop` CLI shell: lazy
command loading for startup performance, the registered command
namespace (groups vs leaf commands), installed console-script entry
points, optional-extra gating, and shared output conventions. This
spec does NOT cover the behaviour of individual commands — those are
owned by `spaced-repetition-review`, `content-generation`,
`voice-tts`, `live-session-orchestration`, `health-and-diagnostics`,
`active-learning-decisions`, `web-ui`, and other sibling specs.

## Requirements

### Requirement: Commands are lazy-loaded to keep startup cost constant
The root `cli()` group (`cli/__init__.py`) SHALL use `LazyGroup`
(`cli/_lazy.py`) so that command modules are imported only when
invoked. `LazyGroup._resolve()` defers `importlib.import_module()`
until `get_command()` is called for a specific name, ensuring that
`studyloop --help` and `studyloop --version` never import heavy
dependencies (pymupdf, FastAPI, mcp, textual, boto3).

#### Scenario: Printing top-level help with no optional extras installed
- **WHEN** a user runs `studyloop --help` with only the base
  dependencies (`click`, `rich`, `pyyaml`, `pexpect`,
  `python-dotenv`) installed
- **THEN** the command completes without ImportError and lists all
  registered command names — no optional-extra module is imported

#### Scenario: Invoking a command triggers its module import
- **WHEN** a user runs `studyloop content split ...`
- **THEN** `LazyGroup._resolve("content")` imports
  `studyloop.cli._content` (and only that module) to obtain the
  `content_group` Click group object

### Requirement: Every lazy_subcommands target must resolve to a valid Click command or group
The `lazy_subcommands` dict in `cli/__init__.py` maps command names
to dotted `"module:attribute"` import paths. Every entry SHALL
resolve via `importlib.import_module(modname)` + `getattr(mod,
attr_name)` to an instance of `click.BaseCommand`. There is no
graceful fallback — a broken target propagates `ImportError` or
`AttributeError` directly to the user.

#### Scenario: A developer adds a new command with a typo in the import path
- **WHEN** `lazy_subcommands` contains an entry pointing to a
  non-existent module or attribute
- **THEN** invoking that command raises an unhandled `ImportError` or
  `AttributeError` — the CLI does not silently drop the command

### Requirement: The command namespace is partitioned into groups and leaf commands
The root `cli()` SHALL register both leaf commands (e.g. `now`,
`review`, `study`, `doctor`, `park`, `web`) and group commands
(e.g. `content`, `session`, `recap`, `mastery`, `practice`,
`bridge`, `backlog`, `config`, `install`) via the same
`lazy_subcommands` dict. The user-facing name is the dict key,
which MAY differ from the group's internal `name=` argument (e.g.
`_topics.py` declares `@click.group("topics")` but is registered
as `"backlog"`).

#### Scenario: User invokes a group without a subcommand
- **WHEN** a user runs `studyloop content` with no subcommand
- **THEN** Click prints the group's help text and lists available
  subcommands — no action is taken

#### Scenario: Lazy registration name overrides internal group name
- **WHEN** `_topics.py` declares `@click.group("topics")` but is
  registered as `"backlog": "studyloop.cli._topics:topics_group"`
- **THEN** the user invokes it as `studyloop backlog list`, not
  `studyloop topics list`

### Requirement: Two workspace packages install distinct console_scripts entry points
The `studyloop` package (`packages/studyloop/pyproject.toml`)
SHALL install `studyloop` (`studyloop.cli:cli`), `studyloop-mcp`
(`studyloop.mcp.server:main`), and `studyloop-fake-agent`
(`studyloop.testing.fake_agent:main`). The `agent-session-tools`
package (`packages/agent-session-tools/pyproject.toml`) SHALL install
`session-export`, `session-query`, `session-maint`, `session-sync`,
`tutor-checkpoint`, `study-speak`, and `session-db-mcp` as separate
entry points.

#### Scenario: Installing with all extras
- **WHEN** a user installs `studyloop[all]`
- **AND** the workspace resolver finds `agent-session-tools`
- **THEN** all entry points from both packages are available

### Requirement: Two workspace packages are joined by a uv workspace and the sessions extra pulls both
The two packages SHALL be independent installables joined by a `uv`
workspace; the `sessions` optional extra on `studyloop` declares
`agent-session-tools` as a workspace dependency so a single
`uv tool install studyloop[sessions]` pulls both.

#### Scenario: Installing studyloop without the sessions extra
- **WHEN** a user installs `studyloop` without the `[sessions]` extra
- **THEN** only `studyloop`, `studyloop-mcp`, and
  `studyloop-fake-agent` are on PATH — `session-export` and
  `session-query` are not available

### Requirement: Optional extras gate command bodies, not command registration
Optional dependencies (`web`, `content`, `mcp`, `bedrock`,
`notebooklm`, `tui`) are declared in
`packages/studyloop/pyproject.toml` `[project.optional-dependencies]`.
Commands that need these extras SHALL defer their imports to function
bodies rather than module top-level, so the command always appears in
`studyloop --help` regardless of installed extras.

#### Scenario: A bare install with no extras still imports the CLI
- **WHEN** the built wheel is installed into a fresh venv with no extras
  and `studyloop --version` and `studyloop doctor --help` are run
- **THEN** both exit `0`: importing `studyloop.cli` pulled in nothing
  beyond the hard dependencies

### Requirement: Optional extras — a missing extra is an install hint or an unhandled ImportError
When invoked
without the required extra, the command SHALL either catch
`ImportError` and print a human-readable install hint (as `web` does:
`"Install: uv pip install 'studyloop[web]'"`) or allow the
`ImportError` to propagate unhandled (as `content split` does when
`pymupdf` is missing).

#### Scenario: Running `studyloop web` without FastAPI installed
- **WHEN** `uvicorn` is not importable (the `web` extra is missing)
- **THEN** the command prints
  `"The web server requires FastAPI.\nInstall: uv pip install 'studyloop[web]'"`
  and exits without traceback

#### Scenario: Running `studyloop content split` without pymupdf
- **WHEN** `pymupdf` is not installed (the `content` extra is
  missing)
- **THEN** the `from studyloop.content.splitter import ...` inside
  the command body raises `ImportError` — there is no explicit
  catch at that call site, so the user sees a traceback

### Requirement: The CLI is invocable via console_scripts and python -m studyloop.cli
`cli/__main__.py` SHALL call `cli()` directly, enabling `python -m
studyloop.cli` as an alternative to the `studyloop` console script.
There is no top-level `studyloop/__main__.py`, so `python -m
studyloop` does NOT work — only the `studyloop.cli` sub-package
supports `-m` invocation.

#### Scenario: Running via python -m
- **WHEN** a user runs `python -m studyloop.cli --version`
- **THEN** it prints the package version and exits identically to
  `studyloop --version`

#### Scenario: Attempting python -m studyloop
- **WHEN** a user runs `python -m studyloop`
- **THEN** Python raises `No module named studyloop.__main__`
  because no `studyloop/__main__.py` exists

### Requirement: Shared output uses a Rich console singleton and click.echo for JSON
Human-readable output SHALL use the `rich.console.Console` singleton
exported from `output.py` and re-exported via `cli/_shared.py`.
Machine-readable output (`--json` flag) SHALL use `click.echo()` with
`json.dumps(..., indent=2)`. When `--json` is passed, the
command SHALL emit valid JSON to stdout and skip Rich formatting.

#### Scenario: Commands that offer --json
- **WHEN** a user or AI agent looks for machine-readable output
- **THEN** commands offering `--json` include:
  `now`, `recap today`, `doctor`, `self-test`, `update`, `chat-note`,
  `practice verify`, `progress`, and several `content` subcommands
  (`discover`, `ingest`, `import-review`)

#### Scenario: Machine consumption of study recommendation
- **WHEN** a user or AI agent runs `studyloop now --json`
- **THEN** stdout contains a single JSON object (parseable by
  `json.loads`) with no Rich escape sequences or ANSI codes

#### Scenario: Human-readable output for the same command
- **WHEN** a user runs `studyloop now` without `--json`
- **THEN** output goes through the shared `console` instance with
  Rich markup (colours, panels, tables) rendered to the terminal

### Requirement: click.version_option exposes the package version
The root `cli()` group SHALL be decorated with
`@click.version_option()` (no explicit version string), which causes
Click to read the version from installed package metadata
(`studyloop` version in `pyproject.toml`, currently `2.5.0`).
`studyloop --version` is the canonical way to check the installed
version.

#### Scenario: Checking installed version
- **WHEN** a user runs `studyloop --version`
- **THEN** Click prints a line containing the package name and
  version (e.g. `studyloop, version 2.5.0`) and exits 0

### Requirement: The brain group is lazily registered and every command has --json
`studyloop.cli.__init__` SHALL register `"brain": "studyloop.cli._brain:brain_group"`
in `lazy_subcommands`; `brain status`, `publish`, `pull`, `enable` and
`template` SHALL each accept `--json`; `studyloop.cli._brain` SHALL import
`studyloop.second_brain` only inside command bodies.

#### Scenario: Help without a backend import
- **WHEN** `studyloop brain --help` runs
- **THEN** it exits 0 and `studyloop.second_brain.obsidian` is not imported

### Requirement: Activation is readiness-gated on every entry path
`studyloop plan status <id> active` SHALL apply a `TransitionLifecycle` intent
through `PlanApplication` rather than checking readiness itself, so the refusal
a learner sees in the terminal is produced from the same `ReadinessView` the
Web API turns into its `422` body.

#### Scenario: The CLI refusal and the Web refusal are the same refusal
- **WHEN** the same unready draft is refused via `studyloop plan status <id>
  active` and via `PATCH /api/plans/{id}` with `{"status": "active"}`
- **THEN** the CLI's `•` bullets, in order, equal the Web `detail.blockers`
  followed by `detail.nudges`, and neither surface has written to the document

#### Scenario: A ready plan activates
- **WHEN** `studyloop plan status <id> active` is run for a plan with a
  mission `why`, a success criterion and a milestone
- **THEN** the exit code is `0`, the output is `<id> → active`, and `plan
  show <id> --json` reports `"status": "active"`

### Requirement: Readiness gate — the CLI refusal exits 1 and prints blockers then nudges
A refused activation SHALL exit `1`, print
`Cannot activate '<id>' — the plan is incomplete.` followed by the blockers and
then the nudges as `•` bullets, print no traceback, and leave the document on
disk byte-identical.

#### Scenario: Status transition to active on an unready plan
- **WHEN** `studyloop plan status vague-plan active` is run for a draft with
  no mission, success criteria or milestones
- **THEN** the exit code is `1`, the output contains `Cannot activate` and the
  word `Mission`, contains no `Traceback`, and `studyloop plan show
  vague-plan --json` still reports `"status": "draft"`

#### Scenario: Create with --activate on an unready plan
- **WHEN** `studyloop plan new --title Empty --activate` is run
- **THEN** the exit code is `1` and the output contains `Cannot activate`;
  no active plan is created

### Requirement: Readiness gate — list and show read through the seam with unchanged --json shapes
`studyloop plan list` and `studyloop plan show` SHALL
read through the seam (`browse` / `inspect`) with their `--json` shapes
unchanged: `list --json` emits the `StudyPlan.summary()` key set per plan;
`show --json` emits `{"plan", "mission", "milestones": [{"title", "done",
"concepts"}], "readiness"}`.

#### Scenario: Unknown id on the seam-backed commands
- **WHEN** `studyloop plan show nope` or `studyloop plan status nope paused`
  is run
- **THEN** the exit code is `1`, the output contains `No study plan with id`
  and no `Traceback`

### Requirement: The CLI maps every seam refusal through one shared mapping and exit 1
Every `studyloop plan` command that reads or writes through `PlanApplication`
SHALL catch `PlanError` and map it in one place (`_fail_for`): `PlanNotFound`
→ `No study plan with id '<id>'. Try: studyloop plan list`; `PlanNotReady` →
`Cannot activate '<id>' — the plan is incomplete.` followed by the blockers
and nudges (several lines — this is the one mapping that prints more than
one).

#### Scenario: A PlanNotReady refusal on create prints the seam's own text
- **WHEN** `studyloop plan new --title Empty --activate` is refused by a seam
  that raises `PlanNotReady` with its own blockers
- **THEN** the exit code is `1` and the output contains
  `Cannot activate 'empty'` followed by each blocker the seam raised

### Requirement: Refusal mapping — conflict, invalid id, invalid field and invalid milestone lines
`_fail_for` SHALL map `PlanConflict` → `A study plan with id '<id>' already exists.
Choose another id.`; `InvalidPlanId` → `Invalid plan id '<id>': <reason>`;
`InvalidField` → `Invalid value: <reason>`; `InvalidMilestone` → `No such
milestone on '<id>': <reason>`, where `<reason>` is the seam's own text (`No
milestone at index <i> (plan has <n>)`).

#### Scenario: Each refusal has its own line
- **WHEN** `studyloop plan status <id> active` is refused with `PlanConflict`,
  `InvalidField`, `InvalidPlanId`, `InvalidMilestone` or `PlanNotReady`
- **THEN** the exit code is `1` in every case, the output contains the
  mapping's distinguishing text (`already exists`, `Invalid value:`, `Invalid
  plan id`, `No such milestone`, `Cannot activate '<id>'`), and no `Traceback`

### Requirement: Refusal mapping — an already-active PlanNotReady adds the pause-or-repair line
When the refused `PlanNotReady` carries
`already_active` (the stored plan was active and incomplete before the write —
a `record`, `milestone` or `evaluate --record` on a hand-edited document), the
mapping SHALL add a line telling the learner to pause the plan
(`studyloop plan status <id> paused`) or repair the blockers, then retry.

#### Scenario: evaluate --record on an active-but-unready plan is refused with the repair hint
- **WHEN** `studyloop plan evaluate husk --record` is run on an active plan
  that is not ready
- **THEN** the exit code is `1`, the output contains `Cannot activate 'husk'`,
  `already active` and `studyloop plan status husk paused`, no `Traceback`,
  and the document and checkpoint history are unchanged

### Requirement: Refusal mapping — every mapping exits 1 and plan list routes browse refusals through it
Every mapping SHALL exit `1` and print no traceback. `studyloop plan list` SHALL route a `browse` refusal through the
same mapping.

#### Scenario: A refusal reaching plan list is a message, not a traceback
- **WHEN** `studyloop plan list --status draft` is run and the seam refuses the
  filter with `InvalidField`
- **THEN** the exit code is `1`, the output contains the seam's reason and no
  `Traceback`

### Requirement: Every plan command reads and writes through the seam
`studyloop plan new|interview|evaluate|milestone|record|reindex` SHALL
delegate to `PlanApplication` like `list|show|status` already do, and
`cli/_plan.py` SHALL import no storage, index, authoring or evaluation module
(the architecture guard `tests/test_architecture_plan_seam.py` fails
otherwise).

#### Scenario: The architecture guard scans the CLI adapter
- **WHEN** the plan-seam architecture guard scans the adapters
- **THEN** `studyloop/cli/_plan.py` is among the files scanned and reports
  no import of a storage, index, authoring or evaluation module

### Requirement: Plan seam — plan new is one CreatePlan and keeps its --json shape
`plan new` SHALL be one `CreatePlan` whose `status` is `"active"`
with `--activate` and `"draft"` without; the `--activate` refusal SHALL be the
seam's `PlanNotReady` reached through `_fail_for` — the command holds no
readiness decision of its own — and a refused create SHALL write nothing.
`plan new --json` SHALL keep `{"plan", "readiness", "path"}`.

#### Scenario: Create with --activate on a ready plan
- **WHEN** `studyloop plan new --title "Glue ETL" --why … --success …
  --milestone … --activate` is run
- **THEN** exactly one `CreatePlan(status="active")` is applied, the exit
  code is `0`, and the stored plan's status is `active`

#### Scenario: Create with --activate on an unready plan writes nothing
- **WHEN** `studyloop plan new --title Empty --activate` is run
- **THEN** the exit code is `1`, the output contains `Cannot activate 'empty'`
  and the blockers, and the plans directory holds no document

### Requirement: Plan seam — interview, reindex and the other plan readers go through the seam
`plan interview`
SHALL be `prepare_planning` and SHALL keep emitting `{"questions", "seed"}`
(no `existing_plans` key is added here). `plan reindex` SHALL call
`PlanApplication.reindex()`. The other CLI readers of plans — `exercise
from-milestone` and `brain publish`'s plan selection — SHALL read through
`inspect` / `browse`.

#### Scenario: plan interview is prepare_planning with the unchanged payload
- **WHEN** `studyloop plan interview --json` is run with
  `PlanApplication.prepare_planning` spied
- **THEN** the exit code is `0`, `prepare_planning` was called exactly once,
  and the payload's keys are exactly `questions` and `seed`

### Requirement: The CLI milestone command is an idempotent set
`studyloop plan milestone <id> <index> [--done|--undone]` SHALL apply one
`SetMilestone`. With a flag the state is set as asked, so running the same
command twice is safe; without a flag the current state is read through the
seam and its opposite is set. A negative index SHALL be refused exactly like
one past the end — the seam's `InvalidMilestone` through the shared mapping
(`No such milestone on '<id>': No milestone at index -1 (plan has <n>)`),
exit `1`, document unchanged.

#### Scenario: Set twice stays set, no flag toggles
- **WHEN** `plan milestone <id> 0 --done` is run twice and then `plan
  milestone <id> 0` once
- **THEN** the outputs report `1/2`, `1/2`, `0/2`, and the three applied
  intents were `SetMilestone(done=True)`, `SetMilestone(done=True)`,
  `SetMilestone(done=False)`

### Requirement: Recorded checkpoints report a complete, partial or absent recording
`studyloop plan evaluate <id> --record` SHALL call `assess(record=True)`,
print the evaluation Markdown, and then print `Checkpoint recorded.` only when
every requested sink was saved.

#### Scenario: Both sinks save
- **WHEN** `plan evaluate glue-etl --phase end --study-id s1 --record` is run
  on a ready plan with both sinks healthy
- **THEN** the exit code is `0`, one `AssessPlan(record=True)` intent was
  applied, the output contains `Checkpoint recorded.`, and both the plan
  document and the checkpoint log hold the `end` checkpoint

### Requirement: Checkpoint recording — a failed sink is named with exit 0, and without --record nothing is written
When a sink failed the command SHALL exit `0`
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

#### Scenario: Each record command applies one RevisePlan carrying the record
- **WHEN** `plan record glue-etl --title Insight --body prose --json` is run
  twice with `PlanApplication.apply` spied
- **THEN** both exit `0`, exactly two intents were applied, each a
  `RevisePlan` whose `learning_record.title` is `Insight`, and the plan holds
  one record

### Requirement: Learning record — created is the mutation's own outcome, never a prior inspect
`created` in the `--json` output SHALL be the mutation's own outcome —
`PlanDetail.learning_record_outcome.created`, the store's
`append_learning_record` verdict relayed by the seam — never inferred from an
`inspect` taken before the revision (a record another writer files in that
window must be reported `created: false`), and the command carries no copy of
the store's identity rule.

#### Scenario: A record filed by another writer just before the mutation
- **WHEN** the same record is written through the store immediately before
  the command's `RevisePlan` runs
- **THEN** the command exits `0` with `created: false, number: 1`, made no
  `inspect` call, and the plan holds one record

### Requirement: Learning record — a retry reports created false and an empty title is refused
A retry with the same title and body SHALL report
`created: false` with the original `number`. An empty title SHALL be the
seam's `Invalid value: …` refusal, exit `1`.

#### Scenario: Retry reports created false
- **WHEN** `plan record <id> --title Insight --body prose --json` is run twice
- **THEN** both exit `0`; the first reports `created: true, number: 1`; the
  second reports `created: false, number: 1`; the plan holds one record

### Requirement: The plan CLI discovers husks and repairs them through the one launch chain
An active plan that is not ready — a "husk" (item 3 / D-C; deviation 12 kept)
— refuses every write until it is repaired or paused, and the CLI SHALL let
the learner find one before they trip over the refusal.

#### Scenario: A husk is visible in plan list before any write trips over it
- **WHEN** one ready active plan, one draft and one active document with no
  mission exist and `plan list` is run
- **THEN** the husk's Status cell reads `active !` while the others read
  `active` and `draft`, so the learner can find it without attempting a write

### Requirement: Husk discovery — plan list marks husks, --husks filters to them, every JSON row carries ready
`studyloop plan list`
SHALL mark a husk with `!` after its status in the Rich table and nothing
after any other status; `--husks` SHALL list only husks (`PlanApplication.husks()`,
read-only, storage-pinned identity, `browse` order); every `--json` row SHALL
carry `ready` as its eighteenth key. `PlanSummary.ready` and
`StudyPlan.summary()["ready"]` SHALL agree, so the D-3 legacy-dict pin holds
with the contract grown by one key on both sides.

#### Scenario: plan list marks the husk, filters to it, and every JSON row carries ready
- **WHEN** one ready active plan, one draft and one active document with no
  mission exist and `plan list`, `plan list --json`, `plan list --husks` and
  `plan list --husks --json` are run
- **THEN** the table's Status cell reads `active !` for the husk and `active` /
  `draft` for the others; every JSON row has 18 keys with `ready` `true` /
  `false` / `false`; `--husks` lists only the husk in both forms

### Requirement: Husk repair — plan repair is the architect launch, inspects first, and has nothing to repair on a ready plan
`studyloop plan repair <id>` SHALL be the architect launch and never a second
path: it SHALL `_inspect(id)` (unknown id → the seam's not-found through
`_fail_for`, exit `1`), SHALL exit `0` with `Nothing to repair on '<id>'` and
no launch for a ready plan.

#### Scenario: Nothing to repair, unknown id, refusal names both exits
- **WHEN** `plan repair glue-etl` is run on a ready active plan; `plan repair
  nope` on no such plan; and `plan evaluate husk --record` on a husk
- **THEN** the first exits `0` with `Nothing to repair on 'glue-etl'` and no
  launch; the second exits `1` naming `nope` with no traceback; the third
  exits `1` and names both `studyloop plan status husk paused` and `studyloop
  plan repair husk`

### Requirement: Husk repair — a non-active plan gets a pointer, a husk gets one study launch with brief keywords
It SHALL exit `0` with no launch and a pointer to
`studyloop plan architect` for a plan that is not active (a draft or a paused
plan is unready by nature, not a husk), and for a husk SHALL `ctx.invoke(study,
…, mode="plan-architect", topic=<the plan's title>, brief=…, brief_intro=…)`.
`brief` and `brief_intro` SHALL be plain keywords on `study()` — not click
options — threaded `study → _handle_start → start_session →
build_canonical_persona`.

#### Scenario: plan repair on an unready draft points at the architect without launching
- **WHEN** `plan repair vague-draft` is run on a draft that is not ready
- **THEN** the exit code is `0`, the output says
  `'vague-draft' is draft, so nothing blocks it` and names
  `studyloop plan architect`, does not say `Nothing to repair`, no launch is
  made, and the plans directory and the plan's status are unchanged

### Requirement: Husk repair — the brief opens with the blockers, then the plan as it stands and its provenance
The brief's first section SHALL be
`### Repair: what this plan is missing` listing exactly `readiness.blockers`
as `- ` lines and nothing else, followed by the plan as it stands (title, id,
status, topics, milestones done/total, created) and one provenance sentence:
`creation stamp predates the readiness gate` (and `cannot tell when it became
incomplete`) only when `created` parses as a date before
`READINESS_GATE_DATE`; otherwise `cannot tell how it got that way`.

#### Scenario: plan repair on a husk launches once with the blockers first and creates nothing
- **WHEN** `plan repair husk` is run on an active document with no mission,
  created before the gate date
- **THEN** exactly one `start_session` call is made with `mode="plan-architect"`
  and `topic` equal to the plan's title; the brief's first section lists
  exactly the two mission blockers; the brief names the title, status,
  topics and `0/1` milestones and says `predates the readiness gate`; the
  intro says `PLAN REPAIR` and not `build a study plan`; the plans directory
  and the checkpoint history are unchanged

### Requirement: Husk repair — the provenance sentence never says never judged and never claims a hand edit
The provenance sentence SHALL never
`never judged` (council review 6 F4). The
sentence SHALL never claim a hand edit.

#### Scenario: plan repair is honest when provenance is unknown
- **WHEN** `plan repair husk` is run on a husk whose `created` is after the
  gate date
- **THEN** the brief says `cannot tell how it got that way`, does not say
  `predates the readiness gate`, and does not say `hand edit`

### Requirement: Husk repair — the brief_intro says PLAN REPAIR and the default intro keeps the planning sentence
The `brief_intro` SHALL say `PLAN
REPAIR` and `ask the learner only for what is missing`; the default intro
(`None`) SHALL keep the planning sentence byte-for-byte so the Web door's
`persona_hash` does not move.

#### Scenario: The repair intro asks only for what is missing
- **WHEN** `plan repair husk` launches the architect
- **THEN** the captured intro contains `PLAN REPAIR` and
  `ask the learner only for what is missing` and does not contain
  `build a study plan`

### Requirement: Husk repair — the command itself writes nothing
The command itself SHALL write nothing: the
document, the plans directory and the checkpoint log are unchanged after it
returns.

#### Scenario: plan repair leaves the documents and the checkpoint log untouched
- **WHEN** `plan repair husk` is run on a husk
- **THEN** after it returns the plans directory holds byte-identical
  documents and the husk's checkpoint history is still empty

### Requirement: Husk repair — the refusal a husk write meets names both exits
The refusal a husk write meets (`_refuse_activation(already_active=True)`)
SHALL name both exits: `studyloop plan repair <id>` and `studyloop plan status
<id> paused`.

#### Scenario: A write refused on a husk names pause and repair
- **WHEN** `plan evaluate husk --record` is run on a husk
- **THEN** the exit code is `1` and the output names both
  `studyloop plan status husk paused` and `studyloop plan repair husk`

### Requirement: The plan CLI closes a fully-checked plan through the one launch chain, consensually
`studyloop plan close <id>` (item 4 / D-G) SHALL be the architect launch and
never a second path — the sibling of `plan repair`, through the same
`ctx.invoke(study, …, mode="plan-architect", topic=<the plan's title>,
brief=…, brief_intro=…)`. It SHALL `_inspect(id)` (unknown id → the seam's
not-found through `_fail_for`, exit `1`).

#### Scenario: plan close on an unknown id is the seam's not-found
- **WHEN** `plan close nope` is run with no such plan
- **THEN** the exit code is `1`, the output names `nope`, and there is no
  `Traceback`

### Requirement: Plan close — open or missing milestones refuse, complete is a no-op, otherwise one preview launch
It SHALL exit `1` with `'<id>' still
has N open milestone(s)` and no launch while any milestone is open; SHALL
exit `1` with a pointer to `studyloop plan architect` for a plan with no
milestones; SHALL exit `0` with no launch for a plan that is already
`complete`; and for a fully-checked plan of any other status SHALL run the end
assessment as a **preview** (`AssessPlan(phase="end", record=False)`) and
launch once.

#### Scenario: plan close on an unfinished plan refuses without launching
- **WHEN** `plan close glue-etl` is run on an active plan with two open
  milestones
- **THEN** it exits `1` with `'glue-etl' still has 2 open milestone(s)`, no
  traceback, no launch, and the plans directory unchanged

### Requirement: Plan close — a fully-checked non-active plan is reviewed and the brief names both doors
A fully-checked `draft`, `paused` or `abandoned` plan is reviewed
like an active one (owner decision 2026-09-18, council review 6 open item 2):
the learner may close it or delete it, and the architect asks which — the
brief's closing section SHALL end with a `Status: <status> — not active; ask
the learner whether to close it (…) or delete it (…)` line naming both doors,
`set_study_plan_status(plan_id, "complete")` and `delete_study_plan(plan_id,
confirmed=True)`.

#### Scenario: plan close on a fully-checked non-active plan launches and names both doors
- **WHEN** `plan close glue-etl` is run on a plan whose two milestones are both
  done and whose status is `abandoned`, `paused` or `draft`
- **THEN** exactly one launch is made; the status line names the status; the
  `### Closing review` section's last line begins `Status: <status>` and names
  `set_study_plan_status`, `delete_study_plan` and asking the learner; the
  plans directory and the plan's status are unchanged

### Requirement: Plan close — the status line names the status and the command itself writes nothing
the status line SHALL name the status. The
command itself SHALL write nothing: the document, the plans directory, the
plan's status and the checkpoint log are unchanged after it returns; the
status moves to `complete` only when the learner agrees in the launched
session and the architect calls `set_study_plan_status`.

#### Scenario: plan close on a paused plan names paused and leaves it paused
- **WHEN** `plan close glue-etl` is run on a fully-checked plan whose status is
  `paused`
- **THEN** the output's status line contains `paused`, exactly one launch is
  made, and after the command returns the plans directory is byte-identical
  and the plan's status is still `paused`

### Requirement: Plan close — the brief opens with the closing review's four count lines and its evidence
The brief's first section SHALL be `### Closing review`, whose first four
`- ` lines are `Due reviews on plan concepts: N`, `Struggles on plan
concepts: N`, `Unverified milestones: N` and `Proposal: extend|close` — or
`Proposal: unassessed — the review is partial` when a reader was unavailable
(council review 6 F1) — followed by one `- ` evidence line per counted item
and one `Not read: …` line per unavailable reader.

#### Scenario: plan close on a fully-checked plan launches once with the review first and writes nothing
- **WHEN** `plan close glue-etl` is run on an active plan whose two milestones
  are both done, with the due reader returning one real due row on a plan
  concept and one `New topic -- start fresh` row (`concept: None`)
- **THEN** exactly one `start_session` call is made with `mode="plan-architect"`
  and `topic` equal to the plan's title; the `### Closing review` section's
  first four lines are `Due reviews on plan concepts: 1`, `Struggles on plan
  concepts: 0`, `Unverified milestones: 0`, `Proposal: extend`, followed by an
  evidence line naming the due concept; the brief says `2/2`; the intro says
  `CLOSING REVIEW` and `only when the learner agrees` and not `build a study
  plan`; the plans directory, the plan's `active` status and the checkpoint
  history are unchanged

### Requirement: Plan close — the review is the now engine's CompletionReview, then the status line, then the plan one value per line
The brief's first section SHALL be the same
`CompletionReview` the `now` engine puts on its completion action, so the two
never disagree on a count (new-topic rows excluded) — then, for a non-active
plan, the `Status:` line above, then the plan as it stands (title, id, status,
topics, milestones done/total, created), every learner-authored value one
line (`planning.one_line`, council review 6 F2).

#### Scenario: Multi-line learner values are rendered one line each in both briefs
- **WHEN** the repair and closing briefs are built for a plan whose title and
  other learner-authored fields contain newlines and markdown headings
- **THEN** each value is rendered on one line, kept verbatim, so the only
  headings in each brief are the brief's own sections — no forged `##` or
  `###` line from a learner value appears

### Requirement: Plan close — the brief_intro says CLOSING REVIEW and only when the learner agrees
The `brief_intro` SHALL say
`CLOSING REVIEW` and `only when the learner agrees`, and SHALL NOT say `build a
study plan`.

#### Scenario: The closing intro asks for consent and does not restart planning
- **WHEN** `plan close glue-etl` launches the architect on a fully-checked plan
- **THEN** the captured intro contains `CLOSING REVIEW` and
  `only when the learner agrees` and does not contain `build a study plan`
