# agent-session-tools

AI session export, search, and sync tools — supports Claude Code, Codex CLI, Grok CLI, Kiro CLI, Gemini CLI, Aider, OpenCode, LiteLLM, RepoPrompt, pi, and oh-my-pi (omp).

Part of [StudyLoop](https://github.com/Hookey-Street-Software/StudyLoop).

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

## Obsidian Vault Export

`session-export` can mirror each session into an Obsidian vault as structured
Markdown, in addition to the SQLite export:

```bash
session-export --obsidian                      # sessions touched this run
session-export --obsidian --obsidian-backfill  # all history (idempotent)
session-export --obsidian --obsidian-dry-run   # preview, write nothing
session-export --obsidian --obsidian-vault ~/Obsidian/Personal
```

Notes are written to `<vault>/AgentMemory/` with Dataview-ready frontmatter
(`type: agent-memory`), `[[wikilink]]` backlinks to matching vault topic notes, and
per-project MOC index notes under `<vault>/AgentMemory/MOC/`. A content hash in each
note's frontmatter makes re-exports idempotent (unchanged sessions are skipped).

Configure defaults via the `obsidian:` section in `~/.config/studyloop/config.yaml`
(`export_enabled`, `vault_path`, `memory_dir`, `moc_dir`, `backlinks`, `granularity`).
See the [setup guide](../../docs/setup-guide.md#obsidian-session-memory-export).

See the [system overview docs](../../docs/system-overview.md) for diagrams and detailed reference.
