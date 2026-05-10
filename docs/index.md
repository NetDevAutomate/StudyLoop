# StudyLoop

**TL;DR:** A local-first, AuDHD-aware study toolkit for live Socratic mentoring, body-doubling, cross-assistant session memory, and supporting spaced repetition.

---

## Quick Start

```bash
# 1. Install and configure
brew install Hookey-Street-Software/studyloop/studyloop
studyloop setup
studyloop doctor --fix

# 2. Start an interactive study session
studyloop study
# or specify a topic directly
studyloop study "Python" --mode co-study
# or launch your preferred assistant directly:
# kiro-cli chat --agent study-mentor
# claude      # then /agent socratic-mentor
# codex       # in the project root with AGENTS.md present

# 3. Optional: generate and review flashcards/quizzes
studyloop content generate-cards ~/Obsidian/Personal/Study/Python --course python
studyloop review
```

!!! tip "First time?"
    Head to the [Setup Guide](setup-guide.md) for full installation details, then [Agent Installation](agent-install.md) to configure your AI tools.

---

## How It Works

```mermaid
graph LR
    subgraph "Study Materials"
        OB[Obsidian Vault]
        SRC[Markdown/PDF/text]
    end

    subgraph "CLI Tools"
        SC[studyloop]
        AST[agent-session-tools]
        DB[(SQLite DB)]
    end

    subgraph "AI Agents"
        KA[kiro-cli]
        CA[Claude Code]
        CX[Codex CLI]
        GA[Gemini CLI]
        OA[OpenCode]
        AA[Amp]
    end

    OB -->|study sources| SC
    SRC -->|parse/generate| SC
    SC -->|sessions + review| DB
    AST -->|export sessions| DB
    DB -->|query history| SC
    KA -->|Socratic sessions| DB
    CA -->|Socratic sessions| DB
    CX -->|Socratic sessions| DB
    GA -->|Socratic sessions| DB
    OA -->|Socratic sessions| DB
    AA -->|Socratic sessions| DB
```

---

## What's Inside

| Tool | Purpose |
|------|---------|
| **studyloop** | Interactive study sessions, local content generation, spaced repetition, struggle detection, win tracking |
| **agent-session-tools** | Export and search AI sessions from Claude Code, Codex, Kiro, Gemini, Aider, and more |
| **AI Agents** | Socratic mentors that adapt to your energy, emotional state, and sensory environment |

!!! energy-check "Designed for AuDHD brains"
    Every session starts with an energy + emotional state check. Low energy? Shorter chunks, more scaffolding. Shutdown? No teaching — just presence. Read the [AuDHD Philosophy](audhd-learning-philosophy.md) to understand why.

---

## Key Sections

- **[Content Pipeline](content-pipeline.md)** — local review artefact generation from study sources
- **[Architecture](architecture.md)** — current and target architecture docs
- **[Target Architecture](architecture/target.md)** — plugin architecture, ACP/PTY live sessions, macOS/iOS direction
- **[TUI Sidebar Guide](tui-guide.md)** — Terminal sidebar layout, timer modes, key bindings
- **[Web UI Guide](web-ui-guide.md)** — live sessions, session dashboard, terminal fallback, review UI
- **[Session Protocol](session-protocol.md)** — How every study session flows, from arrival to close
- **[CLI Reference](cli-reference.md)** — Full command reference for `studyloop` and `session-query`
- **[Repository Standards](standards/repo-standards.md)** — naming, doc, and structure standards
- **[AuDHD Framework](audhd-framework.md)** — The cognitive support framework behind the agents
- **[Network Bridges](network-bridges.md)** — Network→Data Engineering analogies for infrastructure people
- **[Roadmap](roadmap.md)** — What's coming next

!!! micro-celebration "You're here"
    Reading docs is the first step. That counts.
