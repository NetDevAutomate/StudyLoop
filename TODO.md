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

## Next

> **Release strategy**: Complete v2.2 Polish + Multi-Agent + Study Backlog, then release as v2.2.0 to GitHub/PyPI/Brew. CI/CD and Devices/LAN come as v2.3/v2.4.

> **Testing mandate**: Every phase MUST include modular tests at all 3 layers:
> - **Unit** (CI-safe) — mocked dependencies, fast, deterministic
> - **Integration** (local tmux) — real tmux with mock agents, poll-based
> - **UAT** (pexpect) — simulated real user terminal sessions
>
> The test harness (`tests/harness/`) is designed to be extended per phase. Add new harness modules (e.g., `harness/web.py`, `harness/topics.py`) alongside feature code. Tests are not an afterthought — they are the definition of done.

### Phase: Session Robustness (~1 session)

| Task | Complexity | Est. Time |
|------|-----------|-----------|
| `studyctl clean` — kill stale tmux sessions, remove old IPC files, prune orphaned session dirs | Low | 1-2 hrs |
| tmux-resurrect compatibility — exclude `study-*` sessions from resurrect save/restore | Medium | 2-3 hrs |
| Nested tmux UAT test — test `studyctl study` from inside existing tmux (`switch_client` path) | Medium | 2-3 hrs |
| `studyctl study --end` UAT test — verify CLI end kills sessions from outside tmux | Low | 1 hr |
| Push to origin + verify CI green | Low | 30 min |

### Phase: Study Backlog — Topic Management (~2-3 sessions)

Persistent cross-session study backlog. Users can see what's outstanding, add topics, and the agent prioritizes based on the bigger learning picture. All data in session-db for cross-machine sync.

**Phase 1 — CRUD + CLI (~1-2 sessions, Medium)**

| Task | Complexity | Est. Time |
|------|-----------|-----------|
| `studyctl topics list` — show outstanding items (parked, struggled, unresolved) across all sessions | Medium | 2-3 hrs |
| `studyctl topics add "topic" --tech "Python" --note "..."` — manually add topics to the backlog | Low | 1-2 hrs |
| `studyctl topics resolve <id>` — mark a topic as covered/resolved | Low | 1 hr |
| Session-db migration — `study_backlog` table (topic, tech_area, source, priority, status, session refs) | Medium | 1-2 hrs |
| Auto-populate from parked topics + struggled topics at session end | Medium | 2-3 hrs |
| Agent surfaces backlog at session start ("you have 3 outstanding Python topics") | Low | 1-2 hrs |
| Tests: unit + integration + UAT for topic CRUD and session-start surfacing | Medium | 2-3 hrs |

**Phase 2 — AI Prioritization (~1 session, Medium)**

| Task | Complexity | Est. Time |
|------|-----------|-----------|
| Agent-driven technology categorization (emerges from topic content, not hardcoded taxonomy) | Medium | 2-3 hrs |
| Priority scoring based on session-db history (frequency, recency, dependency on other concepts) | Medium | 2-3 hrs |
| `studyctl topics suggest` — AI-ranked "what to study next" based on backlog + progress | Medium | 2-3 hrs |
| Tests: priority scoring unit tests, suggest command integration test | Medium | 2 hrs |

### Phase: v2.2 Polish (~1-2 sessions)

| Task | Complexity | Est. Time |
|------|-----------|-----------|
| Vendor HTMX + Alpine.js into `web/static/` (remove CDN, enable offline PWA) | Low | 1-2 hrs |
| Parked topic warmup at session start (surface unresolved topics) | Low | 1-2 hrs |
| Break suggestions at timer threshold crossings (from `break-science.md`) | Medium | 2-3 hrs |
| Energy streaks — correlate energy levels with session outcomes in `studyctl streaks` | Medium | 2-3 hrs |
| Tests: web dashboard harness (`harness/web.py`), break suggestion unit tests | Medium | 2-3 hrs |

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
