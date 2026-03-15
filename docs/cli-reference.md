# CLI Reference

## studyctl

Study pipeline management — sync notes, spaced repetition, progress tracking.

```bash
studyctl sync [TOPIC] --all --dry-run   # Sync notes to NotebookLM
studyctl status [TOPIC]                  # Show sync status
studyctl review                          # Check spaced repetition due dates
studyctl struggles --days 30             # Find recurring struggle topics
studyctl wins --days 30                  # Show your learning wins
studyctl progress CONCEPT -t TOPIC -c LEVEL  # Record progress on a concept
studyctl schedule-blocks --start 14:00   # Generate .ics calendar study blocks
studyctl topics                          # List configured topics
studyctl audio TOPIC                     # Generate NotebookLM audio overview
studyctl dedup [TOPIC] --all --dry-run   # Remove duplicate notebook sources
studyctl resume                          # Where you left off (auto-context)
studyctl streaks                         # Study streak and consistency stats
studyctl progress-map                    # Visual map of all tracked concepts
studyctl state push|pull|status|init     # Cross-machine state sync
studyctl schedule install|remove|list|add|delete  # Manage scheduled jobs
studyctl config init                     # Interactive setup wizard
studyctl config show                     # Display current configuration
studyctl docs serve [--port PORT]        # Serve docs site locally
studyctl docs open                       # Build and open docs in browser
studyctl docs list                       # List available doc pages
studyctl tui                             # Launch interactive TUI dashboard
studyctl docs read PAGE                  # Read a page aloud via study-speak
```

### Confidence Levels

Used with `studyctl progress`:

| Level | Meaning |
|-------|---------|
| `struggling` | Can't solve without heavy guidance |
| `learning` | Getting it with some scaffolding |
| `confident` | Can apply independently |
| `mastered` | Can teach it to others |

### Spaced Repetition Intervals

Review schedule: **1 → 3 → 7 → 14 → 30 days**

`studyctl review` shows what's due based on when you last recorded progress.

### TUI Dashboard

`studyctl tui` launches an interactive terminal dashboard. Requires `uv pip install studyctl[tui]`.

| Key | Action | When |
|-----|--------|------|
| `d` | Dashboard tab | Always |
| `r` | Review tab | Always |
| `c` | Concepts tab | Always |
| `s` | Sessions tab | Always |
| `f` | Start flashcard session | Always |
| `z` | Start quiz session | Always |
| `space` | Flip card / submit answer | During review |
| `y` | Mark correct | After flip |
| `n` | Mark incorrect | After flip |
| `s` | Skip card | During review |
| `h` | Show hint | Quiz mode |
| `r` | Retry wrong answers | After session, if wrong answers exist |
| `v` | Toggle voice output | Always |
| `q` | Quit | Always |

**Course picker:** When multiple directories are configured in `review.directories`, a modal picker appears on session start. Single directory launches directly.

**Retry mode:** After a session, press `r` to drill only the cards you got wrong. SM-2 scheduling is not updated during retry — the original incorrect answer already penalised the card.

---

## agent-session-tools

AI session export, search, and management.

```bash
session-export [--source SOURCE]         # Export AI sessions to SQLite
session-query search QUERY               # Full-text search across sessions
session-query list --since 7d            # List recent sessions
session-query show SESSION_ID            # Show session details
session-query context SESSION_ID         # Generate context for resuming
session-query stats                      # Database statistics
session-sync push|pull REMOTE            # Sync database across machines
session-maint vacuum|reindex|schema|archive  # Database maintenance
tutor-checkpoint code --skill SKILL      # Record study progress
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
| `bedrock` | Bedrock Proxy |
| `repoprompt` | RepoPrompt |

### Optional Extras

```bash
uv pip install agent-session-tools[semantic]  # Vector embeddings search
uv pip install agent-session-tools[tokens]    # Token counting
uv pip install studyctl[tui]                   # TUI interface
```
