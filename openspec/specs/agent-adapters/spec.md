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
instances via `build_custom_adapter()`. Custom adapters are merged after
built-ins, winning on name collision. The launch string is shell text:
each placeholder value and each `env` value is substituted
`shlex.quote`d, except a placeholder the template itself already wraps
in quotes (`"{persona}"`), which is substituted raw so it is not quoted
twice.

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

#### Scenario: Custom adapter entry fields
- **WHEN** an `agents.custom` entry is read from config
- **THEN** Each entry specifies `binary`,
  `strategy` (`"cli-flag"` or `"cwd-file"`), `launch` template (with
  `{binary}`, `{persona}`, `{session_dir}` placeholders), optional
  `resume` template, optional `env` vars, optional `teardown` shell
  command, and optional `mcp` config.

### Requirement: Agent detection respects STUDYLOOP_AGENT env var and configured priority order
`detect_agents()` in `registry.py` SHALL return agent names filtered
to those whose `binary` is resolvable via `shutil.which`. Priority
order: (1) if `STUDYLOOP_AGENT` env var is set and its binary is on
PATH, return only that agent; (2) otherwise walk `agents.priority`
from `AgentsConfig` (default: `harnesses.RELEASE_HARNESSES` in order —
kiro, codex, claude, pi, opencode, grok), then append any registry
entries not in the priority list.

#### Scenario: STUDYLOOP_AGENT=kiro with kiro-cli on PATH
- **WHEN** the env var is set to `"kiro"` and `shutil.which("kiro-cli")`
  succeeds
- **THEN** `detect_agents()` returns `["kiro"]` only — the env var
  acts as an exclusive override

#### Scenario: STUDYLOOP_AGENT set but binary missing
- **WHEN** the env var names an agent whose binary is not on PATH
- **THEN** `detect_agents()` returns an empty list rather than
  falling through to priority order (explicit intent honoured)

#### Scenario: get_default_agent returns the first detected agent
- **WHEN** `detect_agents()` has produced its ordered list
- **THEN** `get_default_agent()` returns the first element or `None`.

### Requirement: Persona injection uses one of two strategies depending on agent capability
Each adapter SHALL inject persona content via either `cli_flag_setup`
(secure temp file with mode 0600 for `--flag /path` agents) or a
CWD-file strategy (named file in the session directory). Codex
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

#### Scenario: Claude and the local-LLM adapters use cli_flag_setup
- **WHEN** the `claude`, `ollama` or `lmstudio` adapter sets up a persona
- **THEN** Claude and
  the local-LLM adapters (ollama, lmstudio) use `cli_flag_setup`.

### Requirement: Local-LLM adapters reuse Claude Code as the frontend with env-var tier-pinning
The `ollama` and `lmstudio` adapters (`ollama.py`, `lmstudio.py`)
SHALL use `cli_flag_setup` for persona injection and launch the
`claude` binary, but prefix the command with `ANTHROPIC_BASE_URL`,
`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, and four tier-pin env vars
(`*_SMALL_FAST_MODEL`, `*_DEFAULT_HAIKU_MODEL`, `*_DEFAULT_SONNET_MODEL`,
`*_DEFAULT_OPUS_MODEL`) — all set to the same model — via
`_local_llm_env_prefix()` in `_local_llm.py`.

#### Scenario: Ollama adapter launch with default config
- **WHEN** `ollama.ADAPTER.launch_cmd(path, resume=False)` is called
  with no custom config
- **THEN** the returned command string exports
  `ANTHROPIC_BASE_URL=http://localhost:4000` and all model tiers set
  to `qwen3-coder`, then invokes `claude --append-system-prompt-file`

#### Scenario: Local-LLM config and its defaults
- **WHEN** the `ollama` or `lmstudio` adapter resolves its base URL and model
- **THEN** Config (base URL, model)
  is read from `AgentsConfig.ollama` / `AgentsConfig.lmstudio` with
  defaults `http://localhost:4000` / `http://localhost:1234` and model
  `qwen3-coder`.

#### Scenario: Local-LLM detection uses the adapter's own binary
- **WHEN** `detect_agents()` probes the `ollama` and `lmstudio` adapters
- **THEN** Detection uses each adapter's own `binary` — `ollama`
  and `lms` respectively — not the `claude` binary they launch.

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
`agents/claude/socratic-mentor.md` → `~/.claude/agents/`). In-repo
targets use relative symlinks; home-dir targets use absolute. The
`--uninstall` flag removes only symlinks that point back to the source.
A shared `agents/shared` → `~/.agents/shared` link is always created.

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

