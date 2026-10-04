# An MCP Tool

<!-- facts: F7 F8 F11 -->

An MCP tool is a plain function inside `register_tools()` in
`packages/studyloop/src/studyloop/mcp/tools.py`, decorated with the module's `@tool()` wrapper and
served over stdio by `packages/studyloop/src/studyloop/mcp/server.py`. It must call the same
service the matching CLI command and web route call — parity is the rule, and a test pins it — and
its test reaches it through the FastMCP registry, never through a subprocess.

1. Add the function inside `register_tools()` with typed parameters and an `Args:` docstring.
2. Call the existing service; raise `ToolError` for a refusal, with the allowed values named.
3. Write `packages/studyloop/tests/test_mcp_<name>.py` that fetches the tool from the registry.
4. If the tool mirrors a CLI command or route, assert the same keys or the same engine output.
5. Run the MCP test files; they are part of the default suite (F7).

## 1. Where it lives

- `packages/studyloop/src/studyloop/mcp/tools.py` — every tool, in one `register_tools(mcp, *,
  include_exercises=False)` function. The local `tool()` decorator wraps each function in
  `_guard_scope`, which turns an unconfigured-scope error into a structured `ToolError` payload,
  then hands it to `mcp.tool()`. Developer-preview tools (the exercise pipeline) register only
  when `include_exercises=True`; they are absent from discovery, not registered-and-refusing.
- `packages/studyloop/src/studyloop/mcp/server.py` — `build_mcp(dev=...)`, the `lifespan` that
  opens the database and settings once, the import-time `mcp` instance tests use, and `main()`
  behind the `studyloop-mcp` console script (`--dev` adds the preview tools).
- `packages/studyloop/src/studyloop/mcp/inventory.py` — the plan-tool names as a tuple importable
  without the SDK; `packages/studyloop/tests/test_docs_plan_integration_contract.py` grounds it in
  the real registry and in `docs/agent-install.md`, so a renamed tool fails a test rather than
  leaving a stale sentence.
- The SDK is the optional `mcp` extra (`mcp[cli]>=1.0.0,<2` in
  `packages/studyloop/pyproject.toml`); tests `importorskip("mcp")`, so check it is installed
  before trusting a green run.

## 2. The smallest complete example

Read `get_next_action` in `packages/studyloop/src/studyloop/mcp/tools.py` (about fifty lines).
It is the parity example: `studyloop now`, `GET /api/now` in
`packages/studyloop/src/studyloop/web/routes/now.py` and this tool all call
`build_now_plan()` from `packages/studyloop/src/studyloop/learning/decision.py`. MCP clients send
strings, so the tool validates each argument against the engine's `Literal` types and raises
`ToolError` naming the allowed set before anything is scored. The smallest *write* tool is
`record_study_progress`, earlier in the same file: sixteen lines, three typed parameters, one
service call, one status dict.

## 3. Its test

Read `packages/studyloop/tests/test_mcp_next_action.py` (133 lines). The pattern, which every
`test_mcp_*.py` file shares, is:

1. `from studyloop.mcp.server import mcp`, then `mcp._tool_manager._tools[name]` — `.fn` is the
   callable, `.parameters` is the JSON schema clients see.
2. Isolate the world first: `tmp_path` HOME and config via a fixture, as the cookbook's
   [unit template](contributor-testing.md#unit-and-cli-template-refusal-means-nothing-executed)
   does for the CLI; patch the service where the tool looks it up.
3. Assert the schema (parameter names and defaults), the refusal (`pytest.raises(ToolError)`
   with the message naming the allowed values) and the result — compared with the same engine
   output the CLI and web tests pin.

```bash
uv run --group dev pytest packages/studyloop/tests/test_mcp_next_action.py -q
```

The parity file is `packages/studyloop/tests/test_mcp_session_parity.py`: it locks
`list_session_options` and `end_session` to the shapes the web picker and end-session button use,
so an agent driving StudyLoop over MCP has exactly the power the browser has.

```bash
uv run --group dev pytest packages/studyloop/tests/test_mcp_session_parity.py -q
```

## 4. The gate that proves it

```bash
uv run --group dev pytest packages/studyloop/tests/test_mcp_*.py -q
```

All of these run in the default selection, so `just test` and `just preflight` include them (F7).
The one exception is `packages/studyloop/tests/test_mcp_stdio_smoke.py`: it spawns the real
server and drives it with the SDK client over stdio, so it is marked `integration`, deselected by
default and run nightly in CI (F8). Run it yourself with `-m integration` only against a throwaway
HOME — its lifespan opens the configured database.

## 5. What reviewers look for

- The tool calls a service in `packages/studyloop/src/studyloop/services/` or
  `packages/studyloop/src/studyloop/learning/`, not the database or the filesystem directly, and
  anything derived from a tool argument goes through `_safe_course_dir` or an equivalent check.
- Every parameter is typed with a default where the CLI has one; the docstring's `Args:` block is
  what the agent reads as the tool description, so it names the accepted values.
- Refusals are `ToolError` with the allowed set in the message, never a bare exception or a
  silently coerced value.
- Parity is asserted, not described: the test compares keys or output with the CLI or route test
  for the same engine.
- A new learner-facing tool is named in `docs/agent-install.md`; a preview tool is behind
  `include_exercises`, not behind an environment variable.
