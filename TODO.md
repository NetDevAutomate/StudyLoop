# Socratic Study Mentor — Active Backlog

> Single source of truth for outstanding work.
> System overview: `docs/system-overview.md`

## Core Features (maintained)

| Feature | Status |
|---------|--------|
| Socratic AI sessions (Claude, Kiro, Gemini, OpenCode) | Active |
| Content pipeline → NotebookLM (split, process, autopilot) | Active |
| Flashcard/quiz review (PWA web app, SM-2) | Active |
| Session intelligence (export, search, sync) | Active |
| Live study sessions (`studyctl study` + tmux + sidebar) | Active |

## Completed (summary)

| Phase | Description | Status |
|-------|-------------|--------|
| 1-9 | Foundation, agents, AuDHD methodology, docs, artefacts, config, TUI, PWA | Done |
| Phase 0 | Config consolidation, CLI split, WAL mode, service layer | Done |
| Phase 1 | Content absorption: 7 modules, 10 CLI commands, 76 tests | Done |
| Phase 4 | PyPI + Homebrew tap, OIDC trusted publishing | Done |
| Phase 5 | Doctor/upgrade/install-mentor: 3 CLI commands, 7 checker modules | Done |
| Compaction | Strip to 4 core features, 13 CLI commands | Done |

### v2.2 — Live Session Dashboard (on `feat+live-session-dashboard` branch)

| Item | Status |
|------|--------|
| Session CLI (`session start/end/status`, `park`) + IPC protocol | Done |
| cmux agent protocol (Phase 1.5) | Done |
| Web dashboard — SSE + HTMX + Alpine.js (`/session`) | Done |
| Bug fixes — parking dedup, IPC permissions 0700/0600, CORS, SSE mtime | Done |
| `studyctl study` — tmux session, agent launcher (Claude), Textual sidebar | Done |
| Agent personas (`study.md`, `co-study.md`) | Done |
| Auto-cleanup on agent exit + sidebar `Q` end session | Done |
| Persistent session directories with conversation resume (`claude -r`) | Done |
| Pomodoro countdown timer (25/5/25/5/25/5/25/15 cycle) | Done |
| Catppuccin-compatible tmux overlay (no theme clobbering) | Done |
| System overview doc (`docs/system-overview.md`) | Done |
| **359 tests pass, all pre-commit hooks pass** | |

### v2.2.1 — CI Fixes, Test Harness & Session Bug Fixes (2026-04-02)

| Item | Status |
|------|--------|
| Fix CI lint + test failures (ruff format, integration test markers) | Done |
| Fix 7 Copilot review comments (migrations, parking dedup, a11y, SW cache) | Done |
| Fix Q quit — kill all study sessions, detach-on-destroy, no tmux residue | Done |
| Fix resume — zombie detection via pgrep, kill_session retry | Done |
| Fix agent not starting — absolute path for claude binary | Done |
| 3-layer test harness (Pilot 5, Lifecycle 15, UAT 6) | Done |
| Add pexpect + textual[dev] test dependencies | Done |
| Documentation updates (setup-guide, session-protocol) | Done |
| Solution doc (`docs/solutions/tmux-session-management-and-ci-issues.md`) | Done |
| **747 tests pass, all pre-commit hooks pass** | |

### v2.2.2 — Architecture Polish & v2.2 Completion (2026-04-03)

| Item | Status |
|------|--------|
| `logic/` subpackage for FCIS cores (clean, backlog, break, streaks) | Done |
| Self-healing `_connect()` — fix parking table schema drift bug | Done |
| Break suggestions — FCIS core + sidebar BreakBanner + IPC | Done |
| Energy streaks — distribution, trend, duration correlation | Done |
| MCP tool registration in agent persona + mcp.json | Done |
| Vendor Inter font (zero CDN dependencies, fully offline PWA) | Done |
| Nested tmux UAT test (switch_client path) | Done |
| `--end` from outside UAT test (kill + cleanup) | Done |
| DRY refactor — sidebar imports thresholds from break_logic.py | Done |
| Documentation updates — roadmap, system-overview, TESTING, FCIS guide | Done |
| **896 tests pass, all pre-commit hooks pass** | |

## Next

> **Release strategy**: v2.2 is feature-complete. Tag release when ready. CI/CD and Devices/LAN come as v2.3/v2.4.

> **Testing mandate**: Every phase MUST include modular tests at all 3 layers:
> - **Unit** (CI-safe) — mocked dependencies, fast, deterministic
> - **Integration** (local tmux) — real tmux with mock agents, poll-based
> - **UAT** (pexpect) — simulated real user terminal sessions
>
> The test harness (`tests/harness/`) is designed to be extended per phase. Add new harness modules (e.g., `harness/web.py`, `harness/topics.py`) alongside feature code. Tests are not an afterthought — they are the definition of done.

### Phase: Session Robustness ✅

| Task | Status |
|------|--------|
| `studyctl clean` — kill stale tmux sessions, remove old IPC files, prune orphaned session dirs | Done |
| tmux-resurrect compatibility — exclude `study-*` sessions from resurrect save/restore | Done |
| Nested tmux UAT test (`switch_client` path verified) | Done |
| `studyctl study --end` UAT test (kill + cleanup from outside) | Done |

### Phase: Study Backlog — Topic Management ✅

