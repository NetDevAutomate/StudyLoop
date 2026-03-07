# Roadmap

## v1.0 — Foundation (current)

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

#### "Where Was I?" Auto-Resume
**Why:** AuDHD learners lose context between sessions constantly. Manual context loading is a barrier to starting.

- Automatic last-session summary on session start
- Built on existing `session-query context` infrastructure
- Shows: what you were learning, where you got stuck, what's next
- Reduces session-start friction (huge for ADHD task initiation)

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

- [ ] PyPI publishing
- [ ] Additional test coverage
- [ ] VSCode integration (fix circular import)
- [ ] TUI interface (textual)
- [ ] Watchdog file watcher for auto-sync
- [ ] Community-contributed study topics
- [ ] Localisation support
- [ ] TTS voice output (kokoro-tts / ltts integration)
- [ ] MkDocs documentation site polish
- [ ] Gemini CLI / OpenCode / Amp agent testing
