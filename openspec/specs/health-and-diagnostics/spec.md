## Purpose

Provide a layered health-check and self-repair system for StudyLoop
installations: a lightweight post-install `self-test`, a comprehensive
`doctor` with category-scoped checks and safe `--fix` auto-repairs, a
PyPI update check with file-based caching, and a `studyloop install
tools` command that installs workspace packages as global `uv` tools.
The voice-tts spec owns `doctor/voice.py` semantics; the agent-adapters
spec owns `install agents` and `_TOOL_LINKS`; the configuration-and-
secrets spec owns config schema — this spec covers the diagnostic engine,
repair contract, and tool-installation lifecycle.

## Requirements

### Requirement: Every check produces a structured CheckResult with category, severity, and fix metadata
The system SHALL model each diagnostic result as a frozen
`CheckResult` dataclass (`doctor/models.py`) carrying `category`
(one of `core`, `database`, `config`, `agents`, `deps`, `voice`,
`updates`, `harness`), `status` (one of `pass`, `warn`, `fail`,
`info`), a human `message`, a `fix_hint` string, and a boolean
`fix_auto` flag indicating whether `--fix` can resolve it.

#### Scenario: A checker returns an invalid status string
- **WHEN** a checker function attempts to construct a `CheckResult`
  with `status="critical"` (not in `VALID_STATUSES`)
- **THEN** `CheckResult.__post_init__` raises `ValueError`

#### Scenario: JSON output from studyloop doctor
- **WHEN** `studyloop doctor --json` is invoked
- **THEN** the output is a JSON array where each element has keys
  `category`, `name`, `status`, `message`, `fix_hint`, `fix_auto`
  — matching the `to_dict()` contract

### Requirement: The CheckerRegistry groups checkers by category and isolates crashes
`CheckerRegistry` (`doctor/__init__.py`) SHALL execute all registered
checker functions via `run_all()` or `run_category(category)`. If any
checker raises an unhandled exception, the registry SHALL catch it and
emit a synthetic `fail` result with `message="Checker crashed: {exc}"`
rather than aborting the entire run.

#### Scenario: A checker function raises an unexpected exception
- **WHEN** `check_obsidian_vault()` raises `PermissionError` during
  a `run_all()` pass
- **THEN** the result list includes a `CheckResult` with
  `status="fail"`, `name="check_obsidian_vault"`, and the remaining
  checkers still execute normally

#### Scenario: Running a single category
- **WHEN** `studyloop doctor --category database` is invoked
- **THEN** only `check_review_db` and `check_sessions_db` execute;
  checkers registered under other categories are skipped

### Requirement: doctor --fix applies safe automatic repairs and re-runs checks
`studyloop doctor --fix` (`cli/_doctor.py::_apply_fixes`) SHALL apply
repairs only for results where `fix_auto=True` and `status` is `warn`
or `fail`. After applying fixes it SHALL re-run all checks so the
output reflects post-fix state. Current auto-fixable repairs include:
creating a default config (`ensure_default_config`), creating missing
review directories (`ensure_review_directories`), migrating the review
database (`ensure_review_database`), reinstalling workspace tools
(`install_workspace_tools`), refreshing agent definitions
(`install_agent_definitions`), wiring session-export steering mandates
(`install_session_db_mandate`), and upgrading packages.

#### Scenario: Config file missing on a fresh install
- **WHEN** `studyloop doctor --fix` runs and the `config_file` check
  is `warn` with `fix_auto=True`
- **THEN** `ensure_default_config()` creates
  `~/.config/studyloop/config.yaml` and the re-run shows `config_file`
  as `pass`

#### Scenario: A failing check has fix_auto=False
- **WHEN** `check_python_version` returns `fail` with
  `fix_auto=False` (Python too old)
- **THEN** `--fix` does not attempt to upgrade Python; the failure
  persists in the re-run output

### Requirement: Exit codes reflect severity with a critical-core-fail distinction
`_compute_exit_code()` SHALL return exit 2 when any `core` category
result is `fail` with `fix_auto=False` (critical, unfixable). It SHALL
return exit 1 when any result is `fail` OR any `warn` has
`fix_auto=True` (actionable). Otherwise it returns 0.

#### Scenario: Python version too old
- **WHEN** `check_python_version` emits `status="fail"`,
  `category="core"`, `fix_auto=False`
- **THEN** `studyloop doctor` exits with code 2

#### Scenario: Only info and pass results
- **WHEN** every `CheckResult` has status `pass` or `info`
- **THEN** `studyloop doctor` exits with code 0

### Requirement: self-test is a lightweight post-install check that avoids network and services
`studyloop self-test` (`self_test.py::run_self_tests`) SHALL validate
basic imports (`studyloop.cli`), config readability (YAML parse of
`config.yaml`), database path usability (parent directory creatable),
and web import (`studyloop.web.app`). It SHALL NOT contact external
systems, install files, or start services. Its `SelfTestResult`
dataclass uses `pass`/`warn`/`fail` (no `info` status).

