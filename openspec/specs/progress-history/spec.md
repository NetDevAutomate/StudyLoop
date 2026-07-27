## Purpose

Track concept-level learning progress, study streaks, teach-back
assessments, knowledge bridges, and struggle signals in SQLite
(`sessions.db`). Surface this data through CLI commands (`progress`,
`wins`, `streaks`, `resume`, `struggles`, `teachback`, `bridge`) and
the `history.*` module API. Excludes: SM-2 card scheduling
(spaced-repetition-review), session export/import (session-export),
the `now` recommendation engine (active-learning-decisions), and
DB file/WAL mechanics (data-store).

## Requirements

### Requirement: Progress is recorded as a per-concept upsert keyed on topic+concept
The system SHALL persist concept progress via
`history.progress.record_progress()` using a deterministic UUID5 of
`"{topic}:{concept}"` as the primary key in the `study_progress` table.
On conflict the row SHALL update `confidence`, `last_seen`, increment
`session_count`, and COALESCE optional provenance columns
(`source_course`, `source_section`, `source_publisher`, `created_by`)
so that a later call without provenance never overwrites provenance
written by an earlier web-flagged row.

#### Scenario: First recording of a concept
- **WHEN** `record_progress("python", "decorators", "learning")` is
  called and no row exists for that topic+concept pair
- **THEN** a new row is inserted with `session_count=1`, `first_seen`
  and `last_seen` set to the current UTC timestamp, and the function
  returns `True`

#### Scenario: Repeated recording updates rather than duplicates
- **WHEN** `record_progress("python", "decorators", "confident")` is
  called and a row already exists for that topic+concept pair
- **THEN** `confidence` is overwritten to `"confident"`, `last_seen`
  is updated, `session_count` is incremented by 1, and no second row
  is created

#### Scenario: Case-insensitive deduplication
- **WHEN** progress is recorded for topic `"Python"` concept
  `"Decorators"` followed by `"python"` concept `"decorators"`
- **THEN** both resolve to the same UUID5 key and the second call
  updates the existing row rather than creating a duplicate

### Requirement: Wins are concepts that reached confident or mastered within a lookback window
`history.progress.get_wins(days)` SHALL return rows from
`study_progress` where `confidence IN ('confident', 'mastered')` and
`last_seen` is within the given number of days. The CLI
`studyloop wins` (`cli/_review.py`) SHALL render these alongside a
`get_progress_summary()` breakdown of total counts per confidence
level.

#### Scenario: Recent mastery surfaces as a win
- **WHEN** a concept's confidence is `"mastered"` and `last_seen` is
  3 days ago, and `studyloop wins --days 7` is run
- **THEN** the concept appears in the wins table output

#### Scenario: Stale mastery excluded by window
- **WHEN** a concept was mastered 60 days ago and
  `studyloop wins --days 30` is run
- **THEN** the concept does not appear in the output

### Requirement: Study streaks are computed from distinct session dates over 90 days
`history.streaks.get_study_streaks()` SHALL query distinct dates from
the `sessions` table (using `COALESCE(updated_at, created_at)`) over
the last 90 days and compute `current_streak` (consecutive days ending
today or yesterday), `longest_streak`, `total_days`, and
`sessions_this_week`. The CLI `studyloop streaks` (`cli/_review.py`)
SHALL render these alongside energy-pattern analysis from
`logic/streaks_logic.py`.

#### Scenario: Two consecutive study days
- **WHEN** the `sessions` table has rows dated today and yesterday but
  no row for two days ago
- **THEN** `current_streak` is `2`

#### Scenario: Energy trend detection
- **WHEN** `studyloop streaks` is run and 30 days of study_sessions
  exist with energy levels recorded
- **THEN** the output includes an energy trend (`improving`, `stable`,
  or `declining`) computed by `analyze_energy_streaks()` comparing the
  older half to the newer half of sessions

### Requirement: Teach-back scoring records a 5-dimension rubric and feeds study_progress
`history.teachback.record_teachback()` SHALL insert a row into
`teach_back_scores` with five 1–4 scores (accuracy, own_words,
structure, depth, transfer), compute a confidence level from the total
via `_confidence_from_teachback()`, and upsert `study_progress` with
`last_teachback_score` and accumulated `angles_used`. The CLI
`studyloop teachback` (`cli/_teachback.py`) accepts scores as a
comma-separated string validated by `TeachbackScoresParam`.

#### Scenario: Recording a micro teach-back with total < 9
- **WHEN** `record_teachback("closures", "python", (2,1,2,1,2),
  "micro")` is called
- **THEN** the `teach_back_scores` row has `total_score=8` (generated
  column) and `study_progress` is upserted with
  `confidence="struggling"` and `last_teachback_score=8`

#### Scenario: Query teach-back history for a concept
- **WHEN** `studyloop teachback-history "closures" --topic python` is
  run
