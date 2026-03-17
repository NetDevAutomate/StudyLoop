# Socratic Study Mentor

> 🧠 An AuDHD-aware Socratic study mentor with AI session management

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![PyPI](https://img.shields.io/pypi/v/studyctl)
![CI](https://github.com/NetDevAutomate/socratic-study-mentor/actions/workflows/ci.yml/badge.svg)

## What is this?

An open-source study toolkit designed specifically for AuDHD learners. It combines two CLI tools with AI mentor agents that teach through Socratic questioning rather than lectures — because our brains get dopamine from *discovering* answers, not being told them. The toolkit tracks your AI study sessions across 7 tools (Claude Code, Kiro CLI, Gemini, etc.) into a searchable database, then uses that history to power spaced repetition scheduling (1/3/7/14/30 day intervals), detect topics you're repeatedly struggling with, and show you concrete evidence of progress — because RSD and imposter syndrome mean we're terrible at recognising how far we've come. It also supports body doubling sessions, energy-adaptive study modes (low energy day? shorter chunks, more scaffolding), and hyperfocus guardrails. It also supports voice output — the mentor can speak questions aloud using high-quality local TTS, adding an auditory channel that helps AuDHD learners stay focused. The agents work with both kiro-cli and Claude Code, and the whole thing syncs across machines. If you're neurodivergent and self-teaching (especially career transitions), this might help — it's built by someone in exactly that position.

## Who is this for?

- **AuDHD learners** who need structured, dopamine-friendly study approaches
- **Self-taught developers** who benefit from Socratic questioning over passive reading
- **Anyone** who wants to track AI study sessions and build spaced repetition into their learning

## Architecture

```mermaid
graph LR
    subgraph "Study Materials"
        OB[Obsidian Vault]
        NLM[NotebookLM<br>optional]
    end

    subgraph "CLI Tools"
        SC[studyctl]
        AST[agent-session-tools]
        DB[(SQLite DB)]
    end

    subgraph "AI Agents"
        KA[kiro-cli]
        CA[Claude Code]
        GA[Gemini CLI]
        OA[OpenCode]
        AA[Amp]
    end

    OB -->|sync| SC
    SC -->|upload| NLM
    SC -->|spaced repetition| DB
    AST -->|export sessions| DB
    DB -->|query history| SC
    KA -->|Socratic sessions| DB
    CA -->|Socratic sessions| DB
    GA -->|Socratic sessions| DB
    OA -->|Socratic sessions| DB
    AA -->|Socratic sessions| DB
```

## Features

**studyctl** — Study pipeline management
- Content pipeline — split PDFs by chapter, upload to NotebookLM, generate audio/video/flashcards
- Syllabus workflow — chunked podcast generation with autopilot and progress tracking
- Obsidian-to-NotebookLM — convert markdown notes to PDFs and upload in one step
- Sync Obsidian notes to Google NotebookLM notebooks
- Spaced repetition scheduling (1/3/7/14/30 day intervals)
- Struggle topic detection from session history
- Win tracking — see concepts you've mastered, fight imposter syndrome
- Calendar time-blocking — generate `.ics` study blocks from your review schedule
- Progress recording with confidence levels (struggling → learning → confident → mastered)
- Concept graph — track how concepts relate (prerequisites, analogies, confusion risks)
- Prerequisite chain traversal — find the root cause when you're stuck
- Cross-machine state sync via SSH
- Scheduled auto-sync (launchd on macOS, cron on Linux)

**agent-session-tools** — AI session management
- 7 source exporters: Claude Code, Kiro CLI, Gemini CLI, Aider, OpenCode, LiteLLM, RepoPrompt
- FTS5 full-text search across all sessions
- Hybrid semantic search (FTS + vector embeddings)
- Session classification and deduplication
- Study progress and energy tracking database
- Cross-machine database sync via SSH

**AI Agents** — Socratic mentoring
- AuDHD-aware teaching methodology (questions > lectures)
- Energy-adaptive sessions (low/medium/high adjusts difficulty and chunk size)
- Emotional regulation check (calm/anxious/frustrated/flat/shutdown)
- Transition support with grounding rituals
- Parking lot for tangential thoughts
- Sensory environment adaptation
- Micro-celebrations for dopamine maintenance
- Interleaved review sessions
- End-of-session protocol: auto-record progress, suggest next review, offer calendar blocks
- Break reminders at 25/50/90 minute intervals
- Claude Code status line showing energy level, session timer, and context usage
- Network→Data Engineering concept bridges
- Body doubling session support
- Progress tracking across agents and machines
- Voice output via study-speak (kokoro-onnx TTS, am_michael voice)
- @speak-start/@speak-stop toggle for voice control
- Configurable voice, speed, and backend

**MCP Integrations** — Optional calendar and reminder support
- Apple Calendar + Reminders (macOS) — native notifications for study time
- Google Calendar (cross-platform) — time-blocking via built-in connector or MCP server
- See [agents/mcp/README.md](agents/mcp/README.md) for setup

## Quick Start

### Install (pick one)

```bash
# PyPI (recommended)
pip install studyctl

# Homebrew (macOS)
brew install NetDevAutomate/studyctl/studyctl

# From source
git clone https://github.com/NetDevAutomate/socratic-study-mentor.git
cd socratic-study-mentor
./scripts/install.sh
```

### 3 Steps to Start

```bash
studyctl setup      # Interactive configuration wizard
studyctl web        # Launch the study web app
studyctl --help     # See all commands
```

### Optional extras

```bash
pip install 'studyctl[all]'       # Everything (web, tui, content, mcp, notebooklm)
pip install 'studyctl[web]'       # FastAPI web UI
pip install 'studyctl[content]'   # PDF splitting + NotebookLM content pipeline
pip install 'studyctl[mcp]'       # MCP server for AI coding assistants
```

### From source (advanced)

The install script registers CLI tools globally, sets up agent definitions for any detected AI tools, and optionally downloads the voice model for TTS support.

```bash
./scripts/install.sh                  # Full install (interactive)
./scripts/install.sh --non-interactive  # For Ansible/CI
./scripts/install.sh --tools-only     # Just CLI tools
./scripts/install.sh --agents-only    # Just agent definitions
```

Then run the interactive setup wizard:

```bash
studyctl config init
```

This asks three core questions: whether to enable knowledge bridging (leveraging topics you already know), NotebookLM integration, and Obsidian vault path.

## Documentation Site

Browse the full docs locally with AuDHD-friendly design (OpenDyslexic font toggle, Nord colour scheme, reading preferences):

```bash
uv pip install 'socratic-study-mentor[docs]'
mkdocs serve
# Open http://localhost:8000
```

## Agent Support

| Platform | Agent | Description |
|----------|-------|-------------|
| kiro-cli | `study-mentor` | Full study session management with spaced repetition and NotebookLM |
| Claude Code | `socratic-mentor` | Socratic questioning with AuDHD-aware pedagogy |
| Claude Code | `mentor-reviewer` | Autonomous code review with scoring and tutorial generation |
| Gemini CLI | `study-mentor` | Socratic study sessions with energy-adaptive teaching |
| OpenCode | `study-mentor` | AuDHD-aware study mentor with spaced repetition |
| Amp | (via AGENTS.md) | Socratic mentoring loaded automatically from project context |

Start a session:

```bash
# kiro-cli
kiro-cli chat --agent study-mentor

# Claude Code
/agent socratic-mentor

# Gemini CLI (subagent auto-detected)
gemini  # then ask for study session

# OpenCode
opencode  # Tab to switch to study-mentor

# Amp
amp  # AGENTS.md loaded automatically
```

See [docs/agent-install.md](docs/agent-install.md) for setup details.

## Optional Dependencies

| Feature | Package | Install |
|---------|---------|---------|
| Content pipeline | `pymupdf`, `httpx` | `uv pip install studyctl[content]` |
| NotebookLM sync | `notebooklm-py` | `uv pip install studyctl[notebooklm]` |
| Semantic search | `sentence-transformers` | `uv pip install agent-session-tools[semantic]` |
| Token counting | `tiktoken` | `uv pip install agent-session-tools[tokens]` |
| TUI interface | `textual` | `uv pip install studyctl[tui]` |
| TTS voice output | `kokoro-onnx` | `uv tool install "./packages/agent-session-tools[tts]"` |

## CLI Reference

### studyctl

```bash
# Study & review
studyctl review                          # Check spaced repetition due dates
studyctl struggles --days 30             # Find recurring struggle topics
studyctl wins --days 30                  # Show your learning wins
studyctl streaks                         # Show study streak and consistency
studyctl resume                          # Where you left off — quick context reload
studyctl progress CONCEPT -t TOPIC -c LEVEL  # Record progress on a concept
studyctl progress-map                    # Visual map of all tracked concepts
studyctl teachback CONCEPT -t TOPIC -s SCORES --type TYPE  # Record teach-back score
studyctl teachback-history CONCEPT       # Show teach-back score progression

# Knowledge bridges
studyctl bridge add SRC TGT -s DOMAIN -t DOMAIN  # Add a knowledge bridge
studyctl bridge list                     # List knowledge bridges

# NotebookLM sync
studyctl sync [TOPIC] --all --dry-run    # Sync notes to NotebookLM
studyctl status [TOPIC]                  # Show sync status
studyctl topics                          # List configured topics
studyctl audio TOPIC                     # Generate NotebookLM audio overview
studyctl dedup [TOPIC] --all --dry-run   # Remove duplicate notebook sources

# Configuration & scheduling
studyctl config init                     # Interactive setup wizard
studyctl config show                     # Display current configuration
studyctl schedule install|remove|list    # Manage scheduled jobs
studyctl schedule-blocks --start 14:00   # Generate .ics calendar study blocks
studyctl state push|pull|status|init     # Cross-machine state sync

# Interfaces
studyctl web [--port PORT] [--host HOST] # Launch study PWA web app
studyctl tui                             # Launch interactive TUI dashboard
studyctl docs serve|open|list|read       # Browse and read documentation
```

### Web PWA (recommended for multi-device study)

Launch the study web app with `studyctl web`. Accessible from any device on the network — phone, tablet, laptop. No extra dependencies.

```bash
studyctl web                    # LAN accessible on port 8567
studyctl web --port 9000        # Custom port
```

**Features:**
- Flashcard and quiz review with SM-2 spaced repetition
- Source/chapter filter — study specific chapters
- Card count limiter — choose 10/20/50/100/All per session
- Due cards indicator on course picker
- Session history with scores and 90-day study heatmap
- Retry wrong answers mode
- Pomodoro timer (25min study / 5min break with audio chime + notifications)
- Voice output via Web Speech API — reads questions/answers aloud, works on any device
- Voice selector dropdown — choose from all English voices available on your device
- Read-once button (speaker icon on card) or auto-voice toggle (header)
- OpenDyslexic font toggle for accessibility
- Dark/light theme toggle
- PWA installable — add to home screen on iOS/Android
- Keyboard shortcuts: `Space` flip, `Y`/`N` answer, `T` read aloud, `V` auto-voice, `S` skip, `R` retry

<img src="images/studyctl_web_ui_quizz.png" alt="Web UI Quiz Mode" width="700">

**Voice setup:** The PWA uses your device's built-in text-to-speech. For best quality, download enhanced voices: Settings → Accessibility → Spoken Content → Voices → English → download Samantha (Enhanced) or Siri voices.

**Config:**

```yaml
# ~/.config/studyctl/config.yaml
review:
  directories:
    - ~/Desktop/ZTM-DE/downloads
    - ~/Desktop/Python/downloads
tui:
  theme: dracula                # Textual theme (TUI only)
  dyslexic_friendly: true       # Wider spacing in TUI
```

### TUI Dashboard (terminal)

Launch the terminal dashboard with `studyctl tui`. Requires the `[tui]` extra (`uv pip install studyctl[tui]`).

**Tabs:** Dashboard, Review, Concepts, Sessions, StudyCards

| Key | Action |
|-----|--------|
| `f` | Start flashcard session |
| `z` | Start quiz session |
| `space` | Flip card / submit answer |
| `y` / `n` | Mark correct / incorrect |
| `r` | Retry wrong answers (after session) |
| `v` | Toggle voice output |
| `o` | Toggle OpenDyslexic spacing |
| `h` | Show hint (quiz mode) |
| `q` | Quit |

<img src="images/socratic_mentor_tui.svg" alt="TUI Dashboard" width="700">

### studyctl content

```bash
# PDF splitting
studyctl content split SOURCE [-o DIR] [-l LEVEL]   # Split PDF by TOC bookmarks
studyctl content split SOURCE --ranges '1-30,31-60'  # Split by page ranges

# Full pipeline (split + upload)
studyctl content process SOURCE [-n NOTEBOOK_ID]     # Split PDFs and upload to NotebookLM

# NotebookLM management
studyctl content list [-n NOTEBOOK_ID]               # List notebooks or sources
studyctl content generate -n ID -c '1-3'             # Generate audio/video overviews
studyctl content download -n ID [-o DIR]             # Download artifacts
studyctl content delete -n ID                        # Delete a notebook

# Syllabus workflow (chunked podcast generation)
studyctl content syllabus -n ID [-o DIR]             # Generate episode plan from sources
studyctl content autopilot [-o DIR]                  # Generate next pending episode
studyctl content status [-o DIR]                     # Show syllabus progress

# Obsidian integration
studyctl content from-obsidian SOURCE_DIR            # Convert markdown → PDF → NotebookLM
```

Requires optional dependencies: `uv pip install studyctl[content]` for PDF splitting, plus `uv pip install studyctl[notebooklm]` for NotebookLM commands.

### agent-session-tools

```bash
session-export [--source SOURCE]         # Export AI sessions to SQLite
session-query search QUERY               # Full-text search across sessions
session-query list --since 7d            # List recent sessions
session-query show SESSION_ID            # Show session details
session-query context SESSION_ID         # Generate context for resuming
session-query stats                      # Database statistics
session-sync push macmini                # Push sessions to a named host
session-sync pull macbookpro             # Pull sessions from a named host
session-sync sync work-macbook           # Two-way sync with a host
session-sync endpoints                   # List all configured remote hosts
session-maint vacuum|reindex|schema      # Database maintenance
tutor-checkpoint code --skill SKILL      # Record study progress
study-speak TEXT                         # Speak text aloud using TTS
study-speak - < file.txt                 # Speak from stdin
study-speak TEXT -v af_heart -s 1.2      # Custom voice and speed
```

> **Single config for all machines:** Define hosts once in `~/.config/studyctl/config.yaml`, deploy the same file everywhere. Both `studyctl state push/pull` and `session-sync push/pull/sync` read from it — local machine auto-detected by hostname. See [Setup Guide](docs/setup-guide.md#hosts--cross-machine-sync).

## Documentation

- [Setup Guide](docs/setup-guide.md) — Installation, configuration, Obsidian setup
- [Agent Installation](docs/agent-install.md) — AI agent setup for kiro-cli, Claude Code, Gemini CLI, OpenCode, and Amp
- [AuDHD Learning Philosophy](docs/audhd-learning-philosophy.md) — Why this exists and how it works
- [MCP Integrations](agents/mcp/README.md) — Calendar, reminders, and other MCP server configs
- [Voice Output Guide](docs/voice-output.md) — TTS setup, configuration, and agent integration
- [Roadmap](docs/roadmap.md) — What's coming in v1.1 and beyond
- [Contributing](CONTRIBUTING.md) — Development setup and contribution guide

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and how to add new exporters or study topics.

## Acknowledgements

> **Special thanks to [Teng Lin](https://github.com/teng-lin)** for creating the excellent [notebooklm-py](https://github.com/teng-lin/notebooklm-py) library, which powers all NotebookLM integration across the study mentor ecosystem. His work in reverse-engineering and wrapping the NotebookLM API made the audio/video overview generation in [notebooklm-pdf-by-chapters](https://github.com/andytaylor/notebooklm-pdf-by-chapters) and [notebooklm-repo-artefacts](https://github.com/andytaylor/notebooklm-repo-artefacts) possible.

<!-- ARTEFACTS:START -->
## Generated Artefacts

> 🔍 **Explore this project** — AI-generated overviews via [Google NotebookLM](https://notebooklm.google.com)

| | |
|---|---|
| 🎧 **[Listen to the Audio Overview](https://artefacts.netdevautomate.dev/socratic-study-mentor/artefacts/)** | Two AI hosts discuss the project — great for commutes |
| 🎬 **[Watch the Video Overview](https://artefacts.netdevautomate.dev/socratic-study-mentor/artefacts/#video)** | Visual walkthrough of architecture and concepts |
| 🖼️ **[View the Infographic](https://artefacts.netdevautomate.dev/socratic-study-mentor/artefacts/#infographic)** | Architecture and flow at a glance |
| 📊 **[Browse the Slide Deck](https://artefacts.netdevautomate.dev/socratic-study-mentor/artefacts/#slides)** | Presentation-ready project overview |

*Generated by [notebooklm-repo-artefacts](https://github.com/NetDevAutomate/notebooklm-repo-artefacts)*
<!-- ARTEFACTS:END -->

## License

MIT
