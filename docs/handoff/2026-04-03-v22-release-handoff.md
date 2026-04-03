---
title: "v2.2 Release Handoff — Remaining Refactors"
date: 2026-04-03
---

# v2.2 Release Handoff

~~Two structural refactors remain before tagging v2.2.0.~~ **All P0 refactors complete (2026-04-03).** All 6 v2.2 features, all debt items, CI fix, documentation current, 898 tests (834 CI-safe passing).

## What's Done (This Session)

| Commit | Description |
|--------|-------------|
| `e28e316` | `logic/` subpackage + parking schema drift fix |
| `92c25b8` | Phase A: break suggestions, energy streaks, MCP reg, vendor Inter |
| `827dd03` | Phase B: nested tmux UAT, --end from outside UAT |
| `40fe146` | Docs: architecture, roadmap, test counts |
| `57b8c49` | Config cleanup, query_sessions split, CI fix |
| `ffbe649` | Docs: fix stale references |
| `37c36f1` | 3 quick fixes: raw SQL, DRY cleanup, hardcoded paths |

**Test suite: 896 passing, 0 failures.**

## ✅ Completed: P0 Refactors

### Refactor 1: Split `history.py` God Module (1029 lines → 9 modules) — DONE

**Why**: 21 functions mixing 7 domain concerns. Hardest file to navigate in the codebase.

**Target structure**:

```
studyctl/history/
├── __init__.py          # re-export all public functions (backwards compat)
├── _connection.py       # _find_db(), _connect() — shared by all modules
├── sessions.py          # start_study_session, end_study_session, get_study_session_stats, get_session_notes, get_energy_session_data
├── progress.py          # record_progress, get_wins, spaced_repetition_due
├── search.py            # topic_frequency, struggle_topics, get_last_session_summary
├── teachback.py         # record_teachback, get_teachback_history
├── bridges.py           # record_bridge, get_bridges, update_bridge_usage, migrate_bridges_to_graph
├── concepts.py          # seed_concepts_from_config, list_concepts
├── streaks.py           # get_study_streaks
└── medication.py        # check_medication_window
```

**Consumer map** (files that import from `history.py`):

| Consumer | Functions Used |
|----------|---------------|
| `cli/_study.py` | `start_study_session`, `end_study_session`, `get_session_notes` |
| `cli/_review.py` | `get_study_streaks`, `get_energy_session_data`, `get_wins`, `spaced_repetition_due`, `record_progress`, `get_bridges`, `record_bridge`, `get_teachback_history`, `record_teachback` |
| `cli/_session.py` | `start_study_session` |
| `cli/_topics.py` | (none — uses parking.py) |
| `cli/_config.py` | `seed_concepts_from_config` |
| `web/routes/history.py` | `get_last_session_summary`, `topic_frequency` |
| `web/routes/session.py` | (uses session_state, not history) |
| `mcp/tools.py` | `topic_frequency`, `get_last_session_summary` |
| `services/review.py` | `spaced_repetition_due`, `record_progress` |
| `doctor/database.py` | `_find_db` (indirect — uses settings) |
| `tests/test_history.py` | All functions |

**Strategy**:
1. Create `history/` package with `__init__.py` that re-exports all public functions
2. Move functions into focused modules
3. All consumers keep importing `from studyctl.history import X` — the `__init__.py` handles routing
4. Zero blast radius for consumers (re-exports maintain API)
5. Run full test suite after each module extraction

**Key risk**: The `__init__.py` re-export approach means consumers don't need to change imports. This is the RIGHT time for re-exports (unlike the `logic/` package where we used explicit paths) because `history` is an internal API with 10+ consumers — changing all imports would be high-risk busywork.

**Estimated effort**: 3-4 hours.

### Refactor 2: Extract Orchestration from `_study.py` (799 → 435 lines) — DONE

**Why**: `_handle_start()` is ~270 lines. The file mixes CLI dispatch with tmux setup, agent launching, and session management.

**Target structure**:

```
studyctl/
├── cli/_study.py          # ~200 lines — thin CLI: study(), _handle_start(), _handle_resume(), _handle_end()
├── session/
│   ├── __init__.py
│   ├── orchestrator.py    # create_study_session() — tmux + agent + sidebar + web
│   ├── resume.py          # check_resumable(), rebuild_session()
│   └── cleanup.py         # _end_session_common() (already extracted this session)
```