- **THEN** `get_teachback_history("closures", topic="python")` returns
  up to 20 rows ordered by `created_at DESC` with all five dimension
  scores and the total

### Requirement: Knowledge bridges link concepts across domains with usage tracking
`history.bridges.record_bridge()` SHALL insert a row into
`knowledge_bridges` with source/target concept+domain, a structural
mapping description, quality, and `created_by`. `get_bridges()` SHALL
support filtering by `source_domain`, `target_domain`, and `quality`,
ordered by `times_helpful DESC`. `update_bridge_usage()` SHALL
increment `times_used` and conditionally `times_helpful`. The CLI
`studyloop bridge add` and `studyloop bridge list` expose these.

#### Scenario: Adding a bridge from the CLI
- **WHEN** `studyloop bridge add "ECMP" -s networking "Spark
  partitions" -t python -m "Both distribute load"` is run
- **THEN** a row is inserted with `source_concept="ECMP"`,
  `source_domain="networking"`, `target_concept="Spark partitions"`,
  `target_domain="python"`, `quality="moderate"`, `created_by="student"`

#### Scenario: Filtering bridges by target domain
- **WHEN** `get_bridges(target_domain="python")` is called
- **THEN** only bridges whose `target_domain` is `"python"` are
  returned

### Requirement: Resume briefing assembles last-session context and in-progress concepts
`history.sessions.get_last_session_summary()` SHALL query the most
recent row from the `sessions` table, its last 6 messages, the top 5
`study_progress` rows with confidence `IN ('struggling', 'learning')`,
and extract mentioned study terms from message content. The CLI
`studyloop resume` (`cli/_review.py`) SHALL render this alongside
streak data from `get_study_streaks()` and medication window from
`check_medication_window()`.

#### Scenario: Resuming with in-progress concepts
- **WHEN** `studyloop resume` is run and `study_progress` has rows
  with confidence `"learning"` or `"struggling"`
- **THEN** the output includes an "In progress" section listing those
  concepts with their topic and confidence level

#### Scenario: Medication window shown when configured
- **WHEN** `config.yaml` contains a `medication:` section with
  `dose_time`, and `studyloop resume` is run
- **THEN** the output includes the current medication phase and
  recommendation from `check_medication_window()`

### Requirement: Struggle extraction writes session struggles into study_progress
`studyloop extract-struggles` (`cli/_extract.py`) SHALL read messages
from `sessions.db`, apply `extractors.pipeline.pre_filter()` (only
`source='kiro_cli'` sessions with <50% tool-noise roles pass), run
an extractor function, and upsert results into `study_progress` via
`record_progress()`. The `--incremental` mode (default) processes one
session; `--full` backfills all qualifying sessions. `--dry-run`
reports without writing.

#### Scenario: Incremental extraction of most recent session
- **WHEN** `studyloop extract-struggles --incremental` is run with no
  `--session-id`
- **THEN** the most recent `kiro_cli` session is processed and
  extracted struggles are upserted into `study_progress`

#### Scenario: Non-study sessions are filtered out
- **WHEN** a session has `source='claude_code'` or more than 50% of
  its messages have role `tool_use` or `tool_result`
- **THEN** `pre_filter()` returns `False` and the session is skipped

### Requirement: Full-text search over session messages uses FTS5
`history.search.topic_frequency()` SHALL query the `messages_fts`
FTS5 virtual table joined to `messages` for rows matching any of the
given keywords within a date cutoff, returning session_id, timestamp,
and a 30-token snippet. `struggle_topics()` SHALL scan recent user
messages containing question marks and count occurrences of configured
study terms, returning topics mentioned in 3+ sessions.

#### Scenario: Topic frequency lookup
- **WHEN** `topic_frequency(["spark", "glue"], days=30)` is called
- **THEN** the FTS5 query `content MATCH 'spark' OR content MATCH
  'glue'` returns matching message snippets from the last 30 days

#### Scenario: Struggle detection from repeated questions
- **WHEN** `studyloop struggles --days 30` is run and the term
  "decorators" appears in user messages across 4 distinct sessions
- **THEN** `"decorators"` appears in the output with mention count 4

### Requirement: Struggling topics union three evidence sources
`history.progress.get_struggling_topics(days)` SHALL query three
tables — `study_progress` (confidence='struggling'), `study_sessions`
(struggle_count > 0), and `parked_topics` (source='struggled') — and
merge results by case-insensitive topic key. Each source is
independently guarded against `OperationalError` so a missing table
never breaks the others. Used by the web history route and
`learning/recap.py`.

#### Scenario: Struggle signal from study_progress only
- **WHEN** a concept has `confidence='struggling'` in `study_progress`
  but no corresponding `study_sessions` or `parked_topics` rows
- **THEN** `get_struggling_topics()` still surfaces that topic

#### Scenario: One source table missing
- **WHEN** the `parked_topics` table does not exist (pre-migration DB)
- **THEN** `get_struggling_topics()` returns results from the other
  two sources without raising an error
