# agent-session-tools

Export, search and sync local coding conversations from Claude Code, Codex,
Grok CLI, Kiro CLI, OpenCode, pi and supported oh-my-pi archives. Grok is an
import source, not a StudyLoop mentor or automatically installed hook.

Part of [StudyLoop](https://github.com/NetDevAutomate/StudyLoop).

This checkout contains the session-memory reliability candidate, awaiting release
acceptance. SQLite remains the source of conversation history. Enforced
work/personal boundaries, propagated forgetting and validated decision arbitration
are not included. See the [conversation memory guide](../../docs/session-memory.md).

## Install

```bash
uv tool install ./packages/agent-session-tools
```

## CLI Tools

| Command | Description |
|---------|-------------|
| `session-export` | Export AI coding sessions to SQLite |
| `session-repair` | Inspect and repair imports, with explicit apply and backup |
| `session-query` | Search and browse session history |
| `session-context` | Scoped source retrieval, exact citations, proposed relationships and recorded-check assessment |
| `session-maint` | Database maintenance and optimization |
| `session-sync` | Sync sessions across machines |
| `session-db-mcp` | MCP server — exposes session DB to AI tools |
| `tutor-checkpoint` | Save/restore tutoring session state |
| `study-speak` | Text-to-speech for study content |

## Recover and share history

Run `session-repair` to inspect an existing database, review the report, then use
`session-repair --apply` to back up and apply recovered conversation rows. Run it
locally on each machine before syncing. See [repair instructions](docs/session-repair.md).

`session-sync all` pushes to every configured peer before pulling from every peer.
Only use it where every destination is permitted to receive the entire selected
database; search project filters are not transfer permissions. Sync does not
propagate forgetting or guarantee convergence after conflicting edits.
See [configuration and reconciliation](docs/sync-after-repair.md).

Do not use this schema-30 candidate against a database upgraded by the context
research branch. It is not a downgrade tool.

## MCP Server (session-db-mcp)

Exposes session history and source-grounded context through stdio. Any compatible
MCP client can use the same configured scope policy as the CLI.

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

**Rich context tools:** `memory_search`, `memory_source`, `memory_propose`,
`memory_relate`, `memory_review`, `memory_reviews`, `memory_assess`, `memory_decide`.
Prefer these for exact source citations, provenance, attributed review history,
proposed relationships and explicit execution requirements. A recorded
check is not an approval to ship. See the [context interface guide](../../docs/context-memory.md)
for scope configuration, examples and limits.

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
