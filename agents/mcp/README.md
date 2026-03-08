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

=== "Claude Code / Gemini / OpenCode / Amp"

    Add to your MCP config (see agent-specific paths below):
    ```json
    {
      "mcpServers": {
        "speaker": {
          "command": "uvx",
          "args": ["--from", "mcp[cli]", "mcp", "run", "/path/to/socratic-study-mentor/agents/mcp/study-speak-server.py"]
        }
      }
    }
    ```

**Configuration** — `~/.config/studyctl/config.yaml`:

```yaml
tts:
  backend: kokoro        # kokoro | qwen3 | macos
  voice: am_michael      # kokoro voices: am_michael, af_heart, bf_emma, etc.
  speed: 1.0             # 0.5 = slow, 1.0 = normal, 1.5 = fast, 2.0 = very fast
  macos_voice: Samantha  # fallback voice for macOS say
```

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

## Suggested Study Workflow

```
1. Morning: Cowork scheduled task runs `studyctl review`
2. Agent creates calendar time blocks for due topics
3. Apple Reminders fires notification: "Time to study Python decorators"
4. You open kiro-cli or Claude Code with study-mentor agent
5. Agent checks energy level, adapts session accordingly
6. After session: agent records progress via `studyctl progress`
7. Session exported to DB automatically (via scheduled session-export)
```
