<p align="center">
  <img src="icons/studyloop-banner.png" alt="StudyLoop — an agentic study platform for AuDHD minds" width="100%">
</p>

# StudyLoop

> An AuDHD-aware study toolkit for turning a messy learning goal into a focused plan, then studying it through Socratic mentoring, body-doubling, and evidence from real sessions.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![CI](https://github.com/NetDevAutomate/StudyLoop/actions/workflows/ci.yml/badge.svg)

## What Does It Do?

Six things:

1. **Agentic study planning** — Type or dictate one unstructured brain dump in the browser. StudyLoop's Architect asks focused questions and proposes a Markdown plan with a rendered learning map. You approve, revise, or reject the exact proposal; at most three plans stay current.
2. **Socratic AI sessions** — Body doubling with AI mentors that ask questions instead of giving answers. Energy-adaptive (low day? shorter chunks, more scaffolding).
3. **Content pipeline** — Chunk eBooks and optional Markdown/plain-text notes → generate quizzes, flashcards, and hands-on practice tasks locally, without requiring external notebook services.
4. **Active learning decisions** — `studyloop now` chooses one useful next action from due reviews, weak concepts, practice tasks, energy, modality, and time available.
5. **Flashcard review** — Spaced repetition (SM-2) in the browser app. Works on tablet and laptop.
6. **Session tracking** — Export AI coding sessions (Claude Code, Codex, Kiro, Gemini, OpenCode, pi, omp, and more) into a searchable SQLite database. Track trends, find struggle topics, search across sessions. Optionally mirror each session into your Obsidian vault (`--obsidian`) as Dataview-compatible Markdown with `[[wikilink]]` backlinks and per-project index notes.

Built by a neurodivergent learner transitioning from networking to data engineering. If you're self-teaching and AuDHD, this might help.

## Quick Start

```bash
# Install from source (no PyPI release)
git clone https://github.com/NetDevAutomate/StudyLoop studyloop
cd studyloop
./scripts/install.sh

# Configure
studyloop self-test        # Lightweight post-install check
studyloop setup              # Notes-optional setup; auto-detects a local planning gateway
studyloop doctor --fix       # Verify and apply safe fixes

# Create the first plan before asking StudyLoop what to do next
studyloop web                # Study Plans → Create with Architect
# Type or dictate one brain dump, answer focused follow-ups, then approve/revise/reject

# Core workflow — live Socratic study (tmux + agent, or web Study Session tab)
studyloop study "Python decorators" --energy 6
# studyloop web              # Alternative: browser picker + PTY/xterm.js terminal

# Supporting workflows
studyloop now                # One recommended study action for your energy/time
studyloop chat-note NOTE.md  # Turn one note into a Socratic context pack
studyloop content generate-cards SOURCE --course python     # Local quiz + flashcard JSON
studyloop content generate-practice SOURCE --course python  # Local hands-on practice JSON
studyloop resume             # Where you left off (session summary)
studyloop review             # Spaced repetition due today
studyloop recap today        # One win, one repair target, one due item, one next action
studyloop recap today --audio-file recap.wav  # Save a local audio recap
studyloop web                # Flashcards, quizzes, live session dashboard
session-export               # Export AI sessions to SQLite
session-query search-cmd "decorators"
```

See [docs/first-week.md](docs/first-week.md) for a day-by-day onboarding path.

## Architecture

```mermaid
graph LR
    subgraph "Study Materials"
        OB[Obsidian Vault]
        SRC[Markdown/PDF/text]
    end

    subgraph "CLI Tools"
        SC[studyloop]
        LEARN["Active learning services<br/>now, chat-note,<br/>practice verify,<br/>recap, mastery"]
        AST[agent-session-tools]
        DB[(SQLite DB)]
    end

    subgraph "Released Live Web Harnesses"
        CA[Claude Code]
        CX[Codex CLI]
        KA[Kiro CLI]
        GA[Gemini CLI]
        OA[OpenCode]
    end

    subgraph "CLI-only Local-model Adapters"
        OL[Ollama]
        LM[LM Studio]
    end

    subgraph "Live Session"
        IPC["IPC Files<br/>(state, topics, parking)"]
        SSE["Web Dashboard<br/>(SSE + HTMX)"]
    end

    OBV["Obsidian Vault<br/>AgentMemory/"]

    OB -->|study source| SC
    SRC -->|parse/generate| SC
    SC --> LEARN
    SC -->|sessions + review| DB
    LEARN -->|recommend + record evidence| DB
    AST -->|export sessions| DB
    AST -.->|"--obsidian (opt-in)"| OBV
    CA -->|Socratic sessions| DB
    CX -->|Socratic sessions| DB
    KA -->|Socratic sessions| DB
    GA -->|Socratic sessions| DB
    OA -->|Socratic sessions| DB
    OL -->|Socratic sessions| DB
    LM -->|Socratic sessions| DB
    CA -->|writes| IPC
    IPC -->|polls| SSE
```

## CLI Reference

### studyloop

```bash
# Study sessions (tmux + AI agent + sidebar)
studyloop study "topic" --energy 7      # Full tmux environment in one command
studyloop study "topic" --web           # Also start web dashboard + auto-open browser
studyloop study "topic" --lan           # LAN auth prompts before the agent starts (implies --web)
studyloop study --resume                # Resume conversation from history
studyloop study --end                   # End session (quit Claude also works)
studyloop park "question"               # Park tangential topic

# Content pipeline
studyloop content split SOURCE       # Split PDF by chapters
studyloop content generate-cards DIR --course COURSE  # Generate local quiz/flashcard JSON
studyloop content generate-practice DIR --course COURSE  # Generate local hands-on practice JSON
studyloop content discover           # Preview configured study sources
studyloop content ingest --dry-run   # Plan course-material ingest

# Review & AuDHD progress
studyloop now                        # Recommend one next study action
studyloop now --energy low --time 15 # Smaller, lower-switching recommendation
studyloop chat-note NOTE.md --mode diagram  # Socratic prompt from a note
studyloop practice verify TASKS.json --task 1 --notes "what passed"
studyloop recap today --speak        # Daily audio recap through study-speak
studyloop recap today --audio-file recap.wav
studyloop mastery graph --topic python  # Mermaid concept dependency graph
studyloop mastery weak-links --topic python
studyloop review                     # Check spaced repetition due dates
studyloop review --interleave adaptive --energy medium
studyloop struggles --days 30        # Find recurring struggle topics
studyloop wins                       # Learning wins (mastered / confident concepts)
studyloop resume                     # Where you left off (session summary)
studyloop streaks                    # Study streak and consistency stats
studyloop web                        # Launch flashcard/quiz web app

# Backlog & cleanup
studyloop backlog list               # Cross-session study backlog
studyloop clean --dry-run            # Preview orphan session cleanup

# Focus & session-DB tiering
studyloop focus                      # Show current focus topics (max 3)
studyloop focus suggest              # Suggest focus from recent sessions + struggles
studyloop focus set "python" "sql"   # Confirm up to 3 focus topics
studyloop prune --days 30            # Preview pruning old local sessions (dry run)
studyloop prune --days 30 --apply    # Delete — only sessions verified in the full DB
session-maint sync-full              # Incremental sync of sessions.db -> full DB
session-maint snapshot               # Point-in-time snapshot of the full DB (rotated)
session-maint fts-check --fix        # Check/repair the FTS index invariant

# Status/topics
studyloop status                     # Show sync status
studyloop topics                     # List configured course topics (config.yaml)

# Health & metrics
studyloop doctor                     # Check installation health
studyloop doctor --fix               # Apply safe automatic fixes
studyloop install agents             # Install AI agent definitions from source checkout
studyloop setup                      # Interactive configuration
studyloop session effectiveness      # Persona effectiveness over time
```

### agent-session-tools

```bash
session-export                       # Export AI sessions to SQLite
session-export --sources claude codex
session-export --pi-only             # Export only pi sessions
session-export --omp-only            # Export only omp sessions
session-export --obsidian            # Also write notes to your Obsidian vault
session-export --obsidian --obsidian-backfill  # one-time: mirror all history
session-query search-cmd QUERY       # Full-text search across sessions
session-query list --since 7d        # List recent sessions
session-query stats-cmd              # Database statistics
session-sync push/pull/sync HOST     # Cross-machine sync
```

## Integration Support

### Five release-gated live web harnesses

| Platform | Agent | Start With |
|----------|-------|------------|
| Claude Code | `socratic-mentor` | `/agent socratic-mentor` |
| Codex CLI | `AGENTS.md` | `codex` in the project root |
| Kiro CLI | `study-mentor` | `kiro-cli chat --agent study-mentor` |
| Gemini CLI | `study-mentor` | `gemini` (auto-detected) |
| OpenCode | `study-mentor` | Tab to switch agent |

These are the v0.1 browser Study Session matrix. The strict release gate drives
each real TUI through terminal paint, resize, refresh, automatic reattachment,
post-refresh input, and regrowth. Missing binaries or authentication fail the
gate rather than becoming skips.

### Other integrations (not v0.1 live web harnesses)

| Integration | What StudyLoop supports |
|-------------|--------------------------|
| pi | `AGENTS.md` persona/steering install and session export |
| omp | `AGENTS.md` persona/steering install and session export |
| Ollama | CLI-only local-model launch adapter: `studyloop study "topic" --agent ollama` |
| LM Studio | CLI-only local-model launch adapter: `studyloop study "topic" --agent lmstudio` |

Those rows are useful integrations, but they are not evidence that the v0.1 web
terminal supports nine harnesses. See [Agent Installation](docs/agent-install.md)
for persona/export setup and [CI Workflows](docs/ci.md) for the strict live
matrix.

## Web PWA

Launch locally with `studyloop web`. To use a tablet or laptop on the same
network, start the authenticated LAN mode with `studyloop web --lan` and open
one of the LAN addresses it prints.

> **Not designed for phone screens.** The layout collapses to a single column
> and the sidebar becomes a bottom bar below 600px wide, but the study panels
> themselves — flashcards, quizzes, plans, Mastery — have no phone treatment and
> are unusable at phone width. Tablet and laptop are the supported sizes.

**Study Plans:**
- Open **Study Plans → Create with Architect**, then type or dictate what is in your head; there is no structured intake form
- Optionally paste a course outline or attach a Markdown/plain-text file as context; possession of notes is never counted as progress
- Review the exact Markdown proposal and rendered Mermaid learning map before choosing **Approve**, **Revise**, or **Reject**
- Open an existing plan and choose **Review with Architect** to propose a change; plan changes are not applied silently
- Requires a live planning model configured by `studyloop setup`; coding harnesses such as Kiro and Codex remain separate study-session integrations

**Flashcard review:**
- SM-2 spaced repetition with source/chapter filter
- Session history with 90-day study heatmap
- Pomodoro timer, voice output, OpenDyslexic font toggle
- Add to home screen for a standalone, browser-chrome-free window (`manifest.json` sets `display: standalone`)

> **Not offline.** There is no service worker, so no page or asset is cached: the
> `studyloop web` server must be reachable every time you open the app.

**Course Explorer** (sidebar "Courses" button):
- Browse course material by provider in horizontal carousels, with per-provider filter
- Click a course to list its lessons; click a lesson to read rendered markdown + mermaid diagrams + syntax-highlighted code
- Global fuzzy search (Fuse.js, instant over titles) + full-text search (SQLite FTS5, over lesson bodies)
- "Struggling?" button in the reader flags a lesson to the session DB; surfaces in next study session and deck generation
- "Discuss" copies a Socratic prompt from the current lesson so the reader becomes an active recall or diagram session without a separate chat backend
- "▶ Listen" read-aloud button — tries the configured Kokoro server, then VoiceMode on port 8880, then your OS voice

**Live session dashboard** (`/session`):
- Real-time activity feed via SSE (Server-Sent Events)
- Timer with energy-adaptive colour phases (green/amber/red)
- Topic counters (wins, parked, review)
- Session summary on completion
- **Terminal panel** — the release path renders every supported agent in xterm.js, driving a PTY over a WebSocket (`transport: "pty"`). Experimental ACP chat is available only when the maintainer starts `studyloop web --dev`; release-mode API requests for ACP are rejected. No external terminal binary is involved. See [ADR-0006](docs/adr/0006-gate-acp-behind-dev-mode.md).
- HTMX + Alpine.js — no build step

> **Practice tasks and topic exercises are CLI-only for now.** Feature 2 above
> generates them, and `studyloop practice verify` / `studyloop exercise` score
> them from the terminal. The web backend route exists, but the browser app has
> no exercises panel yet.

## Optional Extras

```bash
# Repo-local optional dependencies
uv sync --all-packages --extra web      # FastAPI web UI
uv sync --all-packages --extra content  # PDF splitting + content pipeline

# Global CLI with the features used in this README
studyloop install tools
```

## Documentation

- [Setup Guide](docs/setup-guide.md) — installation and configuration
- [Your First Week](docs/first-week.md) — minimal day-by-day onboarding
- [Architecture](docs/architecture.md) — current and target architecture
- [Session-DB Tiering](docs/session-db-tiering.md) — hot/full DB tiers, sync, prune, snapshots, restore procedures
- [Content Pipeline](docs/content-pipeline.md) — local generation of review artefacts
- [Study Plans](docs/study-plans.md) — browser Architect, Markdown plan format, review, and current limitations
- [TUI Sidebar Guide](docs/tui-guide.md) — terminal sidebar layout, timer, key bindings
- [Web UI Guide](docs/web-ui-guide.md) — live sessions, live terminal, flashcards, quizzes
- [Agent Installation](docs/agent-install.md) — per-platform agent setup
- [CI Workflows](docs/ci.md) — local and GitHub Actions quality gates
- [Ownership Map](docs/ownership.md) — where common changes should live
- [System Overview](docs/system-overview.md) — architecture and data flow diagrams
- [Repository Standards](docs/standards/repo-standards.md)
- [AuDHD Learning Philosophy](docs/audhd-learning-philosophy.md)
- [AuDHD Learning Loop Implementation](docs/audhd-learning-loop-implementation.md) — how optional notes feed recall and practice, while sessions, teach-backs, and verified attempts become mastery evidence
- [AuDHD Deep Technical Learning Roadmap](docs/audhd-deep-technical-learning-roadmap.md) — implementation status and next refinements for the six active-learning features
- [Voice Output Guide](docs/voice-output.md)
- [Contributing](CONTRIBUTING.md)

## Maintainer Tasks

For local contributor and release workflows, use `just`:

```bash
just preflight
just release-check
just smoke-installed
```

Use `just sync-web`, `just sync-content`, or `just sync-semantic` before optional profile tests when the active `.venv` does not include that dependency set.

Install `just` with:

```bash
brew install just
```

<!-- ARTEFACTS:START -->
## Generated Artefacts

> Explore this project — generated overviews from the historical artefact pipeline.

| | |
|---|---|
| 🎧 **[Listen to the Audio Overview](https://artefacts.netdevautomate.dev/studyloop/artefacts/)** | Two AI hosts discuss the project — great for commutes |
| 🎬 **[Watch the Video Overview](https://artefacts.netdevautomate.dev/studyloop/artefacts/#video)** | Visual walkthrough of architecture and concepts |
| 🖼️ **[View the Infographic](https://artefacts.netdevautomate.dev/studyloop/artefacts/#infographic)** | Architecture and flow at a glance |
| 📊 **[Browse the Slide Deck](https://artefacts.netdevautomate.dev/studyloop/artefacts/#slides)** | Presentation-ready project overview |

*Historical generated artefacts. NotebookLM is not required for the core study workflow.*
<!-- ARTEFACTS:END -->

## Maintainer Notes

### Set the GitHub social preview image

The OpenGraph card shown when this repo is shared on Slack / X / LinkedIn / etc. is **not** picked up automatically — GitHub requires a one-time upload via the web UI:

1. Go to **Settings → General** (top of the repo).
2. Scroll to **Social preview**.
3. Click **Edit** → **Upload an image…**
4. Pick `icons/studyloop-social.png` (1280×640, generated from `icons/studyloop-banner.svg`).
5. Save.

After this, link previews use the proper StudyLoop card. If the banner ever changes, regenerate the social PNG with:

```bash
rsvg-convert -w 1280 -h 640 icons/studyloop-banner.svg -o icons/studyloop-social.png
```

…then re-upload via the same Settings page. The repo can't trigger this from CI.

## License

MIT — see [LICENSE](LICENSE).

Third-party work that influenced StudyLoop is credited in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
