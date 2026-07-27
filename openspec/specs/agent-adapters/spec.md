## Purpose

Provide a uniform protocol for spawning any AI coding agent with a
StudyLoop persona, discovering which agents are installed, and
installing platform-specific agent definitions from the source checkout.
The adapter layer decouples session management from agent-specific
persona injection, launch commands, and MCP wiring. Scope boundary:
ACP/PTY transport internals (session-transports), persona content
(socratic-methodology), and session export are specified elsewhere.

## Requirements

### Requirement: Every adapter satisfies a six-member runtime-checkable protocol
The system SHALL enforce a contract via the `@runtime_checkable`
`AdapterProtocol` in `adapters/_protocol.py` requiring two attributes
(`name: str`, `binary: str`) and four methods
(`setup(canonical_content, session_dir) -> Path`,
`launch_cmd(persona_path, resume) -> str`, `teardown(session_dir)`,
`mcp_setup(session_dir)`). The frozen dataclass `AgentAdapter`
implements this with callables; `teardown` and `mcp_setup` are
optional (default `None`).

#### Scenario: Custom class checked against the protocol
- **WHEN** code performs `isinstance(obj, AdapterProtocol)`
- **THEN** the check succeeds for any object exposing the six
  required attributes/methods, without requiring inheritance

### Requirement: The registry auto-discovers built-in adapters from sibling modules
`registry._discover_builtins()` SHALL scan all non-underscore-prefixed
modules in `studyloop.adapters` via `pkgutil.iter_modules`, import each,
and collect any module-level `ADAPTER` attribute that is an
`AgentAdapter` instance. Modules that set `ADAPTER = None` are silently
skipped (opt-out, not a warning). The module-level cache (`_registry`)
is built on first access and cleared by `reset_registry()` for test
isolation.

#### Scenario: Normal startup with Claude and Gemini installed
- **WHEN** `get_all_adapters()` is called for the first time
- **THEN** it returns a dict keyed by adapter name (e.g. `"claude"`,
  `"gemini"`) containing `AgentAdapter` instances loaded from
  `claude.py`, `gemini.py`, etc.

#### Scenario: Adapter module raises on import
- **WHEN** a sibling module throws during import (e.g. missing
  optional dependency)
- **THEN** the registry logs a warning and continues — other
  adapters are still available

### Requirement: Custom adapters from config override built-in adapters of the same name
`_custom.load_custom_adapters()` SHALL read the `agents.custom` dict
from `settings.py` (`AgentsConfig.custom`) and build `AgentAdapter`
instances via `build_custom_adapter()`. Each entry specifies `binary`,
`strategy` (`"cli-flag"` or `"cwd-file"`), `launch` template (with
`{binary}`, `{persona}`, `{session_dir}` placeholders), optional
`resume` template, optional `env` vars, optional `teardown` shell
command, and optional `mcp` config. Custom adapters are merged after
built-ins, winning on name collision.

#### Scenario: User defines a custom "aider" adapter in config.yaml
- **WHEN** `agents.custom.aider` is configured with
  `strategy: cli-flag` and `launch: "{binary} --read {persona}"`
- **THEN** `get_adapter("aider")` returns a functional adapter that
  writes persona to a secure temp file and produces the templated
  launch command

#### Scenario: Custom adapter overrides a built-in
- **WHEN** `agents.custom.claude` is defined in config
- **THEN** `get_adapter("claude")` returns the custom-built adapter,
  not the built-in `claude.py` adapter

### Requirement: Agent detection respects STUDYLOOP_AGENT env var and configured priority order
`detect_agents()` in `registry.py` SHALL return agent names filtered
to those whose `binary` is resolvable via `shutil.which`. Priority
order: (1) if `STUDYLOOP_AGENT` env var is set and its binary is on
PATH, return only that agent; (2) otherwise walk `agents.priority`
from `AgentsConfig` (default: claude, kiro, gemini, opencode, codex,
grok, ollama, lmstudio), then append any registry entries not in the
priority list. `get_default_agent()` returns the first element or
`None`.

#### Scenario: STUDYLOOP_AGENT=kiro with kiro-cli on PATH
- **WHEN** the env var is set to `"kiro"` and `shutil.which("kiro-cli")`
  succeeds
- **THEN** `detect_agents()` returns `["kiro"]` only — the env var
  acts as an exclusive override

#### Scenario: STUDYLOOP_AGENT set but binary missing
- **WHEN** the env var names an agent whose binary is not on PATH
- **THEN** `detect_agents()` returns an empty list rather than
  falling through to priority order (explicit intent honoured)

### Requirement: Persona injection uses one of two strategies depending on agent capability
Each adapter SHALL inject persona content via either `cli_flag_setup`
(secure temp file with mode 0600 for `--flag /path` agents) or a
CWD-file strategy (named file in the session directory). Claude and
the local-LLM adapters (ollama, lmstudio) use `cli_flag_setup`. Codex
and Grok write `AGENTS.md`; Gemini writes `GEMINI.md`; OpenCode
writes `.opencode/agents/study-mentor.md` with YAML frontmatter;
Kiro writes a temp persona file and atomically updates
`~/.kiro/agents/study-mentor.json` to reference it via `file://` URI,
with crash-recovery backup/restore.

