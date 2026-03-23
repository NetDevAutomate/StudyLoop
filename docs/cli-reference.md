# CLI Reference

## studyctl

Study pipeline management — content, review, and session tracking.

```bash
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
