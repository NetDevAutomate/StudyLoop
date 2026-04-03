# Session Handoff — 2026-04-03

## What Was Done

### 1. Pre-commit Fix + Push
- Fixed pre-push pytest hook missing `-m "not integration"` (matched CI config)
- Established bundle push workflow: this machine → scp bundle → remote pulls → remote pushes to GitHub

### 2. `studyctl clean` Command
- **FCIS architecture** — pure logic in `_clean_logic.py` (`plan_clean()` returns `CleanResult`), thin CLI shell in `_clean.py`
- Kills zombie tmux sessions (no child process + aged >60s)
- Removes stale session directories, resets ended state files
- `--dry-run` flag for preview, TOCTOU protection via `LOCK_FILE`
- Symlink safety, graceful tmux-server-down handling
- 17 new tests, zero mocks on the core logic

### 3. tmux-resurrect Compatibility
- **Auto-clean on startup**: `_auto_clean_zombies()` runs at top of `studyctl study` before session creation
- **Documented restore hook**: `@resurrect-restore-hook` config snippet in `setup-guide.md`
- **Doctor check**: detects tmux-resurrect plugin, warns if restore hook not configured
- 4 new tests

### 4. Study Backlog Phase 1 — CRUD + CLI
- `studyctl backlog list/add/resolve` commands
- Migration v16: `source` (parked|struggled|manual) + `tech_area` columns on `parked_topics`
- `backlog_logic.py` — FCIS functional core with `format_backlog_list()`, `build_backlog_summary()`, `plan_auto_persist()`
- Auto-persist struggled topics at session end
- Inject backlog summary into agent persona at session start
- 27 new tests (14 unit, 9 CLI, 4 fixture updates)

### 5. Study Backlog Phase 2 — AI Prioritization + MCP
- Migration v17: `priority` INTEGER column on `parked_topics` (agent-assessed importance 1-5)
- `score_backlog_items()` — algorithmic scoring: 60% importance + 40% frequency
- `studyctl backlog suggest` — ranked topic suggestions CLI
- **4 new MCP tools**: `get_study_backlog`, `get_topic_suggestions`, `get_study_history`, `record_topic_progress`
- `parking.py`: `get_topic_frequencies()`, `update_topic_priority()`
- Architecture docs with PlantUML: session-db as first-class component
- 13 integration tests (real DB, full pipeline, all session types)
- 11 new unit/CLI tests

### 6. Vendor Static Assets for Offline PWA
- Vendored HTMX 2.0.4, htmx-ext-sse 2.2.2, Alpine.js 3.14.8
- Vendored OpenDyslexic font (CSS + woff2/woff files)
- Service worker cache bumped to v4 with vendor assets
- 10 new vendor tests
- Note: Google Fonts (Inter) still CDN with system fallback

### Documentation Created
- `docs/mentoring/functional-core-imperative-shell.md` — comprehensive FCIS learning doc with Mermaid diagrams
- `docs/architecture/study-backlog-phase1.md` — PlantUML architecture for Phase 1
- `docs/architecture/study-backlog-phase2.md` — PlantUML architecture for Phase 2 + session-db integration
- 4 brainstorm docs in `docs/brainstorms/`

## Test Summary

| Suite | Count |
|-------|-------|
| CI-safe (`-m "not integration"`) | 786 passed |
| Integration (real DB) | 13 passed |
| **Total** | **799 tests** |

Started session at 738, ended at 799 (+61 new tests).

## Current State

- **Branch**: `main` (in sync with origin)
- **Both machines in sync**: `user` + `user@192.168.1.22`
- **Clean working tree**: no uncommitted changes
- **Schema version**: v17

## Key Patterns Established

- **Functional Core, Imperative Shell (FCIS)**: `_clean_logic.py`, `backlog_logic.py` — pure logic, zero mocks in tests
- **Query layer over existing data**: study backlog uses `parked_topics`, no new table (YAGNI)
- **MCP tools as extensibility layer**: agent gets direct session-db read/write access
- **Bundle push workflow**: git bundle → scp → remote pull → remote push to GitHub

## Key Files Modified/Created

| File | What |
|------|------|
| `cli/_clean.py` + `_clean_logic.py` | Clean command (FCIS) |
| `cli/_topics.py` | Backlog CLI (list/add/resolve/suggest) |
| `backlog_logic.py` | FCIS core (format, score, persist planning) |
| `mcp/tools.py` | 4 new MCP tools for session-db |
| `parking.py` | source, tech_area, priority, frequencies |
| `tmux.py` | is_tmux_server_running, list_study_sessions, is_zombie_session |
| `cli/_study.py` | auto-clean zombies, auto-persist struggled, backlog injection |
| `doctor/config.py` | tmux-resurrect detection |
| `web/static/vendor/` | Vendored JS/CSS/fonts |
| `migrations.py` | v16 (source, tech_area) + v17 (priority) |

## Known Issues / Gaps

1. **Google Fonts (Inter)** still loaded from CDN — needs vendoring for true offline or system font fallback
2. **Nested tmux UAT test** — untested `is_in_tmux()` → `switch_client()` path (needs tmux)
3. **`--end` from outside UAT test** — `studyctl study --end` CLI path has no UAT test (needs tmux)
4. **MCP tools not yet registered in agent persona** — agent needs to be told about the new tools via persona/CLAUDE.md

## Next Session — Recommended Start

1. **Verify CI green** on GitHub Actions
2. **Parked topic warmup at session start** — partially done (backlog injection), could enhance with spaced repetition signals
3. **Break suggestions at timer threshold crossings** — from `break-science.md`
4. **Energy streaks** — correlate energy levels with session outcomes in `studyctl streaks`
5. **Phase 3: Devices** — ttyd + LAN access (needs tmux machine)

## Run Commands

```bash
# Full CI-safe suite
uv run ruff check . && uv run ruff format --check . && uv run pytest --tb=short -m "not integration"

# Integration tests (real DB)
uv run pytest packages/studyctl/tests/test_session_db_integration.py -v

# All new test files from this session
uv run pytest packages/studyctl/tests/test_clean.py packages/studyctl/tests/test_backlog_logic.py packages/studyctl/tests/test_topics_cli.py packages/studyctl/tests/test_web_vendor.py packages/studyctl/tests/test_session_db_integration.py -v

# Live test
uv run studyctl study "Python Decorators" --energy 7

# Try the new commands
uv run studyctl backlog list
uv run studyctl backlog add "Closures" --tech Python --note "Need deeper dive"
uv run studyctl backlog suggest
uv run studyctl clean --dry-run
uv run studyctl doctor
```
