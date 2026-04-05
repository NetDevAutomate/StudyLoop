# System Overview — How Everything Connects

> A complete map of the studyctl ecosystem: from Obsidian notes to AI study sessions to spaced repetition.

---

## The Big Picture

```mermaid
graph TB
    subgraph "Content Creation"
        OV["Obsidian Vault<br/>(course notes, .md)"]
        PDF["PDF Textbooks"]
    end

    subgraph "Content Pipeline"
        SYNC["studyctl sync<br/>(hash-based change detection)"]
        CONTENT["studyctl content<br/>(split, process, from-obsidian)"]
        PANDOC["pandoc + typst<br/>(markdown to PDF)"]
    end

    subgraph "Google NotebookLM"
        NB["NotebookLM Notebook<br/>(per-topic)"]
        ART["Generated Artefacts<br/>(audio, video, slides,<br/>quizzes, flashcards)"]
    end

    subgraph "Review System"
        FC["Flashcard/Quiz JSON<br/>(downloaded artefacts)"]
        SM2["SM-2 Spaced Repetition<br/>(card_reviews table)"]
        WEB["Web PWA<br/>localhost:8567"]
    end

    subgraph "Study Sessions"
        STUDY["studyctl study 'topic'"]
        TMUX["tmux Session"]
        AGENT["AI Agent<br/>(Claude Code)"]
        SIDEBAR["Textual Sidebar<br/>(timer, activity, counters)"]
        DASH["Live Dashboard<br/>/session (SSE + HTMX)"]
    end

    subgraph "Session Intelligence"
        EXPORT["session-export<br/>(import AI conversations)"]
        QUERY["session-query<br/>(search, context, continue)"]
        SSYNC["session-sync<br/>(cross-machine SSH)"]
    end

    DB[(sessions.db<br/>SQLite)]
    IPC["IPC Files<br/>(state, topics, parking)"]

    OV -->|"studyctl sync"| SYNC
    OV -->|"studyctl content from-obsidian"| CONTENT
    PDF -->|"studyctl content split/process"| CONTENT
    SYNC --> PANDOC -->|upload chapters| NB
    CONTENT --> PANDOC
    CONTENT -->|upload + generate| NB
    NB -->|generate| ART
    ART -->|download| FC
    FC --> SM2
    SM2 --> WEB
    WEB --> DB

    STUDY --> TMUX
    TMUX --> AGENT
    TMUX --> SIDEBAR
    STUDY -.->|"--web"| DASH
    STUDY -.->|"--lan"| TTYD["ttyd<br/>(port 7681)"]
    TTYD -.->|"attaches to"| TMUX
    DASH -.->|"/terminal/ proxy"| TTYD
    AGENT -->|writes| IPC
    SIDEBAR -->|polls| IPC
    DASH -->|polls SSE| IPC
    AGENT --> DB
    SIDEBAR -->|session-oneline.txt| TMUX

    AGENT -.->|"AI coding sessions"| EXPORT
    EXPORT --> DB
    QUERY --> DB
    SSYNC -->|"SSH delta"| DB

    style DB fill:#89b4fa,color:#1e1e2e
    style IPC fill:#f5a97f,color:#1e1e2e
    style NB fill:#a6da95,color:#1e1e2e
```

---

## Component Deep-Dives

### 1. Content Pipeline — From Notes to NotebookLM

The content pipeline turns your study materials into AI-generated learning artefacts.

```mermaid
flowchart LR
    subgraph "Sources"
        A["Obsidian .md files"]
        B["PDF textbooks"]
    end

    subgraph "Processing"
        C["markdown_converter.py<br/>(pandoc + typst + mmdc)"]
        D["splitter.py<br/>(PyMuPDF TOC split)"]
    end

    subgraph "NotebookLM"
        E["notebooklm_client.py<br/>(notebooklm-py library)"]
        F["Per-topic Notebook"]
        G["Audio Overview"]
        H["Quiz JSON"]
        I["Flashcard JSON"]
        J["Video / Slides"]
    end

    A -->|"content from-obsidian<br/>or sync"| C
    C -->|"chapter PDFs"| D
    B -->|"content split"| D
    D -->|"upload chapters"| E
    E --> F
    F -->|generate| G
    F -->|generate| H
    F -->|generate| I
    F -->|generate| J
```

