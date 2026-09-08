# MCP servers

StudyLoop installs two local stdio MCP servers:

| Registration name | Command | Purpose |
| --- | --- | --- |
| `session-db` | `session-db-mcp` | Session/context search, concept recall, provenance and review tools |
| `studyloop` | `studyloop-mcp` | Study planning, review, progress and learner-state tools |

Run `studyloop install agents` to register both servers for Claude Code,
Kiro and Codex. The installer merges only these owned entries into
`~/.claude.json`, `~/.kiro/settings/mcp.json` and `~/.codex/config.toml`;
unrelated entries remain in place. Repeating the command is byte-idempotent.
`studyloop doctor --category agents` reports each harness's registration
state without changing configuration.

## `memory_recall`

`memory_recall(question, k=5, project=null)` performs concept-first lexical
recall. `question` must be non-empty and at most 4,000 characters; `k` is a
strict integer from 1 through 50. The result shape is frozen by
[`recall-contract.json`](data/recall-contract.json).

The shared query planner lowercases and tokenizes the question, drops pinned
stop words and tokens shorter than three characters, quotes every remaining
term for FTS5, and tries implicit AND first. OR runs only when AND has not
filled the requested result count; its unseen results are appended after AND
results. The existing `session_search` tool uses this same planner while
retaining its row fields, filters, SQL ranking and 300-character previews.

Recall returns:

1. Scope-authorized, non-retired concepts ordered by FTS rank and full concept
   id, including their explicit bound or legacy-unbound provenance.
2. Scope-visible raw sessions ordered deterministically, excluding sessions
   already represented by returned concepts.
3. The exact query plan and whether OR contributed a result.

The tool reuses B3's authorization seam, so work/personal/unclassified scope,
tombstones and retired concepts behave exactly as concept projection does. It
does not import semantic search, read embedding tables or consult ontology
tables. Missing scope returns the shared B1 `scope_unconfigured` MCP error.

## Determinism evidence

B4 compares public `memory_recall` ordered concept/session ids with released
SessionWeaver v0.2.0 (`fe15996c`) for all 25 frozen questions. Both sides are
prepared from clones of one read-only SQLite Online Backup and use
`memory.default_scope: unclassified`; separate clones are required because the
released library owns schema v47 while StudyLoop B3 owns v49. Aggregate-only
evidence is retained in
[`b4-recall-live-evidence.json`](data/b4-recall-live-evidence.json).
