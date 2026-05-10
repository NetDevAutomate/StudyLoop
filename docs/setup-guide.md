# Setup Guide

Step-by-step installation and configuration for StudyLoop.

## Table of Contents

- [Prerequisites](#prerequisites)
  - [tmux-resurrect Compatibility](#tmux-resurrect-compatibility)
- [Installation](#installation)
- [Configuration](#configuration)
- [Obsidian Vault Setup](#obsidian-vault-setup)
- [Session Database](#session-database)
- [Content Pipeline](#content-pipeline)
- [Cross-Machine Sync](#cross-machine-sync)
- [Scheduling](#scheduling)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- **Python 3.12+** (both studyloop and agent-session-tools require 3.12+)
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **tmux 3.1+** — required for `studyloop study` split-pane sessions (`brew install tmux` on macOS, `apt install tmux` on Linux)
- **Obsidian** — for study notes (any vault structure works)
- **Optional**: `sentence-transformers` for semantic search
- **Optional**: `ttyd` — enables web terminal access from browser or iPad (`brew install ttyd` on macOS, `apt install ttyd` on Linux)

> **tmux-resurrect / tmux-continuum users**: studyloop automatically cleans up
> zombie sessions on startup, so resurrect-restored sessions are handled
> gracefully. For the best experience, add the restore hook below to prevent
> resurrect from saving study sessions at all. See
> [tmux-resurrect compatibility](#tmux-resurrect-compatibility) for details.

### tmux-resurrect Compatibility

studyloop creates temporary `study-*` tmux sessions that should not persist
across tmux restarts. If you use **tmux-resurrect** or **tmux-continuum**,
these plugins may save and restore killed study sessions as zombies.

**Automatic handling (no action required):** `studyloop study` automatically
detects and kills zombie sessions before starting a new session. This works
out of the box — no configuration needed.

**Recommended: add a restore hook** to prevent resurrect from restoring
study sessions at all. Add this to your `~/.tmux.conf`:

```bash
# Kill any restored study-* sessions immediately after resurrect restore.
# studyloop sessions are temporary and should not survive tmux restarts.
set -g @resurrect-restore-hook 'for s in $(tmux list-sessions -F "#{session_name}" 2>/dev/null | grep "^study-"); do tmux kill-session -t "$s" 2>/dev/null; done'
```

After adding, reload your tmux config:

```bash
tmux source-file ~/.tmux.conf
```

Run `studyloop doctor` to verify the configuration — it checks for
tmux-resurrect and warns if the restore hook is not detected.

## Installation

### User Install (recommended)

Install from a source checkout with `uv`. The PyPI/Homebrew distribution
was yanked; source install is the current supported path.

```bash
git clone https://github.com/Hookey-Street-Software/StudyLoop.git studyloop
cd studyloop
uv sync --all-packages
uv tool install ./packages/studyloop
studyloop setup
studyloop doctor --fix
```

### Repo Bootstrap

```bash
git clone https://github.com/Hookey-Street-Software/StudyLoop.git studyloop
cd studyloop
./scripts/install.sh
```

This will:
1. Verify Python 3.12+ is installed
2. Install `uv` if not already available
3. Run `uv sync`
4. Delegate to `studyloop install tools`
5. Delegate to `studyloop install agents`

The shell script is now only a bootstrap wrapper. The real install surface lives in typed CLI commands:

```bash
studyloop install tools
studyloop install agents
studyloop doctor --fix
```

### Developer Install

If you are contributing to the repo or running from source, prefer `uv sync` in the checkout:

```bash
git clone https://github.com/Hookey-Street-Software/StudyLoop.git studyloop
cd studyloop
uv sync
```

Then use the repo-local commands directly, or install/editable tools only when you explicitly want global entrypoints.

For contributor setups, the cleanest flow is usually:

```bash
uv sync
uv run studyloop install agents
uv run studyloop doctor --fix
```

### Legacy Script Modes

```bash
git clone https://github.com/Hookey-Street-Software/StudyLoop.git studyloop
cd studyloop

# Full bootstrap from a repo checkout
./scripts/install.sh

# Full install without prompts (for Ansible/CI compatibility)
./scripts/install.sh --non-interactive

# Just reinstall/upgrade CLI tools globally
./scripts/install.sh --tools-only

# Just reinstall agent definitions
./scripts/install.sh --agents-only

# Direct typed commands
studyloop install tools
studyloop install agents
studyloop doctor --fix

# Install optional semantic search support
uv pip install agent-session-tools[semantic]
```

For **Ansible playbooks**, clone the repo then run the install script:

```yaml
- name: Install StudyLoop
  hosts: study_machines
  tasks:
    - name: Clone repo
      git:
        repo: https://github.com/Hookey-Street-Software/StudyLoop.git
        dest: ~/code/personal/tools/studyloop

    - name: Run installer
      command: ./scripts/install.sh --non-interactive
      args:
        chdir: ~/code/personal/tools/studyloop
```

## Configuration

### Interactive Setup (recommended)

Run the interactive wizard to configure your study environment:

```bash
studyloop config init
```

This walks you through three core questions:

1. **Knowledge bridging** — Do you want to leverage a topic you already know well (e.g. networking, cooking, music theory) so the mentor can draw analogies to new topics you're studying?
2. **Study material location** — Where are your study sources? The default is `~/Obsidian/Personal/Study`.
3. **Obsidian vault** — Do you want to integrate with an existing Obsidian vault? If so, provide the base path (e.g. `~/Obsidian/Personal`).

The wizard creates or updates `~/.config/studyloop/config.yaml` with your choices. You can re-run it at any time to change settings.

### Manual Configuration

All configuration lives in a single YAML file: `~/.config/studyloop/config.yaml`. This file is shared between `studyloop` and all `session-*` tools — use the same file on every machine.

`STUDYLOOP_CONFIG` can point at a different YAML file for testing, alternate profiles, or machine-specific overrides:

```bash
export STUDYLOOP_CONFIG=~/.config/studyloop/work.yaml
studyloop config show
```

TOML is not currently supported. Use YAML for the production config contract; adding TOML would require a deliberate parser, migration, and compatibility test pass.

Minimal production example:

```yaml
obsidian_base: ~/Obsidian/Personal
session_db: ~/.config/studyloop/sessions.db
state_dir: ~/.local/share/studyloop

content:
  base_path: ~/study-materials
  study_paths:
    - ~/Obsidian/Personal/Study
  inter_episode_gap: 30

topics:
  - name: Python
    slug: python
    obsidian_path: 2-Areas/Study/Python
    tags: [python, programming]

  - name: Data Engineering
    slug: data-engineering
    obsidian_path: ~/Obsidian/Work/Study/Data-Engineering
    tags: [data-engineering, analytics]
```

Path rules:

- Relative `topics[].obsidian_path` values are resolved under `obsidian_base`.
- Absolute `topics[].obsidian_path` values are used as-is.
- Relative `content.study_paths` values are resolved under `obsidian_base`.
- `content.study_paths` augments topic paths for `studyloop content discover` and `studyloop content generate-cards` when you do not pass source directories manually.

To make Codex CLI the default coding assistant for study sessions, set the agent priority explicitly:

```yaml
agents:
  priority: [codex, claude, gemini, opencode, kiro, ollama, lmstudio]
```

### Web PWA (recommended)

The study web app requires no extra dependencies — just run:

```bash
studyloop web
```

This starts a web server on `http://127.0.0.1:8567`. Use `studyloop web --lan` if you want to expose it to other devices on your network.

**Install as PWA (iOS/Android):** Open in Safari → Share → Add to Home Screen. The app then works full-screen like a native app.

Configure flashcard/quiz directories:

```yaml
# ~/.config/studyloop/config.yaml
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

### Remote Study (iPad on the Bus)

Use `--lan` to make the web dashboard and terminal accessible from any device on your network — phone, iPad, second laptop:

```bash
studyloop study "Python Decorators" --energy 7 --lan
# Auto-generates password and saves LAN info to session state:
#   Dashboard: http://192.168.1.42:8567/session
#   Password:  <auto-generated>

# Or set a known password:
studyloop study "Python Decorators" --energy 7 --lan --password mysecret
```

Access the live dashboard and embedded terminal from your iPad at `http://<mac-ip>:8567/session`. Enter any username and the displayed password when prompted. The terminal panel (ttyd iframe) is proxied through the web server on the same origin, so pop-out/return works seamlessly. ttyd must be installed for the terminal panel to work (`brew install ttyd`).

**Password sources** (checked in order):
1. `--password` CLI flag
2. `lan_password` in `~/.config/studyloop/config.yaml`
3. Auto-generated (displayed in terminal output, saved to session state)

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
    state_json: ~/.config/studyloop/state.json
    sessions_db: ~/.config/studyloop/sessions.db

  macbookpro:
    hostname: Andys-MacBook-Pro-Max
    ip_address:
      primary: 192.168.1.21
    user: user
    state_json: ~/.config/studyloop/state.json
    sessions_db: ~/.config/studyloop/sessions.db

  work-macbook:
    hostname: 842f575e3614
    ip_address:
      primary: 192.168.1.20
    user: user
    state_json: ~/.config/studyloop/state.json
    sessions_db: ~/.config/studyloop/sessions.db
```

**One config file on all machines.** Deploy the same `config.yaml` everywhere — each machine auto-detects itself by hostname and treats the rest as remotes.

| Field | Description |
|-------|-------------|
| `hostname` | Must match `socket.gethostname()` on that machine |
| `ip_address.primary` | Wired/ethernet IP (tried first for rsync/SSH) |
| `ip_address.secondary` | Wifi IP (optional fallback if primary unreachable) |
| `user` | SSH username for this machine |
| `state_json` | Path to studyloop state file |
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
| `topics[].tags` | Keywords for session search matching | `[]` |

### Database & Search Settings

```yaml
database:
  path: ~/.config/studyloop/sessions.db
  archive_path: ~/.config/studyloop/sessions_archive.db
  backup_dir: ~/.config/studyloop/backups

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

### Web Terminal Settings

```yaml
# Web terminal (optional — requires ttyd installed)
ttyd_port: 7681      # ttyd listens on this port (default 7681)
web_port: 8567       # web dashboard port (default 8567)
browser: ""          # auto-open browser: chrome, safari, firefox, brave, or empty for system default
lan_password: ""     # persistent LAN password (auto-generated per session if empty)
```

### TTS Voice Settings

```yaml
tts:
  voice: am_michael      # kokoro voice (am_michael, af_heart, bf_emma, etc.)
  speed: 1.5             # 0.5 = slow, 1.0 = normal, 1.5 = fast
  pause: 0.0             # seconds between sentences
  backend: kokoro        # kokoro | qwen3 | macos
```

## Obsidian Vault Setup

studyloop expects your study notes in directories under your Obsidian vault. The structure is flexible — just point each topic's `obsidian_path` at the right directory.

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

studyloop syncs `.md`, `.pdf`, and `.txt` files. It skips:
- Files under 100 bytes
- Obsidian metadata files (`.obsidian/`, index files)
- Common non-content directories (`node_modules`, `__pycache__`)


5. Sync and generate audio:
   ```bash
   studyloop sync python          # Upload changed notes
   studyloop audio python         # Generate audio overview
   ```

## Session Database

The session database stores exported AI conversations from all your tools. It powers spaced repetition, struggle detection, and session search.

### Populate the database

```bash
# Export from all detected sources
session-export

# Export specific sources
session-export --sources claude codex
session-export --sources gemini opencode

# Legacy convenience flags
session-export --claude-only
session-export --kiro-only
session-export --gemini-only
```

Supported sources: `claude`, `codex`, `kiro`, `gemini`, `opencode`, `aider`, `litellm`, `repoprompt`

### Verify it's working

```bash
session-query stats              # Show database statistics
session-query list --since 7d    # List recent sessions
session-query search "python"    # Search across all sessions
```

## Content Pipeline

The content pipeline converts local study sources into review artefacts that support interactive study sessions. The primary path is local quiz/flashcard generation.

### Install content dependencies

```bash
# PDF splitting and local content processing
uv pip install studyloop[content]
```

### Configure study sources

The default study material source is `~/Obsidian/Personal/Study`.

```yaml
# ~/.config/studyloop/config.yaml
content:
  base_path: ~/study-materials
  study_paths:
    - ~/Obsidian/Personal/Study
```

### Typical workflow

```bash
# 1. Preview available sources
studyloop content discover

# 2. Generate local flashcards and quizzes
studyloop content generate-cards ~/Obsidian/Personal/Study/Python --course python

# 3. Review
studyloop web
```

See the [CLI Reference](cli-reference.md) for all available commands.

## Cross-Machine Sync

Both tools support syncing state across machines via SSH.

### Session database sync

```bash
session-sync push macmini        # Push sessions to a named host
session-sync pull macbookpro     # Pull sessions from a named host
session-sync sync work-macbook   # Two-way sync with a host
session-sync endpoints           # List all configured remote hosts
```

Both commands read host definitions from `~/.config/studyloop/config.yaml` (the `hosts` section). See [Host Configuration](#host-configuration) below for the schema. Delta sync transfers only new sessions, not the entire database.

## Scheduling

Set up automatic sync so your notes and sessions stay current.

```bash
# Install all default scheduled jobs
studyloop schedule install

# List active jobs
studyloop schedule list

# Remove all jobs
studyloop schedule remove

# Add a custom job
studyloop schedule add my-sync "studyloop sync --all" "daily 3am"
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

- All CLI tools (`studyloop`, `session-export`, `session-query`, etc.)
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

If your Obsidian vault is on the Windows filesystem, configure the path in `~/.config/studyloop/config.yaml`:

```yaml
obsidian_base: /mnt/c/Users/YourName/Obsidian
```

For better performance, consider keeping the vault inside WSL2's native filesystem (`~/Obsidian/`) and syncing with Obsidian Sync or Git.

## Verify Installation

After installing and configuring, run the health check to make sure everything is working:

```bash
studyloop doctor
```

This checks Python version, installed packages, config validity, databases, optional dependencies, and AI agent definitions. You'll see a colour-coded table:

- Green tick = healthy
- Yellow ! = warning (often auto-fixable)
- Red cross = failure (needs attention)
- Blue i = informational (optional)

If issues are found:

```bash
studyloop doctor --fix         # Apply safe auto-fixes first
studyloop upgrade              # Apply package/database/agent upgrades
studyloop upgrade --dry-run    # Preview changes first
```

For machine-readable output (used by CI pipelines and AI agents):

```bash
studyloop doctor --json
```

### AI-Guided Setup

If you're using an AI coding assistant, the **install-mentor agent** can guide you through the entire setup process conversationally. It automatically detects your environment, installs packages, runs `studyloop doctor`, and fixes issues.

The prompt lives at `agents/shared/install-mentor.md` and works with any AI tool that can run shell commands — Claude Code, Codex CLI, Kiro CLI, Gemini CLI, OpenCode, or Amp.

For example, in Claude Code or Codex:
```
Read agents/shared/install-mentor.md and follow its instructions to set up studyloop
```

## Troubleshooting

### First step: run `studyloop doctor`

Before investigating specific issues, always start with the health check:

```bash
studyloop doctor
```

This will identify most common problems and tell you how to fix them. If auto-fixable issues are found, run `studyloop upgrade` to resolve them.
This will identify most common problems and tell you how to fix them. Start with `studyloop doctor --fix` for safe local repairs, then use `studyloop upgrade` for package-level updates.

### `studyloop: command not found`

The package isn't on your PATH. Either:
- Run via `uv run studyloop` instead
- Or ensure `uv sync` completed successfully and your shell can find uv-installed scripts

### `session-export` finds no sessions

Check that the AI tool's data directory exists:
- Claude Code: `~/.claude/projects/`
- Kiro CLI: `~/Library/Application Support/kiro-cli/data.sqlite3` (macOS)
- Gemini CLI: `~/.gemini/tmp/`
- Codex CLI: exported from Codex transcript storage if present on this machine
- OpenCode: `~/.local/share/opencode/storage/`
- Aider: `.aider.chat.history.md` files in project directories

### `studyloop review` shows nothing

The session database may be empty. Run `session-export` first to populate it, then `studyloop review` can check your study history.

### Config file not loading

studyloop looks for config at `~/.config/studyloop/config.yaml`. Override with:
```bash
export STUDYLOOP_CONFIG=/path/to/your/config.yaml
```

### Database too large

```bash
session-maint vacuum             # Reclaim space
session-query stats              # Check current size
session-maint archive            # Archive old sessions
```