#### Scenario: Platform detection before linking
- **WHEN** `install_agent_definitions()` decides which platforms to link
- **THEN** It detects
  available platforms via `detect_available_agent_tools()` (checks for
  `~/.kiro`, `~/.claude`, `~/.gemini` dirs or `shutil.which` for CLI
  tools).

#### Scenario: The CLI surface of studyloop install agents
- **WHEN** the installer is invoked from the command line
- **THEN** The CLI surface is `studyloop install agents`
  (`cli/_install.py`), accepting `--tool` (repeatable, constrained to
  `_AGENT_CHOICES` = `harnesses.RELEASE_HARNESSES`: kiro, codex, claude,
  pi, opencode, grok — the core tier is kiro, codex, claude and pi; opencode
  and grok are preview) and `--uninstall`.

### Requirement: Persona resolution by purpose
`studyloop.agent_launcher` SHALL expose one resolver,
`persona_mode_for(purpose: str) -> str`, mapping a session purpose to the
persona mode that serves it: `planning` → `plan-architect`, anything else →
`focus`. Every web start path (PTY and ACP alike) SHALL obtain its mode
through this resolver; no route SHALL name a persona mode as a literal
(`rg 'build_canonical_persona\("focus"' packages/studyloop/src/studyloop/web` → 0).

#### Scenario: Resolver maps the two purposes
- **WHEN** `persona_mode_for("planning")` and `persona_mode_for("focus")` are called
- **THEN** they return `plan-architect` and `focus` respectively

### Requirement: Persona resolution — the planning brief renders as its own section, never via previous_notes or topic
`build_canonical_persona(mode, topic, energy, *, previous_notes=None,
brief=None)` SHALL accept the planning brief through the `brief` keyword and
render it as its own `## Planning brief` section — introduced as data about
the learner, not instructions — placed with the other context sections ahead
of the persona body. The brief SHALL NOT be carried through `previous_notes`
(which renders `Resuming Previous Session`, the framing for a resumed study
session) and SHALL NOT be folded into `topic`.

#### Scenario: Brief renders as its own section
- **WHEN** `build_canonical_persona("plan-architect", "Study plan", 5, brief="- item")` is called
- **THEN** the result contains `## Planning brief`, contains `- item`, contains
  the plan-architect persona body, and does not contain `Resuming Previous Session`

### Requirement: Persona resolution — no brief, byte-identical output
With `brief=None` the output
SHALL be byte-identical to the pre-`brief` output, so no existing session's
`persona_hash` changes.

#### Scenario: No brief, no section
- **WHEN** `build_canonical_persona("focus", "Python", 5)` is called
- **THEN** the result contains no `## Planning brief` section and is
  byte-identical to the output before the `brief` keyword existed

### Requirement: Architect persona prefers the MCP plan tools
The canonical study-plan-architect persona (`agents/shared/personas/plan-architect.md`,
the body every harness projection carries verbatim after its own header) SHALL
carry one tooling section that introduces the plan tools over MCP **before** the
CLI fallback.

#### Scenario: Planning persona names the nine tools before the fallback
- **WHEN** `build_canonical_persona(persona_mode_for("planning"), "Study plan", 5, brief="- item")` is rendered
- **THEN** the result names all nine lifecycle tool names inside the MCP
  subsection, the MCP subsection precedes the `CLI fallback` subsection and
  closes before it, no `studyloop plan` recipe appears inside the MCP
  subsection, and the `CLI fallback` subsection names `studyloop plan
  interview`, `list`, `show`, `new`, `status`, `milestone`, `evaluate` and
  `record` and no `studyloop plan delete`

#### Scenario: Projections and manifest regenerate byte-identically
- **WHEN** `agents/claude/study-plan-architect.md`, `agents/opencode/study-plan-architect.md`
  and `agents/kiro/study-plan-architect/persona.md` are read
- **THEN** each body after its harness header equals the canonical persona
  byte-for-byte, and `agents/manifest.json` carries the generator's own hash
  for every architect projection it tracks

