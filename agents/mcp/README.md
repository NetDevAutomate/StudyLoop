# MCP Server Integrations

Optional MCP (Model Context Protocol) servers that enhance the study mentor experience.

## Study-Speak TTS

Speak agent responses aloud using local TTS. Wraps the `study-speak` CLI as an MCP tool.

**Install the TTS package:**
```bash
uv tool install "./packages/agent-session-tools[tts]" --force
```

**Agent configs** — each agent's `mcp.json` already references the speaker server. To use it manually:

=== "Kiro CLI"

    The Kiro agent config (`agents/kiro/study-mentor.json`) includes the MCP server automatically. It runs:
    ```bash
    uvx --from "mcp[cli]" mcp run agents/mcp/study-speak-server.py
    ```

=== "Claude Code / Codex / OpenCode / pi"

    Add to your MCP config (see agent-specific paths below):
    ```json
    {
      "mcpServers": {
        "speaker": {
          "command": "uvx",
          "args": ["--from", "mcp[cli]", "mcp", "run", "/path/to/studyloop/agents/mcp/study-speak-server.py"]
        }
      }
    }
    ```

=== "Grok Build"

    Grok Build reads MCP servers from `$GROK_HOME/config.toml` (default
    `~/.grok/config.toml`), not a repo-owned `mcp.json`. Register with the CLI:
    ```bash
    grok mcp add speaker -- uvx --from "mcp[cli]" mcp run /path/to/studyloop/agents/mcp/study-speak-server.py
    ```

    Or write the entry by hand:
    ```toml
    [mcp_servers.speaker]
    command = "uvx"
    args = ["--from", "mcp[cli]", "mcp", "run", "/path/to/studyloop/agents/mcp/study-speak-server.py"]
    ```

**Configuration** — `~/.config/studyloop/config.yaml`:

```yaml
tts:
  backend: kokoro        # kokoro | openvox | qwen3 | macos
  voice: am_michael      # kokoro voices: am_michael, af_heart, bf_emma, etc.
  speed: 1.0             # 0.5 = slow, 1.0 = normal, 1.5 = fast, 2.0 = very fast
  macos_voice: Samantha  # fallback voice for macOS say
```

Optional OpenVox profile:

```yaml
tts:
  backend: openvox
  openvox_base_url: http://127.0.0.1:8000/v1
  openvox_model: kokoro
  openvox_voice: af_bella
  openvox_language: en
  openvox_response_format: wav
  openvox_timeout: 30
```

OpenVox is optional and works best for terminal/MCP voice when its Local API is enabled. If its local API server is not running or is busy, `study-speak` falls back to the existing Kokoro/macOS path.

**Toggle during a session:**

- Kiro: `@speak-start` / `@speak-stop`
- Claude Code: `/speak-start` / `/speak-stop`
- Others: `@speak-start` / `@speak-stop`

See [Voice Output Guide](../voice-output.md) for full details, backend comparison, and troubleshooting.

## Apple Calendar & Reminders (macOS only)

Native calendar time-blocking and reminder notifications.

**Install:**
```bash
npx -y @nicepkg/gkd@latest install FradSer/mcp-server-apple-reminders
```

**Or manual config** — add to your MCP client config:

```json
{
  "mcpServers": {
    "apple-reminders": {
      "command": "npx",
      "args": ["-y", "mcp-server-apple-reminders"]
    }
  }
}
```

