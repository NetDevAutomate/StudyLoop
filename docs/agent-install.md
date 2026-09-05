# Connect your AI coding tool

StudyLoop turns a supported coding assistant into an AuDHD-aware Socratic mentor. You keep using the tool you already know; StudyLoop supplies the study behaviour, session context, and progress export.

## Supported in the initial pre-release

The core release harnesses are:

- **Kiro CLI** — the reference experience used in StudyLoop demos
- **Codex**
- **Claude Code**

StudyLoop also includes complete integrations for **OpenCode** and **pi**. They are shown as preview harnesses until their live release checks pass on the target environment.

Gemini CLI, Antigravity, and Grok are not part of this pre-release. Their presence on your computer will not make StudyLoop advertise or select them.

## Install automatically

From a StudyLoop source checkout, install every supported harness detected on your computer:

```bash
studyloop install agents
```

Or install one explicitly:

```bash
studyloop install agents --tool kiro
studyloop install agents --tool codex
studyloop install agents --tool claude
studyloop install agents --tool opencode
studyloop install agents --tool pi
```

Then check the result:

```bash
studyloop doctor --category agents
```

The installer links StudyLoop-managed definitions while preserving an existing file as a `.bak` backup when necessary. Use `studyloop install agents --uninstall` to remove links created by StudyLoop.

## Start a study session

The easiest route is the Web UI: open **Study Session**, choose an available harness, and start. From the command line:

```bash
studyloop study "Python generators" --agent kiro
```

Replace `kiro` with `codex`, `claude`, `opencode`, or `pi`.

## What each integration installs

### Kiro CLI

Kiro receives the `study-mentor` agent, its focused skills, and the voice helper. Start it directly with:

```bash
kiro-cli chat --agent study-mentor
```

Kiro is the demo harness because it makes the named mentor and session flow visible without requiring users to understand prompt files.

Kiro also receives the opt-in `studyloop-xtiles-wind-down` skill at `~/.kiro/skills/`, as a symlink to the shared copy described below. It stays silent unless your second-brain provider is `xtiles` and an `xtiles` MCP server is connected.

### Codex

Codex reads the StudyLoop `AGENTS.md` from the project. Launching through `studyloop study` creates the session context and starts Codex in that directory.

That `AGENTS.md` carries one self-gated line about xTiles at wind-down, inert unless your provider is `xtiles` and an `xtiles` MCP server is connected. Codex needs no skill link of its own: it reads `~/.agents/skills/` natively, which is where the shared copy lives.

### Claude Code

Claude Code receives the `socratic-mentor` agent and a session-export hook. The installer merges the hook into existing settings and does not replace unrelated hooks.

Configure Claude Code's model provider before starting a StudyLoop session. If
you use AWS Bedrock, Claude Code needs Bedrock enabled and valid AWS credentials
in its own settings or launch environment. A credit error from the direct
Anthropic service is a reason to check which provider Claude Code is using;
it does not establish that your Bedrock access is unavailable. StudyLoop's
mentor installation does not configure or switch your model provider.

It also receives the opt-in `studyloop-xtiles-wind-down` skill at `~/.claude/skills/`, as a symlink to the shared copy described below. It does nothing at all unless your provider is `xtiles` and an `xtiles` MCP server is connected.

### OpenCode

Two separate mechanisms write two separate sets of files, at two different times:

- **`studyloop install agents --tool opencode`** (the install command above) writes a **global** `study-mentor` agent definition to `~/.config/opencode/agents/study-mentor.md`, available to any OpenCode session on the machine.
- **`studyloop study --agent opencode`** (starting a session) separately writes a **project-local** `.opencode/agents/study-mentor.md` and `.opencode/opencode.json` (StudyLoop's MCP server, in OpenCode's own config schema) into that session's working directory. This happens at session start, not at install time — if you only ran the install command and are looking for these project-local files, that's why they aren't there yet.

Either path gets you the same mentor behaviour. StudyLoop does not choose or hard-code an OpenCode model; your working OpenCode provider and model remain authoritative.

Both copies of the mentor definition carry the same self-gated xTiles line as
Codex's. OpenCode reads the shared `~/.agents/skills/` hub directly, so the
installer does not create a redundant `~/.config/opencode/skills/` link.

### pi

pi reads the project `AGENTS.md` and resumes through its native `--continue` option. Its session-export mandate writes real pi sessions to StudyLoop’s session database; it does not generate fixture or placeholder progress.

Its `AGENTS.md` carries the same self-gated xTiles line. pi discovers the
shared `~/.agents/skills/` hub natively, so both the xTiles wind-down skill and
the session-memory skill are available without a duplicate link.

## Session memory and automatic export

`studyloop install agents` installs one canonical
`studyloop-session-memory` skill into `~/.agents/skills/`. Codex, OpenCode and
pi discover that hub directly; Kiro and Claude receive links from their native
skill directories. The skill prefers the `session_search` MCP tool and falls
back to the installed `session-query` CLI, so a missing MCP registration never
silently disables retrieval.

The installer also installs a real lifecycle hook for every release harness:

| Harness | Automatic export hook | Query path |
|---|---|---|
| Kiro CLI | `stop` hook in the global `study-mentor` agent | bundled `session-db-mcp`, plus skill fallback |
| Codex | global `~/.codex/hooks.json` `SessionEnd` hook | shared skill + `session-query` |
| Claude Code | global `~/.claude/settings.json` `Stop` hook | native skill link + `session-query` |
| OpenCode | global plugin, `session.idle` event | shared skill + `session-query` |
| pi | global extension, `session_shutdown` event | shared skill + `session-query` |

All hooks run `session-export --<harness>-only` best-effort and never block
session close. Codex reviews and trusts a newly installed command-hook hash on
first use; StudyLoop does not bypass that security prompt.

Check both layers (skill/query and hook/export), or repair them, with:

```bash
studyloop doctor --category harness
studyloop doctor --category harness --fix
```

### Desktop applications

Codex's official hook configuration is global (`~/.codex/hooks.json`) and is
used by Codex sessions that load that config, including the Codex app. Claude
Code's hook is installed into Claude Code's own `~/.claude/settings.json`.
The consumer **Claude Desktop** application is a different product: this repo
has no evidence that it supports Claude Code hooks or writes Claude Code's
session store, so StudyLoop does not claim or fake support for it. Doctor
reports only evidence-backed coding-harness integrations.

## Data integrity

Agent installation never seeds study progress. Session export records genuine harness sessions, and struggle extraction requires an explicitly configured live model. If the live extractor cannot authenticate or returns invalid data, it fails without writing partial progress.

## Troubleshooting

Run:

```bash
studyloop doctor --category agents --json
```

The human-readable output gives repair guidance; JSON is useful when another agent is helping with setup. If a harness appears unavailable, first confirm its binary responds to `--version`, then rerun the installer for that harness.

For a clean removal:

```bash
studyloop install agents --uninstall
```

## Shared skill hub

StudyLoop installs canonical skills once under `~/.agents/skills/`:

```text
~/.agents/skills/
├── studyloop-session-memory/
│   └── SKILL.md
└── studyloop-xtiles-wind-down/
    ├── SKILL.md
    └── references/harnesses.md
```

Codex, OpenCode and pi discover this directory directly. Kiro and Claude use
symlinks from `~/.kiro/skills/` and `~/.claude/skills/`. One body per skill
means an update reaches every supported harness without copy drift.

The xTiles skill remains self-gating: it is silent unless the configured
second-brain provider is xTiles and an xTiles MCP server is connected. The
session-memory skill is always relevant: it queries at session start and names
the matching export command, while native hooks provide the automatic
end-of-session safety net.
