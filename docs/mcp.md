# MCP servers

StudyLoop installs two local stdio MCP servers:

| Registration name | Command | Purpose |
| --- | --- | --- |
| `session-db` | `session-db-mcp` | Session/context search, provenance and review tools |
| `studyloop` | `studyloop-mcp` | Study planning, review, progress and learner-state tools |

Run `studyloop install agents` to register both servers for Claude Code,
Kiro and Codex. The installer merges only these owned entries into
`~/.claude.json`, `~/.kiro/settings/mcp.json` and `~/.codex/config.toml`;
unrelated entries remain in place. Repeating the command is byte-idempotent.
`studyloop doctor --category agents` reports each harness's registration
state without changing configuration.