**What moves out of `_study.py`**:

| Current Function | Lines | Target |
|-----------------|-------|--------|
| `_handle_start()` lines 350-515 (tmux setup) | ~165 | `session/orchestrator.py` |
| `_handle_start()` lines 420-475 (agent + sidebar) | ~55 | `session/orchestrator.py` |
| `_handle_resume()` lines 520-607 | ~87 | `session/resume.py` |
| `_end_session_common()` | ~45 | `session/cleanup.py` (already extracted) |
| `_auto_clean_zombies()` | ~30 | stays in `_study.py` (thin, calls FCIS) |
| `_build_backlog_notes()` | ~25 | stays in `_study.py` (thin, calls FCIS) |
| `_auto_persist_struggled()` | ~20 | stays in `_study.py` (thin, calls FCIS) |
| `_start_web_background()` | ~20 | `session/orchestrator.py` |
| `sidebar_cmd()` | ~15 | stays in `_study.py` (Textual entry point) |

**Consumer map** (files that import from `_study.py`):

| Consumer | What it uses |
|----------|-------------|
| `cli/__init__.py` | `study` (Click command) — no change |
| `tui/sidebar.py` | (doesn't import _study.py) |
| Tests | `test_study.py` — mocks `_handle_start`, `_handle_resume`, `_handle_end` |

**Strategy**:
1. Create `session/` package
2. Move `_end_session_common()` to `session/cleanup.py` (already extracted)
3. Extract `create_study_session()` from `_handle_start()` into `session/orchestrator.py`
4. Extract resume logic into `session/resume.py`
5. `_study.py` becomes a thin dispatcher: parse CLI args → call orchestrator/resume/cleanup

**Key risk**: The tmux setup code has subtle ordering requirements (session creation → pane split → agent launch → sidebar launch → switch/attach). The orchestrator must preserve this exact sequence.

**Estimated effort**: 3-4 hours.

### Also Completed (P1)

| Task | Status | Notes |
|------|--------|-------|
| Split `settings.py` dual purpose | **Done** | `settings.py` (config) + `topics.py` (topic definitions) |
| Fix SM-2 interval overflow | **Done** | Capped interval at 365 days in `review_db.py` |
| Wire `cli/_review.py` through `services/review.py` | **Skipped** | Wrong abstraction — different domains (topic SR vs SM-2 flashcards) |
| Nightly CI for UAT tests | Deferred | GitHub Actions macOS runner with tmux |

## Test Strategy for Refactors

Both refactors are **pure moves** — no behavior changes. The test strategy is:

1. **Before**: run full suite, record baseline (896 pass)
2. **During**: run affected test files after each module extraction
3. **After**: run full suite, confirm identical pass count
4. **Ruff + pyright**: must pass on every new/modified file

## Architecture After Completion

```
studyctl/
├── logic/                  # FCIS cores (clean, backlog, break, streaks)
├── history/                # Data access (sessions, progress, teachback, bridges, etc.)
├── session/                # Session orchestration (create, resume, cleanup)
├── services/               # Service layer (review, content)
├── cli/                    # Thin CLI handlers (Click commands)
├── tui/                    # Textual sidebar + break banner
├── web/                    # FastAPI + HTMX (fully offline PWA)
├── mcp/                    # 10 MCP tools
├── doctor/                 # Health checks (19 checks, 7 categories)
├── content/                # Content pipeline (splitter, notebooklm, syllabus)
├── parking.py              # Parked topics CRUD
├── session_state.py        # IPC file protocol
├── tmux.py                 # tmux session management
├── review_db.py            # SM-2 spaced repetition
└── settings.py             # Config loading (topics removed to config.yaml)
```

## How to Start Next Session

1. Read this handoff document
2. Start with Refactor 1 (`history.py` split) — it's lower risk (re-exports maintain API)
3. Then Refactor 2 (`_study.py` extraction) — higher risk, needs careful ordering
4. Wire `cli/_review.py` through service layer
5. Run full test suite
6. Tag v2.2.0
