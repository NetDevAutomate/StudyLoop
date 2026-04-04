# agent-session-tools

AI session export, search, and sync tools — supports Claude Code, Kiro CLI, Gemini CLI, Aider, OpenCode, LiteLLM, and RepoPrompt.

Part of [socratic-study-mentor](https://github.com/NetDevAutomate/Socratic-Study-Mentor).

## Install

```bash
uv tool install ./packages/agent-session-tools
```

## CLI Tools

| Command | Description |
|---------|-------------|
| `session-export` | Export AI coding sessions to SQLite |
| `session-query` | Search and browse session history |
| `session-maint` | Database maintenance and optimization |
| `session-sync` | Sync sessions across machines |
| `session-db-mcp` | MCP server — exposes session DB to AI tools |
| `tutor-checkpoint` | Save/restore tutoring session state |
| `study-speak` | Text-to-speech for study content |

## MCP Server (session-db-mcp)

Exposes the session database as 7 MCP tools via stdio transport. Any MCP-compatible AI tool can search, browse, and retrieve context from past sessions.

```json
{
  "mcpServers": {
    "session-db": {
      "command": "session-db-mcp"
    }
  }
}
```

**Tools:** `session_search`, `session_list`, `session_show`, `session_context`, `session_stats`, `session_clean`, `session_hotspots`

See the [system overview docs](../../docs/system-overview.md) for diagrams and detailed reference.
