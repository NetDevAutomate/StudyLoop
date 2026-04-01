# CLI Reference

## studyctl

Study pipeline management — content, review, sessions, and tracking.

```bash
# Study sessions (tmux + AI agent + Textual sidebar)
studyctl study "topic" --energy 7        # Full tmux environment in one command
studyctl study "topic" --mode co-study   # Co-study mode (user drives)
studyctl study --resume                  # Reattach to existing session
studyctl study --end                     # End session cleanly
studyctl study "topic" --web             # Also start web dashboard
studyctl park QUESTION [-t TOPIC]        # Park tangential topic

# Low-level session commands (used internally by study)
studyctl session start -t TOPIC -e 7    # Start session (DB + IPC files)
studyctl session status                  # Timer, topics, parking lot
studyctl session end [-n NOTES]          # End session, show summary

# Content pipeline
studyctl content split SOURCE            # Split PDF by chapters
studyctl content process SOURCE          # Split + upload to NotebookLM
studyctl content autopilot               # Generate next pending episode
studyctl content from-obsidian DIR       # Markdown → PDF → NotebookLM
studyctl content status                  # Show content pipeline status
studyctl content syllabus                # Manage syllabus workflow

# Sync & topics
studyctl sync [TOPIC] --all --dry-run    # Sync notes to NotebookLM
studyctl status [TOPIC]                  # Show sync status
studyctl topics                          # List configured topics
studyctl audio TOPIC                     # Generate NotebookLM audio overview
studyctl dedup [TOPIC] --all --dry-run   # Remove duplicate notebook sources

# Review
studyctl review                          # Check spaced repetition due dates
studyctl struggles --days 30             # Find recurring struggle topics

# Configuration & health
studyctl setup                           # Interactive setup wizard
studyctl config init                     # Interactive config (3 questions)
studyctl config show                     # Display current configuration
studyctl doctor                          # Full health check
studyctl update                          # Check for available updates
studyctl upgrade                         # Apply all available updates

# Web
studyctl web [--port PORT] [--host HOST] # Launch study web app (PWA)
```

### Study Sessions

The primary entry point is `studyctl study`, which creates a complete tmux-based study environment:

```bash
studyctl study "Python Decorators" --energy 7          # Socratic mentor session
studyctl study "Spark Internals" --mode co-study       # User-driven co-study
studyctl study "topic" --timer pomodoro                # Override default timer
studyctl study "topic" --agent claude --web            # Explicit agent + web dashboard
studyctl study --resume                                # Resume conversation (-r)
studyctl study --end                                   # End session cleanly
studyctl park "How does asyncio compare?"              # Park mid-session
```

**What `studyctl study` creates:**
- tmux session with agent pane (left) + Textual sidebar (right)
- AI agent launched with mode-specific persona (clean pane, no visible command)
- Persistent session directory at `~/.config/studyctl/sessions/{name}/` — preserves AI conversation history (`.claude/`, `.kiro/`, etc.)
- Sidebar shows timer, activity feed, counters (keyboard: `p` pause, `r` reset, `Q` end session)
- IPC files for dashboard viewports
- Optional web dashboard at `/session` via `--web`

**Session lifecycle:**
- **Start:** `studyctl study "topic"` — creates tmux session, agent, sidebar
- **Exit:** quit Claude normally (`/exit`, Ctrl+C) — auto-cleans up tmux, IPC files, switches back to previous session. Session directory preserved.
- **Resume:** `studyctl study --resume` — if tmux alive, reattaches. If ended, rebuilds tmux and passes `-r` to the agent to continue the conversation from history.
- **End explicitly:** `studyctl study --end` or sidebar `Q` — same cleanup as quitting Claude

**Modes:**

| Mode | Flag | Timer default | Agent role |
|------|------|---------------|------------|
| Study | (default) | Elapsed | Socratic mentor drives |
| Co-study | `--mode co-study` | Pomodoro | User drives, agent available |

**Low-level session commands** (used internally by `studyctl study`):

```bash
studyctl session start -t "Decorators" -e 7    # Start session record
studyctl session status                         # Show current state
studyctl session end -n "Got through closures"  # End with notes
```

### Health & Updates

```bash
studyctl doctor                          # Full health check (Rich table)
studyctl doctor --json                   # JSON output (for AI agents and CI)
studyctl doctor --quiet                  # One-line summary
studyctl doctor --category core          # Check specific category only
studyctl update --json                   # Machine-readable update info
studyctl upgrade --dry-run               # Preview what would change
studyctl upgrade --component packages    # Upgrade only packages
studyctl upgrade --component database    # Run DB migrations only
studyctl upgrade --component agents      # Update agent definitions only
```

**Exit codes for `studyctl doctor`:**

| Code | Meaning |
|------|---------|
| `0` | All checks pass — installation is healthy |
| `1` | Warnings or failures that can be fixed — run `studyctl upgrade` |
| `2` | Core failure — a fundamental component is broken (e.g. wrong Python version) |

**Check categories:** `core` (Python, packages, config), `database` (review DB, sessions DB), `config` (Obsidian vault, review dirs, pandoc), `deps` (optional packages), `agents` (AI tool definitions), `updates` (PyPI versions).

### Spaced Repetition Intervals

Review schedule: **1 → 3 → 7 → 14 → 30 days**

`studyctl review` shows what's due based on when you last recorded progress.

### Web PWA

`studyctl web` launches a progressive web app for flashcard and quiz review. LAN accessible by default.

```bash
studyctl web                    # Serve on 0.0.0.0:8567
studyctl web --port 9000        # Custom port
studyctl web --host localhost   # Local only
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

**Voice:** Uses Web Speech API (browser built-in). Two modes:
- **Read once** — speaker icon on card or `T` key
- **Auto-voice** — header toggle or `V` key (reads everything automatically)

---

## agent-session-tools

AI session export, search, and cross-machine sync.

```bash
session-export [--source SOURCE]         # Export AI sessions to SQLite
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
| `kiro` | Kiro CLI |
| `gemini` | Gemini CLI |
| `aider` | Aider |
| `opencode` | OpenCode |
| `litellm` | LiteLLM |
| `repoprompt` | RepoPrompt |

### Optional Extras

```bash
uv pip install agent-session-tools[semantic]  # Vector embeddings search
uv pip install agent-session-tools[tokens]    # Token counting
```