### Requirement: Architect persona — the MCP subsection names the nine lifecycle tools in order
The
MCP subsection SHALL name the nine plan lifecycle tools (the
plan-application-seam design, §4) — `list_study_plans`, `get_study_plan`, `get_planning_interview`,
`create_study_plan`, `update_study_plan`, `set_study_plan_status`,
`set_study_plan_milestone`, `evaluate_study_plan`, `delete_study_plan` — in
lifecycle order (discover → interview → create as `draft` → revise → activate →
tick → evaluate → delete).

#### Scenario: Every one of the nine tools is introduced inside the MCP subsection
- **WHEN** the planning persona is rendered and its MCP subsection is isolated
- **THEN** each of the nine lifecycle tool names appears as a backticked
  identifier inside that subsection, not only after the `CLI fallback`

### Requirement: Architect persona — the MCP subsection states the three seam guards
The MCP subsection SHALL state the three guards the plan
application layer enforces: activation only once `readiness` reports ready
(never creating as `active` to skip the gate), `evaluate_study_plan` with
`record=False` as a preview that writes nothing versus `record=True` to
persist a checkpoint, and `delete_study_plan` only with `confirmed=True` after
the learner has explicitly confirmed.

#### Scenario: The MCP subsection states the lifecycle guards
- **WHEN** the planning persona's MCP subsection is read
- **THEN** it mentions `readiness` and `active` for activation, `confirm`
  beside `delete_study_plan`, and `record=False` (or a preview) against
  `record=True`

