# Roadmap

> ⚠️ **Compaction (March 2026)**: The project was stripped to 4 core features: Socratic AI sessions, content pipeline (NotebookLM), flashcard/quiz review (PWA), and session intelligence (export + search + sync). Features listed below as completed may have been archived — see `docs/plans/compaction-plan.md` for details. The TUI dashboard, scheduler, calendar, knowledge bridges DB, teach-back scoring DB, win/streak tracking CLI commands, and state push/pull CLI were removed. Agent support was consolidated to Claude Code, Kiro, Gemini, and OpenCode.

## v1.0 — Foundation

- [x] Monorepo with studyctl + agent-session-tools
- [x] Kiro CLI + Claude Code agent definitions
- [x] Spaced repetition scheduling (1/3/7/14/30 days)
- [x] Session export from 8+ AI tools
- [x] FTS5 + hybrid semantic search
- [x] Cross-machine sync
- [x] Obsidian → NotebookLM sync
- [x] Install scripts for both platforms

## v1.1 — AuDHD Learning Intelligence

Features designed specifically for AuDHD brains, ranked by impact.

### 🔴 High Priority

#### ~~Win Tracking~~ ✅
**Why:** AuDHD brains are terrible at recognising progress (RSD + imposter syndrome). Seeing concrete evidence of improvement is genuinely therapeutic.

- [x] `studyctl wins` — show concepts that moved from "struggled" to "confident"
- [x] Session count trends (studying more consistently?)
- [x] Skills where scaffolding level decreased over time
- [x] Queryable from agents for positive reinforcement during sessions

#### ~~Energy-Adaptive Sessions~~ ✅
**Why:** Variable capacity is THE defining AuDHD challenge. A "high energy" day and a "low energy" day need completely different study approaches.

- [x] `--energy low|medium|high` flag on session start
- [x] Low → shorter chunks, more scaffolding, review-only mode
- [x] High → deeper dives, harder Socratic questions, new material
- [x] Historical energy patterns → "you do your best Python work on Tuesday mornings"
- [x] Claude Code status line shows current energy level
- [x] Emotional regulation check (calm/anxious/frustrated/flat/shutdown)

#### ~~Struggle → Adaptive Difficulty~~ ✅
**Why:** Repeating the same explanation doesn't work for neurodivergent brains. If a concept appears in 3+ sessions with questions, try a different approach.

- [x] Auto-detect recurring struggles from session history
- [x] Agent offers different analogies, smaller pieces, different modalities
- [x] "Try writing a small program that uses X" vs "let me explain X again"
- [x] Feeds into spaced repetition scheduling
- [x] struggle_topics now config-driven

### 🟡 Medium Priority

#### ~~"Where Was I?" Auto-Resume~~ ✅
**Why:** AuDHD learners lose context between sessions constantly. Manual context loading is a barrier to starting.

- [x] `studyctl resume` — automatic last-session summary with topics, concepts in progress
- [x] Built on existing session query infrastructure
- [x] Shows: what you were learning, where you got stuck, what's next
- [x] Integrated into session protocol — agents run it at session start

#### ~~Hyperfocus Guardrails~~ ✅
**Why:** Hyperfocus is a superpower but needs channeling. A study partner would say "you've been at this for 2 hours."

- [x] Session duration tracking with configurable nudges
- [x] Rabbit hole detection: "you started SQL but you've been in Python for 40 min"
- [x] Break reminders at configurable intervals (25/50/90 min)
- [x] Claude Code status line shows elapsed time + focus state

#### ~~Calendar Time-Blocking & Reminders~~ ✅
**Why:** ADHD task initiation is the hardest part. External triggers (notifications, calendar blocks) bypass the executive function barrier.

- [x] Apple Calendar + Reminders MCP integration (macOS) — native notifications
- [x] Google Calendar MCP integration (cross-platform)
- [x] Auto-create study time blocks from `studyctl review` output
- [x] Daily study briefing generation
- [x] Break reminders via native notifications
- [x] Note: Windows/WSL2 users use Google Calendar; macOS users can use either

### 🔵 Nice to Have

#### Pomodoro Session Structure
**Why:** Time-boxed structure helps ADHD brains with task initiation and sustained attention.

- 5 min review → 20 min focus → 5 min summarise
- Agent adapts behaviour to current phase
- Claude Code status line shows phase + timer
- Configurable intervals

#### Claude Code Status Line Integration
**Why:** Persistent visual feedback without interrupting flow. Shows energy, timer, pomodoro phase, context usage.

- Custom status line script reading session state file
- Display: 🔋 Energy | ⏱️ Timer | 🍅 Pomodoro | 📊 Context %
- Agent writes state → script reads state → user sees it
- Note: kiro-cli does not support status lines (state shown in chat messages instead)

#### Cowork Integration (Claude Desktop)
**Why:** Scheduled daily study briefings without opening a terminal.

- Cowork folder instructions for Socratic mentoring behaviour
- `/schedule` recurring tasks for daily study review
- Google Calendar connector for schedule-aware study planning
- Note: Requires Claude Desktop open + computer awake

## v1.2 — Community & Polish

