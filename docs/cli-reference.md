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
studyctl state push|pull|status|init     # Cross-machine state sync
studyctl schedule install|remove|list    # Manage scheduled jobs
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
session-maint vacuum|reindex|schema      # Database maintenance
tutor-checkpoint code --skill SKILL      # Record study progress
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
uv pip install agent-session-tools[tui]       # TUI interface
```
