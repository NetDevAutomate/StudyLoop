# CLI Reference

## studyloop

Study pipeline management — content, review, sessions, and tracking.

```bash
# Study sessions (tmux + AI agent + Textual sidebar)
studyloop study "topic" --energy 7        # Full tmux environment in one command
studyloop study "topic" --mode co-study   # Co-study mode (user drives)
studyloop study --resume                  # Reattach to existing session
studyloop study --end                     # End session cleanly
studyloop study "topic" --web             # Also start web dashboard
studyloop park QUESTION [-t TOPIC]        # Park tangential topic

# Low-level session commands (used internally by study)
studyloop session start -t TOPIC -e 7    # Start session (DB + IPC files)
studyloop session status                  # Timer, topics, parking lot
studyloop session end [-n NOTES]          # End session, show summary
studyloop session effectiveness           # Persona effectiveness metrics

# Content pipeline
studyloop content split SOURCE            # Split PDF by chapters
studyloop content generate-cards DIR --course COURSE # Local quiz/flashcard JSON
studyloop content discover                # Preview configured study sources
studyloop content ingest --dry-run        # Plan source ingest
studyloop content import-review DIR --course COURSE  # Import existing JSON artefacts
studyloop content process SOURCE          # Legacy optional NotebookLM upload path
studyloop content from-obsidian DIR       # Legacy optional NotebookLM path

# Sync & topics
studyloop sync [TOPIC] --all --dry-run    # Legacy optional notebook sync
studyloop status [TOPIC]                  # Show sync status
studyloop topics                          # List configured topics
studyloop audio TOPIC                     # Legacy optional audio overview
studyloop dedup [TOPIC] --all --dry-run   # Remove duplicate notebook sources

# Review
studyloop review                          # Check spaced repetition due dates
studyloop progress                        # Summarize local course progress
studyloop progress --course python        # Summarize one course
studyloop progress --json                 # Machine-readable progress summary
studyloop progress CONCEPT -t TOPIC -c confident # Record concept confidence
studyloop struggles --days 30             # Find recurring struggle topics

# Configuration & health
studyloop setup                           # Interactive setup wizard
studyloop install tools                   # Install global CLI entrypoints from repo
studyloop install agents                  # Install agent definitions for detected tools
studyloop config init                     # Interactive config (3 questions)
studyloop config show                     # Display current configuration
studyloop doctor                          # Full health check
studyloop update                          # Check for available updates
studyloop upgrade                         # Apply all available updates

# Backup & restore
studyloop backup [--tag NAME]             # Snapshot DB + config to backups/
studyloop restore                         # List available backups
studyloop restore BACKUP --confirm        # Restore from backup (safety backup first)

# Web
studyloop web [--port PORT] [--lan] [--password SECRET] # Launch study web app (PWA)
```

### Study Sessions

The primary entry point is `studyloop study`, which creates a complete tmux-based study environment:

```bash
studyloop study "Python Decorators" --energy 7          # Socratic mentor session
studyloop study "Spark Internals" --mode co-study       # User-driven co-study
studyloop study "topic" --timer pomodoro                # Override default timer
studyloop study "topic" --agent claude --web            # Explicit agent + web dashboard
studyloop study "topic" --agent codex                  # Explicit Codex CLI session
studyloop study "topic" --lan                           # Bind to 0.0.0.0, password-protected (implies --web)
studyloop study "topic" --lan --password SECRET         # Explicit password for LAN auth
studyloop study "topic" --agent ollama                  # Local LLM via Ollama + LiteLLM
studyloop study "topic" --agent lmstudio                # Local LLM via LM Studio
studyloop study --resume                                # Resume conversation (-r)
studyloop study --end                                   # End session cleanly
studyloop park "How does asyncio compare?"              # Park mid-session
```

Run `studyloop study` without a topic to open the textual picker for body double, topic directory, course vendor, or course.

