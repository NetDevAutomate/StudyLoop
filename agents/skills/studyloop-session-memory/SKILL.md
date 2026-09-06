---
name: studyloop-session-memory
description: Use when starting or ending a coding-agent session, or when prior StudyLoop decisions, struggles, context, or session history may be relevant.
---

# StudyLoop Session Memory

## Contract

At session start, query the shared StudyLoop session database for this project.
At session end, export the current harness transcript. Native hooks are the
safety net; do not skip the explicit export when the workflow calls for it.

## Query

Prefer the `session_search` MCP tool when it is connected:

- Query with the current project path plus the user's topic.
- Retrieve details with `session_context` rather than loading whole sessions.
- Mention only findings that affect the current task.

If the MCP tool is unavailable, use the installed CLI:

```bash
session-query search "<topic or error>" --project "$PWD"
```

Run `session-query --help` for filters and output modes. A missing MCP server is
not a reason to skip retrieval; the CLI is the deterministic fallback.

Project filters narrow retrieval; they are not enforced work/personal permissions.
Use only a database the current agent is permitted to read. Identify relevant
session IDs and distinguish what earlier messages reported from what was actually
validated. Surface conflicting advice and missing validation rather than treating
recency or repetition as proof. This release does not provide automatic decision
arbitration or source-bound validation of an answer.

## Export

Use the flag matching the current harness:

| Harness | Command |
|---|---|
| Kiro CLI | `session-export --kiro-only` |
| Codex | `session-export --codex-only` |
| Claude Code | `session-export --claude-only` |
| OpenCode | `session-export --opencode-only` |
| pi | `session-export --pi-only` |

The installer also registers a native session-end hook for each supported
mentor harness. Hooks must fail open (`|| true` or equivalent), never trap the
user inside the harness. Report an observed export error; doctor checks wiring
but does not establish success of the latest export. Verify a recent session
through query when capture is uncertain.

Grok's local transcripts can be imported with `session-export --grok-only`.
Grok is not an installed mentor/hook integration in this release.

## Repair and sharing limits

Use `session-repair` to inspect an existing database before proposing an explicit
`--apply` repair with backup. Do not use this schema-30 candidate on a database
upgraded by the separate context-memory research branch.

`session-sync all` transfers through the existing trusted-database transport.
Each destination must be permitted to receive the entire selected database.
Do not promise propagated forgetting: original transcripts, peers, backups and
exported notes can retain data or restore a locally deleted conversation.

## Common mistakes

- Calling `session_search` without checking whether the MCP tool exists, then
  silently skipping history when it does not. Use `session-query` fallback.
- Searching every past session instead of scoping by project and topic.
- Treating a prompt reminder as an automatic hook. Doctor checks both the skill
  and the native hook separately.
- Assuming desktop apps share CLI stores/configuration. Desktop support is
  evidence-gated and reported separately by doctor.
