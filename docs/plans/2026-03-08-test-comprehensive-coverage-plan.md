---
title: "test: Comprehensive Test Coverage"
type: test
date: 2026-03-08
finding: 30
priority: P3
---

# Comprehensive Test Coverage

## Overview

Add meaningful test coverage for all untested modules. Currently 925 lines of tests cover 5 modules. The target is ~3500 total test lines covering 25+ modules, prioritised by risk and value.

## Current State

### Tested (5 files, 925 lines)
- `test_config_loader.py` (128 lines) — config loading
- `test_query_sessions.py` (175 lines) — date parsing, thresholds, FTS, DB size
- `test_sync.py` (190 lines) — session sync round-trips
- `test_calendar.py` (159 lines) — ICS generation, scheduling
- `test_history.py` (163 lines) — spaced repetition, wins, streaks

### Untested (20+ modules, ~3500 lines of source code)
- 8 exporters (aider, bedrock, claude, gemini, kiro, litellm, opencode, repoprompt)
- `base.py` (ExportStats, commit_batch)
- `formatters.py` (markdown, XML, summary, context-only)
- `query_utils.py` (date parsing, FTS escaping, session resolution)
- `utils.py` (stable_id, content_hash, file_fingerprint)
- `scheduler.py` (launchd/cron generation)
- `speak.py` (TTS backends)
- `pdf.py` (markdown→PDF)
- `cli.py` (studyctl Click commands)
- `migrations.py` (schema versioning)
- `tutor_checkpoint.py` (progress recording)
- `maintenance.py` (vacuum, archive, dedup)
- `classifier.py` (session classification)
- `deduplication.py` (duplicate detection)

## Commit Strategy

One commit per test wave. Each wave is independently valuable.

## Implementation Phases

### Wave 1: Pure Functions (Low Risk, High Value)
**Commit:** `test: add tests for utils, formatters, query_utils, base`

These modules are pure functions with no I/O — easiest to test, highest confidence gain.

#### 1.1 `test_utils.py` (~40 lines)
- [ ] `stable_id` returns deterministic IDs for same input
- [ ] `stable_id` returns different IDs for different inputs
- [ ] `stable_id` normalises path case
- [ ] `content_hash` returns consistent hashes
- [ ] `file_fingerprint` includes mtime and size

#### 1.2 `test_formatters.py` (~120 lines)
- [ ] `format_markdown` includes session headers when not compressed
- [ ] `format_markdown` compresses long assistant responses
- [ ] `format_markdown` skips tool messages by default
- [ ] `format_xml` produces valid XML structure
- [ ] `format_xml` escapes `&`, `<`, `>` in content
- [ ] `format_xml` extracts code blocks into `<code>` elements
- [ ] `format_summary` extracts first user message as topic
- [ ] `format_summary` limits to 3 code blocks
- [ ] `format_context_only` extracts only code blocks
- [ ] `render_profile` substitutes placeholders
- [ ] `render_profile` falls back to compressed markdown without template

#### 1.3 `test_query_utils.py` (~80 lines)
- [ ] Move existing parse_date/build_date_filter/check_thresholds/get_db_size tests here
- [ ] `escape_fts_query` preserves FTS operators (AND, OR, NOT)
- [ ] `escape_fts_query` wraps multi-word queries in quotes
- [ ] `escape_fts_query` leaves single words unquoted for stemming
- [ ] `resolve_session_id` exact match returns immediately
- [ ] `resolve_session_id` prefix match returns unique result
- [ ] `resolve_session_id` raises ValueError for no match
- [ ] `resolve_session_id` raises ValueError for ambiguous match

#### 1.4 `test_base.py` (~60 lines)
- [ ] `ExportStats` defaults to zeros
- [ ] `ExportStats.__iadd__` accumulates correctly
- [ ] `commit_batch` inserts sessions and messages
- [ ] `commit_batch` handles missing optional fields via .get()
- [ ] `commit_batch` updates stats from session status flags
- [ ] `commit_batch` rolls back and increments errors on failure