**What `studyloop study` creates:**
- tmux session with agent pane (left) + Textual sidebar (right)
- AI agent launched with mode-specific persona (clean pane, no visible command)
- Persistent session directory at `~/.config/studyloop/sessions/{name}/` — preserves AI conversation history (`.claude/`, `.kiro/`, etc.)
- Sidebar shows timer, activity feed, counters (keyboard: `p` pause, `r` reset, `Q` end session)
- IPC files for dashboard viewports
- Optional web dashboard at `/session` via `--web`
- `--web` auto-opens a browser to the dashboard on startup
- `--lan` binds the web server and ttyd to `0.0.0.0` with HTTP Basic Auth, prints dashboard URL and password (implies `--web`). Password is auto-generated if not set via `--password` or `lan_password` in config
- `--password SECRET` sets the LAN authentication password (used with `--lan`)

**Session lifecycle:**
- **Start:** `studyloop study "topic"` — creates tmux session, agent, sidebar
- **Exit:** quit Claude normally (`/exit`, Ctrl+C) — auto-cleans up tmux, IPC files, switches back to previous session. Session directory preserved.
- **Resume:** `studyloop study --resume` — if tmux alive, reattaches. If ended, rebuilds tmux and passes `-r` to the agent to continue the conversation from history.
- **End explicitly:** `studyloop study --end` or sidebar `Q` — same cleanup as quitting Claude

**Modes:**

| Mode | Flag | Timer default | Agent role |
|------|------|---------------|------------|
| Study | (default) | Elapsed | Socratic mentor drives |
| Co-study | `--mode co-study` | Pomodoro | User drives, agent available |

**Low-level session commands** (used internally by `studyloop study`):

```bash
studyloop session start -t "Decorators" -e 7    # Start session record
studyloop session status                         # Show current state
studyloop session end -n "Got through closures"  # End with notes
studyloop session effectiveness                  # Win rate per persona version
studyloop session effectiveness -p abc123...     # Filter by persona hash
```

### Health & Updates

```bash
studyloop doctor                          # Full health check (Rich table)
studyloop doctor --json                   # JSON output (for AI agents and CI)
studyloop doctor --quiet                  # One-line summary
studyloop doctor --category core          # Check specific category only
studyloop doctor --fix                    # Apply safe automatic fixes
studyloop update --json                   # Machine-readable update info
studyloop upgrade --dry-run               # Preview what would change
studyloop upgrade --component packages    # Upgrade only packages
studyloop upgrade --component database    # Run DB migrations only
studyloop upgrade --component agents      # Update agent definitions only
```

**Exit codes for `studyloop doctor`:**

| Code | Meaning |
|------|---------|
| `0` | All checks pass — installation is healthy |
| `1` | Warnings or failures that can be fixed — run `studyloop doctor --fix` |
| `2` | Core failure — a fundamental component is broken (e.g. wrong Python version) |

**Check categories:** `core` (Python, packages, config), `database` (review DB, sessions DB), `config` (Obsidian vault, review dirs, pandoc), `deps` (optional packages), `agents` (AI tool definitions), `updates` (PyPI versions).

### Spaced Repetition Intervals

Review schedule: **1 → 3 → 7 → 14 → 30 days**

`studyloop review` shows what's due based on when you last recorded progress.

### Progress

`studyloop progress` has two modes:

- With no concept argument, it summarizes local course progress from `content.base_path` and the review database.
- With a concept argument, it records confidence for a study concept.

```bash
studyloop progress                                  # Course summary table
studyloop progress --course python                  # One course only
studyloop progress --json                           # JSON for scripts/agents
studyloop progress "list comprehensions" \
  --topic python \
  --confidence confident                           # Record concept confidence
```

The summary includes local source count, unique review cards, due cards, mastered cards, review sessions, and review accuracy. Course filtering uses the course slug, such as `python` or `data-engineering`.

### Web PWA

`studyloop web` launches a progressive web app for flashcard and quiz review. By default it binds to `127.0.0.1`; use `--lan` to expose it on your network with HTTP Basic Auth.

