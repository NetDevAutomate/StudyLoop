# Setup Guide

Step-by-step installation and configuration for Socratic Study Mentor.

## Table of Contents

- [Prerequisites](#prerequisites)
  - [tmux-resurrect Compatibility](#tmux-resurrect-compatibility)
- [Installation](#installation)
- [Configuration](#configuration)
- [Obsidian Vault Setup](#obsidian-vault-setup)
- [NotebookLM Setup](#notebooklm-setup-optional)
- [Session Database](#session-database)
- [Content Pipeline](#content-pipeline)
- [Cross-Machine Sync](#cross-machine-sync)
- [Scheduling](#scheduling)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- **Python 3.12+** (both studyctl and agent-session-tools require 3.12+)
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **tmux 3.1+** — required for `studyctl study` split-pane sessions (`brew install tmux` on macOS, `apt install tmux` on Linux)
- **Obsidian** — for study notes (any vault structure works)
- **Optional**: `notebooklm-py` for Google NotebookLM sync
- **Optional**: `sentence-transformers` for semantic search

> **tmux-resurrect / tmux-continuum users**: studyctl automatically cleans up
> zombie sessions on startup, so resurrect-restored sessions are handled
> gracefully. For the best experience, add the restore hook below to prevent
> resurrect from saving study sessions at all. See
> [tmux-resurrect compatibility](#tmux-resurrect-compatibility) for details.

### tmux-resurrect Compatibility

studyctl creates temporary `study-*` tmux sessions that should not persist
across tmux restarts. If you use **tmux-resurrect** or **tmux-continuum**,
these plugins may save and restore killed study sessions as zombies.

**Automatic handling (no action required):** `studyctl study` automatically
detects and kills zombie sessions before starting a new session. This works
out of the box — no configuration needed.

**Recommended: add a restore hook** to prevent resurrect from restoring
study sessions at all. Add this to your `~/.tmux.conf`:

```bash
# Kill any restored study-* sessions immediately after resurrect restore.
# studyctl sessions are temporary and should not survive tmux restarts.
set -g @resurrect-restore-hook 'for s in $(tmux list-sessions -F "#{session_name}" 2>/dev/null | grep "^study-"); do tmux kill-session -t "$s" 2>/dev/null; done'
```

After adding, reload your tmux config:

```bash
tmux source-file ~/.tmux.conf
```

Run `studyctl doctor` to verify the configuration — it checks for
tmux-resurrect and warns if the restore hook is not detected.

## Installation

### Automatic (recommended)

```bash
git clone https://github.com/NetDevAutomate/Socratic-Study-Mentor.git
cd socratic-study-mentor
./scripts/install.sh
```

This will:
1. Verify Python 3.12+ is installed
2. Install `uv` if not already available
3. Run `uv sync` to install both packages
4. Run `install-agents.sh` to set up AI agent definitions
5. Create a default config at `~/.config/studyctl/config.yaml`
6. Optionally download the kokoro-onnx voice model (~85MB) for TTS support

### Manual

```bash
git clone https://github.com/NetDevAutomate/Socratic-Study-Mentor.git
cd Socratic-Study-Mentor

# Full install (interactive — prompts for TTS voice model)
./scripts/install.sh

# Full install without prompts (for Ansible/CI)
./scripts/install.sh --non-interactive

# Just reinstall/upgrade CLI tools globally
./scripts/install.sh --tools-only

# Just reinstall agent definitions
./scripts/install.sh --agents-only

# Install optional extras
uv pip install studyctl[notebooklm]
uv pip install agent-session-tools[semantic]
```

For **Ansible playbooks**, clone the repo then run the install script:

```yaml
- name: Install Socratic Study Mentor
  hosts: study_machines
  tasks:
    - name: Clone repo
      git:
        repo: https://github.com/NetDevAutomate/Socratic-Study-Mentor.git
        dest: ~/code/personal/tools/Socratic-Study-Mentor

    - name: Run installer
      command: ./scripts/install.sh --non-interactive
      args:
        chdir: ~/code/personal/tools/Socratic-Study-Mentor
```

## Configuration

### Interactive Setup (recommended)

Run the interactive wizard to configure your study environment:

```bash
studyctl config init
```

This walks you through three core questions:

1. **Knowledge bridging** — Do you want to leverage a topic you already know well (e.g. networking, cooking, music theory) so the mentor can draw analogies to new topics you're studying?
2. **NotebookLM integration** — Do you want to integrate with Google's NotebookLM to use notebooks as a knowledge source?
3. **Obsidian vault** — Do you want to integrate with an existing Obsidian vault? If so, provide the base path (e.g. `~/Obsidian/Vault`).

The wizard creates or updates `~/.config/studyctl/config.yaml` with your choices. You can re-run it at any time to change settings.

### Manual Configuration

All configuration lives in a single file: `~/.config/studyctl/config.yaml`. This file is shared between `studyctl` and all `session-*` tools — use the same file on every machine.

### Web PWA (recommended)

The study web app requires no extra dependencies — just run:

```bash
studyctl web
```

This starts a web server on `http://0.0.0.0:8567` accessible from any device on your network. Open it on your phone, tablet, or laptop.

**Install as PWA (iOS/Android):** Open in Safari → Share → Add to Home Screen. The app then works full-screen like a native app.

Configure flashcard/quiz directories:

```yaml
# ~/.config/studyctl/config.yaml
review:
  directories:
    - ~/Desktop/ZTM-DE/downloads
    - ~/Desktop/Python/downloads
```

**Voice output** uses the Web Speech API (built into all browsers). For best quality voices:

- **macOS**: System Settings → Accessibility → Spoken Content → System Voice → Manage Voices → download Samantha (Enhanced) or Ava (Premium)
- **iOS**: Settings → Accessibility → Spoken Content → Voices → English → download Siri voices
- **Windows**: Settings → Time & Language → Speech → Manage voices

Two voice modes in the PWA:
- **Read once** — tap the speaker icon on a card, or press `T`. Reads the current content once.
- **Auto-voice** — toggle the header speaker icon, or press `V`. Reads everything automatically as you navigate.

**Accessibility:** The `Aa` button toggles [OpenDyslexic](https://opendyslexic.org) font. The sun icon toggles light/dark theme. Both are persisted across sessions.

### Hosts — Cross-Machine Sync

#### Prerequisites: Passwordless SSH

Cross-machine sync uses SSH and rsync under the hood. **Passwordless SSH must be configured** between all machines before sync will work. If you're prompted for a password, sync will hang or fail.

Set up SSH key-based auth between each pair of machines:

```bash
# 1. Generate a key (if you don't have one)
ssh-keygen -t ed25519 -C "your-email@example.com"

# 2. Copy your public key to each remote machine
ssh-copy-id user@192.168.1.22    # macmini
ssh-copy-id user@192.168.1.21    # macbookpro

# 3. Verify passwordless login works
ssh user@192.168.1.22 "echo ok"  # should print "ok" with no password prompt
```

Do this from **every machine** to **every other machine** you want to sync with. If machine A syncs with B and C, then A needs key access to B and C, B needs access to A and C, etc.

> **Platform limitation:** Cross-machine sync requires a native Unix/Linux SSH server on the remote host with direct access to the filesystem. This means sync **does not work** with:
>
> - **Windows hosts running WSL** — SSH connects to Windows, not the WSL filesystem where the database lives. The `$HOME` path and `sqlite3` binary won't resolve correctly.
> - **Docker containers** — unless SSH is exposed from the container (not recommended). The database path inside the container differs from the host path.
> - **Network-attached storage** — the remote needs `sqlite3` installed and SSH access.
>
> Supported targets: macOS, native Linux, any Unix system with SSH + sqlite3.

#### Host Configuration

The `hosts` section defines all your machines. The local machine is auto-detected by matching your system hostname, and everything else becomes a sync target.

```yaml
hosts:
  macmini:
    hostname: study-hub          # must match socket.gethostname()
    ip_address:
      primary: 192.168.1.22        # wired / ethernet
      secondary: 192.168.1.12      # wifi (optional fallback)
    user: user
    state_json: ~/.config/studyctl/state.json
    sessions_db: ~/.config/studyctl/sessions.db

  macbookpro:
    hostname: Andys-MacBook-Pro-Max
    ip_address:
      primary: 192.168.1.21
    user: user
    state_json: ~/.config/studyctl/state.json
    sessions_db: ~/.config/studyctl/sessions.db

  work-macbook:
    hostname: 842f575e3614
    ip_address:
      primary: 192.168.1.20
    user: user
    state_json: ~/.config/studyctl/state.json
    sessions_db: ~/.config/studyctl/sessions.db
```

**One config file on all machines.** Deploy the same `config.yaml` everywhere — each machine auto-detects itself by hostname and treats the rest as remotes.

| Field | Description |
|-------|-------------|
| `hostname` | Must match `socket.gethostname()` on that machine |
| `ip_address.primary` | Wired/ethernet IP (tried first for rsync/SSH) |
| `ip_address.secondary` | Wifi IP (optional fallback if primary unreachable) |
| `user` | SSH username for this machine |
| `state_json` | Path to studyctl state file |
| `sessions_db` | Path to the AI session SQLite database |

Use `session-sync` for cross-machine database sync:

```bash
session-sync push macmini
session-sync pull macbookpro
session-sync sync work-macbook
session-sync endpoints            # list all remote hosts
```

### Study Topics

```yaml
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
| `topics[].name` | Display name for the topic | required |
| `topics[].slug` | URL-safe identifier | required |
| `topics[].obsidian_path` | Path relative to `obsidian_base` | required |
| `topics[].notebook_id` | NotebookLM notebook ID (if using sync) | empty |
| `topics[].tags` | Keywords for session search matching | `[]` |

### Database & Search Settings

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

### TTS Voice Settings

```yaml
tts:
  voice: am_michael      # kokoro voice (am_michael, af_heart, bf_emma, etc.)
  speed: 1.5             # 0.5 = slow, 1.0 = normal, 1.5 = fast
  pause: 0.0             # seconds between sentences
  backend: kokoro        # kokoro | qwen3 | macos
```

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

## Content Pipeline

The content pipeline converts PDFs and Obsidian notes into NotebookLM-powered study materials (audio overviews, flashcards, quizzes). It was absorbed from [notebooklm-pdf-by-chapters](https://github.com/andytaylor/notebooklm-pdf-by-chapters) and lives under `studyctl content`.

### Install content dependencies

```bash
# PDF splitting (pymupdf + httpx)
uv pip install studyctl[content]

# NotebookLM integration (required for upload/generate/download commands)
uv pip install studyctl[notebooklm]
```

### Configure review directories

Point studyctl at the directories where content pipeline outputs land (flashcards, quizzes). These are picked up by `studyctl review`, the web PWA, and the TUI:

```yaml
# ~/.config/studyctl/config.yaml
review:
  directories:
    - ~/Desktop/ZTM-DE/downloads
    - ~/Desktop/Python/downloads
```

### Typical workflow

```bash
# 1. Split a PDF textbook into per-chapter files
studyctl content split ~/Books/my-textbook.pdf -o ./chapters

# 2. Upload chapters to NotebookLM and generate audio overviews
studyctl content process ~/Books/my-textbook.pdf -n NOTEBOOK_ID

# 3. Or use the syllabus workflow for multi-episode podcast generation
studyctl content syllabus -n NOTEBOOK_ID -o ./chapters
studyctl content autopilot -o ./chapters

# 4. Convert Obsidian notes to PDFs and upload in one step
studyctl content from-obsidian ~/Obsidian/Vault/Study/Python
```

See the [CLI Reference](../README.md#studyctl-content) for all available commands.

## Cross-Machine Sync

Both tools support syncing state across machines via SSH.

### Session database sync

```bash
session-sync push macmini        # Push sessions to a named host
session-sync pull macbookpro     # Pull sessions from a named host
session-sync sync work-macbook   # Two-way sync with a host
session-sync endpoints           # List all configured remote hosts
```

Both commands read host definitions from `~/.config/studyctl/config.yaml` (the `hosts` section). See the [Hosts configuration](#hosts--cross-machine-sync) in the README for the full schema. Delta sync transfers only new sessions, not the entire database.

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
2. Inside WSL2, install Python 3.12+ and uv:
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

## Verify Installation

After installing and configuring, run the health check to make sure everything is working:

```bash
studyctl doctor
```

This checks Python version, installed packages, config validity, databases, optional dependencies, and AI agent definitions. You'll see a colour-coded table:

- Green tick = healthy
- Yellow ! = warning (often auto-fixable)
- Red cross = failure (needs attention)
- Blue i = informational (optional)

If issues are found:

```bash
studyctl upgrade              # Fix auto-fixable issues (packages, DB, agents)
studyctl upgrade --dry-run    # Preview changes first
```

For machine-readable output (used by CI pipelines and AI agents):

```bash
studyctl doctor --json
```

### AI-Guided Setup

If you're using an AI coding assistant, the **install-mentor agent** can guide you through the entire setup process conversationally. It automatically detects your environment, installs packages, runs `studyctl doctor`, and fixes issues.

The prompt lives at `agents/shared/install-mentor.md` and works with any AI tool that can run shell commands — Claude Code, Kiro CLI, Gemini CLI, OpenCode, or Amp.

To use it in Claude Code:
```
Read agents/shared/install-mentor.md and follow its instructions to set up studyctl
```

## Troubleshooting

### First step: run `studyctl doctor`

Before investigating specific issues, always start with the health check:

```bash
studyctl doctor
```

This will identify most common problems and tell you how to fix them. If auto-fixable issues are found, run `studyctl upgrade` to resolve them.

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
