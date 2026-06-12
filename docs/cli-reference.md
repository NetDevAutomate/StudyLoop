# CLI Reference

## studyloop

Study pipeline management — content, review, sessions, and tracking.

```bash
# Study sessions (tmux + AI agent + Textual sidebar)
studyloop study "topic" --energy 7        # Full tmux environment in one command
studyloop study "topic" --mode co-study   # Co-study mode (user drives)
studyloop study --resume                  # Reattach to existing session
studyloop study --end                     # End session cleanly
studyloop study "topic" --web             # Also start web dashboard
studyloop park QUESTION [-t TOPIC]        # Park tangential topic

# Low-level session commands (used internally by study)
studyloop session start -t TOPIC -e 7    # Start session (DB + IPC files)
studyloop session status                  # Timer, topics, parking lot
studyloop session end [-n NOTES]          # End session, show summary
studyloop session effectiveness           # Persona effectiveness metrics

# Content pipeline
studyloop content split SOURCE            # Split PDF by chapters
studyloop content generate-cards DIR --course COURSE # Local quiz/flashcard JSON
studyloop content generate-practice DIR --course COURSE # Local hands-on practice JSON
studyloop content discover                # Preview configured study sources
studyloop content ingest --dry-run        # Plan source ingest
studyloop content import-review DIR --course COURSE  # Import existing JSON artefacts
studyloop content process SOURCE          # Legacy optional NotebookLM upload path
studyloop content from-obsidian DIR       # Legacy optional NotebookLM path

# Sync & topics
studyloop sync [TOPIC] --all --dry-run    # Legacy optional notebook sync
studyloop status [TOPIC]                  # Show sync status
studyloop topics                          # List configured topics
studyloop audio TOPIC                     # Legacy optional audio overview
studyloop dedup [TOPIC] --all --dry-run   # Remove duplicate notebook sources

# Review
studyloop now                            # Recommend one next study action
studyloop now --energy low --time 15     # Smaller, lower-switching recommendation
studyloop now --modality hands-on --interleave adaptive
studyloop chat-note NOTE.md --mode recall      # Build a Socratic context pack
studyloop chat-note NOTE.md --mode diagram --voice
studyloop practice verify TASKS.json --task 1 --notes "what passed"
studyloop practice verify TASKS.json --task 1 --run-command --workdir . --timeout 120
studyloop recap today                    # One win, repair target, due item, next action
studyloop recap today --speak            # Speak through study-speak
studyloop recap today --audio-file recap.wav
studyloop mastery graph --topic python   # Mermaid concept graph
studyloop mastery graph --topic python --format json
studyloop mastery weak-links --topic python
studyloop review                          # Check spaced repetition due dates
studyloop review --interleave adaptive --energy medium
studyloop progress                        # Summarize local course progress
studyloop progress --course python        # Summarize one course
studyloop progress --json                 # Machine-readable progress summary
studyloop progress CONCEPT -t TOPIC -c confident # Record concept confidence
studyloop teachback CONCEPT -t TOPIC --score 3,3,4,3,2 --type structured
studyloop teachback-history CONCEPT [-t TOPIC]
studyloop struggles --days 30             # Find recurring struggle topics
studyloop wins --days 30                  # Concepts mastered / confident (AuDHD wins)
studyloop resume                          # Where you left off (last session summary)
studyloop streaks                         # Study streak and consistency stats
studyloop backlog list                    # Pending study backlog (parked/struggled/manual)
studyloop bridge list                     # Network→DE (or cross-domain) knowledge bridges
studyloop clean --dry-run                 # Preview orphan tmux/session cleanup
studyloop extract-struggles --incremental # Session DB → study_progress (stub or --llm)

# Configuration & health
studyloop setup                           # Interactive setup wizard
studyloop install tools                   # Install global CLI entrypoints from repo
studyloop install agents                  # Install agent definitions for detected tools
studyloop config init                     # Advanced/legacy config initializer
studyloop config show                     # Display current configuration
studyloop self-test                       # Lightweight post-install smoke check
studyloop doctor                          # Full health check
studyloop update                          # Check for available updates
studyloop upgrade                         # Apply all available updates

# Backup & restore
studyloop backup [--tag NAME]             # Snapshot DB + config to backups/
studyloop restore                         # List available backups
studyloop restore BACKUP --confirm        # Restore from backup (safety backup first)

# Web
studyloop web [--port PORT] [--lan] [--password SECRET] # Launch study web app (PWA)
```

### Study Sessions

The primary entry point is `studyloop study`, which creates a complete tmux-based study environment:

