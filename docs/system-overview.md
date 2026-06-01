# System Overview

This page explains how the active system fits together from a user and operator perspective.

For deeper diagrams, see:

- [Current Architecture](architecture/current.md)
- [Target Architecture](architecture/target.md)
- [Web UI Guide](web-ui-guide.md)
- [Repository Standards](standards/repo-standards.md)

## Big Picture

```mermaid
flowchart TB
    subgraph "Study Sources"
        Obsidian["Obsidian<br/>~/Obsidian/Personal/Study"]
        PDF["PDF/eBook"]
        Text["Markdown/text"]
    end

    subgraph "Core Tools"
        StudyLoop["studyloop"]
        AST["agent-session-tools"]
        DB[("SQLite<br/>sessions + review")]
    end

    subgraph "Interactive Study"
        Picker["studyloop study<br/>session picker"]
        Agent["Selected assistant<br/>Claude/Codex/Gemini/Kiro/OpenCode"]
        Tmux["tmux/Textual<br/>current runtime"]
        Web["Web/PWA<br/>dashboard + review"]
        Explorer["Course Explorer<br/>(browse + read + search<br/>study material)"]
        TTYD["ttyd<br/>browser terminal fallback"]
    end

    subgraph "Review Support"
        Generator["Card generator<br/>(pluggable: Ollama / Bedrock /<br/>OpenAI / OpenRouter / Gemini /<br/>Anthropic / Stub)"]
        JSON["Flashcard/quiz JSON"]
        Review["SM-2 review"]
    end

    subgraph "Outputs"
        AgentMemory["AgentMemory/<br/>(Obsidian vault notes)<br/>Dataview frontmatter +<br/>[[wikilinks]] + MOC index"]
    end

    Obsidian --> StudyLoop
    PDF --> StudyLoop
    Text --> StudyLoop
    StudyLoop --> Picker
    Picker --> Tmux
    Tmux --> Agent
    StudyLoop --> Web
    Web --> TTYD
    Web --> Explorer
    Explorer -->|"reads source material"| Obsidian
    Explorer -->|"writes struggle flags"| DB
    TTYD --> Tmux
    Agent --> DB
    AST --> DB
    AST -.->|"--obsidian (opt-in)<br/>obsidian_writer"| AgentMemory
    StudyLoop --> Generator
    Generator --> JSON
    JSON --> Review
    Review --> DB
    Web --> DB
```

## Primary Workflow: Interactive Study

The main workflow is live interaction with a mentor agent.

```mermaid
sequenceDiagram
    actor User
    participant StudyLoop
    participant DB as Shared DB
    participant Agent as Assistant
    participant UI as Web/tmux UI

    User->>StudyLoop: studyloop study
    StudyLoop-->>User: picker: body double/topic/vendor/course
    User->>StudyLoop: select session type
    StudyLoop->>DB: create session
    StudyLoop->>Agent: launch selected assistant
    StudyLoop->>UI: show live state
    User->>Agent: ask questions / explain confusion
    Agent->>DB: query struggles, wins, history
    Agent-->>User: Socratic question or targeted explanation
    Agent->>DB: record progress
    Agent->>UI: update topic/win/parking state
```

The shared DB matters because it lets the agent adapt using evidence:

- recurring struggle topics
- previous study sessions
- code-assistant sessions imported from other tools
- wins and progress
- spaced repetition state
- parked topics

## Supporting Workflow: Local Review Artefacts

Flashcards and quizzes support study, but they are not the product centre.

```bash
studyloop content generate-cards ~/Obsidian/Personal/Study/Python --course python
studyloop web
```

```mermaid
flowchart LR
    Source["Markdown/text source"]
    Generate["studyloop content generate-cards<br/>or Generate panel<br/>(WebUI)"]
    Backend["CardGenerator<br/>Ollama / Bedrock /<br/>OpenAI / OpenRouter / Gemini /<br/>Anthropic / Stub"]
    Schema["Pydantic validation"]
    Artefacts["course/flashcards<br/>course/quizzes"]
    PWA["Web review"]

    Source --> Generate --> Backend --> Schema --> Artefacts --> PWA
```

The producer side is **pluggable**: a `ProviderProfile` registry plus two generic HTTP adapters (OpenAI Chat Completions and Anthropic Messages), with Bedrock and Ollama as first-class registry entries, cover six providers via registry rows. Adding a new provider is a registry edit, not new code. Auth credentials resolve **encrypted store first** (`~/.config/studyloop/secrets.bin`, written by the **Settings → LLM Providers** panel after a live verification), then a project-root `.env` (auto-loaded via `python-dotenv`); models are curated per-provider with cost-tier and thinking-flag annotations. See [Content Pipeline § Pluggable Provider Abstraction](content-pipeline.md#pluggable-provider-abstraction).

NotebookLM is not required for this workflow.

## Presentation Model

Current:

- tmux + assistant CLI for live interaction
- Textual sidebar for timer/activity
- Web dashboard for session state
- ttyd for browser terminal access

Target:

- Web/PWA live session panel as primary learner UI
- ACP transport where available
- PTY transport fallback where ACP is not available
- ttyd retained until the web session layer can fully replace it
- macOS/iOS apps use the same local API later

```mermaid
flowchart TD
    Web["Web/PWA<br/>chat surface + dashboard"]
    API["Study Session API<br/>(/api/session/*)"]
    Runtime["Agent Runtime<br/>(active-session singleton)"]
    ACP["ACPTransport<br/>JSON-RPC over stdio"]
    PTY["PTYTransport<br/>raw bytes / WINSZ"]
    Persona["build_canonical_persona<br/>(per topic + energy)"]
    DB["sessions.db<br/>(study state, progress)"]

    Web -->|"POST /session/start"| API
    Web <-->|"WebSocket /session/ws"| API
    API -->|"persona_text returned<br/>inline in /start response"| Persona
    API --> Runtime
    Runtime --> ACP
    Runtime --> PTY
    ACP -->|"first session/prompt =<br/>invisible persona"| Web
    Runtime --> DB
    API -->|"stream events"| Web
```

**Persona delivery — different per transport.** On the PTY path the persona is written to a temp file and embedded in the agent's launch command. On the ACP path (added 2026-05-28) the persona text is returned inline in the `/api/session/start` response and the browser ships it as the first invisible `session/prompt` after the WebSocket opens — ACP agents have no argv/env hook for system context, the prompt channel is the only injection point. The browser hides it from the chat (no user bubble, no assistant ack scrolls past) and shows a brief "Setting up your mentor…" banner instead.

## Data Stores

| Store | Purpose |
|---|---|
| SQLite `sessions.db` | study sessions, progress, review state, imported assistant sessions |
| SQLite `explorer_fts.db` | derived lesson full-text index (rebuildable cache, separate from `sessions.db`, no migration) |
| IPC files | current live session state for sidebar/dashboard |
| `content.base_path` | source study material (markdown/text) + generated flashcard and quiz JSON |
| assistant session dirs | per-agent local conversation state |

## Optional Integrations

Optional integrations should be plugins, not core requirements:

- NotebookLM for audio/video artefacts if retained
- OCR/image parsing
- Office document parsing
- website scraping
- autoagent prompt/agent evaluation
- native macOS/iOS clients
