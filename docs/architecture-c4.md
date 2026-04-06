# C4 Architecture Diagrams

This document describes the architecture of the socratic-study-mentor system at three levels of abstraction, following the C4 model (Context, Container, Component).

---

## Level 1 — System Context

The System Context diagram shows studyctl and the external actors it interacts with. The student is the primary user; AI coding agents are the learning partners that the system orchestrates. External services provide content, storage, and infrastructure.

```mermaid
C4Context
    title System Context — socratic-study-mentor

    Person(student, "Student", "The learner. Runs studyctl from a terminal or browser.")

    System(studyctl, "studyctl", "AuDHD-aware study pipeline. Orchestrates AI sessions, manages spaced-repetition review, syncs content, and tracks learning history.")

    System_Ext(claude, "Claude Code", "Primary AI coding assistant. Runs as the study-mentor agent inside a tmux pane.")
    System_Ext(gemini, "Gemini CLI", "Google Gemini agent. Auto-loads GEMINI.md persona from session directory.")
    System_Ext(kiro, "Kiro", "Amazon Kiro agent. Persona injected via ~/.kiro/agents/ JSON.")
    System_Ext(opencode, "OpenCode", "OpenCode agent. Persona written as .opencode/agents/study-mentor.md.")
    System_Ext(ollama, "Ollama / LM Studio", "Local LLM backends. Accessed via LiteLLM proxy (Ollama) or OpenAI-compat API (LM Studio). Claude Code is used as the frontend.")
    System_Ext(tmux, "tmux", "Terminal multiplexer. Hosts the agent pane and sidebar pane.")
    System_Ext(ttyd, "ttyd", "Browser-based terminal. Exposes the tmux session over HTTP for remote or non-terminal access.")
    System_Ext(obsidian, "Obsidian Vault", "Personal knowledge base. Study notes, course content, and flashcards live here.")
    System_Ext(notebooklm, "Google NotebookLM", "AI notebook service. Generates audio summaries and study artefacts from uploaded source material.")
    System_Ext(pypi, "PyPI / Homebrew", "Distribution. studyctl is published to PyPI and available via a Homebrew tap.")

    Rel(student, studyctl, "Runs CLI commands", "terminal / browser")
    Rel(studyctl, claude, "Launches with study-mentor persona", "subprocess + temp file")
    Rel(studyctl, gemini, "Launches with study-mentor persona", "subprocess + GEMINI.md")
    Rel(studyctl, kiro, "Launches with study-mentor persona", "subprocess + ~/.kiro/agents/")
    Rel(studyctl, opencode, "Launches with study-mentor persona", "subprocess + .opencode/agents/")
    Rel(studyctl, ollama, "Launches Claude Code pointed at local LLM", "env vars: ANTHROPIC_BASE_URL")
    Rel(studyctl, tmux, "Creates and manages sessions", "subprocess + tmux CLI")
    Rel(studyctl, ttyd, "Spawns browser terminal", "subprocess")
    Rel(studyctl, obsidian, "Reads/writes notes and flashcards", "filesystem")
    Rel(studyctl, notebooklm, "Uploads sources and triggers artefact generation", "notebooklm-py HTTP")
    Rel(claude, studyctl, "Calls study tools via MCP", "stdio MCP")
    Rel(gemini, studyctl, "Calls study tools via MCP", "stdio MCP")
    Rel(opencode, studyctl, "Calls study tools via MCP", "stdio MCP")
    Rel(student, ttyd, "Interacts with agent session in browser", "HTTP")
```

---

## Level 2 — Container

The Container diagram zooms into studyctl itself, showing the distinct deployable units and libraries, and how data flows between them. All containers run on the student's local machine.