### Requirement: Architect persona — the CLI fallback covers every step that has a command and names those it cannot
The CLI fallback subsection SHALL give
the `studyloop plan` command for every lifecycle step that has one
(`interview`, `list`, `show`, `new`, `status`, `milestone`, `evaluate`,
`record`) and SHALL say plainly which steps the CLI cannot perform (revising an
existing plan's fields; deletion) rather than inventing a command.

#### Scenario: The CLI fallback names every subcommand and no delete
- **WHEN** the planning persona's `CLI fallback` subsection is isolated
- **THEN** it names `studyloop plan interview`, `list`, `show`, `new`,
  `status`, `milestone`, `evaluate` and `record`, and the persona nowhere
  names `studyloop plan delete`

### Requirement: Architect persona — a missing tool routes to the CLI fallback, else the architect says so and stops
A tool
missing from the connected server's inventory SHALL route to that step's CLI
fallback where one exists; for the two steps with no CLI command (revising an
existing plan's fields, deletion) the persona SHALL have the architect say so
to the learner and stop, never improvise a shell edit of the document.

#### Scenario: Revise and Delete rows point at the MCP tool and say so, not at a Web UI door
- **WHEN** the `Revise` and `Delete` rows of the `CLI fallback` table are read
- **THEN** neither row points at the Web UI, `Revise` names `update_study_plan`,
  `Delete` names `delete_study_plan` with no Web UI control, and the MCP
  subsection tells the architect to say so to the learner

### Requirement: Architect persona — interview protocol and focus persona unchanged
The
interview protocol (one question per turn) SHALL be unchanged,
and the `focus` persona SHALL be byte-identical before and after this change.

#### Scenario: Focus persona untouched
- **WHEN** `build_canonical_persona("focus", "Python", 5)` is rendered with the
  three session paths fixed
- **THEN** its SHA-256 digest equals the digest recorded at `205819c7`

### Requirement: Harness-launched architects carry the plan tools
The `study-plan-architect` definitions for Kiro CLI (`agents/kiro/study-plan-architect.json`) and Claude
Code (`agents/claude/study-plan-architect.md`) SHALL attach the `studyloop` MCP server.

#### Scenario: Installed Kiro architect resolves its prompt and its servers
- **WHEN** `studyloop install agents --tool kiro` has run into a sandboxed home
- **THEN** `~/.kiro/agents/study-plan-architect.json` is a symlink whose `prompt` `file://` URI resolves to a
  file, whose `mcpServers` names `studyloop`, and whose stop hook is `session-export --kiro-only`

### Requirement: Harness architects — exactly the ten plan tools are allowed, in the harness's spelling
The `study-plan-architect` definitions SHALL allow exactly the
nine plan lifecycle tools named by `studyloop.mcp.inventory.PLAN_TOOL_NAMES` plus
`studyloop.mcp.inventory.LEARNING_RECORD_TOOL` — and no other tool of that server — in the spelling the
harness honours (owner decision D-A, 2026-09-16: no harness-launched architect falls back to the CLI with full
shell permissions; receipt `docs/architecture/plan-integration/receipts/kiro-agent-tools-probe-2026-09-16.md`).

#### Scenario: Kiro architect grants exactly the ten plan tools
- **WHEN** `agents/kiro/study-plan-architect.json` is parsed and its `@studyloop/...` grants collected
- **THEN** they equal `PLAN_TOOL_NAMES` plus `LEARNING_RECORD_TOOL` exactly, with no duplicates

#### Scenario: Claude architect grants exactly the ten plan tools
- **WHEN** the frontmatter of `agents/claude/study-plan-architect.md` is parsed and its `mcp__` entries collected
- **THEN** they equal `mcp__studyloop__<name>` for `PLAN_TOOL_NAMES` plus `LEARNING_RECORD_TOOL` exactly, with
  no wildcard or bare `mcp__studyloop` entry and no duplicates

### Requirement: Harness architects — Kiro: visibility and trust are two arrays
For Kiro, visibility and trust are two arrays: `tools` SHALL contain `@builtin`, `@studyloop` and
`@session-db`; `mcpServers` SHALL declare `studyloop` (`studyloop-mcp`) and `session-db` (`session-db-mcp`);
`allowedTools` SHALL carry `@studyloop/<name>` for exactly the ten and SHALL NOT carry a bare `@studyloop`
(which would trust every tool of the server) nor any `mcp_<server>_<tool>` entry (inert in an agent config).

#### Scenario: Kiro architect definition carries the server and exactly the plan tools
- **WHEN** `agents/kiro/study-plan-architect.json` is parsed
- **THEN** `mcpServers["studyloop"]["command"] == "studyloop-mcp"` and `mcpServers["session-db"]["command"]
  == "session-db-mcp"`, `tools` contains `@builtin`, `@studyloop` and `@session-db`, and the set of
  `allowedTools` entries starting with `@studyloop` equals `{f"@studyloop/{name}" for name in
  PLAN_TOOL_NAMES + (LEARNING_RECORD_TOOL,)}`, with no bare `@studyloop` and no entry starting with `mcp_`

#### Scenario: session-db is visible but not trusted
- **WHEN** the Kiro architect loads `shared/session-protocol.md` and reaches its session-start step
- **THEN** The `session-db` server is visible for the loaded `shared/session-protocol.md` session-start step and
  is not trusted: its tools prompt.

### Requirement: Harness architects — Claude Code: the frontmatter allow-list
For Claude Code, the frontmatter `tools:` allow-list SHALL carry
`mcp__studyloop__<name>` for exactly the ten and no other `mcp__` entry, alongside its built-in tools.

#### Scenario: Claude architect allow-list is exactly the plan tools
- **WHEN** the frontmatter of `agents/claude/study-plan-architect.md` is parsed
- **THEN** the `mcp__` entries of `tools:` equal `{f"mcp__studyloop__{name}" ...}` for exactly the ten names,
  and the body after the frontmatter is byte-identical to `agents/shared/personas/plan-architect.md`

### Requirement: Harness architects — the mentor uses the same spelling
`agents/kiro/study-mentor.json` SHALL use the same spelling: `@studyloop` in `tools` and every MCP grant in
`allowedTools` as `@<server>/<tool>`.

#### Scenario: Mentor grants use the spelling the CLI honours
- **WHEN** `agents/kiro/study-mentor.json` is parsed
- **THEN** `tools` contains `@studyloop`, no `allowedTools` entry starts with `mcp_`, and each MCP grant is
  `@<server>/<tool>` for a server declared in `mcpServers`

### Requirement: Harness architects — manifest hashes and byte-identical persona bodies
`agents/manifest.json` SHALL carry the generator's hash for each
edited definition, and the persona body of every architect projection SHALL remain byte-identical to the
canonical persona (the frontmatter and JSON header are the only edits). Learner confirmation before
`delete_study_plan` remains a persona rule: tool permission is not user authorisation.

#### Scenario: Manifest hashes regenerate for the architect projections
- **WHEN** the generator recomputes the hash of each architect projection it tracks
- **THEN** every recomputed hash equals the entry recorded in `agents/manifest.json`