**Two paths to NotebookLM:**

| Command | What it does | When to use |
|---------|-------------|-------------|
| `studyctl sync TOPIC` | Hash-based change detection, syncs only modified files. Converts .md to PDF via pandoc. | Ongoing sync as you take notes |
| `studyctl content from-obsidian DIR` | Full pipeline: markdown to PDF, split by chapter, upload, generate artefacts, download | First-time processing of a course |
| `studyctl content process PDF` | Split PDF by TOC, upload chapters, generate artefacts | Processing a textbook |
| `studyctl content split PDF` | Just split a PDF by chapter bookmarks | Prep step before manual upload |

**NotebookLM gotchas:**
- Generation takes 15+ minutes for slides/video (timeout must be >= 900s)
- Daily quota ~20-25 for infographics/slides (Pro tier)
- Sequential generation with 30s gap between types to avoid rate limits

---

### 2. Study Sessions — One Command, Full Environment

```mermaid
sequenceDiagram
    participant U as User
    participant CLI as studyctl study
    participant DB as sessions.db
    participant TMUX as tmux
    participant AGENT as Claude Code
    participant TUI as Textual Sidebar
    participant IPC as IPC Files
    participant WEB as Web Dashboard

    U->>CLI: studyctl study "Decorators" --energy 7
    CLI->>DB: start_study_session()
    CLI->>IPC: Write session-state.json + empty topics/parking
    CLI->>TMUX: Create session (cwd=sessions/study-decorators-xxx/, window-size largest)
    CLI->>TMUX: Split pane 75/25
    TMUX->>AGENT: Main pane: claude --append-system-prompt-file persona.md
    TMUX->>TUI: Sidebar pane: python -m studyctl.tui.sidebar

    opt --lan flag
        CLI->>WEB: Start ttyd (attaches to tmux session, port 7681)
        CLI->>WEB: Start web with Basic Auth + ttyd proxy
        Note over WEB: Web dashboard proxies ttyd at /terminal/<br/>(same-origin — pop-out/return preserves WS)<br/>HTTP Basic Auth protects all routes on LAN
    end

    loop Every 2 seconds
        TUI->>IPC: stat() mtime check
        IPC-->>TUI: Update timer, activity, counters
        TUI->>TMUX: Write session-oneline.txt (status bar)
    end

    Note over AGENT,IPC: Agent writes topics + parking during session

    opt --web flag
        CLI->>WEB: Start uvicorn background
        loop SSE every 2 seconds
            WEB->>IPC: stat() mtime check
            IPC-->>WEB: Push HTML fragments via SSE
        end
    end

    U->>AGENT: /exit or Ctrl+C
    AGENT->>CLI: Wrapper runs _cleanup_session()
    CLI->>DB: end_study_session()
    CLI->>IPC: Clear IPC files
    CLI->>TMUX: Switch to previous session
    CLI->>TMUX: Kill study session

    Note over U: Session dir preserved with .claude/ history
```

**Session directory structure:**
```
~/.config/studyctl/sessions/
  study-python-decorators-abc12345/
    .claude/          # Claude conversation history (preserved!)
  study-spark-internals-xyz98765/
    .claude/          # Separate conversation
```

**Resume flow:**
```bash
# tmux still alive → reattach
studyctl study --resume

# tmux dead, session dir preserved → rebuild + claude -r
studyctl study --resume
# Claude: "Last time we covered closures, you were about to..."
```

---

### 3. Review System — Spaced Repetition

```mermaid
flowchart TB
    subgraph "Content Sources"
        NLM["NotebookLM artefacts<br/>(quiz.json, flashcards.json)"]
        DIR["config.yaml<br/>review.directories[]"]
    end

    subgraph "Review Engine"
        LOAD["review_loader.py<br/>(discover + parse JSON)"]
        SM2["SM-2 Algorithm<br/>(ease_factor, interval_days)"]
        HASH["Card identity:<br/>SHA256(content)[:16]"]
    end

    subgraph "Interfaces"
        PWA["Web PWA<br/>(localhost:8567)"]
        RCLI["studyctl review<br/>(CLI due dates)"]
        MCP["MCP Server<br/>(agent tool access)"]
    end

    DB[(sessions.db<br/>card_reviews<br/>review_sessions)]

    NLM --> DIR
    DIR --> LOAD
    LOAD --> HASH
    HASH --> SM2
    SM2 --> DB
    DB --> PWA
    DB --> RCLI
    DB --> MCP
```

