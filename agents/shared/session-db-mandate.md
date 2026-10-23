## Session Memory (session-db)

At the **start** of each session, follow the `studyloop-session-memory` skill.
Prefer the `session_search` MCP tool with the current project path; if that MCP
tool is unavailable, run the installed `session-query` CLI instead. Then call
`memory_search` for prior decisions and disputes about the topic, and
`get_concept_context` for its prerequisite edges, before choosing what to teach
first. This file is shared across harnesses: in Claude Code, Kiro CLI, Codex,
OpenCode and Grok Build the session-db MCP server is registered; in other
harnesses use `session-query` instead. Briefly mention only findings relevant
to the user's current request.

## Session Export (end of session)

The session database is StudyLoop's core knowledge base and the single source
of truth for what the user is learning and struggling with. It is shared across
machines and powers cross-harness search.

Export is the harness's job: its StudyLoop hook runs `session-export` for this
harness at session end. Run it yourself only if the learner asks or the hook is
reported missing — the manual command for this harness is:

```
session-export --SESSION_EXPORT_FLAG
```

Also explicitly record anything the user struggled with this session so it
surfaces for spaced repetition. If `session-export` is unavailable, note the
failure but do not block the session close.

<!-- studyloop:session-export-mandate -->
