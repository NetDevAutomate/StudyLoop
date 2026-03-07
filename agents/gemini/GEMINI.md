# Socratic Study Mentor

An AuDHD-aware Socratic study toolkit for self-taught developers. Combines two CLI tools (`studyctl` and `agent-session-tools`) with AI mentor agents that teach through guided questioning rather than lectures.

## Project Structure

- `src/studyctl/` — Study pipeline management (sync, spaced repetition, progress tracking)
- `src/agent_session_tools/` — AI session export, search, and sync
- `agents/` — AI agent definitions for multiple platforms
- `agents/shared/` — Shared methodology docs (AuDHD framework, Socratic engine, network bridges)

## Key Commands

```bash
studyctl status              # Check sync state
studyctl review              # Spaced repetition due dates
studyctl struggles           # Recurring struggle topics
studyctl wins                # Learning wins (fight imposter syndrome)
studyctl progress CONCEPT    # Record progress
session-export               # Export AI sessions to SQLite
session-query search QUERY   # Search across sessions
```

## Study Mentor Agent

Use the `study-mentor` subagent for learning sessions. It provides:
- Socratic questioning (guides discovery, doesn't give answers)
- AuDHD cognitive support (executive function scaffolding, RSD management)
- Network → Data Engineering concept bridges
- Energy-adaptive sessions
- Spaced repetition integration

Start with: "I'd like to study [topic]" or "Quiz me on [concept]"