```mermaid
C4Container
    title Container Diagram — studyctl system

    Person(student, "Student", "Runs CLI or accesses the Web UI")

    System_Boundary(studyctl_sys, "studyctl system") {

        Container(cli, "studyctl CLI", "Python / Click + LazyGroup", "Entry point for all commands. 26 commands across 12 lazy-loaded modules. Delegates to services, session orchestrator, and specialist packages.")

        Container(web, "Web UI", "Python / FastAPI + Alpine.js PWA", "Dashboard served on localhost:8567 (configurable). Shows session state, flashcard review, artefacts, and terminal embed. Optional HTTP Basic Auth for LAN mode.")

        Container(mcp_server, "MCP Server (studyctl-mcp)", "Python / FastMCP via stdio", "Exposes study tools to AI agents: list_courses, get_study_context, record_study_progress, park_question, get_session_state. Launched automatically by each agent adapter.")

        Container(orchestrator, "Session Orchestrator", "Python / subprocess + tmux CLI", "Creates the tmux study session. Writes CLAUDE.md and per-agent persona files. Splits the terminal into agent pane (75%) and sidebar pane (25%). Starts ttyd and web dashboard as background processes.")

        Container(agent_session_tools, "agent-session-tools", "Python library", "Captures and stores AI coding-agent sessions to sessions.db. Provides exporters for 8 agent formats, semantic search, MCP server, cross-session context, and Obsidian export.")

        ContainerDb(review_db, "review.db", "SQLite (WAL mode)", "Spaced-repetition history. Stores per-card SM-2 review records keyed by 16-hex-char card_hash. Located at ~/.config/studyctl/review.db (implicit, inside sessions.db path dir) or configured path.")

        ContainerDb(sessions_db, "sessions.db", "SQLite (WAL mode)", "AI session history. Stores agent conversation exports, topics, parking lot questions, session metadata. Located at ~/.config/studyctl/sessions.db.")
    }

    Rel(student, cli, "Runs commands", "terminal (zsh/bash)")
    Rel(student, web, "Views dashboard and reviews flashcards", "HTTP (browser)")
    Rel(cli, orchestrator, "Delegates study/session commands", "function call")
    Rel(cli, web, "Starts as background subprocess", "subprocess.Popen")
    Rel(cli, agent_session_tools, "Calls query, export, and search functions", "import")
    Rel(orchestrator, mcp_server, "Configures agent MCP config files", "filesystem")
    Rel(web, review_db, "Reads flashcard due state and history", "sqlite3")
    Rel(web, sessions_db, "Reads session history and parking lot", "sqlite3")
    Rel(mcp_server, review_db, "Records review results and reads due cards", "sqlite3")
    Rel(mcp_server, sessions_db, "Reads and writes session state", "sqlite3")
    Rel(agent_session_tools, sessions_db, "Writes session exports and reads history", "sqlite3")
    Rel(cli, review_db, "Direct SM-2 review commands", "sqlite3")
    Rel(cli, sessions_db, "Session search and context commands", "sqlite3")
```

---

## Level 3a — Components: studyctl CLI

This diagram shows the internal component structure of the studyctl CLI package. The CLI layer is deliberately thin — it delegates immediately to services, logic, or specialist packages.

```mermaid
C4Component
    title Component Diagram — studyctl CLI package

    Container_Boundary(cli_pkg, "studyctl CLI package") {

        Component(cli_entry, "cli/ (LazyGroup)", "Click + LazyGroup", "Root Click group. 26 commands across 12 modules: _sync, _setup, _config, _review, _content, _web, _session, _study, _clean, _topics, _doctor, _upgrade, _backup. Modules are only imported when the command is invoked.")

        Component(services, "services/", "Python", "Framework-agnostic business logic layer. review.py (get_due, get_stats, record_review, list_course_summaries, get_backlog). content.py (storage wrappers). Called by CLI, Web UI routes, and MCP tools.")

        Component(session_pkg, "session/", "Python", "Tmux environment orchestration. orchestrator.py: create tmux session, split panes, start web/ttyd background processes. cleanup.py: post-session teardown. resume.py: load previous-session notes.")

        Component(agent_launcher, "agent_launcher.py", "Python", "Multi-agent adapter registry. AgentAdapter dataclass with setup/launch_cmd/teardown/mcp_setup callables. Six adapters: Claude, Gemini, Kiro, OpenCode, Ollama, LM Studio. detect_agents() reads priority from config.")

        Component(history_pkg, "history/", "Python", "Review history and statistics. _connection.py: WAL-mode SQLite helper. sessions.py, progress.py, streaks.py, bridges.py, concepts.py, teachback.py, medication.py, search.py.")

        Component(doctor_pkg, "doctor/", "Python", "Diagnostic health checks. CheckerRegistry with exception isolation. Six checker modules: core.py, database.py, config.py, deps.py, agents.py, updates.py. models.py: frozen CheckResult dataclass (JSON contract). Exit codes: 0=healthy, 1=actionable, 2=core failure.")

        Component(content_pkg, "content/", "Python", "Content pipeline (absorbed from pdf-by-chapters). splitter.py: PDF chapter splitting. notebooklm_client.py: upload and trigger artefact generation. syllabus.py: course syllabus parsing. storage.py, models.py, markdown_converter.py.")

        Component(web_pkg, "web/", "Python / FastAPI", "Web dashboard. app.py: FastAPI application factory with security headers and optional Basic Auth middleware. auth.py: HTTP Basic Auth. routes/: artefacts, cards, courses, history, session, terminal_proxy. static/: Alpine.js PWA assets.")

        Component(mcp_pkg, "mcp/", "Python / FastMCP", "MCP server entry point. server.py: FastMCP app with lifespan DB connection. tools.py: register_tools() wires list_courses, get_study_context, record_study_progress, park_question, get_session_state.")

        Component(logic_pkg, "logic/", "Python", "Domain logic modules. break_logic.py: break detection and timing. streaks_logic.py: study streak calculation. briefing_logic.py: pre-session briefing generation. backlog_logic.py: topic backlog management. clean_logic.py: orphan cleanup. topic_resolver.py: topic name resolution.")

        Component(settings_mod, "settings.py", "Python / dataclasses", "Single configuration source. Settings dataclass loaded from ~/.config/studyctl/config.yaml. Contains: TopicConfig, AgentsConfig, ContentConfig, NotebookLMConfig, KnowledgeDomainsConfig, EvalConfig.")
    }

    Rel(cli_entry, services, "Calls business logic", "import")
    Rel(cli_entry, session_pkg, "Delegates study/session commands", "import")
    Rel(cli_entry, doctor_pkg, "Runs health checks", "import")
    Rel(cli_entry, content_pkg, "Delegates content pipeline commands", "import")
    Rel(cli_entry, logic_pkg, "Calls domain logic", "import")
    Rel(cli_entry, web_pkg, "Starts web dashboard", "import")
    Rel(cli_entry, mcp_pkg, "Entry point for studyctl-mcp command", "import")
    Rel(session_pkg, agent_launcher, "Detects agents and builds launch commands", "import")
    Rel(mcp_pkg, services, "Calls review and content services", "import")
    Rel(services, history_pkg, "Reads/writes review history", "import")
    Rel(cli_entry, settings_mod, "Loads all config", "import")
    Rel(session_pkg, settings_mod, "Reads web_port, ttyd_port, browser", "import")
    Rel(agent_launcher, settings_mod, "Reads agents.priority and local LLM config", "import")
```