**Web PWA features:**
- Flashcard flip (Space), answer (Y/N), read aloud (T)
- Source/chapter filter, card count limiter
- 90-day study heatmap
- Pomodoro timer with audio chime
- OpenDyslexic font toggle, dark/light theme
- Installable as PWA on phone/tablet

---

### 4. Session Intelligence — Cross-Session Learning

```mermaid
flowchart LR
    subgraph "AI Sessions"
        CC["Claude Code"]
        KI["Kiro CLI"]
        GE["Gemini CLI"]
    end

    subgraph "Export"
        EX["session-export<br/>(incremental, per-source)"]
    end

    subgraph "Query"
        FTS["FTS5 Full-Text Search<br/>(BM25 ranking)"]
        CTX["Context Export<br/>(markdown/xml/summary)"]
        CONT["Continue<br/>(resume/branch/summarize)"]
    end

    subgraph "Sync"
        PUSH["session-sync push"]
        PULL["session-sync pull"]
    end

    DB[(sessions.db)]
    REMOTE[(Remote DB<br/>via SSH)]

    CC -->|"~/.claude/projects/"| EX
    KI --> EX
    GE -->|"~/.gemini/tmp/"| EX
    EX --> DB

    DB --> FTS
    DB --> CTX
    DB --> CONT

    DB -->|"SQL delta over SSH"| PUSH --> REMOTE
    REMOTE -->|"SQL delta over SSH"| PULL --> DB
```

**Key commands:**
```bash
session-export                          # Import all AI sessions
session-query search "decorators"       # Full-text search
session-query context SESSION_ID        # Export for LLM consumption
session-query continue SESSION_ID       # Resume context
session-sync push mac-mini              # Push to remote
session-sync pull mac-mini              # Pull from remote
```

#### session-db-mcp — MCP Server for Session Access

A standalone MCP server exposing the session database to any MCP-compatible AI tool via stdio transport. Installed as part of `agent-session-tools`.

```mermaid
graph TB
    subgraph "AI Coding Tools"
        CC["Claude Code"]
        KC["Kiro CLI"]
        GC["Gemini CLI"]
        OC["OpenCode / Aider"]
    end

    subgraph "session-db-mcp<br/>(FastMCP, stdio)"
        S1["session_search<br/><i>FTS5 keyword search</i>"]
        S2["session_list<br/><i>Chronological browse</i>"]
        S3["session_show<br/><i>Full session content</i>"]
        S4["session_context<br/><i>Token-efficient excerpts</i>"]
        S5["session_stats<br/><i>DB statistics</i>"]
        S6["session_clean<br/><i>Secret scrubbing</i>"]
        S7["session_hotspots<br/><i>File access frequency</i>"]
    end

    subgraph "Data Layer"
        DB[(sessions.db<br/>SQLite WAL v19)]
        FTS["messages_fts<br/>(FTS5 porter)"]
        FR["file_references"]
        SL["scrub_log"]
    end

    CC -->|"MCP stdio"| S1
    KC -->|"MCP stdio"| S1
    GC -->|"MCP stdio"| S1
    OC -->|"MCP stdio"| S1

    S1 --> FTS
    S2 --> DB
    S3 --> DB
    S4 --> DB
    S5 --> DB
    S6 --> SL
    S7 --> FR
```

**Tool reference:**

| Tool | Type | Description |
|------|------|-------------|
| `session_search` | read-only | FTS5 keyword search with porter stemming. Supports AND/OR/NOT. Filter by `source`, `project` |
| `session_list` | read-only | List sessions chronologically with pagination. Filter by `source`, `project` |
| `session_show` | read-only | Full session with all messages. Supports partial ID prefix matching |
| `session_context` | read-only | Token-efficient excerpts: `compressed` (~35%), `summary` (~20%), `context_only` (~25%), `markdown`, `xml`. Respects `max_tokens` budget |
| `session_stats` | read-only | Total sessions/messages, sources breakdown, date range, storage size |
| `session_clean` | destructive | Scrub secrets (API keys, tokens, credentials) with format-preserving placeholders. `dry_run=True` default; audit trail in `scrub_log` |
| `session_hotspots` | read-only | Most-discussed files ranked by reference count. Filter by `project`, `days` |

