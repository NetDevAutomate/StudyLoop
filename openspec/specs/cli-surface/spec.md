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
