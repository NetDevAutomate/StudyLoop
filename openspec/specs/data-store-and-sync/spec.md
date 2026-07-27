## Purpose

Provide a single shared SQLite database (`sessions.db`) with a
deterministic connection contract (WAL mode, foreign keys, busy timeout),
forward-only numbered migrations tracked via `PRAGMA user_version`, CLI
backup/restore, orphan artifact cleanup, and cross-machine SQL-delta sync.
Feature tables (progress, review, session-export) depend on this layer but
are specified separately.

## Requirements

### Requirement: Every database surface opens connections through connect_db with WAL, foreign keys, and busy timeout
The system SHALL open all SQLite connections via `db.connect_db()` which
applies `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`, and
`PRAGMA busy_timeout=5000` on every connection. Callers optionally pass
`row_factory=True` to enable `sqlite3.Row` access.

#### Scenario: A new module opens the sessions database
- **WHEN** any caller invokes `connect_db(path)` from `studyloop.db`
- **THEN** the returned connection has WAL journal mode active, foreign
  key enforcement enabled, and a 5-second busy timeout configured
- **AND** the caller is responsible for closing the connection

#### Scenario: review_db opens its connection
- **WHEN** `review_db._connect(db_path)` is called
- **THEN** it delegates to `connect_db(db_path)` from `studyloop.db`,
  inheriting all pragma settings without re-implementing them

### Requirement: Both packages resolve to the same default database path
The system SHALL default the sessions database path to
`~/.config/studyloop/sessions.db` in both packages — via
`settings.DEFAULT_DB` / `settings.get_db_path()` in the `studyloop`
package and via `config_loader.get_db_path()` (reading
`config["database"]["path"]`) in `agent-session-tools`. The
`DATABASE_PATH` environment variable overrides the resolved path
directly; `STUDYLOOP_CONFIG` changes it only indirectly, by pointing
config discovery at a different `config.yaml`.

#### Scenario: Fresh install with no config file
- **WHEN** neither `~/.config/studyloop/config.yaml` nor environment
  variables are set
- **THEN** both `studyloop.settings.get_db_path()` and
  `agent_session_tools.config_loader.get_db_path()` resolve to
  `~/.config/studyloop/sessions.db`

#### Scenario: Environment override for testing
- **WHEN** `DATABASE_PATH=/tmp/test.db` is set in the environment
- **THEN** `agent_session_tools.config_loader.get_db_path()` returns
  `/tmp/test.db`

### Requirement: Schema is created from schema.sql and evolved by forward-only numbered migrations
The system SHALL create the base schema from
`agent_session_tools/schema.sql` on first use and evolve it through
numbered migration functions (`migrate_v1` through `migrate_v25`) in
`agent_session_tools.migrations`. The current target version is stored as
`CURRENT_VERSION = 25`. Each migration is registered via a `@migration`
decorator, applied in sequence, and committed individually. On failure a
migration rolls back and raises, leaving the database at the last
successful version.

#### Scenario: First connection on a fresh machine
- **WHEN** `history/_connection.py::_connect()` opens a database file
  that has no `study_sessions` table
- **THEN** it executes `schema.sql` to create base tables (`sessions`,
  `messages`, `messages_fts`) and immediately runs `migrate(conn)` to
  apply all 25 migrations, setting `PRAGMA user_version = 25`

#### Scenario: Database at version 20, application expects 25
- **WHEN** `migrate(conn)` detects `PRAGMA user_version` is 20
- **THEN** it applies migrations 21 through 25 in order, committing
  each individually, and returns a list of 5 applied descriptions

#### Scenario: Migration fails mid-sequence
- **WHEN** migration v23 raises an exception during application
- **THEN** that migration's transaction is rolled back, the database
  remains at version 22, and the exception propagates to the caller

### Requirement: Migrations are idempotent and use ALTER TABLE with column-existence guards
Each migration function SHALL check column existence via
`PRAGMA table_info` (or the helper `_table_columns()`) before issuing
`ALTER TABLE ... ADD COLUMN`, and use `CREATE TABLE IF NOT EXISTS` /
`CREATE INDEX IF NOT EXISTS` for new objects. Re-running an already-applied
migration against a database at that version produces no errors and no
duplicate schema objects.

#### Scenario: migrate_v1 runs against a database that already has content_hash
- **WHEN** `migrate_v1(conn)` executes and the `sessions` table already
  has a `content_hash` column
- **THEN** the `ALTER TABLE` is skipped (guarded by column-set check)
  and no `OperationalError` is raised

### Requirement: Backup creates timestamped copies of sessions.db, review.db, and config.yaml
`cli/_backup.py::backup` SHALL copy all existing assets (`sessions.db`,
`review.db`, `config.yaml`) into a timestamped directory under
`~/.config/studyloop/backups/backup_{tag}_{YYYYMMDD_HHMMSS}/`. The
`restore` command SHALL create a safety backup of the current state before
overwriting assets from a named backup, and requires `--confirm` to
execute.