**Architecture:**

```mermaid
graph LR
    subgraph "mcp_server.py"
        MCP["FastMCP server"]
        T["7 tool functions"]
    end

    subgraph "Core Modules<br/>(one-way imports)"
        QU["query_utils.py"]
        QL["query_logic.py"]
        FM["formatters.py"]
        SC["scrubber.py"]
        FH["file_hotspots.py"]
        CL["config_loader.py"]
    end

    MCP --> T
    T --> QU
    T --> QL
    T --> FM
    T --> SC
    T --> FH
    T --> CL
```

**Registration:**
```json
{
  "mcpServers": {
    "session-db": {
      "command": "session-db-mcp"
    }
  }
}
```

**Usage examples:**
```python
# Search past work
session_search(query="JWT middleware", source="claude_code", limit=5)

# Token-efficient context for reuse
session_context(session_id="sess-auth", format="compressed", max_tokens=2000)

# Most-discussed files this week
session_hotspots(days=7, limit=10)

# Audit secrets before sharing
session_clean(session_id="sess-abc123", dry_run=True)
```

---

### 5. Agent Protocol — How AI Mentors Behave

```mermaid
flowchart TB
    subgraph "Shared Protocols"
        SP["session-protocol.md<br/>(session lifecycle)"]
        SE["socratic-engine.md<br/>(70/30 questioning)"]
        AF["audhd-framework.md<br/>(energy/emotion/sensory)"]
        BS["break-science.md<br/>(energy-adaptive breaks)"]
        KB["knowledge-bridging.md<br/>(domain analogies)"]
        TB["teach-back-protocol.md<br/>(5-dimension scoring)"]
        WD["wind-down-protocol.md<br/>(end-of-session)"]
    end

    subgraph "Personas"
        PS["study.md<br/>(Socratic, agent drives)"]
        PC["co-study.md<br/>(companion, user drives)"]
    end

    subgraph "Per-Agent Config"
        CLAUDE["agents/claude/<br/>socratic-mentor.md"]
        GEMINI["agents/gemini/<br/>study-mentor.md"]
        KIRO["agents/kiro/<br/>rules"]
    end

    SP --> PS
    SP --> PC
    SE --> PS
    SE --> PC
    AF --> PS
    AF --> PC
    BS --> PS
    KB --> PS
    TB --> PS
    WD --> PS

    PS --> CLAUDE
    PC --> CLAUDE
    PS --> GEMINI
    PS --> KIRO
```

---

### 6. Autoresearch Harness — Self-Improving Quality Loop

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch): define a metric, iterate autonomously, keep improvements, discard regressions. Applied to both **code correctness** and **teaching effectiveness**.

```mermaid
graph TB
    subgraph "Test Matrix (42 tests)"
        AGENTS["6 Agent Adapters<br/>claude, gemini, kiro,<br/>opencode, ollama, lmstudio"]
        TESTS["7 Lifecycle Checks<br/>start, launch, topic resolution,<br/>briefing, topics, end, flashcards"]
        AGENTS --> TESTS
    end

    subgraph "Iterate Runner"
        RUN["Run pytest<br/>(JUnit XML)"]
        PARSE["Parse results"]
        TSV["Log to results.tsv"]
        DECIDE{All pass?}
        REPORT["Failure report<br/>with source context"]
        DONE["Done"]

        RUN --> PARSE --> TSV --> DECIDE
        DECIDE -->|yes| DONE
        DECIDE -->|no| REPORT --> RUN
    end

    subgraph "Persona Effectiveness"
        HASH["SHA-256 persona hash<br/>stored at session start"]
        COUNTS["win_count + struggle_count<br/>extracted at session end"]
        QUERY["get_persona_effectiveness()<br/>win rate per persona version"]
        CLI["studyctl session effectiveness"]

        HASH --> QUERY
        COUNTS --> QUERY
        QUERY --> CLI
    end

    TESTS --> RUN
    COUNTS -.->|"future: Tier 2"| RUN
```

**What it tracks:**

