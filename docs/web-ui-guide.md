# Web UI Guide

> The web interface is the primary direction for learner-facing study: live interactive mentor sessions, body-doubling, session state, and supporting flashcards/quizzes.

---

## Starting the Web UI

```bash
studyloop web                        # localhost:8567
studyloop web --lan                  # LAN-accessible with auto-generated password
studyloop web --lan --password SECRET  # LAN with explicit password
studyloop web -p 9000                # custom port
```

Open your browser to `http://localhost:8567`. The PWA is installable; add it to your home screen on a tablet for review and session visibility. Phone screens are not supported — the study panels have no phone layout.

!!! note "Core workflow"
    The core workflow is interactive study with an agent. Flashcards and quizzes are useful support tools, but the web UI should increasingly serve the live mentor/body-doubling experience.

---

## The Today View (default landing)

The app opens on **Today** — a single next-action card so you never have to
decide "what now" unaided (the AuDHD one-next-thing principle):

- **Your one next action** — the top recommendation from the shared decision
  engine (`/api/now`): concept, time estimate, action type, and *why*. One
  **Start** button jumps straight to the right view.
- **Context-aware resume** — if a session is live you get **Rejoin session**;
  otherwise **Resume: \<last topic\>** (pre-fills the study-session form), or
  **Resume deck** for your last review course.
- **Not now?** — a collapsed alternates list if the primary doesn't fit your
  current energy.
- **Parked thoughts** — one-tap chips to pick up something you parked earlier.

### Quick-park a thought (protect your flow)

A tangent popping up mid-study is the classic focus-killer. Hit the floating
**＋ Park a thought** button (or press `p` anywhere outside an input), type
the thought, Enter — it lands in the parking lot and you stay exactly where
you were. A toast confirms the save.

### The 3-topic rule (park-first friction)

Starting a **4th** topic while three are active opens an in-page dialog:
pick one active topic to park (it moves to the back of the parking lot) or
keep all three and don't start. This is deliberate friction — the limit is
what keeps the active set workable.

---

## Flashcard Review

```mermaid
graph TB
    HOME["Home: Course List<br/>(grouped by publisher, searchable)"]
    CONFIG["Session Config<br/>(filter by chapter, set card limit)"]
    STUDY["Card View<br/>(flip to reveal answer)"]
    ANSWER["Mark: Correct / Incorrect / Skip"]
    SUMMARY["Session Summary<br/>(score, time, per-card breakdown)"]
    RETRY["Retry Wrong Answers"]

    HOME -->|"click Flashcards"| CONFIG
    CONFIG -->|"Start Session"| STUDY
    STUDY -->|"Space to flip"| ANSWER
    ANSWER -->|"Y=correct, N=wrong, S=skip"| STUDY
    STUDY -->|"all cards done"| SUMMARY
    SUMMARY -->|"R = retry wrong"| STUDY
    SUMMARY -->|"Escape = home"| HOME
```

### The course list (scales to 100+ sets)

The **Flashcards** and **Quizzes** panels are **mode-specific**: the Flashcards
panel lists only courses that have flashcards (with a single **Flashcards**
action per row); the Quizzes panel lists only courses with quiz questions (with
a single **Quiz** action). Each label means exactly what it says — neither panel
shows the other's button.

Courses render as **compact one-line rows** grouped under **collapsible publisher
headers** (e.g. `ARJANCODES (1)`, `CODEWITHMOSH (3)`), derived from the
`publisher/course` folder layout. A **search box** at the top filters by course
name instantly. This keeps the list usable as your library grows to hundreds of
sets: collapse the publishers you're not studying, type to filter, and each row
is far denser than the old cards.

- **Search** — type any substring of a course name; non-matching rows hide, and a
  publisher group with no matches disappears entirely. Clear the box to restore all.
- **Collapse/expand** — click a publisher header to fold its courses away; the
  collapsed state is per-group and persists while you browse (resets on reload).
- **Row meta** — each row shows the card count, a **due** badge when cards are
  due, and a **mastered** count once you've reviewed.

### Walkthrough

1. **Home screen** — shows courses grouped by publisher with a search box and
   per-row due-count badges. A 90-day activity heatmap below shows your study
   consistency.

2. **Pick a course** — click the **Flashcards** button on a course row. If the
   course has multiple chapters, you'll see a filter dropdown to select specific
   chapters and a card limit picker.

3. **Study cards** — each card shows the front (question). Press **Space** to flip and reveal the answer, or click the card. Enter is not bound.

4. **Mark your answer**:
   - **Y** or click the green button — Correct (SM-2 interval increases)
   - **N** or click the red button — Incorrect (interval resets to 1 day)
   - **S** or click Skip — skip this card (no SM-2 update)

5. **Session summary** — shows your score (correct/incorrect/skipped), total time, and a per-card breakdown. Press **R** to retry only the cards you got wrong.

6. **Return home** — press **Escape** at any time.

### Keyboard Shortcuts (Flashcard Mode)

These fire only while the **Flashcards** panel is the active panel.