#### Scenario: User runs studyloop backup --tag pre-upgrade
- **WHEN** `studyloop backup --tag pre-upgrade` is invoked and
  `sessions.db` and `config.yaml` exist
- **THEN** both files are copied to
  `~/.config/studyloop/backups/backup_pre-upgrade_{timestamp}/`
  preserving metadata via `shutil.copy2`

#### Scenario: Restore without --confirm
- **WHEN** `studyloop restore backup_pre-upgrade_20260101_120000` is
  invoked without `--confirm`
- **THEN** the command prints what would be restored and exits without
  modifying any files (dry-run mode)

#### Scenario: Restore with --confirm
- **WHEN** `studyloop restore <name> --confirm` is invoked
- **THEN** a safety backup tagged `pre-restore` is created first, then
  each file in the named backup is copied to its canonical location

### Requirement: Clean removes orphaned tmux sessions, stale directories, and ended state files
`cli/_clean.py` SHALL delegate decisions to `logic/clean_logic.py`
(`plan_clean()`) which identifies zombie tmux sessions (no child process,
aged >60s), session directories not matching a live tmux session, and a
`session-state.json` with `mode == "ended"` whose tmux session no longer
exists. The imperative shell executes the plan with a file lock to prevent
TOCTOU with `--resume`.

#### Scenario: studyloop clean --dry-run with orphaned directory
- **WHEN** `~/.config/studyloop/sessions/stale-session/` exists but no
  tmux session named `stale-session` is running
- **THEN** `plan_clean()` includes that path in `dirs_to_remove` and
  `--dry-run` prints "would remove stale-session" without deleting

#### Scenario: State file changed between plan and execute
- **WHEN** `plan_clean()` marks `state_to_clean=True` but between
  planning and execution another process resumes the session (changing
  `mode` away from `"ended"`)
- **THEN** the lock-guarded execution re-reads state and skips deletion

### Requirement: Cross-machine sync streams SQL deltas over SSH using INSERT OR REPLACE with last-writer-wins on updated_at
`agent_session_tools.sync` SHALL transfer new and updated sessions between
machines by comparing `updated_at` timestamps. The session with the later
`updated_at` wins on conflict. Sync streams `INSERT OR REPLACE` SQL over
SSH (with `-C` compression) rather than copying the entire database. Global
tables (`study_progress`, `study_sessions`, `teach_back_scores`,
`knowledge_bridges`, `concepts`, `concept_aliases`, `concept_relations`,
`message_concepts`, `parked_topics`, `scrub_log`) are synced in full on
every operation. Session-scoped tables (`sessions`, `messages`,
`session_notes`, `session_tags`, `session_learning_metadata`,
`file_references`) are filtered to only the delta session IDs.

#### Scenario: Push to a remote that has never been seeded
- **WHEN** `session-sync push <remote>` runs and `_remote_db_exists()`
  returns False (no sessions table on remote)
- **THEN** the entire local database is copied via `scp` to seed the
  remote (first-time full copy)

#### Scenario: Bidirectional sync with divergent sessions
- **WHEN** `session-sync sync <remote>` runs and the local machine has
  3 sessions newer than remote, while the remote has 2 sessions not
  present locally
- **THEN** Step 1 pulls the 2 remote sessions into local (INSERT OR
  REPLACE), Step 2 pushes the 3 local sessions to remote (INSERT OR
  REPLACE), and both machines end up with all 5 sessions

#### Scenario: Same session exists on both sides, local is newer
- **WHEN** session `abc123` has `updated_at = 2026-07-20T10:00:00` locally
  and `updated_at = 2026-07-19T15:00:00` on remote
- **THEN** push includes `abc123` in the delta (local wins), and all
  related rows in session-scoped tables are overwritten on remote via
  INSERT OR REPLACE

### Requirement: Sync validates session IDs against an allow-pattern before building SQL
`sync._validate_session_ids()` SHALL reject any session ID not matching
`^[a-zA-Z0-9_.-]+$` by raising `ValueError`, preventing SQL injection via
crafted IDs received from a remote database.

#### Scenario: Remote returns a session ID with shell metacharacters
- **WHEN** the remote database contains a session with ID
  `"; DROP TABLE sessions; --`
- **THEN** `_validate_session_ids()` raises `ValueError` before any SQL
  is constructed or executed

### Requirement: Sync creates a backup before pulling and supports configured named endpoints
`session-sync pull` and `session-sync sync` SHALL call
`maintenance.create_backup()` before importing remote data (skippable
with `--no-backup`). Endpoints MAY be configured in `config.yaml` under
a `hosts` section with `hostname`, `user`, `ip_address.primary`,
`ip_address.secondary`, and `sessions_db` fields. The local machine
(detected by hostname match) is excluded from the endpoint list.
Resolution tries primary IP then secondary IP with a 3-second SSH
connection timeout.

#### Scenario: Configured endpoint with primary IP unreachable
- **WHEN** `session-sync push macmini` is invoked and the endpoint's
  `primary_ip` times out after 3 seconds
- **THEN** the system tries `secondary_ip`; if that also fails it
  raises a `BadParameter` error stating all IPs unreachable
