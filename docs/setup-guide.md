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
- [Scheduling Status](#scheduling-status)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- **Python 3.12+** (both studyloop and agent-session-tools require 3.12+)
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **tmux 3.1+** — required for `studyloop study` split-pane sessions (`brew install tmux` on macOS, `apt install tmux` on Linux)
- **Optional**: Obsidian or another Markdown folder for study notes. Notes are
  context, not a requirement; Study Session, review, and session history work
  without a notes folder.
- **Optional**: `sentence-transformers` for semantic search
- **Optional**: a Kokoro TTS server for voice output — [VoiceMode](https://github.com/mbailey/voicemode), [OpenVox](https://openvoxai.com/), or `docker/kokoro/docker-compose.yml`. Used by both `study-speak` and the web app. Without one, the web app uses your OS voices. See [Voice Output](voice-output.md#kokoro-server-backends)

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

Install from a source checkout. There is no current PyPI or Homebrew release, so
source install is the supported path, and `scripts/install.sh` is the
primary installer because it installs both `studyloop` and the
`agent-session-tools` console scripts used by the session database workflow.

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop
./scripts/install.sh
studyloop self-test
studyloop setup
studyloop doctor --fix
```

`studyloop self-test` is the fastest post-install confidence check. It verifies
that the CLI imports, config is readable if present, the sessions database path
is usable, and the web module imports. A warning exit (`1`) is acceptable before
first setup if `config.yaml` does not exist yet.

> If `studyloop doctor` reports `agent-session-tools not installed`, run
> `studyloop install tools` — it reinstalls the workspace tools with
> agent-session-tools wired into the studyloop tool venv.

### What the installer does

`./scripts/install.sh` will:
1. Verify Python 3.12+ is installed
2. Install `uv` if not already available
3. Run `uv sync`
4. Delegate to `studyloop install tools` — installs `studyloop[all]` (web UI,
   content generation, Bedrock, MCP, NotebookLM, TUI) and
   `agent-session-tools[all]` (TTS, semantic session search), and always adds
   `agent-session-tools` into the `studyloop` tool venv too — that part is not
   gated behind any extra, so it happens on every source install
5. Delegate to `studyloop install agents`
6. Run lightweight installed CLI smoke checks

The typed CLI commands are available when you need to refresh one side of the
install:

```bash
studyloop install tools
studyloop install agents
studyloop self-test
studyloop doctor --fix
```

### Advanced Manual Tool Install

You can install the `studyloop` tool venv manually, but this only exposes the
`studyloop` entry point. Dependency console scripts from `agent-session-tools`
such as `session-export`, `session-query`, and `session-sync` may not appear on
`PATH` unless `agent-session-tools` is installed as its own tool.

```bash
uv sync --all-packages
uv tool install --editable './packages/studyloop[all]' \
  --with-editable ./packages/agent-session-tools
uv tool install --editable './packages/agent-session-tools[all]'
```

Prefer `./scripts/install.sh` or `studyloop install tools` for normal source
checkout installs because they keep the two tool venvs wired together.

### Optional Extras

These are `studyloop`'s own extras — every one of them installs from a bare
built wheel, with no workspace checkout required. There is no `sessions`
extra: `agent-session-tools` (the session DB / cross-harness knowledge base)
is not published anywhere, so it cannot be an installable extra of a wheel.
It is instead a hard dependency of the source-install path described above —
`studyloop install tools` and `./scripts/install.sh` always add it,
unconditionally, alongside whichever of these extras you choose.

| Extra | Use |
|-------|-----|
| `content` | PDF splitting and local content processing |
| `bedrock` | AWS Bedrock generator support |
| `notebooklm` | NotebookLM API workflow |
| `tui` | terminal UI dependencies |
| `web` | FastAPI web UI |
| `mcp` | MCP server integration |
| `all` | `content`, `bedrock`, `notebooklm`, `tui`, `web`, and `mcp` together |

### Developer Install

If you are contributing to the repo or running from source, prefer `uv sync` in the checkout:

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop
uv sync
```

Then use the repo-local commands directly, or install/editable tools only when you explicitly want global entrypoints.

For contributor setups, the cleanest flow is usually:

```bash
uv sync
uv run studyloop install agents
uv run studyloop self-test
uv run studyloop doctor --fix
```

### Legacy Script Modes

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop

# Full bootstrap from a repo checkout
./scripts/install.sh

# Full install without prompts (for Ansible/CI compatibility)
./scripts/install.sh --non-interactive

# Just reinstall/upgrade CLI tools globally
./scripts/install.sh --tools-only

# Just reinstall agent definitions
./scripts/install.sh --agents-only

# Skip installed CLI smoke checks
./scripts/install.sh --no-smoke

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
        repo: https://github.com/NetDevAutomate/StudyLoop.git
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
studyloop setup
```

Two questions on the happy path, three at most, and every one of them accepts
Enter (blank is a valid, first-class answer, not a degraded one):

1. **Where do your study notes live?** A folder of `.md`/`.txt` files;
   sub-folders become topics. Leave it blank if you have none yet — your
   study sessions become the source instead, which the wizard treats as the
   better source anyway, not a fallback.
2. **Focus on up to 3 topics to start?** Asked only if question 1 found a
   notes folder with sub-folders to suggest — ranked by note count, offered
   as a comma-separated default you can edit or accept as-is.
3. **Which AI assistant should run your study sessions?** Asked only when
   more than one supported harness is detected on `PATH`. Exactly one found →
   used automatically, no prompt. None found → skipped; studyloop works
   standalone and you can install one later.

The wizard creates or updates `~/.config/studyloop/config.yaml` with your
answers, preserving everything else in the file untouched. You can re-run it
at any time — a second run defaults every prompt to what you answered last
time, so accepting every default changes nothing.

`studyloop config init` is a separate, older wizard with its own three
questions (knowledge bridging, Google NotebookLM integration, and an
Obsidian vault path) and its own defaults. `studyloop setup` is the
recommended first-run path; `config init` remains for the bridging/
NotebookLM/Obsidian options it alone asks about.

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

# Opt-in: write one Markdown note per AI session into the vault.
# Coexists with the flat `obsidian_base` key above (which is for study sources).
obsidian:
  export_enabled: false          # off by default; --obsidian overrides per-run
  vault_path: ~/Obsidian/Personal # defaults to obsidian_base when omitted
  memory_dir: AgentMemory         # notes written under <vault>/AgentMemory/
  moc_dir: AgentMemory/MOC        # per-project index notes
  backlinks: true                 # inject [[wikilink]]s to matching topic notes
  granularity: both               # both | session (per-session notes ± MOC index)

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
  priority: [codex, kiro, claude, opencode, pi]
```

### Web PWA (recommended)

The study web app requires no extra dependencies — just run:

```bash
studyloop web
```

This starts a web server on `http://127.0.0.1:8567`. Use `studyloop web --lan` if you want to expose it to other devices on your network.

**Add to home screen (iPadOS):** Open in Safari → Share → Add to Home Screen. `manifest.json` sets `display: standalone`, so it launches without browser chrome.

> **The web app does not work offline.** There is no service worker anywhere in
> the app, so no page and no asset is cached. Every launch — including from a
> home-screen icon — needs the `studyloop web` server reachable on the network.

Configure flashcard/quiz directories:

```yaml
# ~/.config/studyloop/config.yaml
review:
  directories:
    - ~/Desktop/ZTM-DE/downloads
    - ~/Desktop/Python/downloads
```

**Voice output** is synthesised by a Kokoro server you run, not in the browser. The page posts text to StudyLoop's own authenticated `/api/tts/speak`, which proxies it to whatever `tts.openvox_base_url` names; the device just plays the audio. That is why a tablet gets the same voice as the desktop. With no server reachable, the app falls back to your operating system's own voices — no install, lower quality — and failing that, to silence. Voice is off until you turn it on in the header.

Two ways to hear a card:
- **Read once** — tap the speaker icon on a card, or press `T`. Reads the current content once.
- **Announcements** — the header speaker toggle enables the app's own spoken announcements (Pomodoro transitions and confirmations) and reveals the voice selector. It does **not** read cards to you automatically; there is no auto-voice mode and `V` is not bound.
- **Stop** — a stop button appears while audio plays; it interrupts mid-utterance.

See [Voice Output § Web App Voice](voice-output.md#web-app-voice-server-side-kokoro) for the full picture, including which server to run and the LAN-exposure trade-off one of them carries.

**Accessibility:** The `Aa` button toggles [OpenDyslexic](https://opendyslexic.org) font. The sun icon toggles light/dark theme. Both are persisted across sessions.

### Remote Study (iPad on the Bus)

Use `--lan` to make the web dashboard and terminal accessible from any tablet or laptop on your network — iPad, Android tablet, second laptop:

```bash
studyloop study "Python Decorators" --energy 7 --lan
# Auto-generates password and saves LAN info to session state:
#   Local:    http://127.0.0.1:8567/session
#   LAN:      http://192.168.1.42:8567/session
#   Username: study
#   Password: <auto-generated>

# Or set a known password:
studyloop study "Python Decorators" --energy 7 --lan --password '<strong-unique-password>'
```

Access the live dashboard from your iPad at `http://<mac-ip>:8567/session`. Use username `study` and the displayed password when prompted. The terminal panel runs in the page itself — xterm.js over a same-origin WebSocket — so nothing extra needs installing on either machine.

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
ssh-copy-id <user>@<remote-host>

# 3. Verify passwordless login works
ssh <user>@<remote-host> "echo ok"  # should print "ok" with no password prompt
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
  desktop:
    hostname: study-desktop           # must match socket.gethostname()
    ip_address:
      primary: 192.168.1.20           # wired / ethernet
      secondary: 192.168.1.21         # wifi (optional fallback)
    user: your-user
    state_json: ~/.config/studyloop/state.json
    sessions_db: ~/.config/studyloop/sessions.db

  laptop:
    hostname: study-laptop
    ip_address:
      primary: 192.168.1.30
    user: your-user
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
# Web dashboard
web_port: 8567       # web dashboard port (default 8567)
browser: ""          # auto-open browser: chrome, safari, firefox, brave, or empty for system default
lan_password: ""     # persistent LAN password (auto-generated per session if empty)
```

> **`ttyd_port` is removed.** ttyd has been fully retired: nothing installs,
> starts, or reads a ttyd process any more, and the key is no longer
> recognised by `load_settings()`. The browser terminal is xterm.js over a
> same-origin WebSocket and never had a ttyd surface. If your `config.yaml`
> still has a `ttyd_port` line from before the retirement, it does nothing —
> `studyloop doctor` names it as an unknown/retired key so you know to
> delete it.

### TTS Voice Settings

```yaml
tts:
  backend: kokoro        # kokoro | openvox | qwen3 | macos
  voice: am_michael      # kokoro voice (am_michael, af_heart, bf_emma, etc.)
  speed: 1.5             # 0.5 = slow, 1.0 = normal, 1.5 = fast
  pause: 0.0             # seconds between sentences
  macos_voice: Samantha
```

Kokoro server profile — used by `study-speak` **and** by the web app:

```yaml
tts:
  backend: openvox
  openvox_base_url: http://127.0.0.1:8000/v1   # or :8880/v1 for VoiceMode / the container
  openvox_model: kokoro
  openvox_voice: bf_emma
  openvox_language: en
  openvox_response_format: wav
  openvox_timeout: 30

  # Kokoro/Qwen/macOS fallback settings still apply.
  voice: am_michael      # kokoro voice (am_michael, af_heart, bf_emma, etc.)
  speed: 1.5             # 0.5 = slow, 1.0 = normal, 1.5 = fast
  pause: 0.0             # seconds between sentences
  macos_voice: Samantha
```

The `openvox_*` keys are named that way for historical reasons and accept **any** OpenAI-compatible Kokoro endpoint — OpenVox, VoiceMode, or the container. Only the URL changes between them. To repoint for one command without editing the file:

```bash
STUDYLOOP_TTS_BASE_URL=http://127.0.0.1:8880/v1 \
  STUDYLOOP_TTS_VOICE=bf_lily studyloop recap today --speak
```

`STUDYLOOP_TTS_MODEL` works the same way. All three override the config **file** only.

Test the server voice:

```bash
study-speak "StudyLoop is speaking through a Kokoro server." -b openvox
studyloop doctor --category voice
```

If the server is not running or is busy, StudyLoop falls back to the existing local voice path so the study session can continue.

## Obsidian Vault Setup

studyloop expects your study notes in directories under your Obsidian vault. The structure is flexible — just point each topic's `obsidian_path` at the right directory.

Example vault layout:

```
~/Obsidian/
├── Personal/
│   ├── 2-Areas/
│   │   └── Study/
│   │       ├── Courses/
│   │       │   ├── ArjanCodes/       ← Python topic
│   │       │   └── DataCamp/         ← SQL topic
│   │       ├── Mentoring/
│   │       │   ├── Python/           ← AI-generated teaching moments
│   │       │   ├── Databases/
│   │       │   └── Data-Engineering/
│   │       └── Study-Plans/
│   └── AgentMemory/                  ← created by `session-export --obsidian`
│       ├── 2026-06-01-claude-code-myproject-1a2b3c4d.md
│       └── MOC/
│           ├── _index.md             ← project index
│           └── myproject.md          ← per-project session list
```

studyloop syncs `.md`, `.pdf`, and `.txt` files. It skips:
- Files under 100 bytes
- Obsidian metadata files (`.obsidian/`, index files)
- Common non-content directories (`node_modules`, `__pycache__`)

### Obsidian session-memory export

`session-export --obsidian` writes one Markdown note per AI coding session into
`<vault>/AgentMemory/`, in addition to the SQLite export. This is **opt-in** and
shared across the supported harnesses — Kiro CLI, Codex, Claude Code, OpenCode,
and pi all flow into the same folder, keeping curated study notes untouched.

Each note carries Dataview-ready frontmatter so vault dashboards pick them up:

```yaml
---
type: agent-memory
id: 2026-06-01-claude-code-myproject-1a2b3c4d
created: 2026-06-01
source_tool: claude_code
source_project: myproject
session_id: <full id>
tags: [agent-memory, claude_code]
date: 2026-06-01
content_hash: 39fa1138   # drives idempotent re-export
---
```

Enable it three ways:

1. **Per-run:** `session-export --obsidian` (or `--obsidian-backfill` for all history).
2. **Config:** set `obsidian.export_enabled: true` (see the `obsidian:` block under
   [Manual Configuration](#manual-configuration)).
3. **Setup wizard:** `studyloop setup` asks whether to enable export at the Obsidian step.

`studyloop doctor` validates the vault path, checks for the `.obsidian/` marker, and
(when export is enabled) confirms the memory directory is writable.


Legacy NotebookLM sync/audio commands are not part of the current session-memory
export path. Use `session-export --obsidian` for Obsidian memory notes and the
local content pipeline for flashcards and quizzes.

## Session Database

The session database stores exported AI conversations from all your tools. It powers spaced repetition, struggle detection, and session search.

### Populate the database

```bash
# Export from all detected sources
session-export

# Export specific sources
session-export --sources claude --sources codex
session-export --sources opencode --sources pi

# One-harness convenience flags
session-export --claude-only
session-export --kiro-only
session-export --codex-only
session-export --opencode-only
session-export --pi-only

# Also write Obsidian session-memory notes (see Obsidian Vault Setup above)
session-export --obsidian
session-export --obsidian --obsidian-backfill   # one-time: all history
```

Supported `--sources` values: `kiro`, `codex`, `claude`, `opencode`, and `pi`.
Repeat `--sources` when selecting more than one.

### Verify it's working

```bash
session-query stats-cmd            # Show database statistics
session-query list --since last-7-days  # List recent sessions
session-query search-cmd "python"  # Search across all sessions
```

## Content Pipeline

The content pipeline converts local study sources into review artefacts that support interactive study sessions. The primary path is local quiz, flashcard, and hands-on practice generation.

### Install content dependencies

```bash
# Repo-local PDF splitting and local content processing
uv sync --all-packages --extra content

# Or refresh the global CLI with the documented feature set
studyloop install tools
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

# 2. Generate local flashcards, quizzes, and hands-on practice
studyloop content generate-cards ~/Obsidian/Personal/Study/Python --course python
studyloop content generate-practice ~/Obsidian/Personal/Study/Python --course python

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

## Scheduling Status

Scheduled sync is not currently shipped. Use system cron/launchd manually if
needed, or track scheduling in the roadmap.

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
studyloop doctor --fix         # Apply safe local repairs first
studyloop upgrade --dry-run    # Preview package/database/agent upgrades
studyloop upgrade              # Apply package/database/agent upgrades
```

For machine-readable output (used by CI pipelines and AI agents):

```bash
studyloop doctor --json
```

### AI-Guided Setup

If you're using an AI coding assistant, the **install-mentor agent** can guide you through the entire setup process conversationally. It automatically detects your environment, installs packages, runs `studyloop doctor`, and fixes issues.

The prompt lives at `agents/shared/install-mentor.md` and is intended for the
supported harnesses: Kiro CLI, Codex, Claude Code, OpenCode, and pi.

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

This will identify most common problems and tell you how to fix them. Run
`studyloop doctor --fix` first for safe local repairs. Use
`studyloop upgrade --dry-run` before package/database/agent upgrades.

### `studyloop: command not found`

The package isn't on your PATH. Either:
- Run via `uv run studyloop` instead
- Or ensure `uv sync` completed successfully and your shell can find uv-installed scripts

### `session-export` finds no sessions

Check that the AI tool's data directory exists:
- Claude Code: `~/.claude/projects/`
- Kiro CLI: `~/Library/Application Support/kiro-cli/data.sqlite3` (macOS)
- Codex CLI: exported from Codex transcript storage if present on this machine
- OpenCode: `~/.local/share/opencode/storage/`
- pi: `~/.pi/agent/sessions/`

For pi or OpenCode, run `studyloop doctor --category agents` first, then use the
general [Troubleshooting](troubleshooting.md) guide with the harness's own CLI
output.

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
session-query stats-cmd          # Check current size
session-maint archive            # Archive old sessions
```
