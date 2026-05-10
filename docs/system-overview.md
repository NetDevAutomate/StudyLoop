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
        Studyctl["studyloop"]
        AST["agent-session-tools"]
        DB[("SQLite<br/>sessions + review")]
    end

    subgraph "Interactive Study"
        Picker["studyloop study<br/>session picker"]
        Agent["Selected assistant<br/>Claude/Codex/Gemini/Kiro/OpenCode"]
        Tmux["tmux/Textual<br/>current runtime"]
        Web["Web/PWA<br/>dashboard + review"]
        TTYD["ttyd<br/>browser terminal fallback"]
    end

    subgraph "Review Support"
        Generator["Local card generator<br/>Ollama/Bedrock"]
        JSON["Flashcard/quiz JSON"]
        Review["SM-2 review"]
    end

    Obsidian --> Studyctl
    PDF --> Studyctl
    Text --> Studyctl
    Studyctl --> Picker
    Picker --> Tmux
    Tmux --> Agent
    Studyctl --> Web
    Web --> TTYD
    TTYD --> Tmux
    Agent --> DB
    AST --> DB
    Studyctl --> Generator
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
    participant Studyctl
    participant DB as Shared DB
    participant Agent as Assistant
    participant UI as Web/tmux UI

    User->>Studyctl: studyloop study
    Studyctl-->>User: picker: body double/topic/vendor/course
    User->>Studyctl: select session type
    Studyctl->>DB: create session
    Studyctl->>Agent: launch selected assistant
    Studyctl->>UI: show live state
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
    Generate["studyloop content generate-cards"]
    Backend["CardGenerator<br/>Ollama or Bedrock"]
    Schema["Pydantic validation"]
    Artefacts["course/flashcards<br/>course/quizzes"]
    PWA["Web review"]

    Source --> Generate --> Backend --> Schema --> Artefacts --> PWA
```

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
    Web["Web/PWA"]
    API["Study Session API"]
    Runtime["Agent Runtime"]
    ACP["ACP<br/>JSON-RPC"]
    PTY["PTY<br/>terminal fallback"]
    DB["Shared DB"]

    Web -->|"message/control"| API
    API --> Runtime
    Runtime --> ACP
    Runtime --> PTY
    Runtime --> DB
    API -->|"stream events"| Web
```

## Data Stores

| Store | Purpose |
|---|---|
| SQLite `sessions.db` | study sessions, progress, review state, imported assistant sessions |
| IPC files | current live session state for sidebar/dashboard |
| `content.base_path` | generated flashcard and quiz JSON |
| assistant session dirs | per-agent local conversation state |

## Optional Integrations

Optional integrations should be plugins, not core requirements:

- NotebookLM for audio/video artefacts if retained
- OCR/image parsing
- Office document parsing
- website scraping
- autoagent prompt/agent evaluation
- native macOS/iOS clients