| Key | Action |
|-----|--------|
| Space | Flip card |
| Y | Mark correct — **only after the card is flipped** |
| N | Mark incorrect — **only after the card is flipped** |
| S | Skip card |
| T | Read card aloud (in-browser neural TTS) |
| Escape | Return to home |
| R | On the session summary: retry the cards you got wrong |
| P | Park a thought (works anywhere outside a text field) |

Case does not matter — the handler lower-cases the key first.

> **Enter does not flip a card, and there is no auto-voice key.** `V` is unbound; voice is a click-only header toggle (see [Voice Output](#voice-output) below). If you expected either from an older version of this guide, that guide was wrong.

> Voice uses an in-browser neural model (Kokoro via WebGPU/WASM) — no text leaves the browser. See [Voice Output § Web PWA Voice](voice-output.md#web-pwa-voice-in-browser-neural-tts).

---

## Quiz Mode

```mermaid
graph TB
    HOME["Home: Course List<br/>(quiz decks only, grouped + searchable)"]
    CONFIG["Session Config<br/>(filter + limit)"]
    QUIZ["Quiz Card<br/>(multiple choice, 4 options)"]
    RESULT["Instant Feedback<br/>(correct/incorrect highlight)"]
    SUMMARY["Session Summary"]

    HOME -->|"click Quiz"| CONFIG
    CONFIG -->|"Start Session"| QUIZ
    QUIZ -->|"1-4 to pick"| RESULT
    RESULT -->|"auto-advance"| QUIZ
    QUIZ -->|"all done"| SUMMARY
    SUMMARY -->|"R = retry wrong"| QUIZ
    SUMMARY -->|"Escape"| HOME
```

The Quizzes panel uses the same grouped, searchable, compact course list as the
Flashcards panel (see [The course list](#the-course-list-scales-to-100-sets)) —
but lists only decks that have quiz questions, with a single **Quiz** action per row.

### Walkthrough

1. **Pick a course** — click the **Quiz** button on a course row.

2. **Answer questions** — each card shows a question with 4 multiple-choice options. Press **1**-**4** to select your answer, or click an option. Correct answers highlight green; wrong answers highlight red with the correct answer shown. `A`-`D` are not bound.

3. **Summary** — same as flashcard mode. Press **R** to retry wrong answers.

### Keyboard Shortcuts (Quiz Mode)

These fire only while the **Quizzes** panel is the active panel.

| Key | Action |
|-----|--------|
| 1-4 | Select answer option — **only before you have answered** |
| T | Read question aloud |
| Escape | Return to home |
| R | On the session summary: retry the questions you got wrong |
| P | Park a thought (works anywhere outside a text field) |

> **`A`-`D` are not bound** — use the number keys or click the option. `V` is not bound either; see the note under [flashcard shortcuts](#keyboard-shortcuts-flashcard-mode).

---

## Course Explorer

The **Course Explorer** is a persistent side panel (a third layout column) opened by the **Courses** button in the sidebar. It is independent of the Flashcards and Quizzes review panels — it is a reading surface for your source study material, not a review surface for generated decks.

```mermaid
flowchart LR
    Open["Click Courses<br/>sidebar button"]
    Browse["Browse view<br/>provider carousels"]
    Filter["Per-provider<br/>filter input"]
    Select["Click a course<br/>→ lesson list"]
    Read["Lesson reader<br/>(markdown + mermaid + code)"]
    Search["Global search<br/>(titles instant + bodies FTS)"]
    Struggle["Struggling? button<br/>→ session DB"]
    Discuss["Discuss button<br/>→ Socratic prompt clipboard"]
    Listen["▶ Listen<br/>(TTS, if installed)"]

    Open --> Browse
    Browse --> Filter
    Browse --> Select
    Select --> Read
    Open --> Search
    Search --> Read
    Read --> Struggle
    Read --> Discuss
    Read --> Listen
```

### Walkthrough

1. **Open the panel** — click the **Courses** button in the sidebar. The layout gains a third column (320 px). Click again, or the × in the panel header, to close. The panel is hidden on screens narrower than 600 px.

2. **Browse by provider** — the browser view shows one horizontal carousel row per provider (top-level directories under `content.base_path`). Each carousel card shows the course name and provider. Use the **filter** input on a provider row to narrow by course name; use the **‹** / **›** buttons to scroll the carousel.

3. **Open a course** — click any course card. A lesson list expands below the carousel showing every source file in that course (`.md`, `.markdown`, `.txt`), numbered in file-system order.

4. **Read a lesson** — click any lesson in the list. The reader view renders the lesson's markdown: headings, lists, code blocks (syntax-highlighted via highlight.js), and mermaid diagrams (two-pass render via mermaid v11.4.1). YAML frontmatter is stripped before rendering. A back arrow returns to the browser view.

5. **Search** — type in the **Search lessons…** box (visible in browser view). Results appear grouped by provider. Two tiers run in parallel:
   - **Fuse.js** (client-side, vendored v7.0.0) — instant fuzzy match over provider/course/lesson titles.
   - **SQLite FTS5** (server-side, debounced) — full-text search over lesson bodies via `GET /api/explorer/search`. Porter-stemmed, BM25-ranked with title weighted higher than body, returns snippet excerpts with `<mark>` highlights. The FTS index (`explorer_fts.db`) is built lazily on first search and refreshed incrementally on each call.

   Click any result to open that lesson directly in the reader.

6. **Mark a struggle** — while reading a lesson, click the **Struggling?** button in the reader header. This writes a `study_progress` row (`confidence='struggling'`) to the session DB via `POST /api/history/struggling-topics`. The row uses the lesson slug as the generation topic and keeps the original course/section/publisher as provenance, so the next Generate session's "Topic I'm struggling on" scope targets the struggled lesson rather than the whole course. It also surfaces in `studyloop struggles`.

7. **Discuss the lesson** — click **Discuss** to open the in-app note companion. Pick recall, diagram, trace, teach-back, or repair mode; write a rough retrieval attempt; then use **Next nudge** or copy the mentor prompt/evidence command. This stays browser-local and does not send lesson text to a separate chat backend.

8. **Listen (TTS)** — the **▶ Listen** button appears only when `window.ttsEngine` is present. When the engine is absent the button is hidden and no-op. When active, click to start reading the lesson aloud; the button becomes **⏹ Stop**.

### Endpoints called

| Endpoint | Purpose |
|---|---|
| `GET /api/explorer/tree` | Provider→course tree (cached by visible tree fingerprint on server) |
| `GET /api/explorer/courses/{course_id}/lessons` | Lesson list for a course (`course_id` = `provider/course`) |
| `GET /api/explorer/lesson/{lesson_id}/content` | Raw markdown for a lesson (`lesson_id` = `provider/course/slug`) |
| `GET /api/explorer/search?q=&limit=20` | FTS5 full-text search over lesson bodies |
| `POST /api/history/struggling-topics` | Write a struggle flag to `study_progress` |

The **Discuss** action does not call a backend endpoint; it builds the prompt in the browser from the already-loaded lesson and writes only to the clipboard when you click a copy button.

All content endpoints are path-traversal guarded (resolved path must be a child of `content.base_path`; suffix restricted to `.md`, `.markdown`, `.txt`). The provider/course tree cache is keyed from the visible source tree, so adding or deleting nested courses refreshes the browser data while generated output folders do not invalidate the tree. The FTS index lives in its own file (`<session_db_dir>/explorer_fts.db`) — it is a derived cache, never touches `sessions.db`, and requires no schema migration.

### From Lesson To Evidence

```mermaid
flowchart LR
    Lesson["Open lesson<br/>markdown, diagrams, code"]
    Discuss["Discuss<br/>browser-local companion"]
    Retrieval["Rough retrieval attempt<br/>recall, diagram, trace, teach-back, repair"]
    Nudge["Next nudge<br/>small repair prompt"]
    Evidence["Copy evidence command<br/>studyloop progress ..."]
    Now["studyloop now<br/>next best action"]
    Mastery["Mastery tab<br/>bounded graph + weak links"]

    Lesson --> Discuss
    Discuss --> Retrieval
    Retrieval --> Nudge
    Nudge --> Evidence
    Evidence --> Now
    Evidence --> Mastery
```

---

## Mastery

The **Mastery** tab renders the same concept dependency data as `studyloop mastery`.

1. Enter a topic, such as `python`, `sql`, or `data-engineering`.
2. Click **Refresh** to load `/api/mastery/graph` and `/api/mastery/weak-links`.
3. Inspect the Mermaid graph, weak-link cards, and summary counts.
4. Use **Copy Mermaid** when you want to paste the graph into Obsidian.

The Web UI requests a bounded JSON graph by default (`limit=80`) and builds the
Mermaid source locally, so broad topics such as `python` stay readable and do
not trigger duplicate graph API calls. The summary shows when the browser is
displaying a subset.

| Endpoint | Purpose |
|---|---|
| `GET /api/mastery/graph?topic=python&limit=80` | JSON graph with nodes, edges, and total/limited metadata |
| `GET /api/mastery/graph?topic=python&format=mermaid&limit=80` | Mermaid graph source for the bounded graph |
| `GET /api/mastery/weak-links?topic=python&limit=12` | Struggling or low-score prerequisites with total/limited metadata |

---

## Live Interactive Sessions

When you start a study session with `--web`, the dashboard provides a real-time view of your session from any tablet or laptop:

```bash
studyloop study "Python Decorators" --energy 7 --web
```

### Accessing the Dashboard

- **Local**: `http://localhost:8567/session`
- **LAN** (with `--lan`): `http://<your-ip>:8567/session` (password-protected)

The LAN URL and password are printed to the terminal at session start.

```mermaid
graph LR
    subgraph "Current Session Dashboard"
        META["Topic + Energy + Timer"]
        FEED["Live Activity Feed<br/>(SSE streaming)"]
        COUNTERS["WINS / PARKED / REVIEW"]
        TERM["Agent Console<br/>(xterm.js over WebSocket,<br/>or ACP chat)"]
    end

    subgraph "Data Sources"
        SSE["Server-Sent Events<br/>(/api/session/stream)"]
        STATE["session-state.json"]
        IPC["session-topics.md"]
    end

    STATE --> META
    SSE --> FEED
    SSE --> COUNTERS
    IPC --> SSE
```

### Current Dashboard Sections

**Header** — shows the study topic, energy level (as a `/10` badge), and a live timer matching the sidebar.

**Activity Feed** — real-time stream of topics as the agent logs them. Updates via SSE (Server-Sent Events) with no page refresh needed. Each entry shows the topic name, status icon, and note.

**Counter Bar** — WINS, PARKED, and REVIEW counts updated live.

**Agent Console** — where you talk to the agent. `liveAgentConsole()` renders one of two surfaces, chosen by the session's transport:

- **`pty`** → **xterm.js**, fed by StudyLoop's own FastAPI WebSocket. This is the default terminal path and it survives a page refresh: the console reads `GET /api/session/state` on init and re-adopts a live session it owns, so the same agent process answers a freshly typed line with no action from you.
- **`acp`** → the [ACP chat surface](#acp-chat-mode-kiro-gemini). Structured markdown rather than a terminal, and the preferred experience where the agent supports it.

Anything else renders an explicit **unavailable** state naming what happened and what to do. There is no iframe fallback — see [Browser terminal surfaces](#browser-terminal-surfaces).

## Target Session Presentation

The target web UI should support live agent interaction without requiring a terminal emulator for the normal learner path.

```mermaid
flowchart TD
    Learner["Learner"]
    Web["Web/PWA<br/>chat + context + controls"]
    API["Local Study API"]
    Runtime["Agent Runtime"]
    ACP["ACP transport<br/>structured JSON-RPC"]
    PTY["PTY transport<br/>terminal fallback"]
    DB["Shared SQLite DB<br/>progress, struggles, sessions"]

    Learner --> Web
    Web -->|"messages + controls"| API
    API --> Runtime
    Runtime --> ACP
    Runtime --> PTY
    Runtime --> DB
    DB --> API
    API -->|"streamed events"| Web
```

### Target Session Controls

The web UI should expose structured controls:

- start session
- choose assistant
- ask a question
- stream agent response
- interrupt/cancel current turn
- park topic
- mark win
- mark struggle
- show recent struggles and wins from the DB
- end and summarize session
- resume previous session

Example target request:

```http
POST /api/sessions
Content-Type: application/json

{
  "topic": "Spark partitioning",
  "mode": "study",
  "agent": "kiro",
  "energy": 5,
  "transport": "auto"
}
```

Example target event:

```json
{
  "type": "agent_message_chunk",
  "content": "What do you already know about partition skew?"
}
```

### Transport Strategy

| Transport | Role | Use when |
|---|---|---|
| ACP | Preferred structured session transport | Agent supports Agent Client Protocol |
| PTY | Default terminal transport | Agent only has an interactive terminal UI |
| Headless CLI | Background jobs only | One-shot summaries, generation, checks |
| ttyd | Server transport only — **no browser renderer** | Maintainer opt-in via `STUDYLOOP_TRANSPORT=ttyd`; not offered in the UI |

The learner-facing transport picker offers **`pty`** and **`acp`** only. That is deliberately narrower than the API, which still accepts `ttyd` — see [ADR-0005](adr/0005-retire-ttyd-browser-surface.md).

---

## Browser terminal surfaces

The dashboard has **two** browser surfaces for talking to the agent, plus an honest error state. There is no iframe and no third fallback.

| Surface | Transport | How it renders |
|---|---|---|
| **xterm.js** | `pty` | The agent's PTY streamed over StudyLoop's own FastAPI WebSocket |
| **ACP chat** | `acp` | Structured ACP events as markdown — see [ACP Chat Mode](#acp-chat-mode-kiro-gemini) |
| **unavailable** | anything else | An explicit message naming what happened and what to do |

`terminalMode` is `'xterm' | 'acp-chat' | 'unavailable' | null`.

### The retired ttyd iframe

Earlier versions embedded [ttyd](https://github.com/tsl0922/ttyd) in an iframe at `/terminal/` as a third surface. **That surface is gone** ([ADR-0005](adr/0005-retire-ttyd-browser-surface.md)), for two reasons worth knowing as a user:

- ttyd is an external binary most machines do not have. Without it the iframe rendered an **empty frame**, which is indistinguishable from a hang — so the "fallback" failed more confusingly than the thing it was covering for.
- The reason for keeping it was that the primary xterm.js path could not survive a page refresh. It now can, so the fallback had nothing left to cover.

What this means in practice:

- **`brew install ttyd` enables nothing user-visible.** You do not need ttyd installed. The `Legacy terminal (ttyd iframe)` option is gone from both transport pickers.
- The **server** transport survives: `POST /api/session/start` still honours `transport: "ttyd"`, `STUDYLOOP_TRANSPORT=ttyd` still works, and `/terminal/` is still proxied. But a session started that way has **no browser renderer** — the console reports `unavailable`. It is a maintainer path, not a learner path.

### LAN access

With `--lan`, the dashboard and its terminal surface are reachable from other devices on your network:

```bash
studyloop study "topic" --web --lan --password mypassword
```

Access from a tablet or phone at `http://<host-ip>:8567/session`. HTTP Basic Auth protects the connection, and the WebSocket rides the same authenticated origin — no extra port to open.

---

## ACP Chat Mode (Kiro / Gemini)

When you start a session with **ACP** as the transport (Kiro or Gemini today), the dashboard renders a structured chat surface instead of a terminal. This is the preferred experience — markdown, syntax-highlighted code, proper headings, and no escape-sequence quirks.

```mermaid
sequenceDiagram
    actor You
    participant PWA as Browser
    participant Agent as Kiro / Gemini

    You->>PWA: pick topic + energy + ACP transport
    PWA->>PWA: "Setting up your mentor…" banner
    Note over PWA,Agent: Persona injected invisibly<br/>(you don't see it scroll past)
    Agent-->>PWA: persona-turn ack (suppressed)
    PWA->>PWA: input enabled, banner hidden
    You->>PWA: type your question
    PWA->>Agent: session/prompt
    Agent-->>PWA: agent_chunk* (typing indicator)
    Agent-->>PWA: turn_end
    PWA->>PWA: render markdown bubble<br/>(headings, code, lists, tables)
```

### What to expect

**On session start.** A "Setting up your mentor…" banner appears in the chat area for a few seconds. The agent receives the StudyLoop persona — your topic, energy level, mode, and the AuDHD-aware Socratic mentoring instructions — as an invisible first prompt. You don't see it scroll past, and the agent's acknowledgement is hidden too. The input box stays disabled until the persona turn settles.

**During the persona turn.** The agent may make a few file-read tool calls to look at session IPC files for context. These tool-call cards are intentionally hidden during this turn and any permission prompts are auto-allowed — they're protocol noise, not something you triggered.

**While the agent is typing.** A subtle three-dot animation appears in the assistant bubble. Markdown is *not* rendered progressively — the previous design did that and it produced raw `##` and `**` source plus a cascade-staircase indent on Kiro's natural output. The fix is to render the full bubble once at `turn_end` instead of token-by-token.

**On `turn_end`.** The full response renders: headings, paragraphs, bullet lists, syntax-highlighted code fences, tables, links with `target="_blank" rel="noopener noreferrer"`. Inline content is sanitised through DOMPurify before insertion.

### Tool calls and permissions (after the persona turn)

Once you've started typing, tool-call cards DO appear — collapsed by default with a status badge (`◷ pending`, `◔ in_progress`, `✓ completed`, `✗ failed`). Click the chevron to expand. Bash-class tools render their output in a dark exec pane.

If the agent needs to do something that requires permission (e.g. write outside `/tmp`, run a destructive command), an inline allow/deny prompt appears in the chat with the available options. The exact prompts come from the agent — StudyLoop doesn't decide what's permissioned, just renders what the agent asks for.

### Live regression test

A real-browser test (`packages/studyloop/tests/test_web_acp_dogfood_kiro.py`, marked `@pytest.mark.live_kiro`) drives a real `kiro-cli acp` session via Playwright, asks "When should I use a SUM function in a SQL statement?", and asserts:

- The response is rendered as proper markdown HTML (no raw `##` or `**`).
- The persona text was actually transmitted on the wire.
- The response carries Socratic-mentor markers (Socratic dialogue patterns, mentor structural conventions).
- The persona-injection turn left zero artefacts in the chat.

Run it locally with `uv run pytest -m live_kiro` (requires `kiro-cli` authenticated).

---

## Generate Panel

> **Status (2026-05-29):** Shipped end-to-end. Backend (registry, two HTTP adapters, scope resolver, job orchestrator), HTTP surface (REST + WS + 4 supporting routes), and the sidebar UI all live on `main`. The Generate tab is now first-class alongside Flashcards / Quizzes / Body Double / Study Session.

The Generate tab in the sidebar (between **Quizzes** and **Body Double**) lets you produce flashcard and quiz decks from any course/section in your `~/Obsidian/Personal/Study/` tree, or from topics you've struggled with recently, without dropping to the CLI.

### Form fields

The content tree is three levels — `content.base_path/<publisher>/<course>/<lesson>.md` (lesson files typically live in a `study-notes/` subdir). The form cascades to match:

| Field | Source | Default |
|---|---|---|
| **Publisher** | Auto-discovered via `GET /api/content/publishers` (top-level dirs under `content.base_path`, e.g. ArjanCodes, CodeWithMosh) | empty — pick one |
| **Course** | `GET /api/content/courses?publisher=<P>` (courses under the chosen publisher) | empty — enabled after a publisher is picked |
| **Scope** | Whole course / One section / Topic I'm struggling on | Whole course |
| **Section** | `GET /api/courses/<course>/sections?publisher=<P>` — one entry per **lesson file** (a "section" is a single `.md`); output dirs skipped | empty — pick one when scope=section |
| **Topic** | `GET /api/history/struggling-topics?days=N` — distinct struggle topics with `confidence='struggling'` in the window; Course Explorer marks use the lesson slug | "all struggling topics in window" |
| **Window days** | numeric, 1-90 (Topic scope only) | 14 |
| **Kinds** | Flashcards / Quizzes (multi-select, ≥1 required) | Flashcards |
| **Count** | 5 / 10 / 15 / 20 / 25 / 50 cards/questions per source; sent as `count_per_source` and copied into every `GenerationTask.count` | 10 |
| **Provider** | `GET /api/content/providers`; providers without an env var are visible but disabled, with tooltip | "stub (offline, free)" |
| **Model** | curated list per provider, with cost-tier + thinking-model badges | provider's first cheap-tier model |
| **On existing** | Overwrite / Merge / New suffix | Merge (least destructive) |

`count_per_source` is a requested per-source target, not a post-write quota. The job plan and WebSocket `started` frame show the requested count, provider, and model so you can check what will run before watching task progress. Providers receive the count in their prompt/schema request, then the validated deck is written as returned by that provider. The deterministic Stub backend honours the requested count exactly; external providers can still under- or over-produce if their response fails to follow the prompt, in which case validation and the task status make the failure visible.

> **Why two course endpoints?** `GET /api/courses` lists courses that already have flashcards/quizzes JSON for the reviewer to render. The Generate panel uses `GET /api/content/courses` instead so a *fresh* course (markdown notes, no decks yet) is still a legitimate target.

### What happens when you click Generate

```mermaid
flowchart TD
    Click["Click Generate"]
    Validate["Client-side validation"]
    Post["POST /api/content/generate"]
    Conflict{"Singleton<br/>busy?"}
    Banner["Banner:<br/>'Another generation<br/>is already running'"]
    Open["Open WS<br/>?job_id=..."]
    Started["Frame: started<br/>(N tasks)"]
    Loop["For each task:<br/>frame: task_complete<br/>(ok/fail + path or error)"]
    Done["Frame: all_done<br/>(written, failed)"]
    Reenable["Re-enable form;<br/>existing reviewer (/cards,<br/>/quizzes) auto-picks up<br/>new files."]

    Click --> Validate --> Post --> Conflict
    Conflict -- "409" --> Banner
    Conflict -- "202" --> Open
    Open --> Started
    Started --> Loop
    Loop --> Done
    Done --> Reenable
```

While the job is in flight, the Generate button is disabled. The progress area shows the planned task/source count, selected kinds, requested count per source, provider, model when known, and one row per task with a status icon, the source title, the deck kind, and the elapsed time.

If generation looks stuck, first check the visible job status in the Generate panel. A `409` banner means another generation job is already active; wait for it to finish. If the local process was killed mid-job and the UI never recovers, restart `studyloop web`. See [Troubleshooting § Generation is busy or stuck](troubleshooting.md#generation-is-busy-or-stuck).

### `on_existing` policies

- **Merge** (default) — loads the existing deck, deduplicates by normalised `front` (flashcards) or `question` (quizzes), and writes the merged result back. The original card content wins on collision; new cards are appended. Result is re-validated by pydantic so the exactly-one-correct-answer invariant survives. **Picked as default because it's the least destructive sensible behaviour** — no work is ever lost, and a re-run that produces overlapping content silently consolidates.
- **Suffix** — keeps the existing file, writes the new one as `<slug>-1-flashcards.json`, `<slug>-2-flashcards.json`, …
- **Overwrite** — replaces the existing file at `course/flashcards/<slug>-flashcards.json`. Destructive.

### Provider plumbing under the hood

The form's **Provider** dropdown is populated from a curated [provider registry](content-pipeline.md#pluggable-provider-abstraction). Six providers ship today: **OpenAI, OpenRouter, Gemini, Anthropic, AWS Bedrock,** and **Ollama** (local). Each provider's available models are tagged with cost-tier (cheap / balanced / premium) and a thinking-model flag; the **Model** dropdown lists the chosen provider's discovered models.

Credentials are resolved by `secrets.get_secret(slug)`, which checks the **encrypted store first, then the environment**:

1. **Encrypted store** — `~/.config/studyloop/secrets.bin` (Fernet-encrypted; key seed in `~/.config/studyloop/.secrets-key`, mode `0600`). This is what the **Settings → LLM Providers** panel writes (see below) — the recommended path.
2. **Environment / project-root `.env`** — `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`. `.env` is auto-loaded on import (`studyloop/__init__.py`); explicitly-exported shell vars win.

Provider availability is computed per auth kind (see Settings below). API-key providers without a stored key or env var appear in the dropdown but are disabled with a tooltip. **Bedrock** authenticates with an AWS profile/SigV4 or an optional bearer token (no typed key); **Ollama** is local and keyless (available iff its endpoint responds).

### CLI parity

Everything the panel does is also available as the existing `studyloop content generate-cards` command. The panel is a UI over the same producer pipeline, not a separate code path.

---

## Settings → LLM Providers

The **Settings** tab in the sidebar holds an **LLM Providers** admin panel for
managing generation credentials from the browser — no `.env` editing required.
Keys are stored **encrypted** at `~/.config/studyloop/secrets.bin` and never
leave the machine.

Each provider renders one row whose controls match its **auth kind**:

| Auth kind | Providers | Controls |
|---|---|---|
| `api_key` | OpenAI, OpenRouter, Gemini, Anthropic | Password field + **Test & save** (the key is verified with a cheap live auth call before it's stored), **Delete**, **Test** |
| `bedrock_bearer` | AWS Bedrock | Optional bearer-token field (`AWS_BEARER_TOKEN_BEDROCK`) + **Test & save** / **Test AWS creds**. Leave empty to use your AWS profile / IAM role instead |
| `local_keyless` | Ollama (local) | Base-URL field (defaults to `http://localhost:11434`) + **Save URL** + **Test connection** (runs a real generation against a recommended model) |

```mermaid
graph TB
    Row["Provider row<br/>(per auth_kind controls)"]
    Save["Test & save"]
    Verify["Live auth check<br/>(cheap call to the provider)"]
    Store[("Encrypted store<br/>~/.config/studyloop/secrets.bin")]
    OK["✓ Verified and saved"]
    Err["✗ error (shown inline on the row)"]

    Row -->|"enter key / token / url"| Save
    Save --> Verify
    Verify -->|ok| Store --> OK
    Verify -->|fail| Err
```

**Why verify before storing?** A key that doesn't authenticate is worse than no
key — it fails silently at generation time. The panel tests the credential live
(or, for Bedrock, checks AWS creds; for Ollama, runs a real generation) and only
stores it on success, showing the result inline on that provider's row.

The same encrypted store backs both this panel and the Generate panel's provider
dropdown — a key added here immediately makes that provider "configured" in
Generate. The panel is its own Alpine component (`settingsPanel()`); it shares no
reactive state with the Generate form, only the store.

---

## Accessibility

### OpenDyslexic Font

Toggle the OpenDyslexic font via the **Aa** button in the header. The preference is saved in localStorage and persists across sessions.

### Theme Palettes

The header has a **theme dropdown** with twelve palettes — four originals plus a
broader set covering the common editor themes:

| Palette | Variant |
|---|---|
| Tokyo Night | dark (default) |
| Dracula | dark |
| Catppuccin Mocha / Latte | dark / light |
| Nord | dark |
| Gruvbox Dark / Light | dark / light |
| Solarized Dark / Light | dark / light |
| One Dark | dark |
| Rosé Pine | dark |
| Everforest | dark |

Selection persists to `localStorage` under `palette`. Each palette overrides a small set of CSS custom properties (`--bg`, `--bg-card`, `--text`, `--accent`, etc.); every component re-themes automatically.

The original light/dark **toggle button** is still present and orthogonal to the palette picker — it adjusts a body-level `light` class for backward compatibility. Most users will pick a palette and leave the legacy toggle alone.

### Voice Output

- **`T`** key, or the speaker icon on a card — read the current card aloud once (in-browser neural TTS — Kokoro on WebGPU/WASM). Works whether or not the header voice toggle is on.
- **Header speaker button** — enables voice for the app's own spoken announcements (Pomodoro transitions, "voice enabled", "voice changed") and reveals the voice selector and engine badge. Persists to `localStorage` under `voice`. **This is a click-only control — no key is bound to it.**
- **Stop button** — appears in the header while speaking; interrupts neural playback mid-utterance.
- **Voice selector dropdown** in the header lets you choose a Kokoro voice (falls back to OS voices if the device can't run the neural model).
- **Engine badge** next to the selector names the tier that is actually speaking (`neural-webgpu`, `neural-wasm`, `web-speech`), shown whenever voice is on rather than only on failure — a badge that appears only when something breaks teaches nobody what working looks like.

!!! warning "There is no auto-voice"
    Earlier versions of this guide documented a **`V`** key that toggled "auto-voice — reads every card automatically". **No such feature exists**, and `V` is not bound to anything. Nothing reads cards to you automatically; card reading is always `T` or the speaker icon, one card at a time. Getting this wrong in the Accessibility section is exactly the kind of error that costs a screen-reader or low-vision user their time, so it is called out rather than quietly deleted.

Speech is synthesised entirely on-device — no text is sent to a remote API. The ~92 MB model downloads once on first use and is then served from browser Cache Storage, so voice keeps working with no network. That caching is done by the TTS libraries themselves and is **not** app-shell caching — the app itself still needs its local server. Full details: [Voice Output § Web PWA Voice](voice-output.md#web-pwa-voice-in-browser-neural-tts).

### Pomodoro Timer (Browser)

The web UI has its own Pomodoro timer in the header (independent of the TUI sidebar timer). Click the Pomodoro icon to start a 25/5/15 cycle. Uses browser notifications and audio chimes for transitions.

---

## PWA Installation

The web UI is a Progressive Web App. To install:

1. Open `http://localhost:8567` in Chrome/Safari
2. Click "Add to Home Screen" (tablet) or the install icon in the address bar (desktop)
3. The app opens in its own window, with the StudyLoop icon and theme colour from `manifest.json`

!!! warning "The app does **not** work offline"
    **There is no service worker.** `static/` ships `manifest.json` and icons only — no `sw.js`, no `navigator.serviceWorker.register()` anywhere in the JavaScript. Nothing is cached for offline use, so:

    - Installing the app does not make it usable without the server. Every page load fetches `index.html`, the vendored JS/CSS, and every `/api/…` call from `studyloop web` on your machine or LAN. With the server down or out of reach, the installed app shows a browser network error.
    - It is a **local** app, not a hosted one. "Offline" would mean running without your own machine's server process — which is not what the install gives you.
    - Browser install prompts differ. iPadOS Safari offers **Add to Home Screen** from the manifest alone; Chromium's install criteria have historically included a service worker with a fetch handler, so the desktop install button may not appear. Not verified here — no browser was launched.

    The one thing that *is* cached is the **voice model**: transformers.js stores the ~92 MB Kokoro weights in Cache Storage (`transformers-cache`) and the voice embeddings in `kokoro-voices`, both managed by the TTS libraries directly with no service worker involved. So voice keeps working after the first download, and a code change never re-downloads it. See [Voice Output § First-run download](voice-output.md#first-run-download).

    Offline app-shell caching is a genuine gap, not an undocumented feature. See the [2026-07-11 review](audit/2026-07-11-comprehensive-review.md) for the cache-versioning work it would need.

---

## Developer Experiment Flags

### `--dev` — ghostty-web terminal renderer

```bash
studyloop web --dev
```

Swaps the xterm.js terminal renderer (used in all study-session and ACP terminal panels) for [ghostty-web](https://github.com/coder/ghostty-web) — Ghostty's VT100 parser compiled to WASM, wrapped in a canvas renderer (MIT, maintained by Coder).

!!! note "wterm is gone"
    A previous version of this flag loaded [wterm](https://github.com/vercel-labs/wterm) (`wterm-0.3.0.js` + a `WTermAdapter` shim). **wterm has been removed** — no `wterm*` file remains in the tree, and `--dev-renderer` now accepts only `ghostty`. The evaluation that led to the swap is at `docs/explorations/ghostty-web-evaluation.md`; the original wterm write-up is kept at `docs/explorations/wterm-evaluation.md` for history.

**What changes in dev mode:**

- The server injects `<meta name="studyloop-dev-mode" content="ghostty">` into the HTML. Every vendored adapter checks this marker before patching `window.Terminal` and stays dormant when it does not match, which is why several adapters can ship side by side.
- The engine's assets are appended inside `<head>`: `ghostty-0.4.0.css`, `ghostty-web-0.4.0.js`, `ghostty-adapter-0.4.0.js`.
- The adapter patches `window.Terminal` — the rest of the JavaScript is unchanged.

The engine is registered in `web/dev_engines.py`, which is the single source of truth for the marker value, the asset list, and the caveats the UI shows in its tooltip. Adding an engine is one entry in `DEV_ENGINES`.

**Why libghostty:**

- Ghostty's battle-tested VT parser, not a ground-up JS rewrite.
- Self-contained: the 423 KB WASM binary is inlined in the bundle as a base64 data URL, so there is no second network fetch, no `.wasm` MIME-type configuration, and it works with no network access.
- Scrollback, selection, fit and `onScroll` are native — nothing has to be stubbed.

**Known gaps (why this is still `--dev`):**

- Clipboard: agent OSC 52 copy requests are silently dropped.
- Scrollback beyond 512 KB is lost when you change palette.
- Emoji and other non-BMP characters cannot be typed (paste instead).
- Canvas rendering only — throughput under heavy output is unmeasured.
- Full-screen TUIs (vim, htop, mouse tracking) are untested.

The transport picker reports which renderer is actually painting, so `--dev` cannot silently masquerade as xterm.js.

**`--dev-renderer ghostty`** is a deprecated alias kept for the original inline injection path. It implies `--dev` but injects *different* markup — `content="ghostty-web"` plus the `ghostty-web-0.4.0.umd.js` / `ghostty-web-bootstrap-0.4.0.js` pair — rather than going through the registry. Prefer bare `--dev`.

**Default mode is unchanged.** `studyloop web` (no `--dev`) continues to load xterm.js exactly as before — no performance or behaviour difference.

---

## Quick Reference

```bash
# Start flashcard/quiz review
studyloop web

# Start a study session with web dashboard
studyloop study "topic" --web

# LAN access (tablet/phone)
studyloop study "topic" --web --lan

# Check what's due for review
studyloop review

# View study streaks and patterns
studyloop streaks
```