```bash
studyloop study "Python Decorators" --energy 7          # Socratic mentor session
studyloop study "Spark Internals" --mode co-study       # User-driven co-study
studyloop study "topic" --timer pomodoro                # Override default timer
studyloop study "topic" --agent claude --web            # Explicit agent + web dashboard
studyloop study "topic" --agent codex                  # Explicit Codex CLI session
studyloop study "topic" --lan                           # LAN access with password auth (implies --web)
studyloop study "topic" --lan --password SECRET         # Explicit password for LAN auth
studyloop study "topic" --agent ollama                  # Local LLM via Ollama + LiteLLM
studyloop study "topic" --agent lmstudio                # Local LLM via LM Studio
studyloop study --resume                                # Resume conversation (-r)
studyloop study --end                                   # End session cleanly
studyloop park "How does asyncio compare?"              # Park mid-session
```

Run `studyloop study` without a topic to open the textual picker for body double, topic directory, course vendor, or course.

**What `studyloop study` creates:**
- tmux session with agent pane (left) + Textual sidebar (right)
- AI agent launched with mode-specific persona (clean pane, no visible command)
- Persistent session directory at `~/.config/studyloop/sessions/{name}/` — preserves AI conversation history (`.claude/`, `.kiro/`, etc.)
- Sidebar shows timer, activity feed, counters (keyboard: `p` pause, `r` reset, `Q` end session)
- IPC files for dashboard viewports
- Optional web dashboard at `/session` via `--web`
- `--web` auto-opens a browser to the dashboard on startup
- `--lan` exposes the dashboard on your LAN with HTTP Basic Auth, prints usable local/LAN URLs, username, and password (implies `--web`). Password is auto-generated if not set via `--password` or `lan_password` in config
- `--password SECRET` sets the LAN authentication password (used with `--lan`)

**Session lifecycle:**
- **Start:** `studyloop study "topic"` — creates tmux session, agent, sidebar
- **Exit:** quit Claude normally (`/exit`, Ctrl+C) — auto-cleans up tmux, IPC files, switches back to previous session. Session directory preserved.
- **Resume:** `studyloop study --resume` — if tmux alive, reattaches. If ended, rebuilds tmux and passes `-r` to the agent to continue the conversation from history.
- **End explicitly:** `studyloop study --end` or sidebar `Q` — same cleanup as quitting Claude

**Modes:**

| Mode | Flag | Timer default | Agent role |
|------|------|---------------|------------|
| Study | (default) | Elapsed | Socratic mentor drives |
| Co-study | `--mode co-study` | Pomodoro | User drives, agent available |

**Low-level session commands** (used internally by `studyloop study`):

```bash
studyloop session start -t "Decorators" -e 7    # Start session record
studyloop session status                         # Show current state
studyloop session end -n "Got through closures"  # End with notes
studyloop session effectiveness                  # Win rate per persona version
studyloop session effectiveness -p abc123...     # Filter by persona hash
```

### Health & Updates

```bash
studyloop self-test                       # Lightweight post-install smoke check
studyloop self-test --json                # JSON output for scripts/agents
studyloop self-test --quiet               # One-line summary
studyloop doctor                          # Full health check (Rich table)
studyloop doctor --json                   # JSON output (for AI agents and CI)
studyloop doctor --quiet                  # One-line summary
studyloop doctor --category core          # Check specific category only
studyloop doctor --category voice         # Check Kokoro, afplay, and optional OpenVox
studyloop doctor --fix                    # Apply safe automatic fixes
studyloop update --json                   # Machine-readable update info
studyloop upgrade --dry-run               # Preview what would change
studyloop upgrade --component packages    # Upgrade only packages
studyloop upgrade --component database    # Run DB migrations only
studyloop upgrade --component agents      # Update agent definitions only
```

Use `studyloop self-test` immediately after install when you only need to
confirm the CLI imports, config can be read, the sessions database path is
usable, and the web module imports. It is deliberately lightweight: it does
not run `doctor --fix`, start web servers, contact external services, or write
agent/harness files.

**Exit codes for `studyloop self-test`:**

| Code | Meaning |
|------|---------|
| `0` | All lightweight checks pass |
| `1` | One or more warnings, with no failures |
| `2` | One or more checks failed |

**Exit codes for `studyloop doctor`:**

| Code | Meaning |
|------|---------|
| `0` | All checks pass — installation is healthy |
| `1` | Warnings or failures that can be fixed — run `studyloop doctor --fix` |
| `2` | Core failure — a fundamental component is broken (e.g. wrong Python version) |