### Wave 2: Exporters (Medium Risk, Highest Value)
**Commit:** `test: add exporter tests with fixture data`

Each exporter needs a fixture (fake data directory or DB) and a test that verifies it produces valid session/message dicts. No live tool installations required.

#### 2.1 `test_exporters_base.py` (~50 lines)
- [ ] All exporters in EXPORTERS registry have correct source_name
- [ ] All exporters implement is_available()
- [ ] All exporters implement export_all()
- [ ] Bedrock exporter is registered (regression test for #15)

#### 2.2 `test_exporter_claude.py` (~100 lines)
- [ ] Fixture: create fake `~/.claude/projects/` with JSONL agent files
- [ ] `is_available()` returns True when projects dir exists
- [ ] `is_available()` returns False when missing
- [ ] `export_all()` parses JSONL entries into sessions and messages
- [ ] Session IDs are stable (same file → same ID)
- [ ] Incremental export skips already-imported sessions

#### 2.3 `test_exporter_aider.py` (~100 lines)
- [ ] Fixture: create fake `.aider.chat.history.md` files
- [ ] `is_available()` checks search paths
- [ ] `export_all()` parses markdown into sessions
- [ ] `_walk_with_exclusions` skips excluded directories
- [ ] `_parse_aider_markdown` handles USER/ASSISTANT blocks

#### 2.4 `test_exporter_kiro.py` (~80 lines)
- [ ] Fixture: create fake kiro SQLite database with conversations table
- [ ] `is_available()` checks database file
- [ ] `export_all()` extracts conversation history
- [ ] Handles malformed JSON gracefully (stats.errors incremented)

#### 2.5 `test_exporter_gemini.py` (~80 lines)
- [ ] Fixture: create fake `~/.gemini/tmp/` session files
- [ ] Parses session JSON into sessions and messages
- [ ] Handles missing/empty files gracefully

#### 2.6 `test_exporter_opencode.py` (~60 lines)
- [ ] `_ms_to_iso` returns None for None
- [ ] `_ms_to_iso` converts milliseconds to ISO string
- [ ] `_ms_to_iso` handles 0 correctly (not falsy, returns epoch)

#### 2.7 `test_exporter_litellm.py` (~80 lines)
- [ ] Fixture: create fake LiteLLM SQLite database
- [ ] Session detection groups requests by time window
- [ ] Handles missing conversations table

#### 2.8 `test_exporter_repoprompt.py` (~60 lines)
- [ ] `cf_timestamp_to_iso` converts Core Foundation timestamps
- [ ] `cf_timestamp_to_iso` returns None for None input
- [ ] Fixture: create fake RepoPrompt SQLite database

### Wave 3: CLI Commands (Medium Risk, Good Value)
**Commit:** `test: add CLI command tests using Click CliRunner`

Use Click's `CliRunner` for studyctl and Typer's `CliRunner` for agent-session-tools.

#### 3.1 `test_studyctl_cli.py` (~200 lines)
- [ ] `studyctl topics` lists configured topics
- [ ] `studyctl review` with empty DB shows "nothing due"
- [ ] `studyctl struggles` with empty DB shows "no struggles"
- [ ] `studyctl wins` with empty DB shows "no progress data"
- [ ] `studyctl progress` records a concept
- [ ] `studyctl resume` with empty DB shows "no sessions"
- [ ] `studyctl streaks` with empty DB shows "no sessions"
- [ ] `studyctl progress-map` with empty DB shows "no progress"
- [ ] `studyctl docs list` shows available pages
- [ ] `studyctl schedule list` shows no jobs when none installed

#### 3.2 `test_export_cli.py` (~60 lines)
- [ ] `session-export --help` shows all options
- [ ] `session-export --sources invalid` raises BadParameter
- [ ] Only one `--*-only` flag at a time

### Wave 4: Infrastructure Modules (Lower Risk)
**Commit:** `test: add tests for scheduler, migrations, tutor_checkpoint`

#### 4.1 `test_scheduler.py` (~100 lines)
- [ ] `Job` dataclass stores name, command, schedule
- [ ] launchd plist generation produces valid XML
- [ ] cron entry generation produces valid cron syntax
- [ ] `list_jobs` returns empty list when none installed
- [ ] `install_all` / `remove_all` are idempotent

#### 4.2 `test_migrations.py` (~60 lines)
- [ ] `get_user_version` returns 0 for fresh DB
- [ ] `set_user_version` updates version
- [ ] `migrate` applies all pending migrations
- [ ] `migrate` skips already-applied migrations
- [ ] `migrate` returns list of applied migration names

#### 4.3 `test_tutor_checkpoint.py` (~50 lines)
- [ ] Creates session and message in DB
- [ ] Session has source="study_mentor" and session_type="study"
- [ ] Handles duplicate checkpoint gracefully (IntegrityError)

### Wave 5: Modules Requiring Mocks (Higher Complexity)
**Commit:** `test: add tests for speak, pdf, maintenance with mocks`

These modules call external processes — tests need mocking.

#### 5.1 `test_speak.py` (~80 lines)
- [ ] `_get_tts_config` returns defaults when no config
- [ ] `_ensure_kokoro_models` returns True when models exist
- [ ] `_speak_macos` calls subprocess with correct args (mock subprocess)
- [ ] `speak` command reads from stdin when text is "-"
- [ ] Backend fallback chain: kokoro → macos

#### 5.2 `test_pdf.py` (~40 lines)
- [ ] Markdown to PDF conversion calls pandoc (mock subprocess)
- [ ] Handles missing pandoc gracefully

#### 5.3 `test_maintenance.py` (~60 lines)
- [ ] `vacuum` runs VACUUM on database
- [ ] `reindex` rebuilds FTS index
- [ ] Archive moves old sessions to archive DB

---

## Testing Patterns

### Fixture Strategy
```python
# Reuse conftest.py temp_db fixture for all DB tests
# Create exporter-specific fixtures that build fake data directories

@pytest.fixture
def fake_claude_dir(tmp_path):
    """Create fake Claude Code project directory with JSONL sessions."""
    projects = tmp_path / ".claude" / "projects"
    project = projects / "-Users-test-myproject"
    project.mkdir(parents=True)
    # Write fake JSONL session file
    session_file = project / "agent-001.jsonl"
    session_file.write_text(...)
    return projects
```

### CLI Testing
```python
from click.testing import CliRunner
from studyctl.cli import cli

def test_topics(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(cli, ["topics"])
    assert result.exit_code == 0
```

### Mock External Dependencies
```python
from unittest.mock import patch

def test_speak_macos():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = Mock(returncode=0)
        result = _speak_macos("hello", voice="Samantha")
        assert result is True
        mock_run.assert_called_once()
```

---

## Priority Order

| Wave | Tests | Lines | Value | Risk |
|------|-------|-------|-------|------|
| 1 | Pure functions | ~300 | High — catch regressions in extracted modules | Low |
| 2 | Exporters | ~610 | Highest — untested core functionality | Medium |
| 3 | CLI commands | ~260 | Good — catch integration issues | Medium |
| 4 | Infrastructure | ~210 | Good — catch scheduler/migration bugs | Low |
| 5 | Mocked modules | ~180 | Medium — external deps are flaky | Higher |
| **Total** | | **~1560** | | |

Combined with existing 925 lines → **~2485 total test lines**.

## Acceptance Criteria

- [ ] `uv run pytest` passes with all new tests
- [ ] `uv run pytest --cov=packages/ --cov-report=term-missing` shows coverage for all tested modules
- [ ] No test requires live AI tool installations
- [ ] No test requires network access
- [ ] Each wave is independently committable and revertable
- [ ] Tests run in < 10 seconds total

## Dependencies

- Waves 1-4 have no external dependencies
- Wave 5 needs `unittest.mock` (stdlib)
- All waves use existing `conftest.py` fixtures

## Risk Mitigation

- **Exporter tests are the highest value** — if time is limited, prioritise Wave 2
- **CLI tests catch integration regressions** — important after the query_sessions.py refactor
- **Mock tests are brittle by nature** — keep them focused on interface contracts, not implementation details