---

## Level 3b — Components: agent-session-tools

This diagram shows the internal structure of the `agent-session-tools` library, which is the cross-agent session capture and retrieval layer shared across all AI coding agents.

```mermaid
C4Component
    title Component Diagram — agent-session-tools library

    Container_Boundary(ast_pkg, "agent-session-tools library") {

        Component(exporters, "exporters/", "Python", "Per-agent session export parsers. base.py: BaseExporter abstract class. claude.py, gemini.py, kiro.py, opencode.py: parse each agent's conversation history format. aider.py, repoprompt.py, litellm.py, bedrock.py: additional tool/API formats.")

        Component(query_logic, "query_logic.py + query_sessions.py", "Python", "Session search and retrieval. query_logic.py: filter sessions by date, agent, topic, and keyword. query_sessions.py: top-level query entrypoint. query_utils.py: shared predicates and helpers.")

        Component(formatters, "formatters.py", "Python", "Output formatters for query results. Renders sessions as plain text, JSON, or Markdown for terminal display and export.")

        Component(mcp_server_ast, "mcp_server.py", "Python / FastMCP", "MCP server for agent-session-tools. Exposes session search, context retrieval, hotspot analysis, and stats tools to AI agents. Runs as a separate stdio MCP process (session-tools-mcp).")

        Component(schema_migrations, "schema.sql + migrations.py", "Python / SQL", "Database schema definition and version-controlled migrations. migrations.py applies pending migrations to sessions.db on startup. Provides temp_db and migrated_db test fixtures.")

        Component(sync_mod, "sync.py", "Python", "Cross-machine session synchronisation. Copies sessions.db to/from remote hosts via passwordless SSH. Uses WAL mode for concurrent safe reads during sync.")

        Component(maintenance_mod, "maintenance.py", "Python", "Database maintenance operations. VACUUM, integrity checks, size reporting, and stale-session pruning.")

        Component(scrubber_mod, "scrubber.py", "Python", "PII and secret scrubbing. Redacts API keys, tokens, passwords, and personal identifiers from session content before export.")

        Component(embeddings_mod, "embeddings.py + semantic_search.py", "Python / sentence-transformers", "Semantic session search. Generates embeddings for session content. semantic_search.py queries by cosine similarity. Optional dep: sentence-transformers.")

        Component(speak_mod, "speak.py + mcp_speak.py", "Python / kokoro", "Text-to-speech output. speak.py: local TTS via kokoro (optional [tts] extra). mcp_speak.py: MCP tool wrapper for TTS in agents.")

        Component(export_sessions, "export_sessions.py", "Python", "Obsidian and file export pipeline. Formats sessions as Markdown with frontmatter for Obsidian vault ingestion.")

        Component(tutor_checkpoint, "tutor_checkpoint.py + profiles.py", "Python", "Tutor progress tracking. tutor_checkpoint.py: per-session skill assessment snapshots. profiles.py: learner profile management.")
    }

    Rel(exporters, schema_migrations, "Writes parsed sessions to sessions.db", "sqlite3")
    Rel(query_logic, schema_migrations, "Reads sessions from sessions.db", "sqlite3")
    Rel(mcp_server_ast, query_logic, "Calls search and context functions", "import")
    Rel(mcp_server_ast, formatters, "Formats results for tool responses", "import")
    Rel(mcp_server_ast, speak_mod, "Optionally speaks responses aloud", "import")
    Rel(query_logic, embeddings_mod, "Falls back to semantic search when keyword search is weak", "import")
    Rel(export_sessions, query_logic, "Fetches sessions to export", "import")
    Rel(export_sessions, scrubber_mod, "Scrubs PII before writing files", "import")
    Rel(sync_mod, schema_migrations, "Transfers sessions.db to/from remote", "SSH/rsync")
    Rel(maintenance_mod, schema_migrations, "Maintains sessions.db", "sqlite3")
    Rel(tutor_checkpoint, schema_migrations, "Reads and writes checkpoint records", "sqlite3")
```
