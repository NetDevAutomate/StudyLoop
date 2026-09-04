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

It also receives the opt-in `studyloop-xtiles-wind-down` skill at `~/.claude/skills/`, as a symlink to the shared copy described below. It does nothing at all unless your provider is `xtiles` and an `xtiles` MCP server is connected.

### OpenCode

Two separate mechanisms write two separate sets of files, at two different times:

- **`studyloop install agents --tool opencode`** (the install command above) writes a **global** `study-mentor` agent definition to `~/.config/opencode/agents/study-mentor.md`, available to any OpenCode session on the machine.
- **`studyloop study --agent opencode`** (starting a session) separately writes a **project-local** `.opencode/agents/study-mentor.md` and `.opencode/opencode.json` (StudyLoop's MCP server, in OpenCode's own config schema) into that session's working directory. This happens at session start, not at install time — if you only ran the install command and are looking for these project-local files, that's why they aren't there yet.

Either path gets you the same mentor behaviour. StudyLoop does not choose or hard-code an OpenCode model; your working OpenCode provider and model remain authoritative.

Both copies of the mentor definition carry the same self-gated xTiles line as Codex's, and OpenCode also gets the `studyloop-xtiles-wind-down` skill at `~/.config/opencode/skills/`, symlinked to the shared copy described below.

### pi

pi reads the project `AGENTS.md` and resumes through its native `--continue` option. Its session-export mandate writes real pi sessions to StudyLoop’s session database; it does not generate fixture or placeholder progress.

Its `AGENTS.md` carries the same self-gated xTiles line, and like every other harness it says nothing about xTiles unless your provider is `xtiles` and an `xtiles` MCP server is connected.

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

## One skill, symlinked into every harness

The `studyloop-xtiles-wind-down` skill is installed **once**, into
`~/.agents/skills/studyloop-xtiles-wind-down/`. Each harness's own skills directory
is then a symlink to that one directory:

```text
~/.agents/skills/studyloop-xtiles-wind-down/   <- the only copy
├── SKILL.md
└── references/harnesses.md

~/.kiro/skills/studyloop-xtiles-wind-down             -> the directory above
~/.claude/skills/studyloop-xtiles-wind-down           -> the directory above
~/.config/opencode/skills/studyloop-xtiles-wind-down  -> the directory above
```

`~/.agents/skills/` is not something StudyLoop made up: Codex reads it as its
user-scope skills location and OpenCode lists it as a global search path. So Codex
is served by that one directory with no link at all, and every other harness is one
symlink away from exactly the same bytes.

Two consequences worth knowing. An edit to the skill reaches every harness at once,
so they cannot drift apart — which matters here, because the rule the skill encodes
is "offer once, only behind both gates, otherwise stay silent". And
`studyloop install agents --uninstall` removes the links and the shared copy
together.

pi is the exception: no pi skills directory is documented anywhere, so pi gets the
self-gated paragraph in its `AGENTS.md` and nothing else. If that changes, pi joins
the list above.