**Config locations:**
- Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json`
- kiro-cli: `~/.kiro/settings.json` (mcpServers section)

**What it enables:**
- Create study session reminders with native macOS notifications
- Time-block study sessions in Apple Calendar
- Daily task organisation from spaced repetition schedule
- Break reminders during long sessions

## Google Calendar (cross-platform)

For Windows/WSL2 users, or anyone preferring Google Calendar.

### Claude Desktop (built-in)
No MCP needed — use the first-party connector:
1. Open Claude Desktop → Settings → Extensions
2. Toggle on Google Calendar
3. Sign in with your Google account

### kiro-cli / Claude Code (MCP server)

**Install:**
```bash
npm install -g @anthropic/mcp-google-calendar
```

**Config:**
```json
{
  "mcpServers": {
    "google-calendar": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-google-calendar"],
      "env": {
        "GOOGLE_CLIENT_ID": "your-client-id",
        "GOOGLE_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

Requires a Google Cloud project with Calendar API enabled. See [setup guide](https://github.com/galacoder/mcp-google-calendar#setup).

<a id="studyloop-mcp-session-db-tools"></a>

## studyloop-mcp (Study tools)

The `studyloop-mcp` server exposes 32 MCP tools: courses and review cards, the study backlog and
progress signals, lesson browsing, the live session, the `now` recommendation, and the learner's
study plans (nine lifecycle tools plus `record_plan_learning`, every one through the same plan
application layer the CLI and Web UI use — see `docs/agent-install.md`, "Study-plan tools over
MCP", for the refusal kinds and the readiness gate). It's registered as a Python entry point and runs
via stdio. The table below is pinned to the production registry by
`tests/test_docs_plan_integration_contract.py`. (This section was headed "Session DB Tools" until
2026-09-16; the old anchor above is kept so external links still land here.)

**Start manually (for testing):**
```bash
uv run --project packages/studyloop studyloop-mcp
```

**Agent config** — already included in `agents/claude/mcp.json`. For other agents, add (the
server NAME is `studyloop`; `studyloop-mcp` is the console-script COMMAND, never a server name):
```json
{
  "mcpServers": {
    "studyloop": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/packages/studyloop", "studyloop-mcp"]
    }
  }
}
```

**Tools:**

| Tool | Description |
|------|-------------|
| `list_courses` | List courses with card counts and review stats |
| `get_study_context` | Current study state — due cards, weak areas |
| `get_chapter_text` | Extract text from chapter PDFs |
| `generate_flashcards` | Save agent-generated flashcards |
| `generate_quiz` | Save agent-generated quiz questions |
| `record_study_progress` | Record a card review result |
| `get_due_cards` | Cards due for spaced-repetition review, one course or all |
| `log_review_outcome` | Record the outcome of reviewing one card (with response time) |
| `get_study_backlog` | List pending backlog topics |
| `get_topic_suggestions` | Ranked topic suggestions (algorithmic scoring) |
| `get_study_history` | Search past sessions for a topic |
| `record_topic_progress` | Update priority or resolve a backlog topic |
| `get_active_topics` | The AuDHD three-topic active set vs the remaining backlog |
| `log_topic` | Record a learning / struggling / insight signal mid-session |
| `log_struggle` | Record a topic the learner struggled with, for later study |
| `get_concept_context` | Concept dependency edges for a topic, with per-edge provenance and `coverage` — the prerequisite structure a mentor sequences from |
| `get_next_action` | The same "what now?" recommendation the web `/api/now` endpoint gives — plan-aware when a plan is active |
| `get_lesson_tree` | Browse the course-material tree: providers → courses → lessons |
| `read_lesson` | The raw Markdown of one lesson |
| `search_lessons` | Full-text search over lesson bodies |
| `list_session_options` | The selectable study targets the web start picker offers |
| `end_session` | End the currently-active study session (idempotent) |
| `list_study_plans` | Study-plan summaries, active first; filter to one status |
| `get_study_plan` | One plan in full — mission, milestones, records, readiness; optional Markdown and checkpoint history |
| `get_planning_interview` | The interview questions, an evidence seed and the existing plans — the architect's brief |
| `create_study_plan` | Draft a plan from interview answers; a taken id is a conflict, never a replacement |
| `update_study_plan` | Revise title, topics, dates, energy floor, cadence, notes, milestones and status as one document, saved once — not the mission, which is edited in the Markdown |
| `set_study_plan_status` | Move a plan between `draft`, `active`, `paused`, `complete`, `abandoned`; activation is readiness-gated |
| `set_study_plan_milestone` | Set one milestone done or not done — set, not toggle, so a retry is safe |
| `evaluate_study_plan` | A `start`/`mid`/`end` checkpoint against real evidence; preview by default, `record=true` reports each write |
| `delete_study_plan` | Delete the plan document — refused unless `confirmed=true`; checkpoint history is kept |
| `record_plan_learning` | Append a learning record to a plan — the wind-down's first write |

## session-db (Session Memory Tools)

The `session-db-mcp` server (package `agent-session-tools`) exposes the
conversation archive and the evidence layer. Every mentor is instructed to call
two of its tools at session start, alongside `get_concept_context` above:

| Tool | Description |
|------|-------------|
| `session_search` | Where a topic was *discussed*: FTS over every harness's transcripts |
| `session_context` | A token-budgeted excerpt of one prior session |
| `session_hotspots` | Most-discussed files over the last N days |
| `memory_search` | What was *concluded* about a topic: quote-bound assertions, their reviews, and `contradicts`/`corrects` relations, with explicit `coverage` limits |
| `memory_source` | The exact stored bytes behind a citation |

**Start manually (for testing):**
```bash
uv run --project packages/agent-session-tools session-db-mcp
```

**Agent config** — included in `agents/claude/mcp.json` and
`agents/kiro/study-mentor.json`. Codex, OpenCode and Grok Build have no
repo-owned MCP file, but need no manual step: `studyloop install agents --tool <x>`
already registers both servers globally for each of them, via
`register_mcp_servers` (`installers.py`). The config below is a reference for
running each harness without the StudyLoop installer:

- Codex — `~/.codex/config.toml` (only needed without the installer):
  ```toml
  [mcp_servers.session-db]
  command = "session-db-mcp"
  args = []

  [mcp_servers.studyloop]
  command = "studyloop-mcp"
  args = []
  ```
- Grok Build — registered with the CLI (never hand-write
  `$GROK_HOME/config.toml`, default `~/.grok/config.toml`; `grok mcp list`
  reads it back):
  ```bash
  grok mcp add --scope user --transport stdio session-db session-db-mcp
  grok mcp add --scope user --transport stdio studyloop studyloop-mcp
  ```
  An older install may instead carry these two names in
  `$GROK_HOME/user-settings.json`'s `mcpServers` map; the installer treats a
  name already present there as registered and does not add a duplicate.
- OpenCode — `studyloop install agents --tool opencode` writes both servers
  into `~/.config/opencode/opencode.json`'s `mcp` object automatically, via
  `_strategies.write_mcp_config(fmt="opencode")`, in OpenCode's own schema
  (flat `command` array, `enabled`/`type: local`). The same per-session
  adapter (`adapters/opencode.py`) writes both into the session-local
  `.opencode/opencode.json` too.
- pi — has no MCP registration path by design: pi's own README states "No
  MCP" (build CLI tools with skills, or an extension), so pi is CLI-fallback
  only. pi mentors use the CLI fallbacks the skill names — `session-query`,
  `session-context search`, `studyloop mastery graph`.

Both commands are installed by `uv tool install studyloop` and
`uv tool install agent-session-tools`; use the `uv run --project ...` form
instead when running from a checkout.

## Suggested Study Workflow

```
1. Morning: Cowork scheduled task runs `studyloop review`
2. Agent creates calendar time blocks for due topics
3. Apple Reminders fires notification: "Time to study Python decorators"
4. You open kiro-cli or Claude Code with study-mentor agent
5. Agent checks energy level, adapts session accordingly
6. After session: agent records progress via `studyloop progress`
7. Session exported to DB automatically (via scheduled session-export)
```
