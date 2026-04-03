---
title: "Phase 6 Complete — CI/CD Pipeline + v2.2 Refactors"
date: 2026-04-03
---

# Session Handoff — 2026-04-03

## What Was Done

### v2.2 Refactors (all P0 items from code review)

| Commit | Description |
|--------|-------------|
| `98b9d88` | Split `history.py` (1029 lines) → `history/` package (9 focused modules) |
| `98b9d88` | Extract `_study.py` (799 lines) → 435 lines + `session/` package (orchestrator, resume, cleanup) |
| `98b9d88` | Split `settings.py` → `settings.py` (config) + `topics.py` (Topic, get_topics) |
| `98b9d88` | Fix SM-2 interval overflow in `review_db.py` (capped at 365 days) |

### Phase 6: CI/CD Pipeline

| Commit | Description |
|--------|-------------|
| `4500e9c` | `nightly-uat.yml` — tmux integration tests on macOS, 03:00 UTC daily |
| `38e7cae` | Fix orphaned process leak — `_kill_orphaned_processes()` in integration test cleanup |
| `28740a0` | `nightly-install.yml` — fresh install + `studyctl doctor --json` gate (Ubuntu + macOS, 3.12 + 3.13) |
| `28740a0` | `pre-release.yml` — N-1 → N upgrade path test on `v*` tags |
| `28740a0` | `studyctl backup` / `studyctl restore` — timestamped snapshots with safety backup |
| `d3747e8` | All documentation updated for current architecture |

### Architecture After This Session

```
studyctl/
├── logic/                  # FCIS cores (clean, backlog, break, streaks)
├── history/                # Data access — 9 modules:
│   ├── _connection.py      #   shared DB helpers
│   ├── sessions.py         #   session CRUD + summary
│   ├── progress.py         #   progress tracking + spaced repetition
│   ├── search.py           #   FTS5 topic frequency + struggles
│   ├── teachback.py        #   5-dimension scoring
│   ├── bridges.py          #   knowledge bridge CRUD + migration
│   ├── concepts.py         #   concept seeding + listing
│   ├── streaks.py          #   study streak calculation
│   └── medication.py       #   medication window checking
├── session/                # Session orchestration:
│   ├── orchestrator.py     #   tmux env creation + pane layout
│   ├── resume.py           #   reattach/rebuild sessions
│   └── cleanup.py          #   end session + IPC cleanup
├── services/               # Service layer (review, content)
├── cli/                    # Thin CLI handlers (Click, LazyGroup)
│   ├── _study.py           #   435 lines — thin dispatcher
│   ├── _backup.py          #   backup/restore commands
│   └── ...                 #   17 other command modules
├── topics.py               # Topic definitions (split from settings.py)
├── settings.py             # Config loading only
├── tui/                    # Textual sidebar + break banner
├── web/                    # FastAPI + HTMX (fully offline PWA)
├── mcp/                    # 10 MCP tools
├── doctor/                 # Health checks (19 checks, 7 categories)
└── content/                # Content pipeline
```

### CI/CD Pipeline (5 workflows)

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| `ci.yml` | push/PR | Lint (ruff) + typecheck (pyright) + unit tests |
| `nightly-uat.yml` | 03:00 UTC daily | tmux integration tests on macOS |
| `nightly-install.yml` | 03:30 UTC daily | Fresh install + doctor gate (Ubuntu + macOS × 3.12 + 3.13) |
| `pre-release.yml` | `v*` tags | N-1 → N upgrade path + doctor gate |
| `publish.yml` | `v*` tags | Build + publish to PyPI via OIDC |

### Test Suite

```
906 tests collected
834 CI-safe passing (non-tmux)
 10 new backup/restore tests
 51 tmux integration tests (need macOS + tmux)
  3 skipped (optional deps)
```

## What's NOT Done

- **v2.2.0 tag not created** — user wants to push and tag separately
- **Git push not done** — 5 commits ready on main, not pushed
- **Conftest collision workaround** — removed conftest.py to avoid pytest plugin collision between packages. Orphan cleanup is handled per-test in `_cleanup_all()` but there's no session-scoped safety net. Consider fixing the pytest plugin registration for monorepos if this recurs.

## Known Issues

1. **tmux "fork failed: Device not configured"** — caused by orphaned test processes exhausting ptys. Fixed in `_cleanup_all()` but can recur if tests are interrupted. Run `pkill -f "studyctl.tui.sidebar"` to recover.
2. **`test_web_app::test_post_review`** — was flaky due to SM-2 interval overflow. Fixed by capping interval at 365 days.

## Next Phase: Phase 2 — Multi-Agent Support

Currently Claude-only for `studyctl study`. The agent framework (`agents/shared/`) already supports 4 platforms. Phase 2 wires the launch path:

- Gemini CLI launch command + persona integration
- Kiro CLI launch command + persona integration
- OpenCode launch command + persona integration
- Agent auto-detection priority order (configurable)

### Then: Phase 3 — Devices (ttyd + LAN)

- ttyd via nginx/Caddy proxy
- `studyctl study --lan` flag
- Docker `studyctl-web` image (deferred from Phase 6)

## How to Start Next Session

1. Read this handoff document
2. Push to remote: use bundle+scp to user@192.168.1.22
3. Optionally tag v2.2.0
4. Start Phase 2 planning with brainstorm
