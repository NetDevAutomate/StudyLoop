# Current Architecture

> Last updated: 2026-06-02. Reflects the ACP chat-UI feature (2026-05-27) + dogfood hotfix (`bfe9210`), the Settings → LLM Providers panel with first-class Bedrock/Ollama + an encrypted secret store, the Anthropic-compat adapter robustness work (MiniMax was trialled then removed for quiz quality), the scalable (mode-split, publisher-grouped, searchable) course-review list, the opt-in Obsidian session-memory export (`session-export --obsidian`), the in-browser neural TTS engine, Course Explorer side panel (Phases 1–6), generation-control honesty (`count_per_source` through `GenerationTask.count`), Explorer tree fingerprint caching, DB/FTS integrity coverage, and route-stubbed browser smoke coverage.

This document describes the system as it works today, using the [C4 model](https://c4model.com/) at three levels of zoom: Context → Container → Component (focused on the ACP chat, Generate, and Review surfaces).

For the planned direction, see [Target Architecture](target.md).

---

## C4 Level 1 — System Context

StudyLoop is single-user and runs primarily on one host. External systems are
the AI agent CLIs (Kiro, Claude Code, Gemini, Codex, OpenCode), optional
generation providers, and the first-run browser TTS model fetch.

```mermaid
flowchart TB
    Learner["Learner<br/>(AuDHD, self-taught)"]

    subgraph "On the learner's machine"
      StudyLoop["StudyLoop<br/>(this system)<br/>──────────<br/>Local-first study tool —<br/>session orchestration,<br/>review, and progress."]
    end

    subgraph "AI agent CLIs (separate processes)"
      Kiro["Kiro CLI<br/>(supports ACP)"]
      Gemini["Gemini CLI<br/>(supports ACP)"]
      Claude["Claude Code<br/>(PTY only)"]
      Codex["Codex CLI<br/>(PTY only)"]
      OpenCode["OpenCode<br/>(PTY only)"]
    end

    subgraph "Optional generation providers"
      OpenAI["OpenAI"]
      OpenRouter["OpenRouter"]
      GeminiAPI["Gemini API"]
      Anthropic["Anthropic"]
      Ollama["Ollama<br/>(local LLM)"]
      Bedrock["AWS Bedrock<br/>(cloud LLM)"]
    end

    subgraph "Model hosting (first-run only)"
      HF["Hugging Face<br/>(Kokoro-82M TTS weights,<br/>fetched by the browser,<br/>then cached on-device)"]
    end

    Learner -->|"studyloop study<br/>or browser"| StudyLoop
    StudyLoop -->|"ACP / JSON-RPC<br/>over stdio"| Kiro
    StudyLoop -->|"ACP / JSON-RPC<br/>over stdio"| Gemini
    StudyLoop -->|"PTY / raw bytes"| Claude
    StudyLoop -->|"PTY / raw bytes"| Codex
    StudyLoop -->|"PTY / raw bytes"| OpenCode
    StudyLoop -.->|"flashcard /<br/>quiz generation"| OpenAI
    StudyLoop -.->|"flashcard /<br/>quiz generation"| OpenRouter
    StudyLoop -.->|"flashcard /<br/>quiz generation"| GeminiAPI
    StudyLoop -.->|"flashcard /<br/>quiz generation"| Anthropic
    StudyLoop -.->|"flashcard /<br/>quiz generation"| Ollama
    StudyLoop -.->|"flashcard /<br/>quiz generation"| Bedrock
    Learner -.->|"browser fetches TTS model<br/>(first run, then offline)"| HF
```

**Trust boundaries** — the learner controls a single-user local StudyLoop
process, but optional providers can create outbound calls. The outbound surfaces
are (a) the agent CLI's own model calls (the agent owns those creds and policy),
(b) optional content generation via OpenAI, OpenRouter, Gemini, Anthropic, AWS
Bedrock, or Ollama on a configured local/remote endpoint, and (c) a first-run
browser fetch of the in-browser TTS model weights from Hugging Face (cached
on-device thereafter; voice synthesis itself is fully local and does not send
review text to a TTS API). StudyLoop does not phone home.

---

## C4 Level 2 — Containers

Inside the StudyLoop boundary the work is split across several long-running processes plus the agent subprocess.

```mermaid
flowchart TB
    Learner["Learner"]

    subgraph "Browser"
      PWA["PWA<br/>(Alpine + HTMX)<br/>──────────<br/>Picker, dashboard,<br/>chat surface,<br/>flashcard / quiz review."]
    end

    subgraph "studyloop web (Python / FastAPI / uvicorn)"
      API["HTTP + WebSocket API<br/>──────────<br/>/api/session/start<br/>/api/session/ws<br/>/api/session/end<br/>SSE for activity feed"]
      ExplorerAPI["Explorer API<br/>──────────<br/>/api/explorer/tree<br/>/api/explorer/courses/{id}/lessons<br/>/api/explorer/lesson/{id}/content<br/>/api/explorer/search"]
      Runtime["SessionRuntime<br/>──────────<br/>Active-session singleton.<br/>Owns the transport.<br/>Forwards events to WS."]
      ACP["ACPTransport<br/>──────────<br/>JSON-RPC over stdio.<br/>session/new,<br/>session/prompt,<br/>session/update,<br/>session/request_permission."]
      PTY["PTYTransport<br/>──────────<br/>Raw bytes,<br/>WINSZ ioctl,<br/>SIGCHLD-driven exit."]
      Agent["Agent subprocess<br/>──────────<br/>kiro-cli acp /<br/>gemini --acp /<br/>claude / codex / opencode"]
    end

    subgraph "Local stores"
      DB[("sessions.db<br/>(SQLite + WAL)<br/>──────────<br/>study sessions,<br/>progress, review state.")]
      FTS[("explorer_fts.db<br/>(SQLite FTS5)<br/>──────────<br/>derived lesson index;<br/>rebuildable cache,<br/>no migration.")]
      IPC["~/.config/studyloop/<br/>session-state.json<br/>session-topics.md<br/>session-parking.md"]
      Persona["agents/shared/personas/*<br/>(canonical persona text)"]
      AgentMemory[("AgentMemory/<br/>(Obsidian vault)<br/>──────────<br/>Markdown notes,<br/>Dataview frontmatter,<br/>[[wikilinks]], MOC index.")]
    end

    subgraph "agent-session-tools (CLI)"
      Export["session-export<br/>──────────<br/>Exports agent CLI sessions<br/>to sessions.db (incremental)."]
      ObsidianWriter["ObsidianWriter<br/>obsidian_writer.py<br/>──────────<br/>--obsidian (opt-in): one note<br/>per session to AgentMemory/.<br/>Idempotent (content-hash skip),<br/>per-project MOC, path-hardened."]
    end

    Learner --> PWA
    PWA -->|"HTTP /api/*"| API
    PWA <-->|"WebSocket /api/session/ws"| API
    PWA -->|"HTTP /api/explorer/*<br/>/api/history/struggling-topics"| ExplorerAPI
    API --> Runtime
    Runtime -->|"transport.start()"| ACP
    Runtime -->|"transport.start()"| PTY
    ACP -->|"asyncio.create_subprocess_exec"| Agent
    PTY -->|"openpty + execvpe"| Agent
    API --> DB
    API --> IPC
    API -->|"build_canonical_persona"| Persona
    ExplorerAPI -->|"reads source markdown"| Persona
    ExplorerAPI --> FTS
    ExplorerAPI --> DB
    Export --> DB
    Export -.->|"after commit, if --obsidian"| ObsidianWriter
    ObsidianWriter --> AgentMemory
    ObsidianWriter -.->|"reads titles for<br/>[[wikilink]] backlinks"| AgentMemory
```

**Key invariants today**:

- **One active session at a time.** `SessionRuntime` is a singleton acquired under `asyncio.Lock`. `/api/session/start` returns 409 if a session is already live.
- **Transport selection is explicit per session.** Body field `transport: "pty" | "ttyd" | "acp"`. The env var `STUDYLOOP_TRANSPORT` can force `pty`/`ttyd` as an operator kill-switch (ACP is body-only).
- **Persona text never reaches the wire on the PTY path** — it's written to a temp file, the agent's launch command embeds the path, and the agent reads it at startup.
- **Persona text DOES travel on the wire on the ACP path** — added 2026-05-28 in commit `bfe9210`. `/api/session/start` returns `persona_text` inline in the JSON body; the browser ships it as the first invisible `session/prompt` after WS open. Hidden client-side: not pushed to `acpMessages`.
- **The PWA owns chat-surface state.** The server never sends server-rendered HTML for chat bubbles — only raw ACP events. Markdown rendering, sanitisation, syntax highlighting, theme palette: all in the browser.

---

## C4 Level 3 — Component (zoomed into the ACP chat surface)

This is the part of the system that the dogfood hotfix touched. It has two halves — the server-side dispatcher and the browser-side Alpine component — connected by the WebSocket frame contract.

```mermaid
flowchart TB
    subgraph "Browser — Alpine `liveAgentConsole` component (index.html)"
      direction TB
      Picker["Session picker<br/>POST /api/session/start"]
      Mount["_mountAcpChat(detail)<br/>──────────<br/>Sets terminalMode='acp-chat'<br/>and resets chat state."]
      OpenWS["_openWebSocket(detail)<br/>──────────<br/>WS open handler:<br/>1. set acpSending=true<br/>2. set personaSetupInFlight=true<br/>3. send persona_text invisibly<br/>4. (do NOT push to acpMessages)"]
      Dispatch["WS message handler<br/>──────────<br/>frame.kind ∈<br/>{agent_chunk,<br/>tool_call,<br/>tool_call_update,<br/>plan, plan_update,<br/>request_permission,<br/>turn_end}"]
      Append["_appendAgentChunk(text)<br/>──────────<br/>Drops chunks while<br/>_suppressStreamingBubble=true.<br/>Otherwise accumulates msg.text."]
      Finalise["_finaliseStreamingBubble(reason)<br/>──────────<br/>If suppression flag set:<br/>clear flag + lock, return.<br/>Else: marked.parse +<br/>DOMPurify + hljs → msg.html"]
      Render["DOM<br/>──────────<br/>Typing indicator while streaming;<br/>marked-rendered bubble<br/>after turn_end."]
    end

    subgraph "Server — FastAPI WS route + ACP transport"
      direction TB
      Route["/api/session/ws<br/>──────────<br/>Origin gate, study_session_id<br/>match, then bidirectional<br/>asyncio.TaskGroup pump."]
      Transport["ACPTransport<br/>(packages/.../session/transports/acp.py)"]
      DispatchFrame["_dispatch_frame<br/>──────────<br/>Translates JSON-RPC frames<br/>from agent stdout into<br/>AgentMessage events."]
      AgentProc["kiro-cli acp / gemini --acp<br/>(subprocess, JSON-RPC over stdio)"]
    end

    Picker --> Mount --> OpenWS
    OpenWS -->|"ws.send invisible<br/>session/prompt"| Route
    Route -->|"forwards as bytes"| Transport
    Transport -->|"writes JSON-RPC line"| AgentProc
    AgentProc -->|"reads stdout"| Transport
    Transport -->|"AgentMessage events"| DispatchFrame
    DispatchFrame -->|"WS frames"| Route
    Route -->|"WS message"| Dispatch
    Dispatch --> Append
    Dispatch --> Finalise
    Append --> Render
    Finalise --> Render
```

**Persona-injection turn (the part the hotfix wired up)**:

```mermaid
sequenceDiagram
    actor User
    participant PWA as Browser PWA
    participant API as FastAPI
    participant Runtime as SessionRuntime
    participant ACP as ACPTransport
    participant Agent as kiro-cli acp

    User->>PWA: pick topic + agent + ACP transport
    PWA->>API: POST /api/session/start
    API->>API: build_canonical_persona(topic, energy)
    API-->>PWA: 201 {ws_url, persona_text, persona_hash, …}
    PWA->>API: WS open /api/session/ws?study_session_id=…
    API->>Runtime: forward WS open
    Runtime->>ACP: transport.start()
    ACP->>Agent: spawn subprocess
    ACP->>Agent: initialize (JSON-RPC)
    ACP->>Agent: session/new
    Agent-->>ACP: sessionId

    Note over PWA: WS "open" handler fires
    PWA->>PWA: _suppressStreamingBubble = true<br/>personaSetupInFlight = true<br/>acpSending = true<br/>(setup banner visible)
    PWA->>API: WS frame {type:"input", data: persona_text}
    API->>ACP: send_input(persona_text)
    ACP->>Agent: session/prompt(persona_text)

    loop Persona turn
      Agent->>ACP: session/update agent_chunk*
      Agent->>ACP: session/update tool_call*
      Agent->>ACP: session/request_permission*
      ACP->>API: AgentMessage frames
      API->>PWA: WS frames
      PWA->>PWA: drop chunks (suppression)<br/>drop tool_call cards<br/>auto-allow permissions
    end

    Agent-->>ACP: session/prompt response (stopReason)
    ACP->>API: AgentMessage(turn_end)
    API->>PWA: WS frame turn_end
    PWA->>PWA: _suppressStreamingBubble = false<br/>personaSetupInFlight = false<br/>acpSending = false<br/>(setup banner hidden)

    Note over PWA: Input now enabled — first user turn
    User->>PWA: type question, Enter
    PWA->>PWA: push user bubble to acpMessages
    PWA->>API: WS frame {type:"input", data: question}
    API->>ACP: send_input(question)
    ACP->>Agent: session/prompt(question)

    loop User turn
      Agent->>ACP: session/update agent_chunk*
      ACP->>API: AgentMessage(agent_chunk)
      API->>PWA: WS frame
      PWA->>PWA: accumulate msg.text<br/>(typing indicator visible)
    end

    Agent-->>ACP: session/prompt response (stopReason)
    ACP->>API: AgentMessage(turn_end)
    API->>PWA: WS frame turn_end
    PWA->>PWA: marked.parse + DOMPurify + hljs<br/>→ acp-message-final bubble<br/>typing indicator hidden
```

**Why suppression exists**: the persona instructs the agent to read IPC files (`session-state.json`, `session-topics.md`, `session-parking.md`) for context. On a fresh session those reads happen as bash tool calls (Kiro auto-approves them today, but the protocol ALSO supports `request_permission`). Without suppression the user would see `▼ ? completed`/`▼ ? failed` cards before they had a chance to type — confusing UX. The fix:

- `agent_chunk` text: dropped (no ack scrolls past).
- `tool_call`, `tool_call_update`: dropped (no cards rendered).
- `plan`, `plan_update`: dropped (no plan tree rendered).
- `request_permission`: auto-allowed with `allow_once`-equivalent (no permission prompt shown to user).

All four are gated on a single non-reactive flag `this._suppressStreamingBubble`, set true on WS-open persona send, cleared on the persona-turn `turn_end`.

---

## Component → file map (for the chat surface)

| Component | File | Notable lines |
|---|---|---|
| Picker / `study-session-start` event | `packages/studyloop/src/studyloop/web/static/index.html` | ~1138 |
| `_mountAcpChat` | `index.html` | ~1585 |
| `_openWebSocket` (incl. invisible-persona send) | `index.html` | ~1601 |
| WS message dispatcher (frame.kind switch) | `index.html` | ~1670 |
| `_appendAgentChunk` (suppression on streaming) | `index.html` | ~1752 |
| `_finaliseStreamingBubble` (suppression on turn_end) | `index.html` | ~1775 |
| `_renderMarkdown` (marked → DOMPurify → hljs) | `index.html` | ~1787 |
| Setup banner DOM | `index.html` | ~828 |
| Typing indicator + final bubble DOM | `index.html` | ~836 |
| Theme palettes (CSS vars) | `packages/studyloop/src/studyloop/web/static/style.css` | end of file |
| Settings store (palette, dyslexic, light) | `packages/studyloop/src/studyloop/web/static/components.js` | ~43 |
| `/api/session/start` (ACP path) | `packages/studyloop/src/studyloop/web/routes/session.py` | ~687 |
| Persona injection backend | `packages/studyloop/src/studyloop/web/routes/session.py` | ~783 |
| ACPTransport `_dispatch_frame` | `packages/studyloop/src/studyloop/session/transports/acp.py` | — |
| Live Kiro Playwright test (regression fence) | `packages/studyloop/tests/test_web_acp_dogfood_kiro.py` | full file |
| Stub-driven chat-UI e2e | `packages/studyloop/tests/test_web_acp_chat_ui.py` | full file |

---

## Component → file map (for the Obsidian session-memory export)

The export path is a CLI feature in `agent-session-tools`, independent of the web
surface. It runs after `session-export` commits to `sessions.db`, only when
`--obsidian` is passed (or `obsidian.export_enabled: true` in config).

| Component | File | Notes |
|---|---|---|
| `write_vault_notes` / `write_session_to_vault` / `write_moc` / `build_topic_index` | `packages/agent-session-tools/src/agent_session_tools/obsidian_writer.py` | core writer; idempotent, path-traversal hardened |
| `--obsidian*` flags + post-commit hook | `packages/agent-session-tools/src/agent_session_tools/export_sessions.py` | `_run_export`: touched-ID diff (incremental) vs all (`--obsidian-backfill`) |
| `get_obsidian_config` + `obsidian` defaults | `packages/agent-session-tools/src/agent_session_tools/config_loader.py` | reads `obsidian:` section from shared `config.yaml` |
| `ObsidianConfig` dataclass + `Settings.obsidian` | `packages/studyloop/src/studyloop/settings.py` | studyloop-side view of the same section; `vault_path` defaults to `obsidian_base` |
| Install prompt (Step 4) | `packages/studyloop/src/studyloop/cli/_setup.py` | `studyloop setup` offers to enable export |
| `check_obsidian_vault` (+.obsidian/ marker) + `check_obsidian_export` | `packages/studyloop/src/studyloop/doctor/config.py` | `studyloop doctor` health checks |
| Writer tests | `packages/agent-session-tools/tests/test_obsidian_writer.py` | 54 tests incl. idempotency, backfill-vs-incremental, traversal |

---

## C4 Level 3 — Component (zoomed into the Generate panel)

Sister surface to the chat surface. The Generate panel reuses the existing `content/generators/` package as its producer; the new layer is the orchestrator + the active-generation singleton + the REST + WS endpoints + the sidebar UI. **All shipped on `main` as of 2026-05-29** — backend, HTTP surface, and browser side.

```mermaid
C4Component
  title Component Diagram - Generate Panel And Struggle Scope

  Container(browser, "Browser UI", "Alpine.js", "Generate tab and Course Explorer")
  Container(api, "FastAPI Web App", "Python", "REST and WebSocket routes")
  ContainerDb(sessionDb, "sessions.db", "SQLite", "Study progress and struggle provenance")
  ContainerDb(contentBase, "content.base_path", "Markdown + JSON", "Source lessons and generated decks")

  Component(genRoutes, "content_gen routes", "FastAPI", "Plans jobs and streams progress")
  Component(activeGen, "active_gen singleton", "Python", "Allows one generation job at a time")
  Component(scopeResolver, "resolve_scope", "Python", "Resolves course, section, and topic_struggles")
  Component(jobRunner, "run_job", "Python", "Builds GenerationTask(count) and writes outputs")
  Component(generator, "CardGenerator adapters", "Python", "Provider prompts, schema validation, and retry")
  Component(historyRoutes, "history routes", "FastAPI", "Writes struggling-topic provenance")

  Rel(browser, genRoutes, "Starts generation with count_per_source", "JSON/HTTPS")
  Rel(genRoutes, activeGen, "Acquires active slot")
  Rel(genRoutes, jobRunner, "Starts async background lifecycle")
  Rel(jobRunner, activeGen, "Releases slot in background finally block")
  Rel(jobRunner, scopeResolver, "Resolves selected scope")
  Rel(scopeResolver, sessionDb, "Reads topic_struggles via study_progress", "SQLite")
  Rel(jobRunner, generator, "Requests GenerationTask.count per source")
  Rel(generator, contentBase, "Reads source markdown", "Filesystem")
  Rel(jobRunner, contentBase, "Writes flashcards/quizzes", "Filesystem")
  Rel(browser, historyRoutes, "Marks lesson as struggling", "JSON/HTTPS")
  Rel(historyRoutes, sessionDb, "Writes source_course/source_section", "SQLite")
```

The dynamic flow below shows the same job from the user's click through REST,
background execution, provider prompt generation, and WebSocket progress frames.

```mermaid
flowchart TB
    subgraph Browser["Browser — Generate sidebar tab (U8)"]
      direction TB
      Form["Form view<br/>──────────<br/>Course / Scope / Section /<br/>Topic / Window / Kinds /<br/>Count / Provider / Model /<br/>On-existing"]
      RestCall["POST /api/content/generate<br/>(202 -> job_id)"]
      WsOpen["WS /api/content/generate/ws<br/>?job_id=..."]
      ProgressUI["Progress renderer<br/>──────────<br/>started / task_complete /<br/>all_done frames"]
    end

    subgraph Backend["Server — FastAPI"]
      direction TB
      Routes["content_gen router<br/>(U5 REST + U7 WS)"]
      Discover["Course / Section /<br/>Topic / Provider lookups<br/>(U9 / U10 / U10.5 +<br/>/api/content/courses)"]
      Single["active_gen singleton<br/>(content/active_gen.py)"]
      Job["run_job orchestrator<br/>(content/job.py)<br/>builds GenerationTask.count"]
      Scope["resolve_scope<br/>(content/scope.py)<br/>course / section /<br/>topic_struggles"]
      Runner["generate_concurrently<br/>(generators/runner.py)"]
      Factory["get_generator<br/>(generators/__init__.py)"]
      Adapters["StubGenerator<br/>OllamaGenerator<br/>BedrockGenerator<br/>OpenAICompatGenerator<br/>AnthropicCompatGenerator<br/>provider prompts + validation"]
      Secrets["secrets.get_secret(slug)<br/>──────────<br/>encrypted store → env.<br/>auth_kind: api_key /<br/>bedrock_bearer / local_keyless"]
      Helpers["on-existing helpers<br/>(storage.next_unique_path,<br/>FlashcardDeck.merge_dedupe,<br/>QuizDeck.merge_dedupe)"]
    end

    Store[("~/.config/studyloop/<br/>secrets.bin (Fernet)")]
    Disk[("content.base_path/<br/>&lt;course&gt;/ or<br/>&lt;publisher&gt;/&lt;course&gt;/<br/>flashcards/ + quizzes/")]
    Reviewer["/api/courses, /api/cards<br/>(review surface — see below)"]

    Form --> RestCall --> Routes
    Form --> WsOpen
    Routes -->|acquire| Single
    Routes -->|"asyncio.create_task"| Job
    Routes -->|on_event queue| WsOpen
    WsOpen --> ProgressUI

    Form -.populate.- Discover

    Job --> Scope
    Job --> Factory
    Factory --> Adapters
    Adapters -->|"resolve key/token"| Secrets
    Secrets -.reads.- Store
    Scope -.->|"topic_struggles reads"| StudyProgress[("sessions.db<br/>study_progress<br/>source_course/source_section")]
    Job -->|"GenerationTask(count)"| Runner
    Runner -->|"on_complete callback"| Job
    Job --> Helpers
    Helpers --> Disk
    Job -->|"release in async background lifecycle"| Single

    Disk -->|discovered by| Reviewer
```

**Job lifecycle (one click of Generate)**:

```mermaid
sequenceDiagram
    actor User
    participant PWA as Browser (Generate tab)
    participant REST as POST /api/content/generate
    participant Single as active_gen singleton
    participant Job as run_job (asyncio task)
    participant Scope as resolve_scope
    participant Runner as generate_concurrently
    participant Gen as Generator (OpenAI / Anthropic / Stub / ...)
    participant FS as content.base_path
    participant WS as WS /content/generate/ws

    User->>PWA: pick course/scope/kinds, click Generate
    PWA->>REST: POST {course, scope, kinds, count_per_source, provider, model, on_existing}
    REST->>Single: acquire(job_id, request)
    alt slot busy
      Single-->>REST: GenerationAlreadyActiveError
      REST-->>PWA: 409 Conflict
    else slot free
      Single-->>REST: ActiveGeneration
      REST->>Job: asyncio.create_task(run_job(...))
      REST-->>PWA: 202 {job_id, plan}

      PWA->>WS: open ?job_id=...
      WS-->>PWA: started {task_count, sources, kinds, count_per_source, provider, model}

      Job->>Scope: resolve_scope(request, settings)
      Scope-->>Job: list[ResolvedSource]
      Job->>Gen: get_generator(config)

      loop one task per source × kind
        Job->>Runner: generate_concurrently
        Runner->>Gen: generate_flashcards / generate_quiz with GenerationTask.count
        Gen-->>Runner: deck or CardGenerationError
        Runner->>Job: on_complete(result)
        Job->>FS: write_json (apply on_existing policy)
        Job-->>WS: task_complete {ok, path / error}
        WS-->>PWA: task_complete frame
      end

      Job-->>WS: all_done {written, failed}
      WS-->>PWA: all_done frame
      Job->>Single: release() in background finally block
    end
```

**Why a singleton + queue, not direct streaming**: a single Ollama process (or a rate-limited cloud token budget) doesn't tolerate two concurrent jobs. The singleton is the simplest possible coordinator -- one process, one heavy LLM job at a time. The per-job WS queue lets clients reconnect / resubscribe without losing events that fire during the gap.

---

## Component → file map (for the generation surface)

| Component | File | Notable lines |
|---|---|---|
| Active-generation singleton | `packages/studyloop/src/studyloop/content/active_gen.py` | full file |
| Job orchestrator (`run_job`) | `packages/studyloop/src/studyloop/content/job.py` | full file |
| Scope resolver (`resolve_scope`) | `packages/studyloop/src/studyloop/content/scope.py` | full file |
| Generator factory + Protocol | `packages/studyloop/src/studyloop/content/generators/__init__.py` | full file |
| Provider profile registry | `packages/studyloop/src/studyloop/content/generators/provider_profiles.py` | full file |
| Stub generator | `packages/studyloop/src/studyloop/content/generators/stub.py` | full file |
| OpenAI Chat Completions adapter | `packages/studyloop/src/studyloop/content/generators/openai_compat.py` | full file |
| Anthropic Messages adapter | `packages/studyloop/src/studyloop/content/generators/anthropic_compat.py` | full file |
| Shared retry-with-correction helper | `packages/studyloop/src/studyloop/content/generators/_retry.py` | full file |
| On-existing helpers (merge / unique-path) | `packages/studyloop/src/studyloop/content/{schemas,storage}.py` | `merge_dedupe`, `next_unique_path` |
| `.env` autoload | `packages/studyloop/src/studyloop/__init__.py` | full file |
| Encrypted secret store + auth-kind taxonomy | `packages/studyloop/src/studyloop/secrets.py` | `get_secret`, `set_secret`, `get_auth_kind` |
| Provider auth tests (Bedrock bearer / Ollama) | `packages/studyloop/src/studyloop/provider_auth.py` | full file |
| `live_provider` pytest marker | `packages/studyloop/pyproject.toml` | `[tool.pytest.ini_options]` |
| Live MVD smoke (parametrised over registry) | `packages/studyloop/tests/test_live_provider_smoke.py` | full file |
| MVD source fixture (photosynthesis) | `packages/studyloop/tests/fixtures/mvd_source.md` | full file |

---

## C4 Level 3 — Component (Review surface + Settings → LLM Providers)

The third browser surface: the **Flashcards/Quizzes review list** (where generated
decks are consumed) and the **Settings → LLM Providers** admin panel (where
generation credentials are managed). Both shipped on `main` 2026-06-01.

```mermaid
flowchart TB
    subgraph Browser["Browser — Alpine"]
      direction TB
      Review["reviewApp('flashcards' | 'quiz')<br/>──────────<br/>mode-split list.<br/>filteredCourses (mode + search),<br/>groupedCourses (by publisher),<br/>toggleGroup, searchQuery"]
      Settings["settingsPanel()<br/>──────────<br/>one row per provider,<br/>controls per auth_kind;<br/>Test &amp; save → live verify"]
    end

    subgraph Backend["Server — FastAPI"]
      direction TB
      Courses["GET /api/courses<br/>(+ publisher field)"]
      Cards["GET /api/cards/&lt;course&gt;"]
      Providers["GET /api/content/providers<br/>(auth_kind + availability)"]
      Test["POST /api/content/providers/&lt;slug&gt;/test"]
      SecretsRoute["POST/DELETE /api/content/secrets"]
      Resolve["settings.resolve_study_dirs()<br/>──────────<br/>review.directories,<br/>else content.base_path"]
      Discover["review_loader.discover_directories<br/>──────────<br/>recursive walk of<br/>&lt;publisher&gt;/&lt;course&gt; (depth 4),<br/>stops at first deck-bearing dir"]
      Auth["provider_auth + secrets<br/>──────────<br/>get_auth_kind, get_secret,<br/>test_bedrock_bearer / ollama"]
    end

    Disk[("content.base_path/<br/>&lt;course&gt;/ or<br/>&lt;publisher&gt;/&lt;course&gt;/<br/>flashcards/ + quizzes/")]
    Store[("~/.config/studyloop/<br/>secrets.bin")]

    Review -->|list| Courses
    Review -->|study| Cards
    Courses --> Resolve --> Discover --> Disk
    Cards --> Discover

    Settings -->|load| Providers
    Settings -->|verify| Test
    Settings -->|store/remove| SecretsRoute
    Providers --> Auth
    Test --> Auth
    SecretsRoute --> Store
    Auth -.reads.- Store
```

**Key points:**

- **Mode split** lives entirely in the shared `reviewApp` component: each panel is
  instantiated with its `mode` (`'flashcards'` or `'quiz'`), and `filteredCourses`
  gates the list on the matching count before the search filter. The Flashcards
  panel shows only flashcard decks (single Flashcards action); Quizzes mirrors.
- **Scaling** is `groupedCourses` (group `filteredCourses` by the API's new
  `publisher` field) + collapsible group headers + a name search box + compact
  one-line rows.
- **Write root ≠ read root.** CLI generation writes under
  `content.base_path/<course>/{flashcards,quizzes}/`; web generation writes under
  `content.base_path/<publisher>/<course>/{flashcards,quizzes}/` when a publisher
  is supplied. The reviewer reads via `resolve_study_dirs()`, which falls back to
  `content.base_path` when `review.directories` is unset, and
  `discover_directories` walks both layouts. (Before this, an unset
  `review.directories` silently left the panels empty.)
- **`name` is the identity key** for `/api/cards`, `openConfig`, and the SM-2
  review DB. `publisher` is display/grouping only — never keyed on.
- **Settings stores credentials only after a live verification** (auth call for
  api_key, AWS-cred check for Bedrock, real generation for Ollama), encrypted in
  `secrets.bin`. The same store backs the Generate panel's provider availability.

### Component → file map (Review + Settings)

| Component | File | Notable |
|---|---|---|
| Review list + mode-split + grouping/search | `web/static/index.html` (courses views) + `web/static/components.js` | `reviewApp`, `filteredCourses`, `groupedCourses`, `toggleGroup` |
| Settings panel | `web/static/index.html` (`settingsPanel()` block) + `components.js` | per-`auth_kind` rows |
| Course list + publisher field | `packages/studyloop/src/studyloop/services/review.py` | `list_course_summaries` |
| Read-root resolver | `packages/studyloop/src/studyloop/settings.py` | `resolve_study_dirs` |
| Recursive deck discovery | `packages/studyloop/src/studyloop/review_loader.py` | `discover_directories` |
| Course / cards routes | `packages/studyloop/src/studyloop/web/routes/courses.py`, `cards.py` | — |
| Providers / test / secrets routes | `packages/studyloop/src/studyloop/web/routes/content_gen.py` | `list_providers`, `/providers/{slug}/test`, `/secrets` |
| Scale + settings e2e | `tests/test_web_course_list_scale_e2e.py`, `tests/test_web_settings_panel_e2e.py` | geometry + behaviour |

---

## C4 Level 3 — Component (zoomed into in-browser neural TTS)

Shipped 2026-06-01. Voice output is a **browser-only** subsystem — there is no server-side TTS component for the web path. The page downloads a neural model once and synthesises speech on-device (WebGPU/WASM); StudyLoop's FastAPI server only serves the static engine module and the vendored ONNX-runtime WASM. This is the first part of the system that reaches an external network host (Hugging Face) directly from the browser.

```mermaid
flowchart TB
    subgraph Browser["Browser"]
      direction TB
      Settings["Alpine settings store<br/>(components.js)<br/>──────────<br/>speak() / stopSpeaking()<br/>isSpeaking, ttsDownloadPct<br/>listens: tts:state-change,<br/>tts:download-progress"]
      Review["reviewApp.speakCurrentCard()<br/>(T key / speaker button)"]
      Engine["ttsEngine singleton<br/>(tts-engine.js)<br/>──────────<br/>init() tier-select,<br/>speak(), stop(),<br/>listVoices()"]
      Tiers["Tier selection<br/>──────────<br/>1. neural-webgpu (navigator.gpu)<br/>2. neural-wasm (numThreads=1)<br/>3. web-speech (fallback)"]
      Kokoro["Kokoro-82M via transformers.js<br/>StyleTextToSpeech2Model<br/>+ AutoTokenizer + phonemizer"]
      ORT["onnxruntime-web<br/>wasmPaths → /vendor/js/<br/>(jsep WASM: webgpu + wasm)"]
      Audio["WebAudio<br/>──────────<br/>AudioBufferSourceNode;<br/>stop() halts source +<br/>settles play promise"]
      Cache[("Cache Storage<br/>'transformers-cache' (~92 MB)<br/>'kokoro-voices'<br/>──────────<br/>spared by sw.js self-destruct")]
    end

    subgraph Server["studyloop web (FastAPI StaticFiles)"]
      Static["/tts-engine.js<br/>/vendor/js/transformers-*.web.js<br/>/vendor/js/ort.all.bundle.min.mjs<br/>/vendor/js/ort-wasm-*.jsep.{wasm,mjs}"]
    end

    HF["Hugging Face<br/>(onnx-community/Kokoro-82M-v1.0-ONNX)<br/>model_quantized.onnx + voices"]

    Settings --> Engine
    Review --> Engine
    Engine --> Tiers
    Tiers --> Kokoro
    Kokoro --> ORT
    Engine --> Audio
    Engine -.->|"import (importmap)"| Static
    ORT -.->|"WASM from"| Static
    Kokoro -->|"first run only"| HF
    HF -->|"cached after 1st load"| Cache
    Cache -->|"subsequent loads (offline)"| Kokoro
    Engine -->|"events"| Settings
```

**Key invariants**:

- **No COOP/COEP headers.** `env.backends.onnx.wasm.numThreads = 1` + WebGPU preference means `SharedArrayBuffer` is never requested, so `SecurityHeadersMiddleware` is untouched and the same-origin ttyd iframe (which relies on `X-Frame-Options: SAMEORIGIN`) keeps working. This is a deliberate engine-choice constraint, not an oversight.
- **ORT WASM is pinned to vendored files.** `wasmPaths = '/vendor/js/'` stops transformers.js falling back to the jsdelivr CDN — which both breaks offline use and triggers a JS-glue/WASM version mismatch (`_OrtGetInputName is not a function`). The vendored `ort-wasm-simd-threaded.jsep.wasm` (23 MB, stored via Git LFS) serves both the webgpu and wasm execution providers.
- **Model persists across reloads.** `env.useBrowserCache = true` (the library default) stores the ~92 MB q8 model in Cache Storage. The PWA service worker's self-destruct handler explicitly spares `transformers-cache` and `kokoro-voices`, so a code-asset refresh never forces a re-download.
- **`stop()` is unified across tiers.** It halts the neural `AudioBufferSourceNode` (`.stop()` + `disconnect()`) AND settles the in-flight playback promise *before* suspending the AudioContext — a suspended context freezes the clock so `onended` never fires. Web-speech tier delegates to `speechSynthesis.cancel()`.
- **Browser → Hugging Face is TTS egress only.** First-run model fetch is the
  single direct browser-to-internet call for voice; optional content providers
  may also create outbound calls from the Python server during generation.
  Engine module and WASM assets are same-origin from FastAPI. After first load
  the model is served from Cache Storage and voice works fully offline.

### Component → file map (for the TTS surface)

| Component | File | Notable lines |
|---|---|---|
| TTS engine (singleton, tiers, speak/stop) | `packages/studyloop/src/studyloop/web/static/tts-engine.js` | full file |
| Settings store TTS wiring (speak / stopSpeaking / isSpeaking / download progress) | `packages/studyloop/src/studyloop/web/static/components.js` | ~44–200 |
| `reviewApp.speakCurrentCard()` | `components.js` | ~590 |
| Importmap + module load + stop button + progress bar | `index.html` | head (importmap) + header controls |
| Service-worker model-cache preservation | `packages/studyloop/src/studyloop/web/static/sw.js` | self-destruct handler |
| Vendored libs (LFS for `*.wasm`) | `packages/studyloop/src/studyloop/web/static/vendor/js/` | — |
| TTS contract + stop-control tests | `packages/studyloop/tests/test_web_tts.py` | full file |

---

## C4 Level 3 — Component (zoomed into the Course Explorer)

The Course Explorer is a read-only study-material browser embedded as a third layout column. It shares no reactive state with the session, review, or generate panels; the only write path is the struggle flag via `POST /api/history/struggling-topics`.

```mermaid
C4Component
  title Component Diagram - Course Explorer, Search Cache, And Struggle Provenance

  Container(browser, "Browser UI", "Alpine.js", "Course Explorer reader and Generate tab")
  Container(api, "FastAPI Web App", "Python", "Explorer and history routes")
  ContainerDb(contentBase, "content.base_path", "Markdown", "Provider/course/lesson source tree")
  ContainerDb(explorerFts, "explorer_fts.db", "SQLite FTS5", "Derived lesson search cache")
  ContainerDb(sessionDb, "sessions.db", "SQLite", "study_progress and provenance columns")

  Component(explorerComponent, "courseExplorer()", "Alpine.js", "Tree, reader, search, and struggle UI")
  Component(treeRoute, "GET /api/explorer/tree", "FastAPI", "Builds provider/course tree")
  Component(treeFingerprint, "tree fingerprint", "Python", "Cache key from visible source tree")
  Component(searchRoute, "GET /api/explorer/search", "FastAPI", "Refreshes and queries derived FTS")
  Component(historyRoute, "POST /api/history/struggling-topics", "FastAPI", "Writes web struggle provenance")
  Component(scopeResolver, "resolve_scope topic_struggles", "Python", "Uses provenance when generating targeted decks")

  Rel(browser, explorerComponent, "Opens Courses panel")
  Rel(explorerComponent, treeRoute, "Loads provider/course tree", "JSON/HTTPS")
  Rel(treeRoute, treeFingerprint, "Computes cache key")
  Rel(treeFingerprint, contentBase, "Stats visible providers/courses/source files", "Filesystem")
  Rel(explorerComponent, searchRoute, "Searches lesson bodies", "JSON/HTTPS")
  Rel(searchRoute, explorerFts, "Refreshes and queries", "SQLite FTS5")
  Rel(explorerFts, contentBase, "Indexes source markdown", "Filesystem")
  Rel(explorerComponent, historyRoute, "Marks lesson as struggling", "JSON/HTTPS")
  Rel(historyRoute, sessionDb, "Writes source_course/source_section/source_publisher", "SQLite")
  Rel(scopeResolver, sessionDb, "Reads provenance for topic_struggles", "SQLite")
```

The dynamic flow below shows the browser component and route-level work in more
detail.

```mermaid
flowchart TB
    subgraph Browser["Browser — Alpine `courseExplorer()` component"]
      direction TB
      Toggle["$store.explorer.toggle()<br/>──────────<br/>Opens 3rd column;<br/>adds .explorer-open to .app-layout"]
      TreeFetch["init() → GET /api/explorer/tree<br/>──────────<br/>Populates providers[]; cached by<br/>visible tree fingerprint.<br/>[] on missing base."]
      Carousel["Provider carousel row<br/>──────────<br/>CSS scroll-snap, data-carousel-id;<br/>filteredCourses(provider) per row;<br/>scrollCarousel() via querySelector"]
      LessonFetch["selectCourse(course)<br/>→ GET /api/explorer/courses/{id}/lessons<br/>──────────<br/>Lesson list below carousel"]
      Reader["openLesson(lesson)<br/>→ GET /api/explorer/lesson/{id}/content<br/>──────────<br/>_stripFrontmatter → renderMarkdown<br/>→ x-html (view='reader')"]
      MermaidPass["_renderMermaidPlaceholders(rootEl)<br/>──────────<br/>Second $nextTick pass;<br/>mermaid.render() per placeholder div"]
      SearchBox["onSearchInput() (debounced)<br/>──────────<br/>Fuse.js instant over titles +<br/>GET /api/explorer/search (FTS5 bodies);<br/>results grouped by provider"]
      StruggleBtn["markStruggle()<br/>→ POST /api/history/struggling-topics<br/>──────────<br/>confidence='struggling', created_by='web';<br/>surfaces in next deck gen scope"]
      TTSBtn["readAloud() / stopReading()<br/>──────────<br/>Gated: ttsAvailable = !!window.ttsEngine;<br/>button hidden when engine absent"]
    end

    subgraph Backend["Server — web/routes/explorer.py"]
      direction TB
      TreeRoute["GET /api/explorer/tree<br/>──────────<br/>_build_tree(base); app.state cache;<br/>[] on missing/empty base"]
      LessonsRoute["GET /api/explorer/courses/{course_id:path}/lessons<br/>──────────<br/>rglob walk; skip _OUTPUT_SUBDIRS;<br/>traversal guard (is_relative_to)"]
      ContentRoute["GET /api/explorer/lesson/{lesson_id:path}/content<br/>──────────<br/>Probe .md/.markdown/.txt in order;<br/>path-traversal + suffix allowlist;<br/>returns {content, lesson_id}"]
      SearchRoute["GET /api/explorer/search?q=&limit=20<br/>──────────<br/>_run_fts_search: lazy-build +<br/>incremental refresh;<br/>bm25 title>body, snippet excerpts"]
      TreeKey["_tree_fingerprint(base)<br/>──────────<br/>visible provider/course/source<br/>state; skips dot + output dirs"]
    end

    subgraph Stores["Stores"]
      ContentBase[("content.base_path/<br/>source markdown files<br/>(read-only)")]
      FTSDb[("explorer_fts.db<br/>──────────<br/>FTS5 virtual table;<br/>lesson_index_meta for mtimes;<br/>porter unicode61 tokenizer")]
      SessionDB[("sessions.db<br/>study_progress table<br/>source_course/source_section/<br/>source_publisher/created_by")]
    end

    Toggle --> TreeFetch
    TreeFetch --> Carousel
    Carousel --> LessonFetch
    LessonFetch --> Reader
    Reader --> MermaidPass
    SearchBox --> TreeFetch
    Reader --> StruggleBtn
    Reader --> TTSBtn

    TreeRoute --> TreeKey
    TreeKey --> ContentBase
    TreeRoute --> ContentBase
    LessonsRoute --> ContentBase
    ContentRoute --> ContentBase
    SearchRoute --> FTSDb
    FTSDb -.->|"indexes"| ContentBase
    StruggleBtn -->|"writes provenance"| SessionDB
```

**Key invariants**:

- **Read-only over content.** The explorer API never writes to `content.base_path`. Every content endpoint resolves paths with `is_relative_to(base)` and restricts suffixes to `.md`, `.markdown`, `.txt`.
- **Tree cache is keyed by visible source state.** `GET /api/explorer/tree` stores the provider/course tree on `app.state` behind `_tree_fingerprint(base)`, which walks visible providers, courses, and source files while skipping dot directories and generated output directories. Adding/deleting nested courses refreshes the tree; writing generated decks does not.
- **FTS index is a derived cache.** `explorer_fts.db` lives in `<session_db_dir>/` alongside `sessions.db` but is never opened by the session migration system. It can be deleted and will be rebuilt on the next search call. No schema migration is required.
- **TTS is gated by feature detection.** `ttsAvailable = !!window.ttsEngine`. The "▶ Listen" button is `x-show="ttsAvailable && activeLesson"` — hidden entirely when the `browser-neural-tts` worktree is not merged.
- **Struggle write reuses the existing pipeline.** `POST /api/history/struggling-topics` calls the same `record_progress()` / `get_struggling_topics()` helpers used by the agent session path and writes `source_course`, `source_section`, `source_publisher`, and `created_by='web'`. The Generate panel's "Topic I'm struggling on" scope sees the web-flagged rows with no extra plumbing and can resolve back to the lesson provenance instead of only a generic topic name.

### Component → file map (Course Explorer)

| Component | File | Notes |
|---|---|---|
| `courseExplorer()` Alpine factory | `packages/studyloop/src/studyloop/web/static/components.js` | ~line 932; owns all panel state |
| `renderMarkdown()` | `components.js` | ~line 44; top-level shared fn; marked → DOMPurify → hljs |
| `_stripFrontmatter()` | `components.js` | ~line 107; strips YAML front matter before render |
| `_renderMermaidPlaceholders()` | `components.js` | ~line 171; second-pass mermaid.render() after `$nextTick` |
| `_mdToPlainText()` | `components.js` | ~line 129; strips markdown to plain text for TTS |
| `<aside class="course-explorer-panel">` | `packages/studyloop/src/studyloop/web/static/index.html` | ~line 248; browser + reader views |
| Courses sidebar button + `$store.explorer` | `index.html` | ~line 225 (button), ~line 1686 (store) |
| Mermaid + Fuse.js `<script>` tags | `index.html` | ~line 39 (mermaid), ~line 48 (fuse) |
| `.course-explorer-panel`, `.explorer-*` CSS | `packages/studyloop/src/studyloop/web/static/style.css` | `.app-layout` 3rd column; 0px closed, 320px `.explorer-open`; hidden ≤600px |
| Explorer API router | `packages/studyloop/src/studyloop/web/routes/explorer.py` | all four endpoints; `_tree_fingerprint`; `_fts_lock` for single-writer FTS |
| Migration v22 | `packages/agent-session-tools/src/agent_session_tools/migrations.py` | ~line 736; adds `source_course`, `source_section`, `source_publisher`, `created_by` to `study_progress` |
| `record_progress()` (provenance args) | `packages/studyloop/src/studyloop/history/progress.py` | keyword-only provenance args; back-compat |
| `POST /api/history/struggling-topics` | `packages/studyloop/src/studyloop/web/routes/history.py` | ~line 82; `StruggleRequest` body |
| Vendored mermaid v11.4.1 | `web/static/vendor/js/mermaid-11.4.1.min.js` | `globalThis.mermaid` assignment; `startOnLoad:false` |
| Vendored Fuse.js v7.0.0 | `web/static/vendor/js/fuse-7.0.0.min.js` | `window.Fuse` UMD global |

---

## What's NOT in this diagram

- **The Pomodoro overlay**, OpenDyslexic toggle — orthogonal UI concerns, not part of the session pipeline. (Voice output is now documented in its own C4 L3 component section above.)
- **The Generate panel implementation details beyond the C4 slice above** — provider-specific prompt tuning and deck-quality judging are documented in [Content Pipeline](../content-pipeline.md).
- **MCP servers** — see [MCP](../mcp.md). Currently only the Kiro adapter exposes any MCP integration.
- **Legacy tmux + ttyd** — kept as fallback; documented in [Web UI Guide § Terminal Fallback (ttyd)](../web-ui-guide.md#terminal-fallback-ttyd). Will be retired once ACP + PTY web sessions cover all agents.
