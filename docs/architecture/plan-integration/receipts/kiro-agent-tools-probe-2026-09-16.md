# Kiro agent-config probe — how `tools` / `allowedTools` govern MCP tools · 2026-09-16

**Why this exists.** Item 1 of the follow-on programme (owner decision D-A) grants the harness-launched
`study-plan-architect` the `studyloop` MCP server "mirroring `agents/kiro/study-mentor.json`". Before pinning
that shape in a test, the coordinator checked what the installed Kiro CLI actually honours, because the
mentor file spells its grants `mcp_<server>_<tool>` and never lists `@studyloop` in `tools`. The result
changes item 1's spelling (not its intent) and exposes a latent defect in the mentor definition.

- Host: macOS, `kiro-cli 2.21.4` / `kiro-cli-chat 2.21.4` (`~/.local/bin`).
- Method: two throw-away local agents under a temp cwd's `.kiro/agents/`, each run once with
  `kiro-cli chat --agent <name> --no-interactive "/tools"` (a local slash command; no model call). The
  `studyloop` server is the installed `studyloop-mcp` console script. Temp dir removed afterwards.
- Documentation read alongside (kiro.dev, fetched 2026-09-16 via the `introspect` agent):
  `custom-agents/configuration-reference` ("The `tools` field lists all tools that the agent can potentially
  use … `@builtin` — All built-in tools … `@server_name` … `@server_name/tool_name`"; `allowedTools`:
  "Specific MCP tools: `@server_name/tool_name`"), `custom-agents/troubleshooting` ("Ensure tools are listed
  in both `tools` and `allowedTools` arrays"), `mcp/usage` (the `mcp_<server>_<tool>` form belongs to
  `mcp.json`'s `autoApprove`, a different file).

## Probe A — `tools: ["@builtin"]`, server declared, `mcp_…` allow entry

```json
{"name":"probe-a","description":"probe","prompt":"You are a probe.",
 "tools":["@builtin"],
 "mcpServers":{"studyloop":{"command":"studyloop-mcp","args":[]}},
 "allowedTools":["fs_read","mcp_studyloop_list_study_plans"]}
```

`/tools` output: the **Built-in** section only (code, shell, read, write, glob, grep, introspect, report,
session, aws, subagent, web_fetch, web_search — 13 tools, 7.3k tokens). **No `studyloop (MCP)` section.**
The server was declared and started, but none of its tools was visible to the agent.

## Probe B — `tools: ["@builtin","@studyloop"]`, both allow spellings side by side

```json
{"name":"probe-b","description":"probe","prompt":"You are a probe.",
 "tools":["@builtin","@studyloop"],
 "mcpServers":{"studyloop":{"command":"studyloop-mcp","args":[]}},
 "allowedTools":["fs_read","@studyloop/list_study_plans","mcp_studyloop_get_study_plan"]}
```

`/tools` output: the Built-in section **plus** `studyloop (MCP)` listing all **32** registered tools
(6.9k tokens). Permission column: `list_study_plans … trusted`; **`get_study_plan … not trusted`**; every
other studyloop tool `not trusted`.

## Reading

1. **Visibility is the `tools` array.** `@builtin` alone hides every MCP tool even when the server is in
   `mcpServers`. An agent needs `@<server>` (all of a server), `@<server>/<tool>` (one tool) or `*`.
2. **Trust is the `allowedTools` array, in the `@<server>/<tool>` spelling.** The `mcp_<server>_<tool>`
   spelling is **inert** in an agent config on this version (probe B: `get_study_plan` stayed `not trusted`).
3. **Consequence for `agents/kiro/study-mentor.json` today:** its `tools` is `["@builtin","@study-speak",
   "@session-db"]` — no `@studyloop` — so its six `mcp_studyloop_*` grants describe tools the mentor cannot
   see, and all twelve `mcp_<server>_<tool>` entries (study-speak, session-db, studyloop) are in the inert
   spelling. The mentor's session-db and study-speak tools are *visible* (their `@server` tags are present)
   but prompt for approval on every call. This is a pre-existing defect the follow-on inherited, not a
   regression of the plan-integration branch; item 1 corrects it in its own commit and pins the working
   spelling.
4. **Consequence for item 1 (D-A):** the architect's grant is written as `tools: ["@builtin","@studyloop",
   "@session-db"]` and `allowedTools` carrying exactly `@studyloop/<the nine>` + `@studyloop/record_plan_learning`
   (the session-db server is visible for the loaded `shared/session-protocol.md`'s session-start step and
   prompts, which is the least-privilege reading of "grant what is needed"). The handover's RED test name
   `test_kiro_architect_carries_the_studyloop_server_and_exactly_the_plan_tools` is kept; its assertions use
   the spelling the CLI honours, derived from `studyloop.mcp.inventory.PLAN_TOOL_NAMES` + `LEARNING_RECORD_TOOL`
   rather than a third hand copy.
5. **Not established here:** whether a future Kiro v3 (`includeMcpJson`, `permissions.rules`) changes either
   rule — the installed CLI is 2.x and the docs quoted are consistent with what it did. Re-run the two probes
   after any Kiro upgrade before trusting this receipt.
