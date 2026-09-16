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
entry points. The two packages are independent installables joined by
a `uv` workspace; the `sessions` optional extra on `studyloop`
declares `agent-session-tools` as a workspace dependency so a single
`uv tool install studyloop[sessions]` pulls both.

#### Scenario: Installing studyloop without the sessions extra
- **WHEN** a user installs `studyloop` without the `[sessions]` extra
- **THEN** only `studyloop`, `studyloop-mcp`, and
  `studyloop-fake-agent` are on PATH — `session-export` and
  `session-query` are not available

#### Scenario: Installing with all extras
- **WHEN** a user installs `studyloop[all]`
- **AND** the workspace resolver finds `agent-session-tools`
- **THEN** all entry points from both packages are available

### Requirement: Optional extras gate command bodies, not command registration
Optional dependencies (`web`, `content`, `mcp`, `bedrock`,
`notebooklm`, `tui`) are declared in
`packages/studyloop/pyproject.toml` `[project.optional-dependencies]`.
Commands that need these extras SHALL defer their imports to function
bodies rather than module top-level, so the command always appears in
`studyloop --help` regardless of installed extras. When invoked
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
`json.dumps(..., indent=2)`. Commands offering `--json` include:
`now`, `recap today`, `doctor`, `self-test`, `update`, `chat-note`,
`practice verify`, `progress`, and several `content` subcommands
(`discover`, `ingest`, `import-review`). When `--json` is passed, the
command SHALL emit valid JSON to stdout and skip Rich formatting.

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

### Requirement: The CLI maps every seam refusal through one shared mapping and exit 1
Every `studyloop plan` command that reads or writes through `PlanApplication`
SHALL catch `PlanError` and map it in one place (`_fail_for`): `PlanNotFound`
→ `No study plan with id '<id>'. Try: studyloop plan list`; `PlanNotReady` →
`Cannot activate '<id>' — the plan is incomplete.` followed by the blockers
and nudges (several lines — this is the one mapping that prints more than
one); `PlanConflict` → `A study plan with id '<id>' already exists.
Choose another id.`; `InvalidPlanId` → `Invalid plan id '<id>': <reason>`;
`InvalidField` → `Invalid value: <reason>`; `InvalidMilestone` → `No such
milestone on '<id>': <reason>`, where `<reason>` is the seam's own text (`No
milestone at index <i> (plan has <n>)`). When the refused `PlanNotReady` carries
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