**Check categories:** `core` (Python, packages, config), `database` (review DB, sessions DB), `config` (Obsidian vault + `.obsidian/` marker, Obsidian export config, review dirs, pandoc), `deps` (optional packages), `agents` (AI tool definitions), `voice` (Kokoro model files, `afplay`, and OpenVox reachability when configured), `harness` (session-export wiring), `updates` (source-install/version metadata).

### Spaced Repetition Intervals

Review schedule: **1 → 3 → 7 → 14 → 30 days**

`studyloop review` shows what's due based on active learning evidence in `study_progress`, such as recorded concept progress and teach-back scores.

Use `studyloop review --interleave adaptive --energy low|medium|high` when you want review to show the active interleaving mix. Low energy keeps the mix close to current or due repair; medium and high energy allow more transfer and weak-link work.

### Active learning decision loop

`studyloop now` is the shared recommendation engine for the CLI and web API (`GET /api/now`). It returns one primary recommendation and up to two alternates. Each recommendation includes the concept, topic or course, reason, action type, estimated minutes, source, score, and the command to record evidence when done.

```bash
studyloop now
studyloop now --energy low --time 15
studyloop now --modality hands-on --interleave adaptive
studyloop now --json
studyloop now --speak
```

Default ranking is due review first, then struggling or low teach-back score, then active-course continuity, then modality match. Low energy suppresses hard context switching.

`studyloop chat-note` turns one markdown/text note into a compact Socratic context pack. V1 prints or speaks the mentor prompt; it does not run a separate chat backend.

```bash
studyloop chat-note ~/Obsidian/Personal/Study/Python/decorators.md
studyloop chat-note NOTE.md --mode diagram
studyloop chat-note NOTE.md --mode trace --json
```

Modes are `recall`, `diagram`, `trace`, `teachback`, and `repair`. The command validates that the note is inside configured vault/content roots, chunks by headings and code blocks, and ends with a suggested `studyloop progress` or `studyloop teachback` command.

`studyloop practice verify` records an attempt against a generated practice deck. Command verification only runs when `--run-command` is explicit; non-command tasks use notes plus expected-artifact checks as a rubric. Newer generated decks can also carry rubric items, evidence prompts, setup commands, and per-task command timeouts.

```bash
studyloop practice verify course-practice.json --task 1 --notes "diagram matched"
studyloop practice verify course-practice.json --task 2 --run-command --workdir . --timeout 120
```

`studyloop recap today` compresses the day into one win, one repair target, one due item, and one next action. `--speak` calls `study-speak`, so Kokoro/OpenVox/macOS backend configuration is inherited. `--audio-file` saves the same recap as a local audio file, preferring OpenVox when configured and falling back to macOS `say`.

```bash
studyloop recap today
studyloop recap today --json
studyloop recap today --speak
studyloop recap today --audio-file ~/Desktop/studyloop-recap.wav
```

`studyloop mastery` exposes concept dependencies and blockers. The Web UI's
**Mastery** tab uses the same data through `GET /api/mastery/graph` and
`GET /api/mastery/weak-links`; those web endpoints accept `limit` so broad
topics stay fast to render in Mermaid.

```bash
studyloop mastery graph --topic python
studyloop mastery graph --topic python --format json
studyloop mastery weak-links --topic python
```

The graph seeds lightweight concept edges from headings, tags, backlinks, existing concept relations, and knowledge bridges, then renders Mermaid by default.

### Progress

`studyloop progress` has two modes:

- With no concept argument, it summarizes local course progress from `content.base_path` and the review database.
- With a concept argument, it records confidence for a study concept.

```bash
studyloop progress                                  # Course summary table
studyloop progress --course python                  # One course only
studyloop progress --json                           # JSON for scripts/agents
studyloop progress "list comprehensions" \
  --topic python \
  --confidence confident                           # Record concept confidence
```

The summary includes local source count, unique review cards, due cards, mastered cards, review sessions, and review accuracy. Course filtering uses the course slug, such as `python` or `data-engineering`.

### Wins, resume, and streaks (AuDHD progress)

These commands surface progress without opening the web UI. Agents often run them at session start (see [Session Protocol](session-protocol.md)).

```bash
studyloop wins                    # Progress overview + recent mastered/confident concepts
studyloop wins --days 14          # Wins in the last N days (default 30)

studyloop resume                  # Last session source, topics, in-progress concepts, streak

studyloop streaks                 # Current/longest streak, weekly sessions, energy patterns
```

`studyloop resume` is **not** the same as `studyloop study --resume`: the latter reattaches a tmux/agent session; `studyloop resume` prints a text summary from session history.