- [x] PyPI publishing (v2.0 — OIDC trusted publishing)
- [ ] Additional test coverage (exporters, scheduler, CLI commands, speak, PDF)
- [ ] VSCode integration (fix circular import)
- [x] TUI interface (textual) (v1.5)
- [ ] Watchdog file watcher for auto-sync
- [ ] Community-contributed study topics
- [ ] Localisation support
- [x] TTS voice output (kokoro-tts / ltts integration)
- [x] MkDocs documentation site (font toggle, Nord colours, reading preferences, 7 admonition types, `studyctl docs` CLI)
- [x] Gemini CLI / OpenCode / Amp agents (unified shared framework)
- [x] CI Python version matrix (3.12, 3.13)
- [x] GitHub Pages deployment workflow
- [x] CHANGELOG.md and release automation (git-cliff + release.yml)
- [ ] `query_sessions.py` refactor — split into CLI, formatters, resolver modules

## v1.3 — AuDHD Intelligence (from review)

Features identified through comprehensive code review:

- [x] **"Where Was I?" auto-resume** — `studyctl resume` shows last session, topics, concepts in progress
- [x] **Medication timing awareness** — optional config for cognitive windows (onset/peak/tapering/worn off)
- [x] **Visual progress map** — `studyctl progress-map` with Mermaid diagram output
- [x] **Routine building / streak tracking** — `studyctl streaks` with current/longest streak, consistency %
- [x] **Interleaving suppression on low-energy days** — automatic rule to disable topic mixing when energy < 4
- [x] **Custom admonition style guide** — document the 7 custom admonition types for contributors

## v1.4 — Pedagogical Intelligence

Features to deepen the mentor's teaching methodology and student wellbeing.

### Active Break Protocol
**Why:** The science shows sustained attention degrades after ~25 minutes (Ariga & Lleras, 2011). ADHD brains deplete faster. Evidence-based break timing dramatically improves retention and focus.

