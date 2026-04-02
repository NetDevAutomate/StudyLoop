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

### Immediate — Session Robustness (est. complexity + time)

| Task | Complexity | Est. Time | Priority |
|------|-----------|-----------|----------|
| `studyctl clean` command — kill stale tmux sessions, remove old IPC files, prune orphaned session dirs | Low | 1-2 hrs | P1 |
| tmux-resurrect compatibility — exclude `study-*` sessions from resurrect save/restore | Medium | 2-3 hrs | P1 |
| Nested tmux UAT test — test `studyctl study` from inside existing tmux session (`switch_client` path) | Medium | 2-3 hrs | P1 |
| `studyctl study --end` UAT test — verify CLI end path kills sessions from outside tmux | Low | 1 hr | P2 |
| Push to origin + verify CI green | Low | 30 min | P1 |
| Sync repo to remote machine (`user@192.168.1.22`) + clean remote worktree | Low | 30 min | P2 |

### v2.2 — Remaining Polish (Phase 2)

- [ ] Vendor HTMX + Alpine.js into `web/static/` (remove CDN, enable offline PWA)
- [ ] Parked topic warmup at session start (surface unresolved topics from previous sessions)
- [ ] Break suggestions at timer threshold crossings (from `break-science.md`)
- [ ] Energy streaks — correlate energy levels with session outcomes in `studyctl streaks`

### Phase 6: CI/CD Pipeline

Nightly drift detection, pre-release gate, Docker image pipeline. Spec at `docs/ci-cd-pipeline.md`.

- [ ] Nightly: fresh install on Ubuntu + macOS, `studyctl doctor --json` as gate
- [ ] Pre-release: upgrade path N-1 → N, triggered on release tags
- [ ] Docker: `studyctl-web` image with server-side TTS, health check via doctor

### Phase 3: Devices (ttyd + LAN access)

- [ ] ttyd via nginx/Caddy proxy (Unix socket, htpasswd auth)
- [ ] pyrage + macOS Keychain for password management
- [ ] Web terminal embed (iframe with LAN IP, `frame-ancestors` CSP)
- [ ] `studyctl study --lan` flag

### Phase 7: Docker Web + Server-Side TTS

- [ ] Docker image running `studyctl web` with kokoro-onnx TTS
- [ ] FastAPI audio endpoint for browser playback

### Future — Test Coverage Expansion

| Task | Complexity | Est. Time | Priority |
|------|-----------|-----------|----------|
| Web dashboard tests — `WebSession` harness (httpx + FastAPI test client, SSE stream, `/session` page) | Medium | 3-4 hrs | P2 |
| Speech integration tests — mock TTS endpoint, audio playback verification | Medium | 2-3 hrs | P3 |
| Cross-machine sync tests — verify rsync/git sync between machines | High | 4-5 hrs | P3 |

## Standalone Items (not blocked by phases)

- [ ] Obsidian export: convert flashcard JSON to Obsidian `#flashcard` format (Spaced Repetition plugin compatible)
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
