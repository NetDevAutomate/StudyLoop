# Harnesses and Agents

<!-- facts: F2 F4 F5 F16 -->

StudyLoop runs a study session inside one of six coding harnesses: 4 core + 2 preview, named in
`packages/studyloop/src/studyloop/harnesses.py`. To change how a harness is launched, edit its
adapter under `packages/studyloop/src/studyloop/adapters/`; to change what the mentor says, edit
the prompts under `agents/`; then run the parity tests below, which fail when any of the six drifts.

## The six harnesses and their tiers

Every user-facing surface imports the tiers from `harnesses.py`; nothing discovers harnesses from
the filesystem. The tiers are core (Kiro CLI, Codex, Claude Code, pi) and
preview (OpenCode, Grok Build). The two preview harnesses ship in the release set but stay preview
until their own live receipts are green. Changing a tier is one edit to `CORE_HARNESSES` /
`PREVIEW_HARNESSES`, and `packages/studyloop/tests/test_docs_harness_tier_contract.py` then fails
every document that still states the old split, including this one.

## What an adapter is

An adapter is a frozen `AgentAdapter` dataclass (`adapters/_protocol.py`) exported as a
module-level `ADAPTER` from `adapters/<harness>.py`. It has four parts:

1. `name` and `binary` -- the harness id and the executable to look for.
2. `setup(canonical_content, session_dir)` -- writes the persona in the shape that harness reads
   (a steering file, an `AGENTS.md`, a settings entry) and returns its path.
3. `launch_cmd(persona_path, resume)` -- the shell command that starts or resumes the harness.
4. Optional `teardown` and `mcp_setup` -- cleanup of global state and the per-session MCP config.

`adapters/registry.py` builds the registry from `RELEASE_HARNESSES` only, so an adapter module for
a name outside the six is never loaded, however well formed.

## What an agent definition is

The persona a live session receives is rendered from `agents/shared/personas/<mode>.md` by
`agent_launcher.build_canonical_persona()`; each adapter's `setup()` then writes it in its own
format. Separately, five of the six harnesses have an installed mentor definition under
`agents/<harness>/` -- `agents/kiro/study-mentor/persona.md`, `agents/claude/socratic-mentor.md`,
`agents/codex/AGENTS.md`, `agents/opencode/study-mentor.md`, `agents/pi/AGENTS.md`. Grok Build
reads the Codex file: `adapters/grok.py` projects `agents/codex/AGENTS.md`, and
`test_adapter_parity.py::test_grok_projects_the_codex_definition` fails the moment a directory
named `agents/grok` appears. Do not create one; change Codex's definition instead.

`agents/shared/` holds the protocols every definition links to. The one that is pinned is
`agents/shared/recording-protocol.md`: every mentor definition and both live personas must name its
four recording writers -- `record_teachback`, `log_struggle`, `log_topic` and
`record_plan_learning` -- and no harness may grant them a pre-approval.

## Change a prompt safely

1. Edit the shared protocol or persona under `agents/shared/` first; edit a per-harness file only
   for that harness's syntax (frontmatter, tool lists, permission blocks).
2. Keep the four writer names and the `recording-protocol.md` reference in every file you touch.
3. Run the parity guard. It checks the six at every layer (contract, doctor, installers, exporters,
   definitions, live personas) and that no permission block grew:

```bash
uv run --group dev pytest packages/studyloop/tests/test_adapter_parity.py -q
```

4. If you changed a tier or a sentence about tiers, run the docs pin too:

```bash
uv run --group dev pytest packages/studyloop/tests/test_docs_harness_tier_contract.py -q
```

5. Try the persona in a real session of that harness before opening the pull request, and say
   which harness you tried under question 3 of the [pull request](contributor-pull-requests.md).

## Change an adapter safely

1. Keep `name` equal to the key in `harnesses.py` and `binary` equal to the installed executable.
2. Keep trust or permission writes (Claude's `~/.claude/settings.json`, Grok's
   `trusted_folders.toml`) inside `setup()`, scoped to the session directory and its parent, and
   touch nothing else in the learner's home -- `adapters/grok.py` documents the pattern.
3. Extend the adapter's test in `packages/studyloop/tests/test_adapter_builtins.py`, then run the
   parity guard above. Both suites are default-tier: no harness binary is needed.

## Why additions are declined

A seventh harness is not a pull request; it is an issue first, and drive-by additions are declined
(`docs/contributing.md`, *Making changes*). The six-adapter set is an owner ruling pinned by
`test_adapter_parity.py::test_release_contract_is_exactly_the_six`, because every layer -- the
tier contract, the doctor table, the installer links, the exporter registry, the export CLI's
source choices -- must agree, and a harness added in one place silently breaks the others. A
proposal must define all seven of:

1. the persona mechanism (how the harness receives instructions);
2. the launch and resume commands;
3. the session store (where transcripts land);
4. the exporter that reads that store into session memory;
5. the health check `studyloop doctor` can run;
6. the failure behaviour when the binary is missing or the session dies;
7. a live acceptance path a maintainer can run.

Open the issue with those seven answered; the proposal then follows the OpenSpec route in
[Conventions](contributor-conventions.md).