- [x] Three-tier break system: micro (2-3 min), short (5-10 min), long (15-20 min)
- [x] Energy-adaptive intervals (shorter breaks when energy is low)
- [x] Wrap-up buffer for flow states (don't hard-stop mid-thought)
- [x] Non-negotiable hydration minimum even during hyperfocus
- [x] PDA-sensitive reminders (information, not instruction)
- [x] Science communication (explain WHY on first break)
- [x] Shared framework: `agents/shared/break-science.md`

### Session Wind-Down
**Why:** NIH research (Buch et al., 2021) shows the brain replays learning at 20x speed during quiet rest — but only if you avoid high-cognitive-load activities for 10-15 minutes after a session. This consolidation is 4x more powerful than overnight sleep.

- [x] Three-phase wind-down: session wrap → consolidation guidance → next session suggestion
- [x] Science-based consolidation advice (walk, avoid phone, leave desk)
- [x] Concrete first step for ADHD transition support ("Stand up. Walk to kitchen.")
- [x] Time-of-day aware next session suggestions
- [x] Shared framework: `agents/shared/wind-down-protocol.md`

### Teach the Teacher
**Why:** The Protege Effect (Chase et al., 2009) — people learn more deeply when teaching. Scoring teach-backs provides concrete mastery evidence (fights RSD/imposter syndrome) and drives adaptive spaced repetition.

- [x] 5-dimension scoring rubric: Accuracy, Own Words, Structure, Depth, Transfer (each 1-4)
- [x] Teach-back layered into every spaced repetition interval (micro at 3 days → full at 30 days)
- [x] Detection probes for understanding vs memorisation
- [x] Angle rotation: Bloom's levels, contexts, modalities, directions
- [x] Score transparency with metacognitive calibration
- [x] `studyctl teachback` and `studyctl teachback-history` CLI commands
- [x] Database migration v10: teach_back_scores table + study_progress extensions
- [x] Shared framework: `agents/shared/teach-back-protocol.md`

### Dynamic Knowledge Bridging
**Why:** The current system hardcodes networking as the bridge domain. Configurable bridges make the tool usable for anyone, and dynamic bridge tracking improves analogy quality over time.

- [x] Configurable knowledge domains via `~/.config/studyctl/config.yaml`
- [x] Interactive configure flow (discover student's expertise, map anchors, generate bridges)
- [x] Bridge lifecycle: proposed → validated → effective (or misleading → rejected)
- [x] Student-generated bridge capture and re-use
- [x] Bridge fading (explicit at L1-L2, prompted at L3, student-generated at L4)
- [x] Warm-up activation before new material
- [x] `studyctl bridge add/list` CLI commands
- [x] Database migration v11: knowledge_bridges table
- [x] Shared framework: `agents/shared/knowledge-bridging.md`
- [x] Default: networking bridges preserved as zero-configuration experience

## v1.5 — Code Quality & Framework Unification

Bug fixes, agent framework unification, and documentation polish.

- [x] **Bug fixes**: `record_progress()` case sensitivity, legacy DB paths removed, `init_config()` hardcoded machine names
- [x] **Study sessions wired up**: `start_study_session()`, `end_study_session()`, `get_study_session_stats()` for the orphaned `study_sessions` table
- [x] **Unified agent framework**: All 5 platforms (Kiro, Claude Code, Gemini, OpenCode, Amp) reference `agents/shared/` — eliminated ~700 lines of inline duplication
- [x] **Interactive config wizard**: `studyctl config init` with knowledge bridging, NotebookLM, Obsidian vault questions
- [x] **Config viewer**: `studyctl config show` with Rich tables
- [x] **Docs site**: `studyctl docs serve/open/list/read` commands
- [x] **Agent installation integration**: `install-agents.sh` called from `config init` flow

## v2.0 — Unified Platform

Monorepo restructure, content pipeline absorption, packaging, and infrastructure hardening.

- [x] **Phase 0**: Config consolidation (`settings.py` single source), CLI split into `cli/` package with LazyGroup (12 modules), WAL mode on all SQLite connections, service layer (`services/review.py`, `services/content.py`), JSON contract formalised
- [x] **Phase 1**: Content absorption — 7 modules from pdf-by-chapters (`splitter`, `notebooklm_client`, `syllabus`, `markdown_converter`, `models`, `storage`), 10 CLI commands under `studyctl content`, 76 tests
- [x] **Phase 4**: PyPI publishing (`studyctl` on PyPI), Homebrew personal tap (`NetDevAutomate/studyctl/studyctl`), OIDC trusted publishing, `studyctl setup` wizard
- [x] **327 tests**, 4 skipped (optional deps)

## v2.1 — Health & Self-Update (current)

Diagnostic engine, self-update mechanism, and AI-guided setup for non-technical users.

- [x] **`studyctl doctor`** — 19 health checks across 7 categories (core, database, config, agents, deps, voice, updates). Rich table output, `--json` for AI agents/CI, `--quiet` for scripts, `--category` for filtering. Exit codes: 0=healthy, 1=actionable, 2=core failure.
- [x] **`studyctl update`** — check for available updates (always exit 0, informational)
- [x] **`studyctl upgrade`** — apply updates with `--dry-run`, `--component`, `--force`. Package manager detection (uv/brew/pip), DB backup with 30-day pruning, agent definition updates.
- [x] **Install-mentor agent** — tool-agnostic AI-guided setup prompt (`agents/shared/install-mentor.md`). Uses `studyctl doctor --json` as contract, fix loop capped at 3 iterations. Works with Claude Code, Kiro, Gemini CLI, OpenCode, Amp.
- [x] **Agent manifest** — `agents/manifest.json` tracks SHA-256 hashes of all agent definitions. `scripts/update-agent-manifest.py` regenerates.
- [x] **Documentation** — README, CLI reference, setup guide, agent-install all updated for non-technical users.

## v2.2 — Live Session Dashboard (in progress)

Live study session with real-time dashboard, parking lot, and timer.

- [x] **Phase 1 — Foundation**: Session CLI (`session start/end/status`, `park`), file-IPC protocol (`session-state.json`, `session-topics.md`, `session-parking.md`), parking lot persistence (migration v14), auto-migration on connect
- [x] **Phase 1.5 — cmux**: Agent protocol for cmux MCP pane control (macOS/Ghostty)
- [x] **Phase 2 — Web Dashboard**: SSE-powered live dashboard (`/session`), HTMX + Alpine.js, energy-adaptive timer, activity feed with visual language, session summary, artefact viewer, 14 tests
- [x] **Bugs fixed**: Parking deduplication (migration v15 + `INSERT OR IGNORE`), IPC file permissions (0700/0600), CORS wildcard removed, SSE mtime optimization, timer pause/reset controls, auto-migrate parked_topics
- [x] **Phase 1 — Unified Session**: `studyctl study` single command, tmux session runtime (`tmux.py`), agent launcher (`agent_launcher.py`, Claude-only), Textual sidebar (`tui/sidebar.py`), `--resume`/`--end`/`--web`, agent personas (`study.md`, `co-study.md`), persistent session directories with conversation history resume (`claude -r`), auto-cleanup on agent exit, catppuccin-compatible tmux overlay, 39 tests.
- [ ] **Phase 2 — Polish**: Energy streaks, break suggestions, parked topic warmup, vendored HTMX/Alpine.js
- [ ] **Phase 3 — Devices**: ttyd via nginx proxy, pyrage + Keychain password, web terminal embed, LAN access

## Next

### Phase 6: CI/CD Pipeline

Nightly drift detection, pre-release gate, and Docker image pipeline. Spec at `docs/ci-cd-pipeline.md`.

- [ ] Nightly: fresh install on Ubuntu + macOS, `studyctl doctor --json` as gate
- [ ] Pre-release: upgrade path N-1 -> N, triggered on release tags
- [ ] Docker: `studyctl-web` image with server-side TTS, health check via doctor
- [ ] `compatibility.json` for pre-flight version checks

### Phase 7: Docker Web + Server-Side TTS

- [ ] Docker image running `studyctl web` with kokoro-onnx TTS
- [ ] FastAPI audio endpoint for browser playback

### Phase 3: MCP Agent Integration

- [ ] FastMCP v1 server with stdio transport
- [ ] Flashcard/quiz generation tools, study context, onboarding agent
