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

### Requirement: A symlink at the target path is never replaced
`write_projection` SHALL refuse, using `lstat` rather than `exists`, when the target
is a symbolic link. The link is content the learner created and StudyLoop cannot
recreate; validating the referent's ownership marker and then calling `os.replace`
would destroy the link itself while reporting success.

#### Scenario: A learner symlinks a projection to somewhere else in the vault
- **WHEN** `Study/Plans/<id>.md` is a symlink to another note inside the vault
- **THEN** `publish_plan(<id>)` raises `SecondBrainError` naming the link, and both
  the link and its target are unchanged

### Requirement: A target exchanged during preparation is refused
`write_projection` SHALL capture the target's device, inode and change time when it
validates ownership, re-check them immediately before `os.replace`, and refuse when
they differ. A vault is written by Obsidian and by sync clients, so a note the
learner owns can appear in the window between the ownership check and the rename,
and `os.replace` would delete it without ever having read its frontmatter.

#### Scenario: A note appears after the ownership check
- **WHEN** the target is replaced by a different file between validation and rename
- **THEN** the write is refused, the temporary file is removed, and the message says
  nothing was written

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

### Requirement: No operation of this feature runs an external program
No module under `studyloop.second_brain` SHALL spawn a subprocess. An adapter for
the official Obsidian CLI was implemented and withdrawn before release: it sent
notes to whichever vault the running desktop app answered for, with no way to bind
that vault to the configured `vault_path`, and it passed the rendered plan as a
command-line argument, where any other local user could read it from the process
table. The guarded file writer SHALL be the only path that produces a note.

#### Scenario: Publishing with subprocess spawning made to fail
- **WHEN** `subprocess.run` and `subprocess.Popen` are replaced with functions that
  raise, and `publish_today()` runs
- **THEN** the note is written and nothing raises

### Requirement: Retired configuration keys are reported rather than ignored
`load_settings()` SHALL raise `ConfigError` naming any of `use_cli`, `vault_name`,
`template` or `daily_note` found under `second_brain`, because a learner who set
`daily_note: true` authorised a write into a note they own and must be told it no
longer happens.

#### Scenario: A pre-release config still names daily_note
- **WHEN** `config.yaml` contains `second_brain: {provider: obsidian, daily_note: true}`
- **THEN** `studyloop brain status` exits 1 with one line naming `daily_note` and
  stating the adapter was withdrawn

### Requirement: The wind-down protocol offers publishing once and only when a publishing provider is configured
`agents/shared/wind-down-protocol.md` SHALL instruct the agent to run
`studyloop brain status --json` and offer `studyloop brain publish` exactly once
when `configured` and `supports_publish` are both true, and to say nothing
otherwise; the offer sentence SHALL be identical in `docs/second-brain.md`.

#### Scenario: xTiles stage 1 configured
- **WHEN** `provider: xtiles`
- **THEN** `supports_publish` is false and the protocol makes no publish offer
