# Connect your AI coding tool

StudyLoop turns a supported coding assistant into an AuDHD-aware Socratic mentor. You keep using the tool you already know; StudyLoop supplies the study behaviour, session context, and progress export.

## Supported in the initial pre-release

The core release harnesses are:

- **Kiro CLI** — the reference experience used in StudyLoop demos
- **Codex**
- **Claude Code**

StudyLoop also includes complete integrations for **OpenCode**, **pi**, and **Grok Build**. They are shown as preview harnesses until their live release checks pass on the target environment.

Gemini CLI and Antigravity are not mentor harnesses in this pre-release.
Their presence on your computer will not make StudyLoop advertise or select them.

The `study-plan-architect` persona (Claude, OpenCode, Kiro) interviews you into
a study plan and evaluates it against real study evidence at the start,
middle, and end of a session — see [Study Plans](study-plans.md). It installs
alongside the mentor via `studyloop install agents` and starts with
`studyloop plan architect` on every harness (see "Start a study session"
below and each harness's section for the native name).

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
studyloop install agents --tool grok
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

Replace `kiro` with `codex`, `claude`, `opencode`, `pi`, or `grok`.

## What each integration installs

### Kiro CLI

Kiro receives the `study-mentor` agent, its focused skills, and the voice helper. Start it directly with:

```bash
kiro-cli chat --agent study-mentor
```

Kiro is the demo harness because it makes the named mentor and session flow visible without requiring users to understand prompt files.

Kiro also receives the `study-plan-architect` agent. Start it directly with:

```bash
kiro-cli chat --agent study-plan-architect
```

Kiro also receives the opt-in `studyloop-xtiles-wind-down` skill at `~/.kiro/skills/`, as a symlink to the shared copy described below. It stays silent unless your second-brain provider is `xtiles` and an `xtiles` MCP server is connected.

### Codex

Codex reads the StudyLoop `AGENTS.md` from the project. Launching through `studyloop study` creates the session context and starts Codex in that directory.

That `AGENTS.md` carries one self-gated line about xTiles at wind-down, inert unless your provider is `xtiles` and an `xtiles` MCP server is connected. Codex needs no skill link of its own: it reads `~/.agents/skills/` natively, which is where the shared copy lives.

Codex has no named-agent feature, so the study-plan-architect persona reaches it the same way the mentor does — through the launcher, not a second `AGENTS.md`:

```bash
studyloop study --mode plan-architect --agent codex
```

### Claude Code

Claude Code receives the `socratic-mentor` agent and a session-export hook. The installer merges the hook into existing settings and does not replace unrelated hooks.

Claude Code also receives the `study-plan-architect` subagent, installed the same way. Inside a Claude Code session, ask for it by name ("use the study-plan-architect subagent to build my study plan"); `/agents` lists the installed subagents. Or launch it through StudyLoop with `studyloop study --mode plan-architect --agent claude`.

Configure Claude Code's model provider before starting a StudyLoop session. If
you use AWS Bedrock, Claude Code needs Bedrock enabled and valid AWS credentials
in its own settings or launch environment. A credit error from the direct
Anthropic service is a reason to check which provider Claude Code is using;
it does not establish that your Bedrock access is unavailable. StudyLoop's
mentor installation does not configure or switch your model provider.

It also receives the opt-in `studyloop-xtiles-wind-down` skill at `~/.claude/skills/`, as a symlink to the shared copy described below. It does nothing at all unless your provider is `xtiles` and an `xtiles` MCP server is connected.

### OpenCode

Two separate mechanisms write two separate sets of files, at two different times:

- **`studyloop install agents --tool opencode`** (the install command above) writes a **global** `study-mentor` agent definition to `~/.config/opencode/agents/study-mentor.md`, available to any OpenCode session on the machine, and registers both StudyLoop MCP servers (`session-db`, `studyloop`) into `~/.config/opencode/opencode.json`'s `mcp` object.
- **`studyloop study --agent opencode`** (starting a session) separately writes a **project-local** `.opencode/agents/study-mentor.md` and `.opencode/opencode.json` (both StudyLoop MCP servers, in OpenCode's own config schema) into that session's working directory. This happens at session start, not at install time — if you only ran the install command and are looking for these project-local files, that's why they aren't there yet.

Either path gets you the same mentor behaviour. StudyLoop does not choose or hard-code an OpenCode model; your working OpenCode provider and model remain authoritative.

Both copies of the mentor definition carry the same self-gated xTiles line as
Codex's. OpenCode reads the shared `~/.agents/skills/` hub directly, so the
installer does not create a redundant `~/.config/opencode/skills/` link.

OpenCode also receives a global `study-plan-architect` agent definition at
`~/.config/opencode/agents/study-plan-architect.md`. Select it from OpenCode's
agent picker, or launch it through StudyLoop with
`studyloop study --mode plan-architect --agent opencode`.

### pi

pi reads the project `AGENTS.md` and resumes through its native `--continue` option. Its session-export mandate writes real pi sessions to StudyLoop’s session database; it does not generate fixture or placeholder progress.

Its `AGENTS.md` carries the same self-gated xTiles line. pi discovers the
shared `~/.agents/skills/` hub natively, so both the xTiles wind-down skill and
the session-memory skill are available without a duplicate link.

pi has no named-agent feature either, so reach the study-plan-architect
persona through the launcher: `studyloop study --mode plan-architect --agent pi`.

### Grok Build

Grok Build is xAI's terminal coding agent (binary `grok`). It reads the repo-root `AGENTS.md` — the same file Codex reads — so `studyloop install agents --tool grok` links that one shared definition instead of a Grok-specific copy that could drift. There is no `agents/grok/` directory, by design. Launching through `studyloop study` creates the session context and starts Grok Build in that directory; it resumes through its native `--resume` option.

Because it is the same file, it carries the same self-gated xTiles line as Codex's. Grok Build also discovers the shared `~/.agents/skills/` hub natively (its skill discovery scans `.agents/skills/` at every tier), so the `studyloop-session-memory` skill reaches it with no Grok-specific link.

Grok Build has no named-agent feature: `studyloop study --mode plan-architect --agent grok` launches the study-plan-architect persona the same way.

If `grok` is not on your PATH yet:

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
```

Then confirm the wiring:

```bash
studyloop doctor --category agents
```

Doctor checks that the `grok` binary responds and that the shared repo-root `AGENTS.md` is in place.

## Session memory and automatic export

`studyloop install agents` installs one canonical
`studyloop-session-memory` skill into `~/.agents/skills/`. Codex, OpenCode,
pi and Grok Build discover that hub directly; Kiro and Claude receive links
from their native skill directories. The skill
prefers the `session_search` MCP tool and falls back to the installed
`session-query` CLI, so a missing MCP registration never silently disables
retrieval.

The installer also installs a real lifecycle hook for every release harness
that exposes one:

| Harness | Automatic export hook | Query path |
|---|---|---|
| Kiro CLI | `stop` hook in the global `study-mentor` agent | bundled `session-db-mcp`, plus skill fallback |
| Codex | global `~/.codex/hooks.json` `SessionEnd` hook | shared skill + `session-query` |
| Claude Code | global `~/.claude/settings.json` `Stop` hook | native skill link + `session-query` |
| OpenCode | global plugin, `session.idle` event | shared skill + `session-db`/`studyloop` MCP + `session-query` fallback |
| pi | global extension, `session_shutdown` event | shared skill + `session-query` (no MCP by design) |
| Grok Build | global `~/.grok/hooks/studyloop.json` `SessionEnd` hook | shared skill + `session-db`/`studyloop` MCP + `session-query` fallback |

All installed hooks run `session-export --<harness>-only` best-effort and never
block session close. Codex reviews and trusts a newly installed command-hook
hash on first use; StudyLoop does not bypass that security prompt.

Check both layers (skill/query and hook/export), or repair them, with:

```bash
studyloop doctor --category harness
studyloop doctor --category harness --fix
```

### Desktop applications

A passing doctor check establishes installed wiring, not successful capture of
the most recent conversation. Check a known recent session with `session-query`.
See [conversation memory](session-memory.md) for repair and sharing limits.

Codex's official hook configuration is global (`~/.codex/hooks.json`) and is
used by Codex sessions that load that config, including the Codex app. Claude
Code's hook is installed into Claude Code's own `~/.claude/settings.json`.
The consumer **Claude Desktop** application is a different product: this repo
has no evidence that it supports Claude Code hooks or writes Claude Code's
session store, so StudyLoop does not claim or fake support for it. Doctor
reports only evidence-backed coding-harness integrations.

## Study-plan tools over MCP

The `studyloop` MCP server (the `studyloop-mcp` command; per-harness
registration is in `agents/mcp/README.md`) exposes the learner's study plans
to any connected agent. Every tool
goes through the same plan application layer the CLI and Web UI use, so the
readiness gate, the lifecycle statuses and the "the Markdown document is the
source of truth" rule are identical on every surface. An agent that cannot
reach the MCP server can do the same work with `studyloop plan …` at a shell.

| Tool | Purpose |
|---|---|
| `list_study_plans(status=None)` | List plan summaries, active first; filter to one lifecycle status. |
| `get_study_plan(plan_id, include_markdown=False, include_history=False, history_limit=20)` | Read one plan in full — mission, milestones, records, readiness — optionally with its Markdown and the checkpoint log (1–200 rows). |
| `get_planning_interview()` | The interview questions, an evidence seed from the study databases, and the plans that already exist — call before interviewing. |
| `create_study_plan(title, answers, plan_id=None, status="draft")` | Draft a new plan from interview answers; never replaces an existing plan (a taken id is a conflict). |
| `update_study_plan(plan_id, …)` | Revise fields, topics, milestones and status together, judged as one document and saved once. |
| `set_study_plan_status(plan_id, status)` | Move a plan between `draft`, `active`, `paused`, `complete`, `abandoned`; activation is readiness-gated. |
| `set_study_plan_milestone(plan_id, index, done)` | Mark one milestone complete (`done=true`) or reopen it (`false`) — set, not toggle, so a retry is safe. |
| `evaluate_study_plan(plan_id, phase, study_id="", record=False)` | Evaluate the plan at a `start`/`mid`/`end` checkpoint against real study evidence. The default is a preview that writes nothing; `record=true` appends the checkpoint to the log and the document and reports each write (`db_write`, `document_write`, `recording_complete`). |
| `delete_study_plan(plan_id, confirmed=False)` | Delete the plan document — irreversible, so it is refused unless `confirmed=true`. The plan's checkpoint history is kept. |
| `record_plan_learning(plan_id, title, body="", status="active")` | Append a learning record to the plan — the wind-down's first write. |

A refused call is a tool error whose message starts with a machine-readable
kind — `not_found:`, `invalid_id:`, `conflict:`, `invalid:`,
`invalid_milestone:`, `not_ready:`, or `plan_error:` for a refusal the
mapping has not met — followed by the plan layer's own message. A `not_ready:` refusal names every blocker, so the agent can ask the
learner for what is missing instead of reporting that something is wrong; on
a plan that is already active it adds "pause it or repair the blockers before
writing". A recorded evaluation whose database or document write failed is
not an error: the response says which write failed (`recording_complete:
false` with the reason in `warnings`) and still carries the evaluation.

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

Codex, OpenCode, pi and Grok Build discover this directory directly. Kiro and
Claude use symlinks from `~/.kiro/skills/` and `~/.claude/skills/`. One body
per skill means an update reaches every supported harness without copy drift.

The xTiles skill remains self-gating: it is silent unless the configured
second-brain provider is xTiles and an xTiles MCP server is connected. The
session-memory skill is always relevant: it queries at session start and names
the matching export command, while native hooks provide the automatic
end-of-session safety net.