| Metric | Source | Purpose |
|--------|--------|---------|
| Test pass/fail per agent | `results.tsv` (iterate runner) | Code correctness over time |
| Persona hash | `study_sessions.persona_hash` | Links persona version to outcomes |
| Win count | `study_sessions.win_count` | Structured outcome (was text-only) |
| Struggle count | `study_sessions.struggle_count` | Structured outcome (was text-only) |
| Win rate | `win_count / (win_count + struggle_count)` | Teaching effectiveness per persona |

**Usage:**

```bash
# Run the test matrix
uv run python scripts/test_iterate.py --no-git-check

# View iteration history
uv run python scripts/test_iterate.py --progress

# View persona effectiveness
studyctl session effectiveness
```

**Future (Tier 2):** The iterate runner can target persona templates instead of code — run simulated study sessions against fixed scenarios, measure teaching quality, keep/discard persona changes via git. The infrastructure is ready; the evaluation harness is the next step.

---

## Data Stores

| Store | Location | What's in it |
|-------|----------|-------------|
| `sessions.db` | `~/.config/studyctl/sessions.db` | Study sessions, card reviews, progress tracking, teach-back scores, knowledge bridges, concepts |
| `config.yaml` | `~/.config/studyctl/config.yaml` | Topics, Obsidian paths, notebook IDs, medication timing, knowledge domains |
| `state.json` | `~/.local/share/studyctl/state.json` | Sync state (per-file hashes, last sync timestamps) |
| Session dirs | `~/.config/studyctl/sessions/` | Per-session `.claude/` conversation history |
| IPC files | `~/.config/studyctl/session-*.{json,md}` | Live session state (transient, cleared on end) |
| Artefacts | Alongside source PDFs | Downloaded NotebookLM audio/video/quiz/flashcard files |

---

## End-to-End Workflow Example

Here's a complete workflow from course materials to mastery:

```
1. PREPARE MATERIALS
   ─────────────────
   Take notes in Obsidian → studyctl content from-obsidian ./notes/
   OR: Have a PDF textbook → studyctl content process textbook.pdf

   Result: chapters uploaded to NotebookLM, artefacts generated

2. REVIEW ARTEFACTS
   ─────────────────
   Listen to NotebookLM audio overviews (podcast-style)
   Download quiz + flashcard JSON to review directory

3. STUDY WITH AI MENTOR
   ─────────────────────
   studyctl study "Python Decorators" --energy 7

   → tmux opens with Claude as Socratic mentor
   → Sidebar shows timer, activity, counters
   → Agent asks questions, tracks wins/struggles
   → Park tangential topics for later
   → Quit Claude when done (auto-cleanup)

4. REVIEW FLASHCARDS
   ──────────────────
   studyctl web → open localhost:8567

   → SM-2 surfaces due cards
   → Review on phone/tablet (PWA)
   → Track accuracy over time

5. TRACK PROGRESS
   ───────────────
   studyctl streaks        → study consistency
   studyctl wins           → mastered concepts
   studyctl struggles      → recurring trouble spots
   studyctl resume         → last session context

6. SYNC ACROSS MACHINES
   ─────────────────────
   session-sync push mac-mini   → push session history
   session-sync pull laptop     → pull on another machine

7. RESUME NEXT DAY
   ────────────────
   studyctl study --resume

   → Claude picks up conversation: "Last time we covered..."
```

---

## Prerequisites

| Component | Required | Install |
|-----------|----------|---------|
| Python 3.12+ | Yes | `mise install python` or system package |
| tmux 3.1+ | For `studyctl study` | `brew install tmux` / `apt install tmux` |
| ttyd | Optional — remote terminal (`--lan`) | `brew install ttyd` / `apt install ttyd` |
| Claude Code | For AI study sessions | `npm install -g @anthropic-ai/claude-code` |
| pandoc | For markdown to PDF | `brew install pandoc` |
| typst | For PDF rendering | `brew install typst` |
| PyMuPDF | For PDF splitting | `pip install 'studyctl[content]'` |
| notebooklm-py | For NotebookLM API | `pip install 'studyctl[notebooklm]'` |
| Textual | For TUI sidebar | `pip install 'studyctl[tui]'` |
| FastAPI + uvicorn | For web UI | `pip install 'studyctl[web]'` |

```bash
# Install everything
pip install 'studyctl[all]'

# Or just what you need
pip install studyctl                    # CLI + review only
pip install 'studyctl[tui,web]'        # + sidebar + web dashboard
pip install 'studyctl[content]'        # + PDF pipeline
```