| Task | Status |
|------|--------|
| `studyctl topics list/add/resolve` — backlog CRUD | Done |
| Session-db migrations v14-v17 (parked_topics + source + tech_area + priority) | Done |
| Auto-populate from parked/struggled topics at session end | Done |
| Agent surfaces backlog at session start | Done |
| AI prioritization scoring (`logic/backlog_logic.py`) | Done |
| `studyctl topics suggest` — algorithmic ranking | Done |
| 4 new MCP tools (backlog, suggestions, history, progress) | Done |

### Phase: v2.2 Polish ✅

| Task | Status |
|------|--------|
| Vendor all web assets (HTMX, Alpine.js, OpenDyslexic, Inter) — zero CDN, offline PWA | Done |
| Break suggestions at timer thresholds (`logic/break_logic.py` + sidebar BreakBanner) | Done |
| Energy streaks — distribution, trend, duration correlation in `studyctl streaks` | Done |
| Register all 10 MCP tools in agent persona + `mcp.json` | Done |
| `logic/` subpackage for FCIS cores | Done |
| Self-healing `_connect()` for schema drift | Done |
| **896 tests passing, 0 failures** | |

### Phase: Multi-Agent Support (~1 session)

| Task | Complexity | Est. Time |
|------|-----------|-----------|
| Gemini CLI launch command + persona integration | Low | 1-2 hrs |
| Kiro CLI launch command + persona integration | Low | 1-2 hrs |
| OpenCode launch command + persona integration | Low | 1-2 hrs |
| Agent auto-detection priority order (configurable in `config.yaml`) | Low | 1 hr |
| Tests: agent launcher unit tests for each agent, integration test with mock binary | Low | 1-2 hrs |

### Phase: CI/CD Pipeline (~2-3 sessions)

| Task | Complexity | Est. Time |
|------|-----------|-----------|
| Nightly: fresh install on Ubuntu + macOS, `studyctl doctor --json` as gate | Medium | 3-4 hrs |
| Pre-release: upgrade path N-1 → N, triggered on release tags | Medium | 2-3 hrs |
| Docker: `studyctl-web` image with health check via doctor | Medium | 3-4 hrs |
| `compatibility.json` for pre-flight version checks | Low | 1-2 hrs |

### Phase: Devices + LAN Access (~3-4 sessions)

| Task | Complexity | Est. Time |
|------|-----------|-----------|
| ttyd via nginx/Caddy proxy (Unix socket, htpasswd auth) | Medium | 3-4 hrs |
| pyrage + macOS Keychain for password management | Medium | 2-3 hrs |
| LAN password auth | Medium | 2-3 hrs |
| Web terminal embed (iframe with LAN IP, `frame-ancestors` CSP) | Medium | 2-3 hrs |
| `studyctl study --lan` flag | Low | 1-2 hrs |
| Tests: LAN access integration tests, auth verification | Medium | 2-3 hrs |

### Phase: MCP Agent Integration (~2-3 sessions)

| Task | Complexity | Est. Time |
|------|-----------|-----------|
| FastMCP v1 server with stdio transport | Medium | 3-4 hrs |
| Flashcard/quiz generation tools | Medium | 2-3 hrs |
| Study context + onboarding agent | Medium | 2-3 hrs |
| Tests: MCP tool unit tests, integration with session-db | Medium | 2-3 hrs |

## Standalone Items

- [x] ~~Merge `feat+live-session-dashboard` to main + release v2.2.0~~ (merged via PR #2)
- [x] ~~Textual sidebar tests (using Textual test framework)~~ (5 Pilot tests added 2026-04-02)

## Archived Features (in git history, restore on demand)

- TUI dashboard (`studyctl tui`) — replaced by Textual sidebar in tmux
- Scheduler (launchd/cron management)
- Calendar .ics generation (`schedule-blocks`)
- Knowledge bridges DB + CLI commands
- Teach-back scoring DB + CLI commands
- Crush + Amp agent definitions

## Deferred (add when real demand appears)

- LAN password auth (Phase 3 — ttyd + pyrage + Keychain)
- Config editor web UI
- Native iOS/macOS app
- AWS cloud sync (Cognito, DynamoDB, push notifications)
- Agents: Gemini, Kiro, OpenCode launch commands (add when testing against binaries)

## Key File References

| Item | Location |
|------|----------|
| System Overview | `docs/system-overview.md` |
| Session Architecture Plan | `docs/plans/2026-03-29-feat-unified-session-architecture-plan.md` |
| FCIS Logic Cores | `packages/studyctl/src/studyctl/logic/` |
| CLI Package | `packages/studyctl/src/studyctl/cli/` |
| Study Orchestrator | `packages/studyctl/src/studyctl/cli/_study.py` |
| tmux Wrapper | `packages/studyctl/src/studyctl/tmux.py` |
| Agent Launcher | `packages/studyctl/src/studyctl/agent_launcher.py` |
| Textual Sidebar | `packages/studyctl/src/studyctl/tui/sidebar.py` |
| Web PWA + Session Dashboard | `packages/studyctl/src/studyctl/web/` |
| Agent Personas | `agents/shared/personas/` |
| Services Layer | `packages/studyctl/src/studyctl/services/` |
| Review DB (SM-2) | `packages/studyctl/src/studyctl/review_db.py` |
| Config | `~/.config/studyctl/config.yaml` |
| Session Directories | `~/.config/studyctl/sessions/` |
