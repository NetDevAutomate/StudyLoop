# Current Architecture

> Last updated: 2026-06-01. Reflects the ACP chat-UI feature (2026-05-27), the dogfood hotfix (2026-05-28, commit `bfe9210`), the Generate panel (2026-05-29), and the in-browser neural TTS engine (2026-06-01).

This document describes the system as it works today, using the [C4 model](https://c4model.com/) at three levels of zoom: Context → Container → Component (focused on the ACP chat surface).

For the planned direction, see [Target Architecture](target.md).

---

## C4 Level 1 — System Context

StudyLoop is single-user and runs entirely on one host. The only external systems are the AI agent CLIs (Kiro, Claude Code, Gemini, Codex, OpenCode) and optional generation backends (Ollama / Bedrock).

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

    subgraph "Optional generation backends"
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
    StudyLoop -.->|"flashcard /<br/>quiz generation"| Ollama
    StudyLoop -.->|"flashcard /<br/>quiz generation"| Bedrock
    Learner -.->|"browser fetches TTS model<br/>(first run, then offline)"| HF
```

**Trust boundaries** — everything happens on the learner's machine. The only outbound network calls are (a) the agent CLI's own model calls (the agent owns those creds and policy), (b) optional Bedrock for content generation, and (c) a one-time browser fetch of the in-browser TTS model weights from Hugging Face (cached on-device thereafter; voice synthesis itself is fully local — no text is ever sent off-device). StudyLoop's Python server has no outbound component and never phones home.

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
      Runtime["SessionRuntime<br/>──────────<br/>Active-session singleton.<br/>Owns the transport.<br/>Forwards events to WS."]
      ACP["ACPTransport<br/>──────────<br/>JSON-RPC over stdio.<br/>session/new,<br/>session/prompt,<br/>session/update,<br/>session/request_permission."]
      PTY["PTYTransport<br/>──────────<br/>Raw bytes,<br/>WINSZ ioctl,<br/>SIGCHLD-driven exit."]
      Agent["Agent subprocess<br/>──────────<br/>kiro-cli acp /<br/>gemini --acp /<br/>claude / codex / opencode"]
    end

    subgraph "Local stores"
      DB[("sessions.db<br/>(SQLite + WAL)<br/>──────────<br/>study sessions,<br/>progress, review state.")]
      IPC["~/.config/studyloop/<br/>session-state.json<br/>session-topics.md<br/>session-parking.md"]
      Persona["agents/shared/personas/*<br/>(canonical persona text)"]
    end

    Learner --> PWA
    PWA -->|"HTTP /api/*"| API
    PWA <-->|"WebSocket /api/session/ws"| API
    API --> Runtime
    Runtime -->|"transport.start()"| ACP
    Runtime -->|"transport.start()"| PTY
    ACP -->|"asyncio.create_subprocess_exec"| Agent
    PTY -->|"openpty + execvpe"| Agent
    API --> DB
    API --> IPC
    API -->|"build_canonical_persona"| Persona
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

## C4 Level 3 — Component (zoomed into the Generate panel)

Sister surface to the chat surface. The Generate panel reuses the existing `content/generators/` package as its producer; the new layer is the orchestrator + the active-generation singleton + the REST + WS endpoints + the sidebar UI. **All shipped on `main` as of 2026-05-29** — backend, HTTP surface, and browser side.

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
      Job["run_job orchestrator<br/>(content/job.py)"]
      Scope["resolve_scope<br/>(content/scope.py)"]
      Runner["generate_concurrently<br/>(generators/runner.py)"]
      Factory["get_generator<br/>(generators/__init__.py)"]
      Adapters["StubGenerator<br/>OllamaGenerator<br/>BedrockGenerator<br/>OpenAICompatGenerator<br/>AnthropicCompatGenerator"]
      Helpers["on-existing helpers<br/>(storage.next_unique_path,<br/>FlashcardDeck.merge_dedupe,<br/>QuizDeck.merge_dedupe)"]
    end

    Disk[("content.base_path/<br/>course/flashcards/<br/>course/quizzes/")]
    Reviewer["/api/cards, /api/quizzes<br/>(existing reviewer)"]

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
    Job --> Runner
    Runner -->|"on_complete callback"| Job
    Job --> Helpers
    Helpers --> Disk
    Job -->|release| Single

    Disk -->|already read by| Reviewer
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
    PWA->>REST: POST {course, scope, kinds, provider, model, on_existing}
    REST->>Single: acquire(job_id, request)
    alt slot busy
      Single-->>REST: GenerationAlreadyActiveError
      REST-->>PWA: 409 Conflict
    else slot free
      Single-->>REST: ActiveGeneration
      REST->>Job: asyncio.create_task(run_job(...))
      REST-->>PWA: 202 {job_id, plan}

      PWA->>WS: open ?job_id=...
      WS-->>PWA: started {task_count, sources}

      Job->>Scope: resolve_scope(request, settings)
      Scope-->>Job: list[ResolvedSource]
      Job->>Gen: get_generator(config)

      loop one task per source × kind
        Job->>Runner: generate_concurrently
        Runner->>Gen: generate_flashcards / generate_quiz
        Gen-->>Runner: deck or CardGenerationError
        Runner->>Job: on_complete(result)
        Job->>FS: write_json (apply on_existing policy)
        Job-->>WS: task_complete {ok, path / error}
        WS-->>PWA: task_complete frame
      end

      Job-->>WS: all_done {written, failed}
      WS-->>PWA: all_done frame
      Job->>Single: release()
    end
```

**Why a singleton + queue, not direct streaming**: a single Ollama process (or a single MiniMax token plan) doesn't tolerate two concurrent jobs. The singleton is the simplest possible coordinator -- one process, one heavy LLM job at a time. The per-job WS queue lets clients reconnect / resubscribe without losing events that fire during the gap.

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
| `live_provider` pytest marker | `packages/studyloop/pyproject.toml` | `[tool.pytest.ini_options]` |
| Live MVD smoke (parametrised over registry) | `packages/studyloop/tests/test_live_provider_smoke.py` | full file |
| MVD source fixture (photosynthesis) | `packages/studyloop/tests/fixtures/mvd_source.md` | full file |

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
- **Browser → Hugging Face is the only new egress.** First-run model fetch is the single direct browser-to-internet call; everything else (engine module, WASM) is same-origin from FastAPI. After first load the model is served from Cache Storage and voice works fully offline.

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

## What's NOT in this diagram

- **The Pomodoro overlay**, OpenDyslexic toggle — orthogonal UI concerns, not part of the session pipeline. (Voice output is now documented in its own C4 L3 component section above.)
- **The flashcard / quiz review path** — separate from interactive sessions; covered in [Web UI Guide](../web-ui-guide.md).
- **The Generate panel UI surface** — see U8 in the [Generation Panel Plan](../plans/2026-05-29-001-feat-content-generation-panel-plan.md). Backend is shipped as of 2026-05-28; UI is Session-2 work.
- **MCP servers** — see [MCP](../mcp.md). Currently only the Kiro adapter exposes any MCP integration.
- **Legacy tmux + ttyd** — kept as fallback; documented in [Web UI Guide § Terminal Fallback (ttyd)](../web-ui-guide.md#terminal-fallback-ttyd). Will be retired once ACP + PTY web sessions cover all agents.
