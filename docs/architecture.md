# Architecture

Current architecture and code map for the `studyctl` monorepo.

This page is the release-oriented source of truth for:
- system boundaries
- runtime containers
- major internal components
- repo structure / code map

For workflow-heavy operational detail, see [System Overview](system-overview.md).

## C4 Context

```mermaid
C4Context
    title System Context - Socratic Study Mentor

    Person(learner, "Learner", "Studies with AI mentors, review workflows, and NotebookLM-backed content")
    System(studyctl, "Socratic Study Mentor", "AuDHD-aware study toolkit for sessions, review, content processing, and session intelligence")

    System_Ext(obsidian, "Obsidian Vault", "Markdown study notes and course materials")
    System_Ext(notebooklm, "Google NotebookLM", "Uploads source material and generates study artefacts")
    System_Ext(ai_tools, "AI Coding Tools", "Claude Code, Codex CLI, Kiro, Gemini CLI, OpenCode, Amp")
    System_Ext(remote_host, "Remote Host", "SSH-accessible machine for session DB sync")

    Rel(learner, studyctl, "Uses")
    Rel(studyctl, obsidian, "Reads and converts notes from")
    Rel(studyctl, notebooklm, "Uploads sources to and downloads artefacts from")
    Rel(ai_tools, studyctl, "Provide study sessions and exported transcripts to")
    Rel(studyctl, remote_host, "Syncs sessions.db with", "SSH + SQLite delta")
```

## C4 Container

```mermaid
C4Container
    title Container Diagram - Socratic Study Mentor

    Person(learner, "Learner", "Runs study sessions and review workflows")
    System_Ext(obsidian, "Obsidian Vault", "Markdown notes")
    System_Ext(notebooklm, "Google NotebookLM", "Study artefact generation")
    System_Ext(ai_tools, "AI Coding Tools", "Claude, Codex, Kiro, Gemini, OpenCode, Amp")
    System_Ext(remote_host, "Remote Host", "SSH target for DB sync")

    System_Boundary(repo, "Socratic Study Mentor Monorepo") {
        Container(studyctl_cli, "studyctl", "Python / Click", "Primary CLI for sessions, review, content, doctor, install, and web")
        Container(agent_tools, "agent-session-tools", "Python / Typer", "Exports, queries, syncs, and maintains AI session history")
        Container(web_ui, "Web UI", "FastAPI + HTMX + Alpine", "Flashcard review PWA and live session dashboard")
        Container(sidebar, "Sidebar", "Textual", "Right-hand tmux pane with timer, activity, and counters")
        ContainerDb(session_db, "sessions.db", "SQLite", "Study sessions, reviews, exported transcripts, tags, notes, concepts, parked topics")
        Container(ipc_files, "IPC State", "JSON / Markdown files", "Live session state shared between tmux pane and dashboard")
    }

    Rel(learner, studyctl_cli, "Runs")
    Rel(studyctl_cli, sidebar, "Launches in tmux")
    Rel(studyctl_cli, web_ui, "Starts optionally", "uvicorn")
    Rel(studyctl_cli, session_db, "Reads and writes")
    Rel(studyctl_cli, ipc_files, "Writes live session state")
    Rel(sidebar, ipc_files, "Polls")
    Rel(web_ui, ipc_files, "Streams via SSE")
    Rel(agent_tools, session_db, "Reads and writes")
    Rel(agent_tools, ai_tools, "Imports transcript/session data from")
    Rel(studyctl_cli, obsidian, "Reads notes and materials from")
    Rel(studyctl_cli, notebooklm, "Uploads sources and fetches artefacts from")
    Rel(agent_tools, remote_host, "Syncs DB to/from", "SSH")
```

## C4 Component