### Struggles and extraction

```bash
studyloop struggles --days 30     # Topics mentioned in 3+ sessions (table)

studyloop extract-struggles --incremental              # Most recent kiro_cli session → study_progress
studyloop extract-struggles --incremental --session-id ID
studyloop extract-struggles --full                     # Backfill all kiro_cli sessions
studyloop extract-struggles --dry-run                  # Show what would be written
studyloop extract-struggles --llm                      # LLM extractor (requires deps; default is stub)
```

Used by session-end hooks and reconciliation; default backend is a **stub** (no API cost). `--llm` enables the real extractor when configured.

### Study backlog

Cross-session backlog over parked topics, detected struggles, and manual entries (`parked_topics` store). Distinct from `studyloop topics`, which lists **configured course topics** in `config.yaml`.

```bash
studyloop backlog list
studyloop backlog list --tech Python --source struggled
studyloop backlog list --all                         # Include resolved/dismissed

studyloop backlog add "Python decorators" --tech Python --note "After Ch. 4"
studyloop backlog resolve 42

studyloop backlog suggest
studyloop backlog suggest --limit 5 --topic "Python Patterns"
```

Mid-session parking uses `studyloop park` (writes to the same backlog with source `parked`).

### Knowledge bridges

Record analogies between domains (e.g. networking → data engineering). Stored in the session/review database.

```bash
studyloop bridge add "ECMP" -s networking "Spark partitions" -t python -m "Both distribute load"
studyloop bridge list
studyloop bridge list --source-domain networking --target-domain python
```

### Session cleanup

```bash
studyloop clean --dry-run         # Preview zombie tmux sessions, orphan dirs, stale state
studyloop clean                   # Apply cleanup (respects lock; safe with --resume)
```

Also runs automatically before `studyloop study` when zombies are detected.

### Web PWA

`studyloop web` launches a progressive web app for flashcard and quiz review. By default it binds to `127.0.0.1`; use `--lan` to expose it on your network with HTTP Basic Auth.

```bash
studyloop web                    # Serve on 127.0.0.1:8567
studyloop web --port 9000        # Custom port
studyloop web --lan              # LAN access with auth
studyloop web --lan --password SECRET
```

| Key | Action | When |
|-----|--------|------|
| `Space`/`Enter` | Flip card | Flashcard, before reveal |
| `Y` | I knew it | Flashcard, after reveal |
| `N` | Didn't know | Flashcard, after reveal |
| `A`-`D` | Select quiz option | Quiz mode |
| `S` | Skip card | During review |
| `T` | Read aloud (once) | During review |
| `V` | Toggle auto-voice | During review |
| `R` | Retry wrong answers | After session |
| `Esc` | Back to home | Anywhere |

**Features:** Source/chapter filter, card count limiter (10/20/50/100/All), due cards badge, session history, 90-day study heatmap, Pomodoro timer (25min/5min), OpenDyslexic font toggle, dark/light theme, PWA installable.

**Live session dashboard** (`/session`): Real-time SSE activity feed, energy-adaptive timer, topic counters, and a **terminal panel** — an embedded ttyd iframe showing the tmux session live via same-origin proxy (`/terminal/`). The panel is draggable (stacked or side-by-side), has a layout toggle and panel-swap buttons, and can be popped out to a separate window (pop-out auto-closes when returning inline). ttyd is optional (`brew install ttyd`) but required for the terminal panel.

**Voice:** In-browser neural TTS (Kokoro on WebGPU/WASM — no remote API; Web Speech API fallback). Two modes:
- **Read once** — speaker icon on card or `T` key
- **Auto-voice** — header toggle or `V` key (reads everything automatically)
- **Stop** — header stop button interrupts playback mid-utterance

**Web + terminal config** (`~/.config/studyloop/config.yaml`):

```yaml
web_port: 8567       # web dashboard port (default 8567)
ttyd_port: 7681      # ttyd web terminal port (default 7681)
browser: ""          # auto-open browser: chrome, safari, firefox, brave, or empty for system default
lan_password: ""     # persistent password for --lan mode (auto-generated if empty)
```

**Agent priority config** (`~/.config/studyloop/config.yaml`):

```yaml
agents:
  priority: [codex, claude, gemini, opencode, kiro, ollama, lmstudio]
```

---

## agent-session-tools

AI session export, search, and cross-machine sync.

