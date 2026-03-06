# MCP Server Integrations

Optional MCP (Model Context Protocol) servers that enhance the study mentor experience.

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