```mermaid
C4Component
    title Component Diagram - studyctl + agent-session-tools

    Container(studyctl_cli, "studyctl", "Python / Click")
    Container(agent_tools, "agent-session-tools", "Python / Typer")
    ContainerDb(session_db, "sessions.db", "SQLite")
    Container(ipc_files, "IPC State", "JSON / Markdown")

    Container_Boundary(studyctl_boundary, "studyctl internals") {
        Component(cli_cmds, "CLI commands", "studyctl/cli", "User-facing command groups and entry points")
        Component(session_runtime, "Session runtime", "studyctl/session + studyctl/history", "tmux orchestration, lifecycle, rollback, persistence")
        Component(adapter_layer, "Agent adapters", "studyctl/adapters + agent_launcher", "Launch strategy for Claude, Codex, Gemini, Kiro, OpenCode, Ollama, LM Studio")
        Component(review_engine, "Review engine", "review_db + review_loader + services/review", "Flashcard review state and spaced repetition")
        Component(content_pipeline, "Content pipeline", "studyctl/content", "PDF splitting, note conversion, NotebookLM integration")
        Component(install_doctor, "Install + doctor", "installers + doctor", "Source install flow, diagnostics, and safe repairs")
        Component(web_sidebar, "UI layer", "web + tui", "PWA dashboard, SSE routes, and Textual sidebar")
    }

    Container_Boundary(agent_boundary, "agent-session-tools internals") {
        Component(exporters, "Exporters", "exporters/*", "Per-tool transcript importers")
        Component(query_sync, "Query + sync", "query_sessions + query_logic + sync", "Search, continuation context, and cross-machine sync")
        Component(schema, "Schema + migrations", "schema.sql + migrations", "SQLite schema evolution and compatibility")
        Component(extras, "Optional extras", "mcp_server + embeddings + semantic_search", "MCP access and semantic retrieval")
    }

    Rel(cli_cmds, session_runtime, "Invokes")
    Rel(cli_cmds, adapter_layer, "Invokes")
    Rel(cli_cmds, review_engine, "Invokes")
    Rel(cli_cmds, content_pipeline, "Invokes")
    Rel(cli_cmds, install_doctor, "Invokes")
    Rel(session_runtime, session_db, "Reads and writes")
    Rel(session_runtime, ipc_files, "Writes")
    Rel(web_sidebar, ipc_files, "Reads")
    Rel(web_sidebar, session_db, "Reads and writes")
    Rel(adapter_layer, session_db, "Uses for session metadata")
    Rel(exporters, schema, "Writes through")
    Rel(query_sync, schema, "Reads through")
    Rel(exporters, session_db, "Writes")
    Rel(query_sync, session_db, "Reads and syncs")
```

## Code Map

### Monorepo

```text
socratic-study-mentor/
├── packages/
│   ├── studyctl/
│   │   ├── src/studyctl/
│   │   │   ├── adapters/      # Agent launch adapters and local-LLM frontends
│   │   │   ├── cli/           # Click command surface
│   │   │   ├── content/       # NotebookLM and PDF processing pipeline
│   │   │   ├── doctor/        # Health checks and auto-fix diagnostics
│   │   │   ├── history/       # Study session persistence layer
│   │   │   ├── logic/         # Functional-core orchestration helpers
│   │   │   ├── mcp/           # studyctl MCP server/tooling
│   │   │   ├── services/      # Review/content service wrappers
│   │   │   ├── session/       # tmux orchestration and cleanup
│   │   │   ├── tui/           # Textual sidebar
│   │   │   ├── web/           # FastAPI routes and static assets
│   │   │   ├── installers.py  # Typed source-install helpers
│   │   │   ├── review_db.py   # Flashcard scheduling DB
│   │   │   └── settings.py    # Shared config loading
│   │   └── tests/
│   └── agent-session-tools/
│       ├── src/agent_session_tools/
│       │   ├── exporters/     # Claude, Codex, Gemini, Kiro, OpenCode, Aider, LiteLLM, RepoPrompt
│       │   ├── integrations/  # Git / editor integration helpers
│       │   ├── migrations.py  # sessions.db schema evolution
│       │   ├── query_logic.py # Search / continuation logic
│       │   ├── query_sessions.py
│       │   ├── sync.py
│       │   ├── mcp_server.py
│       │   └── export_sessions.py
│       └── tests/
├── agents/                    # Per-tool agent definitions and shared prompts
├── docs/                      # User, developer, architecture, and ops docs
├── scripts/                   # Thin source-install and helper scripts
├── Formula/studyctl.rb        # Homebrew formula
└── pyproject.toml             # Workspace root
```

### Important entry points

| Area | Entry point | Notes |
|---|---|---|
| Main CLI | `packages/studyctl/src/studyctl/cli/__init__.py` | Lazy command registration |
| Study sessions | `packages/studyctl/src/studyctl/cli/_study.py` | High-level session UX |
| Session runtime | `packages/studyctl/src/studyctl/session/start.py` | Startup, rollback, tmux orchestration |
| Install flow | `packages/studyctl/src/studyctl/cli/_install.py` | Typed tool/agent install commands |
| Doctor | `packages/studyctl/src/studyctl/cli/_doctor.py` | Diagnostics and `--fix` |
| Export | `packages/agent-session-tools/src/agent_session_tools/export_sessions.py` | Transcript import CLI |
| Query | `packages/agent-session-tools/src/agent_session_tools/query_sessions.py` | Search and write actions |
| Sync | `packages/agent-session-tools/src/agent_session_tools/sync.py` | Cross-machine DB sync |

## Design Notes

- `studyctl` is the user-facing orchestration package.
- `agent-session-tools` is the durable session-intelligence/data package.
- The cross-package dependency is one-way: `studyctl` uses `agent-session-tools`, not the reverse.
- Source installs are now driven by `studyctl install tools`, `studyctl install agents`, and `studyctl doctor --fix`; the shell scripts are compatibility wrappers.
- Session startup is designed to fail closed: if tmux/sidebar/agent startup breaks, the DB session and IPC state are rolled back.
