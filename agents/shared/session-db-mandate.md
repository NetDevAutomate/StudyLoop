## Session Memory (session-db)

At the **start** of each session, follow the `studyloop-session-memory` skill.
Prefer the `session_search` MCP tool with the current project path; if that MCP
tool is unavailable, run the installed `session-query` CLI instead. Briefly
mention only findings relevant to the user's current request.

## Session Export (end of session)

The session database is StudyLoop's core knowledge base and the single source
of truth for what the user is learning and struggling with. It is shared across
machines and powers cross-harness search.

At the **end** of every session — when the user wraps up, says goodbye, or the
work is clearly done — persist this conversation and any struggle signals to the
database by running:

```
session-export --SESSION_EXPORT_FLAG
```

Also explicitly record anything the user struggled with this session so it
surfaces for spaced repetition. If `session-export` is unavailable, note the
failure but do not block the session close.

<!-- studyloop:session-export-mandate -->