#### Scenario: Fresh install with no config file yet
- **WHEN** `studyloop self-test` runs before `studyloop setup`
- **THEN** the `config_read` check is `warn` (not `fail`) with a
  message suggesting `studyloop setup`, and the process exits 1

#### Scenario: Web extra not installed
- **WHEN** `studyloop.web.app` cannot be imported
- **THEN** the `web_import` check is `warn` with a message noting the
  web extra is unavailable, and the process exits 1

### Requirement: PyPI update checks use a 1-hour file cache to avoid repeated network calls
`doctor/updates.py::check_pypi_versions` SHALL cache latest-version
responses in `~/.cache/studyloop/pypi-check.json` with a TTL of 3600
seconds (`CACHE_TTL_SECONDS`). Within that window, subsequent calls
read from cache without network access. It checks both `studyloop` and
`agent-session-tools` packages. When the installed version differs from
the latest, the result is `warn` with `fix_auto=True` and a hint of
`studyloop upgrade --component packages`.

#### Scenario: Cache is fresh (less than 1 hour old)
- **WHEN** `check_pypi_versions` runs 30 minutes after the last
  successful PyPI fetch
- **THEN** no HTTP request is made; the cached versions are compared
  against installed versions

#### Scenario: Network unreachable on first run
- **WHEN** PyPI is unreachable and no cache file exists
- **THEN** a single `info` result is returned with message "Could not
  reach PyPI (offline?)" and no `warn` or `fail` is emitted

### Requirement: install tools installs workspace packages as global uv tools with all extras
`studyloop install tools` (`installers.py::install_workspace_tools`)
SHALL iterate directories under `{repo_root}/packages/`, installing
each as an editable `uv tool` with the `[all]` extra. For the
`studyloop` package it additionally passes `--with-editable` pointing
at `agent-session-tools` so both are co-installed in one tool
environment. The `--force` flag (default True) ensures reinstall on
re-runs. An optional `--sync/--skip-sync` flag controls whether
`uv sync --all-packages` runs first.

#### Scenario: Normal install from source checkout
- **WHEN** `studyloop install tools` runs from a valid source checkout
- **THEN** `uv tool install {pkg}[all] --editable --force` executes
  for each package under `packages/`, and the command reports the list
  of installed package names

#### Scenario: Not running from a source checkout
- **WHEN** `studyloop install tools` runs from a directory where
  `find_repo_root()` returns `None`
- **THEN** `require_repo_root()` raises `InstallError` with message
  "This command requires a source checkout of socratic-study-mentor"

### Requirement: upgrade orchestrates component-scoped updates with dry-run support
`studyloop upgrade` (`cli/_upgrade.py`) SHALL accept
`--component {packages|agents|database|voice|all}` (default `all`)
and `--dry-run`. It runs all doctor checks, filters to actionable
results matching the component, and applies upgrades: package upgrade
via the detected manager (`uv`/`brew`/`pip`), database backup + schema
migration, or agent definition refresh. `--dry-run` shows what would
happen without mutating state.

#### Scenario: Package update available, dry-run mode
- **WHEN** `studyloop upgrade --dry-run --component packages` runs and
  a newer version exists on PyPI
- **THEN** the output shows the `uv tool upgrade studyloop` command
  that would run, but no packages are actually upgraded

#### Scenario: Nothing to upgrade
- **WHEN** `studyloop upgrade` runs and all actionable checks are
  `pass`
- **THEN** the output says "Everything is up to date" and exits 0

### Requirement: install.sh guarantees a working CLI with self-test and doctor validation
`scripts/install.sh` SHALL verify Python ≥ 3.12 and `uv` are present
(installing `uv` if missing), sync the workspace, install tools via
`studyloop install tools`, install agent definitions via `studyloop
install agents`, and run smoke checks. The smoke checks validate that
`studyloop self-test --json` emits valid JSON with exit 0 or 1 (warn
acceptable), and `studyloop doctor --json` emits valid JSON with exit
0, 1, or 2 (all acceptable). The script accepts `--tools-only`,
`--agents-only`, `--no-smoke`, and `--non-interactive` flags.

#### Scenario: Fresh machine with uv not installed
- **WHEN** `./scripts/install.sh` runs and `uv` is not on PATH
- **THEN** the script downloads and installs `uv` via the official
  install script before proceeding, and adds `~/.local/bin` to PATH

#### Scenario: Self-test returns exit 2 (fail)
- **WHEN** the post-install `studyloop self-test --json` returns exit
  code 2
- **THEN** `install.sh` prints an error and exits non-zero, halting
  the installation