#### Scenario: Claude adapter setup
- **WHEN** `claude.ADAPTER.setup(content, session_dir)` is called
- **THEN** it writes `content` to a temp file with mode 0600 and
  returns the temp path; `launch_cmd` emits
  `claude --append-system-prompt-file <path>`

#### Scenario: Kiro adapter crash recovery
- **WHEN** a Kiro session's teardown never ran (crash) and the next
  session's `_kiro_setup` is called
- **THEN** the stale `.studyloop-backup` file is detected, the
  original agent JSON is restored before proceeding, and setup
  continues normally

### Requirement: Local-LLM adapters reuse Claude Code as the frontend with env-var tier-pinning
The `ollama` and `lmstudio` adapters (`ollama.py`, `lmstudio.py`)
SHALL use `cli_flag_setup` for persona injection and launch the
`claude` binary, but prefix the command with `ANTHROPIC_BASE_URL`,
`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, and four tier-pin env vars
(`*_SMALL_FAST_MODEL`, `*_DEFAULT_HAIKU_MODEL`, `*_DEFAULT_SONNET_MODEL`,
`*_DEFAULT_OPUS_MODEL`) — all set to the same model — via
`_local_llm_env_prefix()` in `_local_llm.py`. Config (base URL, model)
is read from `AgentsConfig.ollama` / `AgentsConfig.lmstudio` with
defaults `http://localhost:4000` / `http://localhost:1234` and model
`qwen3-coder`. Detection uses each adapter's own `binary` — `ollama`
and `lms` respectively — not the `claude` binary they launch.

#### Scenario: Ollama adapter launch with default config
- **WHEN** `ollama.ADAPTER.launch_cmd(path, resume=False)` is called
  with no custom config
- **THEN** the returned command string exports
  `ANTHROPIC_BASE_URL=http://localhost:4000` and all model tiers set
  to `qwen3-coder`, then invokes `claude --append-system-prompt-file`

### Requirement: The fake adapter is gated behind STUDYLOOP_TEST_AGENT and opts out of production registries
`fake.py` SHALL set `ADAPTER = AgentAdapter(...)` only when
`os.environ.get("STUDYLOOP_TEST_AGENT") == "1"`; otherwise `ADAPTER =
None`. The registry treats `None` as an intentional opt-out (debug log,
no warning). The fake adapter's binary is `studyloop-fake-agent` (a
console script defined elsewhere), uses `cli_flag_setup`, and produces
a launch command that passes the persona path as argv[1].

#### Scenario: Normal user session without the env var
- **WHEN** `STUDYLOOP_TEST_AGENT` is unset or not `"1"`
- **THEN** the `"fake"` agent does not appear in `get_all_adapters()`
  or `detect_agents()` output

#### Scenario: E2E test with STUDYLOOP_TEST_AGENT=1
- **WHEN** the env var is set to `"1"` before registry build
- **THEN** `get_adapter("fake")` returns a usable adapter and the
  e2e journey can exercise the full spawn→PTY→WebSocket path
  without a vendor CLI

### Requirement: MCP config is written for agents that declare mcp_setup
Adapters that define `mcp_setup` SHALL invoke
`write_mcp_config(session_dir, fmt=...)` from `_strategies.py` to
write agent-appropriate MCP server configuration. The `"generic"`
format writes `.mcp.json` (Claude Code schema); `"gemini"` writes
`.gemini/settings.json`; `"opencode"` writes
`.opencode/opencode.json` with `"type": "local"` and `"command"` as a
flat list. The MCP command resolves to `studyloop-mcp` if on PATH, else
falls back to `uv run --project <packages/studyloop> studyloop-mcp`.

#### Scenario: Gemini session setup
- **WHEN** a Gemini session is started and `mcp_setup` is invoked
- **THEN** `.gemini/settings.json` is created in the session directory
  containing a `studyloop-mcp` server entry

### Requirement: `studyloop install agents` symlinks platform-specific definitions from the source checkout
`install_agent_definitions()` in `installers.py` SHALL create symlinks
from the `agents/` tree in the repo root to each platform's expected
location (e.g. `agents/kiro/study-mentor.json` → `~/.kiro/agents/`,
`agents/claude/socratic-mentor.md` → `~/.claude/agents/`). It detects
available platforms via `detect_available_agent_tools()` (checks for
`~/.kiro`, `~/.claude`, `~/.gemini` dirs or `shutil.which` for CLI
tools). In-repo targets use relative symlinks; home-dir targets use
absolute. The `--uninstall` flag removes only symlinks that point back
to the source. A shared `agents/shared` → `~/.agents/shared` link is
always created. The CLI surface is `studyloop install agents`
(`cli/_install.py`), accepting `--tool` (repeatable, constrained to
`_AGENT_CHOICES`: kiro, claude, gemini, opencode, codex, grok, amp,
pi, omp) and `--uninstall`.

#### Scenario: Fresh install on a machine with Claude and Kiro
- **WHEN** `studyloop install agents` runs with `~/.kiro` and
  `~/.claude` directories present
- **THEN** symlinks are created for both platforms' agent definitions
  plus the shared link, and Claude-specific extras (statusline script,
  settings.json bootstrap) are applied

#### Scenario: Uninstall only removes StudyLoop-owned symlinks
- **WHEN** `studyloop install agents --uninstall` runs
- **THEN** only symlinks whose targets resolve to the repo's
  `agents/` tree are removed; user-owned files at the same paths
  are left untouched