```bash
session-export [--sources SOURCE ...]    # Export AI sessions to SQLite
session-export [--obsidian] [--obsidian-vault PATH] [--obsidian-backfill] [--obsidian-dry-run]
session-query search QUERY               # Full-text search across sessions
session-query list --since 7d            # List recent sessions
session-query show SESSION_ID            # Show session details
session-query context SESSION_ID         # Generate context for resuming
session-query stats                      # Database statistics
session-sync push|pull|sync REMOTE       # Sync database across machines
session-maint vacuum|reindex|schema|archive  # Database maintenance
study-speak "text" [-b openvox|kokoro|qwen3|macos] [-v VOICE] [-s SPEED]
                                          # Speak text aloud using local TTS
```

### Supported Sources

| Source | Tool |
|--------|------|
| `claude` | Claude Code |
| `codex` | OpenAI Codex CLI |
| `kiro` | Kiro CLI |
| `gemini` | Gemini CLI |
| `aider` | Aider |
| `opencode` | OpenCode |
| `litellm` | LiteLLM |
| `bedrock` | Bedrock proxy |
| `repoprompt` | RepoPrompt |
| `pi` | pi coding agent (`@earendil-works/pi-coding-agent`) |
| `omp` | oh-my-pi (`@oh-my-pi/pi-coding-agent`) |

### Results & Incremental Behaviour

By default `session-export` runs **incrementally**: it only imports sessions
that are new or whose source file changed since the last export. The summary
reports four outcomes:

| Outcome | Meaning |
|---------|---------|
| `added` | New session imported for the first time |
| `updated` | Existing session re-imported because its source changed |
| `skipped` | Already up-to-date since last export (unchanged) — **not** re-read |
| `empty` | No extractable messages (header-only, content-less, or only tool-results) |

```text
Export results:
  added:   0
  updated: 6
  skipped: 710 (unchanged since last export)
  empty:   96 (no extractable messages)

note: 'skipped' = sessions already up-to-date since last export;
re-run with --full to force a full re-import.
```

`skipped` is the steady-state for a repeat run — a large `skipped` count is
normal and means deduplication is working, not that anything failed. `empty`
is tracked separately so a session with no usable text is never mistaken for
one that was simply unchanged.

Use `--full` to ignore change-detection and re-import every session (every
unchanged session then re-imports as `updated` instead of `skipped`).

### Install & Export Examples

```bash
studyloop install tools
studyloop install agents
studyloop install agents --tool codex
studyloop install agents --tool claude --tool gemini
studyloop install agents --tool pi
studyloop install agents --tool omp

session-export
session-export --sources claude codex
session-export --sources gemini opencode
session-export --sources pi omp
session-export --claude-only
session-export --gemini-only
session-export --pi-only
session-export --omp-only
session-export --full
```

### Obsidian Vault Export (opt-in)

`session-export` can also write one Markdown "session-memory" note per session
into an Obsidian vault, alongside the SQLite export. Notes carry Dataview-ready
YAML frontmatter (`type: agent-memory`), `[[wikilink]]` backlinks to matching
vault topic notes, and per-project MOC index notes. Output lands in
`<vault>/AgentMemory/` (and `<vault>/AgentMemory/MOC/`).

Enable it per-run with `--obsidian`, or set `obsidian.export_enabled: true` in
`~/.config/studyloop/config.yaml` (see [Configuration](setup-guide.md#obsidian-session-memory-export)).

```bash
session-export --obsidian                      # write notes for sessions touched this run
session-export --obsidian --obsidian-vault ~/Obsidian/Personal  # override vault path
session-export --obsidian --obsidian-backfill  # write notes for ALL historical sessions (idempotent)
session-export --obsidian --obsidian-dry-run   # preview what would be written; write nothing
session-export --no-obsidian                   # force-disable even if config enables it
```

| Flag | Effect |
|------|--------|
| `--obsidian` / `--no-obsidian` | Enable/disable export for this run; overrides the `obsidian.export_enabled` config gate. |
| `--obsidian-vault PATH` | Override the vault root (default: `obsidian.vault_path`, falling back to `obsidian_base`). |
| `--obsidian-backfill` | Export every session in the DB, not just those touched this run. Idempotent — unchanged notes are skipped. |
| `--obsidian-dry-run` | Print the written/skipped/MOC counts without writing any files. |

Notes are **idempotent**: a content hash in each note's frontmatter means re-runs
skip unchanged sessions. A normal `--obsidian` run only writes sessions added or
updated in that run; use `--obsidian-backfill` for the one-time full history import.

### Optional Extras

```bash
uv pip install agent-session-tools[semantic]  # Vector embeddings search
uv pip install agent-session-tools[tokens]    # Token counting
```
