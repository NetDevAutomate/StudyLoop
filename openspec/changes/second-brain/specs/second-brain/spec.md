## Purpose

Publish read-only projections of study plans and of today's study into an
optional, user-chosen second brain (Obsidian first; xTiles via an assistant),
keeping the plan Markdown under `STUDYLOOP_PLANS_DIR` as the single source of
truth. Nothing here runs unless `second_brain.provider` is set.

## ADDED Requirements

### Requirement: A disabled or absent second_brain section imports no backend and writes nothing
`studyloop.second_brain.factory.get_backend()` SHALL return
`studyloop.second_brain.core.NullBackend` when `Settings.second_brain.provider`
is `none` or the section is absent, without importing
`studyloop.second_brain.obsidian`, and every operation on it SHALL return a
skipped result without touching the filesystem.

#### Scenario: Status with no configuration
- **WHEN** `studyloop brain status --json` runs with no `second_brain` section
- **THEN** it prints `configured: false` and `studyloop.second_brain.obsidian`
  is not in `sys.modules`, and no file is created anywhere

### Requirement: The SecondBrain protocol has exactly six methods
`studyloop.second_brain.core.SecondBrain` SHALL be a runtime-checkable
`Protocol` exposing exactly `describe`, `is_available`, `publish_plan`,
`publish_today`, `publish_learning_record` and `pull_notes`; every backend
SHALL satisfy `isinstance(backend, SecondBrain)`.

#### Scenario: A backend gains a method
- **WHEN** a seventh public method is added to the protocol
- **THEN** `tests/test_second_brain_protocol.py` fails until the spec and the
  method-set guard are updated together

### Requirement: The Obsidian backend writes only StudyLoop-owned files under the configured vault folder
`studyloop.second_brain.obsidian.ObsidianBackend` SHALL write only under
`<vault_path>/<folder>/` (default `Study/`), only to files whose frontmatter
carries a `studyloop:` ownership marker with matching identity, atomically
(temporary file and `os.replace`), and SHALL refuse with `SecondBrainError`
any target that resolves outside the vault or lacks the marker.

#### Scenario: A user note occupies the target path
- **WHEN** `Study/Plans/<id>.md` exists without a `studyloop:` marker
- **THEN** `publish_plan(<id>)` raises `SecondBrainError` naming the file and
  the file's bytes are unchanged

#### Scenario: A symlinked folder points outside the vault
- **WHEN** `<vault>/Study` is a symlink to a directory outside the vault
- **THEN** every publish operation is refused before any write

### Requirement: Republishing unchanged content performs no write
`ObsidianBackend` SHALL compare the rendered projection against the existing
file's own contents and, when they are identical, return the path under
`PublishResult.unchanged` without calling `os.replace` or changing `st_mtime_ns`.
The comparison SHALL NOT use the `content_hash` recorded in the existing file's
ownership marker: that value records what StudyLoop last intended to write, so a
projection the learner has edited by hand still carries the hash of the correct
content and would be reported as unchanged, leaving the edit in place and making
the vault a second source of truth.

#### Scenario: Publish twice
- **WHEN** `publish_plan(<id>)` runs twice with the plan unchanged
- **THEN** the second result lists the path under `unchanged` and the file's
  mtime is identical

#### Scenario: An edited projection is restored
- **WHEN** the learner appends a line to `Study/Plans/<id>.md` and
  `publish_plan(<id>)` runs again
- **THEN** the file is rewritten from the plan document and the appended line is
  gone

### Requirement: Publishing never modifies the plan file
No operation of any `SecondBrain` backend SHALL write to
`STUDYLOOP_PLANS_DIR/<id>.md`; the plan bytes SHALL be identical before and
after `publish_plan`, `publish_today`, `publish_learning_record` and `pull_notes`.

#### Scenario: Backend contract fixture
- **WHEN** the shared contract in `tests/test_second_brain_backend_contract.py`
  runs against every registered backend
- **THEN** the byte snapshot of the plan file matches after every operation

### Requirement: Pulling notes is explicit and read-only
`ObsidianBackend.pull_notes(plan_id)` SHALL read only
`<vault>/<folder>/Plans/<id>.notes.md`, SHALL never create or modify it, and
SHALL return a `PullNotesResult` with `found: false` when it is absent;
`studyloop brain pull` is the only caller.

#### Scenario: No user note yet
- **WHEN** `studyloop brain pull <id>` runs and the sibling note does not exist
- **THEN** the command exits 0, reports `found: false`, and creates nothing

### Requirement: The Obsidian CLI adapter is opt-in and degrades to the file writer
`studyloop.second_brain.obsidian_cli.resolve_cli_mode()` SHALL return `cli`
only when `second_brain.use_cli` is `on` or `auto`, `shutil.which("obsidian")`
succeeds and a probe subprocess (argv list, `shell=False`, `timeout=10`) exits
0; otherwise `files`. With `use_cli: on` a failed probe SHALL log one WARNING;
with `auto` it SHALL log at DEBUG only; with `off` no subprocess SHALL be
spawned. The backend SHALL never prompt.

#### Scenario: The Obsidian app is not running
- **WHEN** `use_cli: on` and the probe fails
- **THEN** the projection is written by the file writer, one WARNING is logged,
  and the command exits 0

### Requirement: The wind-down protocol offers publishing once and only when a publishing provider is configured
`agents/shared/wind-down-protocol.md` SHALL instruct the agent to run
`studyloop brain status --json` and offer `studyloop brain publish` exactly once
when `configured` and `supports_publish` are both true, and to say nothing
otherwise; the offer sentence SHALL be identical in `docs/second-brain.md`.

#### Scenario: xTiles stage 1 configured
- **WHEN** `provider: xtiles`
- **THEN** `supports_publish` is false and the protocol makes no publish offer