```bash
studyloop web                    # Serve on 127.0.0.1:8567
studyloop web --port 9000        # Custom port
studyloop web --lan              # Bind to 0.0.0.0 with auth
studyloop web --lan --password SECRET
```

| Key | Action | When |
|-----|--------|------|
| `Space`/`Enter` | Flip card | Flashcard, before reveal |
| `Y` | I knew it | Flashcard, after reveal |
| `N` | Didn't know | Flashcard, after reveal |
| `A`-`D` | Select quiz option | Quiz mode |
| `S` | Skip card | During review |
| `T` | Read aloud (once) | During review |
| `V` | Toggle auto-voice | During review |
| `R` | Retry wrong answers | After session |
| `Esc` | Back to home | Anywhere |

**Features:** Source/chapter filter, card count limiter (10/20/50/100/All), due cards badge, session history, 90-day study heatmap, Pomodoro timer (25min/5min), OpenDyslexic font toggle, dark/light theme, PWA installable.

**Live session dashboard** (`/session`): Real-time SSE activity feed, energy-adaptive timer, topic counters, and a **terminal panel** — an embedded ttyd iframe showing the tmux session live via same-origin proxy (`/terminal/`). The panel is draggable (stacked or side-by-side), has a layout toggle and panel-swap buttons, and can be popped out to a separate window (pop-out auto-closes when returning inline). ttyd is optional (`brew install ttyd`) but required for the terminal panel.

**Voice:** Uses Web Speech API (browser built-in). Two modes:
- **Read once** — speaker icon on card or `T` key
- **Auto-voice** — header toggle or `V` key (reads everything automatically)

**Web + terminal config** (`~/.config/studyloop/config.yaml`):

```yaml
web_port: 8567       # web dashboard port (default 8567)
ttyd_port: 7681      # ttyd web terminal port (default 7681)
browser: ""          # auto-open browser: chrome, safari, firefox, brave, or empty for system default
lan_password: ""     # persistent password for --lan mode (auto-generated if empty)
```

**Agent priority config** (`~/.config/studyloop/config.yaml`):

```yaml
agents:
  priority: [codex, claude, gemini, opencode, kiro, ollama, lmstudio]
```

---

## agent-session-tools

AI session export, search, and cross-machine sync.

```bash
session-export [--sources SOURCE ...]    # Export AI sessions to SQLite
session-query search QUERY               # Full-text search across sessions
session-query list --since 7d            # List recent sessions
session-query show SESSION_ID            # Show session details
session-query context SESSION_ID         # Generate context for resuming
session-query stats                      # Database statistics
session-sync push|pull|sync REMOTE       # Sync database across machines
session-maint vacuum|reindex|schema|archive  # Database maintenance
study-speak "text" [-v VOICE] [-s SPEED] # Speak text aloud using TTS
```

### Supported Sources

| Source | Tool |
|--------|------|
| `claude` | Claude Code |
| `codex` | OpenAI Codex CLI |
| `kiro` | Kiro CLI |
| `gemini` | Gemini CLI |
| `aider` | Aider |
| `opencode` | OpenCode |
| `litellm` | LiteLLM |
| `repoprompt` | RepoPrompt |
| `pi` | pi coding agent (`@earendil-works/pi-coding-agent`) |
| `omp` | oh-my-pi (`@oh-my-pi/pi-coding-agent`) |

### Install & Export Examples

```bash
studyloop install tools
studyloop install agents
studyloop install agents --tool codex
studyloop install agents --tool claude --tool gemini
studyloop install agents --tool pi
studyloop install agents --tool omp

session-export
session-export --sources claude codex
session-export --sources gemini opencode
session-export --sources pi omp
session-export --claude-only
session-export --gemini-only
session-export --pi-only
session-export --omp-only
session-export --full
```

### Optional Extras

```bash
uv pip install agent-session-tools[semantic]  # Vector embeddings search
uv pip install agent-session-tools[tokens]    # Token counting
```
