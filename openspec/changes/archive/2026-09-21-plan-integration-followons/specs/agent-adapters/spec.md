## ADDED Requirements

### Requirement: Harness-launched architects carry the plan tools
The `study-plan-architect` definitions for Kiro CLI (`agents/kiro/study-plan-architect.json`) and Claude
Code (`agents/claude/study-plan-architect.md`) SHALL attach the `studyloop` MCP server and allow exactly the
nine plan lifecycle tools named by `studyloop.mcp.inventory.PLAN_TOOL_NAMES` plus
`studyloop.mcp.inventory.LEARNING_RECORD_TOOL` — and no other tool of that server — in the spelling the
harness honours (owner decision D-A, 2026-09-16: no harness-launched architect falls back to the CLI with full
shell permissions; receipt `docs/architecture/plan-integration/receipts/kiro-agent-tools-probe-2026-09-16.md`).

For Kiro, visibility and trust are two arrays: `tools` SHALL contain `@builtin`, `@studyloop` and
`@session-db`; `mcpServers` SHALL declare `studyloop` (`studyloop-mcp`) and `session-db` (`session-db-mcp`);
`allowedTools` SHALL carry `@studyloop/<name>` for exactly the ten and SHALL NOT carry a bare `@studyloop`
(which would trust every tool of the server) nor any `mcp_<server>_<tool>` entry (inert in an agent config).
The `session-db` server is visible for the loaded `shared/session-protocol.md` session-start step and is not
trusted: its tools prompt. For Claude Code, the frontmatter `tools:` allow-list SHALL carry
`mcp__studyloop__<name>` for exactly the ten and no other `mcp__` entry, alongside its built-in tools.

`agents/kiro/study-mentor.json` SHALL use the same spelling: `@studyloop` in `tools` and every MCP grant in
`allowedTools` as `@<server>/<tool>`. `agents/manifest.json` SHALL carry the generator's hash for each
edited definition, and the persona body of every architect projection SHALL remain byte-identical to the
canonical persona (the frontmatter and JSON header are the only edits). Learner confirmation before
`delete_study_plan` remains a persona rule: tool permission is not user authorisation.

#### Scenario: Kiro architect definition carries the server and exactly the plan tools
- **WHEN** `agents/kiro/study-plan-architect.json` is parsed
- **THEN** `mcpServers["studyloop"]["command"] == "studyloop-mcp"` and `mcpServers["session-db"]["command"]
  == "session-db-mcp"`, `tools` contains `@builtin`, `@studyloop` and `@session-db`, and the set of
  `allowedTools` entries starting with `@studyloop` equals `{f"@studyloop/{name}" for name in
  PLAN_TOOL_NAMES + (LEARNING_RECORD_TOOL,)}`, with no bare `@studyloop` and no entry starting with `mcp_`

#### Scenario: Claude architect allow-list is exactly the plan tools
- **WHEN** the frontmatter of `agents/claude/study-plan-architect.md` is parsed
- **THEN** the `mcp__` entries of `tools:` equal `{f"mcp__studyloop__{name}" ...}` for exactly the ten names,
  and the body after the frontmatter is byte-identical to `agents/shared/personas/plan-architect.md`

#### Scenario: Installed Kiro architect resolves its prompt and its servers
- **WHEN** `studyloop install agents --tool kiro` has run into a sandboxed home
- **THEN** `~/.kiro/agents/study-plan-architect.json` is a symlink whose `prompt` `file://` URI resolves to a
  file, whose `mcpServers` names `studyloop`, and whose stop hook is `session-export --kiro-only`

#### Scenario: Mentor grants use the spelling the CLI honours
- **WHEN** `agents/kiro/study-mentor.json` is parsed
- **THEN** `tools` contains `@studyloop`, no `allowedTools` entry starts with `mcp_`, and each MCP grant is
  `@<server>/<tool>` for a server declared in `mcpServers`
