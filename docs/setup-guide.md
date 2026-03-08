# Setup Guide

Step-by-step installation and configuration for Socratic Study Mentor.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Obsidian Vault Setup](#obsidian-vault-setup)
- [NotebookLM Setup](#notebooklm-setup-optional)
- [Session Database](#session-database)
- [Cross-Machine Sync](#cross-machine-sync)
- [Scheduling](#scheduling)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- **Python 3.10+** (studyctl requires 3.12+, agent-session-tools works with 3.10+)
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **Obsidian** — for study notes (any vault structure works)
- **Optional**: `notebooklm-py` for Google NotebookLM sync
- **Optional**: `sentence-transformers` for semantic search

## Installation

### Automatic (recommended)

```bash
git clone https://github.com/NetDevAutomate/Socratic-Study-Mentor.git
cd socratic-study-mentor
./scripts/install.sh
```

This will:
1. Verify Python 3.10+ and `uv` are installed
2. Run `uv sync` to install both packages
3. Run `install-agents.sh` to set up AI agent definitions
4. Create a default config at `~/.config/studyctl/config.yaml`

### Manual

```bash
git clone https://github.com/NetDevAutomate/Socratic-Study-Mentor.git
cd socratic-study-mentor

# Install both packages in the workspace
uv sync

# Install optional extras
uv pip install studyctl[notebooklm]
uv pip install agent-session-tools[semantic]

# Install agents separately
./scripts/install-agents.sh
```

## Configuration

### studyctl — `~/.config/studyctl/config.yaml`

```yaml
# Base path to your Obsidian vault
obsidian_base: ~/Obsidian

# Path to the AI session database
session_db: ~/.config/studyctl/sessions.db

# State directory for sync tracking
state_dir: ~/.local/share/studyctl

# Remote sync (optional — for cross-machine state sync)
# sync_remote: your-remote-host
# sync_user: your-username

# Study topics — each maps to an Obsidian directory
topics:
  - name: Python
    slug: python
    obsidian_path: 2-Areas/Study/Python
    # notebook_id: your-notebooklm-notebook-id  # optional
    tags: [python, programming]

  - name: SQL
    slug: sql
    obsidian_path: 2-Areas/Study/SQL
    tags: [sql, databases]
```

| Field | Description | Default |
|-------|-------------|---------|
| `obsidian_base` | Root of your Obsidian vault | `~/Obsidian` |
| `session_db` | Path to the session SQLite database | `~/.config/studyctl/sessions.db` |
| `state_dir` | Where studyctl stores sync state | `~/.local/share/studyctl` |
| `topics[].name` | Display name for the topic | required |
| `topics[].slug` | URL-safe identifier | required |
| `topics[].obsidian_path` | Path relative to `obsidian_base` | required |
| `topics[].notebook_id` | NotebookLM notebook ID (if using sync) | empty |
| `topics[].tags` | Keywords for session search matching | `[]` |

### agent-session-tools — `~/.config/studyctl/config.yaml`

Created automatically on first run. Key settings:

```yaml
database:
  path: ~/.config/studyctl/sessions.db
  archive_path: ~/.config/studyctl/sessions_archive.db
  backup_dir: ~/.config/studyctl/backups

thresholds:
  warning_mb: 100
  critical_mb: 500

semantic_search:
  model: all-mpnet-base-v2    # embedding model
  fts_weight: 0.4             # hybrid search: FTS weight
  semantic_weight: 0.6        # hybrid search: vector weight
  min_content_length: 50
  auto_embed: true
```

Environment variable overrides:
- `DATABASE_PATH` — override database location
- `LOG_LEVEL` — set logging level (DEBUG, INFO, WARNING, ERROR)
- `EMBEDDING_MODEL` — override embedding model

## Obsidian Vault Setup

studyctl expects your study notes in directories under your Obsidian vault. The structure is flexible — just point each topic's `obsidian_path` at the right directory.

Example vault layout:

```
~/Obsidian/
├── Personal/
│   └── 2-Areas/
│       └── Study/
│           ├── Courses/
│           │   ├── ArjanCodes/       ← Python topic
│           │   └── DataCamp/         ← SQL topic
│           ├── Mentoring/
│           │   ├── Python/           ← AI-generated teaching moments
│           │   ├── Databases/
│           │   └── Data-Engineering/
│           └── Study-Plans/
```

studyctl syncs `.md`, `.pdf`, and `.txt` files. It skips:
- Files under 100 bytes
- Obsidian metadata files (`.obsidian/`, index files)
- Common non-content directories (`node_modules`, `__pycache__`)

## NotebookLM Setup (optional)

NotebookLM sync lets you upload your Obsidian notes as sources in Google NotebookLM notebooks, then generate audio overviews.

1. Install the optional dependency:
   ```bash
   uv pip install studyctl[notebooklm]
   ```

2. Create notebooks in [NotebookLM](https://notebooklm.google.com/) — one per study topic

3. Get each notebook's ID from its URL:
   ```
   https://notebooklm.google.com/notebook/NOTEBOOK_ID_HERE
   ```

4. Add the IDs to your config:
   ```yaml
   topics:
     - name: Python
       slug: python
       obsidian_path: 2-Areas/Study/Python
       notebook_id: your-notebook-id-here
   ```

5. Sync and generate audio:
   ```bash
   studyctl sync python          # Upload changed notes
   studyctl audio python         # Generate audio overview
   ```

## Session Database

The session database stores exported AI conversations from all your tools. It powers spaced repetition, struggle detection, and session search.

### Populate the database

```bash
# Export from all detected sources
session-export

# Export from a specific source
session-export --source claude
session-export --source kiro
session-export --source aider
```

Supported sources: `claude`, `kiro`, `gemini`, `opencode`, `aider`, `litellm`, `repoprompt`

### Verify it's working

```bash
session-query stats              # Show database statistics
session-query list --since 7d    # List recent sessions
session-query search "python"    # Search across all sessions
```

## Cross-Machine Sync

Both tools support syncing state across machines via SSH.

### studyctl state sync

```bash
# Initialize sync config
studyctl state init

# Edit ~/.config/studyctl/sync.yaml to add your remotes
# Then:
studyctl state push              # Push local state to remotes
studyctl state pull              # Pull state from remotes
studyctl state status            # Check connectivity
```

### Session database sync

```bash
# Push sessions to a remote machine
session-sync push user@remote-host

# Pull sessions from a remote machine
session-sync pull user@remote-host
```

This uses delta sync — only new sessions are transferred, not the entire database.

## Scheduling

Set up automatic sync so your notes and sessions stay current.

```bash
# Install all default scheduled jobs
studyctl schedule install

# List active jobs
studyctl schedule list

# Remove all jobs
studyctl schedule remove

# Add a custom job
studyctl schedule add my-sync "studyctl sync --all" "daily 3am"
```

On macOS, this creates launchd plists. On Linux, it uses cron.

## Windows (WSL2)

The toolkit runs on Windows via WSL2 (Windows Subsystem for Linux).

### Prerequisites

1. Install WSL2 with Ubuntu: `wsl --install -d Ubuntu`
2. Inside WSL2, install Python 3.10+ and uv:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Clone and install as normal (all commands run inside WSL2)

### What works

- All CLI tools (`studyctl`, `session-export`, `session-query`, etc.)
- kiro-cli and Claude Code (terminal-based)
- SQLite database, FTS5 search, session sync
- Cron scheduling (enable with `sudo service cron start` or systemd)
- Git, pre-commit, ruff, pyright, pytest

### Differences from macOS

| Feature | macOS | WSL2 |
|---------|-------|------|
| Scheduling | launchd (automatic) | cron (enable manually) |
| Calendar MCP | Apple Calendar or Google | Google Calendar only |
| Reminders | Apple Reminders (native notifications) | Google Calendar reminders |
| Obsidian vault | `~/Obsidian/` | `/mnt/c/Users/<name>/Obsidian/` |
| PDF rendering | `brew install pandoc mactex` | `sudo apt install pandoc texlive-xetex` |
| Claude Desktop | Native app | Runs on Windows side |

### Connecting WSL2 MCP servers to Claude Desktop (Windows)

Claude Desktop runs on Windows but can connect to MCP servers inside WSL2:

```json
{
  "mcpServers": {
    "study-tools": {
      "command": "wsl",
      "args": ["--", "npx", "-y", "your-mcp-server"]
    }
  }
}
```

### Obsidian vault path

If your Obsidian vault is on the Windows filesystem, configure the path in `~/.config/studyctl/config.yaml`:

```yaml
obsidian_base: /mnt/c/Users/YourName/Obsidian
```

For better performance, consider keeping the vault inside WSL2's native filesystem (`~/Obsidian/`) and syncing with Obsidian Sync or Git.

## Troubleshooting

### `studyctl: command not found`

The package isn't on your PATH. Either:
- Run via `uv run studyctl` instead
- Or ensure `uv sync` completed successfully and your shell can find uv-installed scripts

### `session-export` finds no sessions

Check that the AI tool's data directory exists:
- Claude Code: `~/.claude/projects/`
- Kiro CLI: `~/Library/Application Support/kiro-cli/data.sqlite3` (macOS)
- Gemini CLI: `~/.gemini/tmp/`
- Aider: `.aider.chat.history.md` files in project directories

### `studyctl review` shows nothing

The session database may be empty. Run `session-export` first to populate it, then `studyctl review` can check your study history.

### NotebookLM sync fails

- Verify `notebooklm-py` is installed: `uv pip install studyctl[notebooklm]`
- Check that your `notebook_id` is correct (copy from the NotebookLM URL)
- Ensure you're authenticated with Google (follow `notebooklm-py` auth docs)

### Config file not loading

studyctl looks for config at `~/.config/studyctl/config.yaml`. Override with:
```bash
export STUDYCTL_CONFIG=/path/to/your/config.yaml
```

### Database too large

```bash
session-maint vacuum             # Reclaim space
session-query stats              # Check current size
session-maint archive            # Archive old sessions
```
