---
title: feat: ACP Chat UI — Replace xterm for ACP transport with structured chat surface
type: feat
status: active
date: 2026-05-27
deepened: 2026-05-27
---

# feat: ACP Chat UI — Replace xterm for ACP transport with structured chat surface

## Summary

Replace the xterm-based live agent surface for ACP sessions with a dedicated chat UI that renders the structured events ACP already emits — `agent_chunk` text (with markdown + syntax-highlighted code), `tool_call` / `tool_call_update` cards (collapsible, with bash-style exec output panes), `plan` / `plan_update` trees, and `request_permission` inline allow/deny prompts. PTY transport keeps the existing xterm path unchanged.

---

## Problem Frame

ACP transport (Kiro + Gemini) emits structured JSON-RPC events that carry far more information than a PTY byte stream — tool calls with arguments, plan trees, permission requests, agent thoughts. Today every event is force-fitted into xterm via `term.write()` (Phase 2 PR-D), which strips structure, loses markdown, hides tool calls entirely, and yields a worst-of-both-worlds UX: terminal-shaped frame with chat-shaped semantics. The user's stated goal: "Mailgraph-style chat with code blocks + bash output panes." This plan delivers that surface and exposes the events that today are silently dropped in `_openWebSocket`'s message handler.

---

## Requirements

- R1. ACP sessions render in a dedicated chat surface (not xterm) with assistant + user messages distinguishable by role.
- R2. `agent_chunk` text renders as markdown with syntax-highlighted code blocks (bash, python, sql, json, ts).
- R3. `tool_call` events render as collapsible cards showing tool name, arguments, status, and output.
- R4. `tool_call_update` events update the matching card in place (no duplicate cards) and update status (pending → running → done | failed).
- R5. Tool calls whose name matches `bash|shell|exec|run` render their output in a terminal-styled pane inside the card.
- R6. `plan` and `plan_update` events render as a live todo-list-style tree with completed steps struck through.
- R7. `request_permission` events render as an inline blocking prompt with allow/deny buttons; conversation flow is locked until resolved.
- R8. PTY transport behaviour, xterm component, and existing PTY tests are unchanged.
- R9. All rendered HTML is sanitised before insertion (no XSS via agent output).
- R10. Existing ACP per-agent matrix tests (Kiro, Gemini) continue to pass; new chat-surface tests cover R1–R7.

---

## Scope Boundaries

- Markdown subset only (no raw HTML pass-through, no embedded `<script>`, no embedded `<iframe>`).
- No conversation persistence across page reload — session ends, log clears.
- No file attachments / image drop in input row.
- No avatar customisation.
- No multiple concurrent sessions in one tab.
- No deep-linking to a specific message.
- PTY → xterm path stays unchanged. No deprecation of PTY.

### Deferred to Follow-Up Work

- Conversation persistence (localStorage / session_dir on server): future PR.
- Markdown export of full session: future PR.
- Voice input via Web Speech API: future PR.
- Multi-part `agent_thought` rendering (currently the normaliser surfaces it; this plan does not render it visibly — internal reasoning stays hidden by default with a toggle as future work).

---

## Context & Research

### Relevant Code and Patterns

- `packages/studyloop/src/studyloop/web/static/index.html` lines 1284–1530 — `liveAgentConsole()` Alpine component, current transport branch, WS message handler.
- `packages/studyloop/src/studyloop/web/static/style.css` lines 1495–1910 — `.agent-console`, `.embedded-terminal-panel`, `.agent-console-log`, `.agent-message`, `.agent-console-input` (pre-existing chat CSS stubs from earlier prototype, ready to reuse).
- `packages/studyloop/src/studyloop/session/transports/acp_normaliser.py` — `AgentMessage(kind=...)` shape table (see Origin docs).
- `packages/studyloop/src/studyloop/session/transports/acp.py` — `_prompt_turn`, `turn_end` synthesis path.
- `packages/studyloop/src/studyloop/web/routes/session.py` lines 1175–1218 — WS pump (no server-side change needed; events already flow).
- `packages/studyloop/tests/test_web_acp_agent_matrix.py` — existing fixture infrastructure (`stub_acp_server`, `acp_page`, `STUDYLOOP_TEST_ACP_CMD`, `STUB_ACP_PROMPT_UPDATES`).
- `packages/studyloop/tests/_stub_acp_agent.py` — scripted stub agent driven by env vars; supports arbitrary `session/update` injection.
- `packages/studyloop/tests/test_web_vendor_xterm.py` — vendored JS smoke-test pattern (UMD globals, load order).

### Institutional Learnings

- `docs/plans/2026-05-09-refactor-agent-session-transport-plan.md` Amendment #11 — Alpine `x-show` keeps elements in DOM; Playwright assertions use `toBeVisible()` not DOM presence.
- `docs/plans/2026-05-09-refactor-agent-session-transport-plan.md` Amendment #12 — `term.buffer.active.translateToString()` is the only reliable Playwright xterm read path (matters for the unchanged PTY tests).
- `docs/research/2026-05-10-acp-event-shapes.md` — canonical `session/update` event shapes; `_extractChunkText` handles both single-object and array `content` forms.
- `splitLayout` component pattern in `index.html` lines 1677–1705 — cross-component Alpine reads need `try/catch` (Alpine init race); `Alpine.store(...)` is the cleaner cross-component bus.
- `docs/archive/local_repo_docs/solutions/integration-issues/multi-agent-adapter-mcp-setup-gap.md` — ACP transport intentionally bypasses `mcp_setup()`; do not re-introduce.

### External References

- `marked` (https://github.com/markedjs/marked) — chosen markdown renderer. GFM support, ~30KB minified, configurable to safe subset (`marked.setOptions({headerIds:false, mangle:false})` and renderer overrides for safety).
- `highlight.js` (https://highlightjs.org/) — chosen syntax highlighter. Common-langs build (~30KB) covers bash, python, sql, json, typescript, javascript.
- `DOMPurify` (https://github.com/cure53/DOMPurify) — XSS sanitiser. Required regardless of renderer choice — the agent can emit anything, including `<script>` and event handlers.

### ACP Event Shapes (carried from repo research)

| `AgentMessage.kind` | Triggered by | Payload (excluding `sessionId`) | UI rendering |
|---|---|---|---|
| `agent_chunk` | `session/update` `agent_message_chunk` | `{content: {type, text} \| [{type, text}]}` | Markdown bubble, assistant role |
| `agent_thought` | `session/update` `agent_thought_chunk` | `{content: ...}` | Hidden by default (deferred toggle) |
| `tool_call` | `session/update` `tool_call` | `{toolCallId, name, arguments, ...}` | New tool-call card |
| `tool_call_update` | `session/update` `tool_call_update` | `{toolCallId, status, output, ...}` | Update existing card by `toolCallId` |
| `plan` | `session/update` `plan` | `{steps: [{title, status}]}` | Plan tree render |
| `plan_update` | `session/update` `plan_update` | `{steps: [...]}` | Replace plan tree |
| `request_permission` | `session/update` `request_permission` | `{toolCallId, options: [{kind, name, optionId}]}` | Inline allow/deny prompt |
| `turn_end` | `_prompt_turn` synth from RPC result | `{reason: stopReason}` | Unlock input; close any pending streaming bubble |
| `available_commands_update` | `session/update` `available_commands_update` | (dropped by normaliser) | Never reaches UI |

---

## Key Technical Decisions

- **Replace xterm entirely for ACP, not augment** — tried hybrid (PR-E), confirmed worst-of-both-worlds. Rationale: ACP's structured events warrant a structured surface; squeezing them through ANSI byte stream throws away the entire ACP value proposition.
- **Vendor `marked`, `highlight.js`, `DOMPurify`** — same pattern as xterm vendoring (committed files, no build step). Avoids npm runtime, no supply-chain drift, cacheable. Hand-rolling markdown costs days, edge cases (nested fenced code) bite indefinitely.
- **Alpine.js, no framework swap** — current stack works; introducing React/Vue creates two paradigms in one file with no payoff.
- **Single seam at `liveAgentConsole.start()`** — branch on `transport === 'acp' ? _mountAcpChat() : _mountXterm()`. PTY path stays untouched.
- **`tool_call` keyed by `toolCallId`** — `tool_call_update` mutates by ID. Tool-call cards stored in `toolCallsById: Map<id, card>` for O(1) lookup; the ordered display list `acpMessages: []` references cards by id. This avoids duplicate cards while preserving the chronological message stream.
- **Bash output rendering inside the card, not a separate persistent pane** — keeps causal link between tool invocation and its output. A persistent pane would force users to scroll between conversation and output.
- **Permission prompt = inline blocking bubble, hold `acpSending = true`** — prevents user racing to send another prompt while a permission decision is pending. Allow/deny buttons send a new WS frame `{type: 'permission_response', toolCallId, optionId}` (see U6 for server-side handling).
- **DOMPurify is the authoritative XSS gate** — marked v12 has a small attack surface and DOMPurify strips scripts/event handlers/iframes regardless. Allow `pre`, `code`, `a` (with `target="_blank"` `rel="noopener noreferrer"`), basic inline formatting. Configure `ADD_ATTR: ['target', 'rel']` for safe link rendering. Do NOT rely on marked options — `headerIds` and `mangle` were removed in marked v9+ and are no-ops in v12. If heading IDs need suppression, override `renderer.heading` directly.
- **Render markdown synchronously per `agent_chunk`** — chunks are small (token-streaming); marked + highlight.js + DOMPurify is fast enough (<5ms per chunk on ARM/M-series). Stream chunks append to the streaming bubble; on `turn_end` the bubble is finalised.
- **No virtualised scroll** — sessions are short (study session = 25-90min focus block); message count stays bounded. Re-evaluate if a single session ever exceeds 200 messages.

---

## Open Questions

### Resolved During Planning

- **Replace vs augment xterm for ACP**: Replace. Confirmed by user; rationale above.
- **PTY future**: Keep both — picker chooses. PTY is unchanged.
- **Markdown library**: `marked` + `highlight.js` + `DOMPurify`, all vendored.
- **Tool-call UI shape**: Collapsible card; bash output renders inside the card (not a separate pane).
- **Permission prompt UX**: Inline blocking bubble with allow/deny buttons.

### Deferred to Implementation

- **Exact CSS animation for status transitions on tool-call cards** (pending → running → done): visual polish, decide while wiring.
- **Whether `agent_thought` toggle ships in v1 or as follow-up**: lean to follow-up; decide when implementing U5 if cheap.
- **Server-side handling of `permission_response` WS frame**: route handler shape decided in U6 once the ACP `request_permission` payload is observed in a real Kiro session (no live trace available at plan time).
- **highlight.js language pack size**: pick `common` build first; trim to bash/python/sql/json/ts/js if size becomes a concern.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Component Layout

```
.session-terminal-area  (existing Alpine x-data="liveAgentConsole()")
├── (transport === 'pty')  →  .embedded-terminal-panel.xterm-panel       [unchanged]
│                              └── xterm mount + acp-input-row [legacy hybrid; remove from ACP path]
└── (transport === 'acp')  →  .embedded-terminal-panel.acp-chat-panel    [NEW]
                               ├── .agent-console-toolbar    (status, agent name, controls)
                               ├── .acp-chat-log             (scrollable, virtualised? No — bounded session)
                               │   ├── .acp-message.assistant   (markdown bubble)
                               │   ├── .acp-message.user        (echo bubble)
                               │   ├── .acp-tool-call           (collapsible card)
                               │   │   ├── .acp-tool-call-header  (name, args, status)
                               │   │   ├── .acp-tool-call-body    (args expanded + output)
                               │   │   └── .acp-tool-exec-pane    (when name ~= bash|shell|exec)
                               │   ├── .acp-plan                (tree of {title, status})
                               │   └── .acp-permission-prompt    (allow / deny — blocks input)
                               └── .acp-input-row            (existing ACP input row, reuse)
```

### State Model (liveAgentConsole additions)

```
acpMessages: []                    // ordered list of message objects (assistant text, user text, tool-call, plan, permission)
toolCallsById: Map<id, card>       // fast lookup for tool_call_update merging
streamingMessageId: null | id      // current streaming assistant bubble (chunks append here)
plan: null | {steps: [...]}        // latest plan/plan_update payload
pendingPermission: null | {...}    // when set, input row is hidden + blocking prompt visible
```

### Frame Routing (in _openWebSocket message handler)

```
frame.type === 'agent_message':
  switch (frame.kind):
    'agent_chunk'         → append text to streamingMessageId; create new bubble if null
    'agent_thought'       → ignore (deferred surface)
    'tool_call'           → push new tool-call card, register in toolCallsById
    'tool_call_update'    → find by toolCallId, merge update; if status terminal, render output
    'plan'                → set plan
    'plan_update'         → set plan
    'request_permission'  → set pendingPermission, lock input
    'turn_end'            → finalise streamingMessageId, set null
```

### Markdown Pipeline

```
chunk.text → marked.parse(text) → DOMPurify.sanitize(html, config) → element.innerHTML
                                                                       ↓
                                                          highlight.js auto-highlight on rendered <pre><code>
```

---

## Output Structure

```
packages/studyloop/src/studyloop/web/static/
├── index.html                                    [modify]
├── style.css                                     [modify]
└── vendor/
    ├── js/
    │   ├── marked-12.0.0.min.js                  [new — vendor]
    │   ├── highlight-11.9.0.min.js               [new — vendor, common build]
    │   └── purify-3.1.0.min.js                   [new — vendor]
    └── css/
        └── highlight-tokyo-night-dark.css        [new — vendor, theme matching --bg]

packages/studyloop/tests/
├── test_web_acp_chat_ui.py                       [new]
├── test_web_acp_agent_matrix.py                  [modify — migrate xterm assertions to chat DOM]
├── test_web_vendor_xterm.py                      [modify — add globals smoke-test for marked/hljs/DOMPurify]
├── test_acp_transport.py                         [modify — add send_permission/permission round-trip tests]
└── _stub_acp_agent.py                            [modify — per-turn scripted updates + permission-response handler]

docs/
└── plans/2026-05-27-001-feat-acp-chat-ui-plan.md [this file]
```

---

## Implementation Units

- U1. **Vendor marked + highlight.js + DOMPurify**

**Goal:** Add three vendored JS libraries + one CSS theme to the static asset tree, exposed as UMD globals (`marked`, `hljs`, `DOMPurify`) so Alpine code can call them inline without bundlers.

**Requirements:** Foundational for R2, R3, R5, R9.

**Dependencies:** None.

**Files:**
- Create: `packages/studyloop/src/studyloop/web/static/vendor/js/marked-12.0.0.min.js`
- Create: `packages/studyloop/src/studyloop/web/static/vendor/js/highlight-11.9.0.min.js`
- Create: `packages/studyloop/src/studyloop/web/static/vendor/js/purify-3.1.0.min.js`
- Create: `packages/studyloop/src/studyloop/web/static/vendor/css/highlight-tokyo-night-dark.css`
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` (add `<script>` and `<link>` tags in head, in load order: DOMPurify → marked → highlight.js → theme CSS)
- Test: `packages/studyloop/tests/test_web_vendor_xterm.py` (extend with parallel cases for the three new globals)

**Approach:**
- Pin specific minor versions in filenames (matches xterm vendoring pattern).
- Source files from official CDNs (jsDelivr / unpkg) at known hashes; record hashes in commit message.
- Load order matters: DOMPurify is independent; marked is independent; highlight.js needs no peer; the theme CSS only styles `<pre><code>` output of highlight.js.

**Patterns to follow:**
- `packages/studyloop/src/studyloop/web/static/vendor/js/xterm-6.0.0.js` and the `<script>` tags already in `index.html`.
- `packages/studyloop/tests/test_web_vendor_xterm.py` for the smoke-test shape (UMD global presence).

**Test scenarios:**
- Happy path. `window.marked`, `window.hljs`, `window.DOMPurify` are defined after `index.html` loads (parallel to existing xterm globals test).
- Edge case. The theme CSS is requested with status 200 and `Content-Type: text/css`.
- Edge case. No `<script src>` 404 in the static asset directory listing.

**Verification:**
- `uv run pytest packages/studyloop/tests/test_web_vendor_xterm.py -m e2e -v` passes.
- Manual: `curl -I http://127.0.0.1:8567/static/vendor/js/marked-12.0.0.min.js` returns 200.

---

- U2. **Mount `_mountAcpChat` and branch transport at `liveAgentConsole.start()`**

**Goal:** Add the ACP chat panel template + Alpine state + `_mountAcpChat(detail)` method. Branch the existing transport gate so PTY → xterm and ACP → chat. Empty placeholder render — message handling lands in U3+.

**Requirements:** R1, R8.

**Dependencies:** U1.

**Files:**
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` (add `<div class="embedded-terminal-panel acp-chat-panel" x-show="terminalMode === 'acp-chat'">` block, change `start(detail)` to branch on transport, add `_mountAcpChat`, register new state fields)
- Modify: `packages/studyloop/src/studyloop/web/static/style.css` (add `.acp-chat-panel`, `.acp-chat-log` flex layout — mirror `.xterm-panel`)

**Approach:**
- New `terminalMode` value: `'acp-chat'`. Existing `'xterm'` and `'ttyd-iframe'` values unchanged.
- `_mountAcpChat` initialises state (`acpMessages = []`, `toolCallsById = new Map()`, `streamingMessageId = null`, `plan = null`, `pendingPermission = null`), sets `terminalMode = 'acp-chat'`, then calls `_openWebSocket(detail)`.
- WS message handler stays in `_openWebSocket`; the chat-vs-xterm branching of `frame.type === 'agent_message'` lands in U3.
- **Relocate `acp-input-row` form OUT of `.xterm-panel` and INTO `.acp-chat-panel`** as part of this unit (do not defer to U8). Only one input row exists per session — never two.
- **`_sendAcpInput` body becomes branched**: `if (this._term) { this._term.writeln(...) } else { this.acpMessages.push({role:'user', text}) }`. Keep the `if (this._term)` guard for PTY (still echoes via xterm); else-branch handles ACP echo via the chat log. Do NOT remove the existing guard wholesale.
- **Extend `stop()` to reset all new ACP chat state**: append `this.acpMessages = []; this.toolCallsById = new Map(); this.streamingMessageId = null; this.plan = null; this.pendingPermission = null; this.terminalMode = null;` to the existing reset block. Latent terminalMode-not-cleared issue is fixed at the same time. Without this, PTY→ACP→PTY session cycling leaks stale state and locks input.

**Patterns to follow:**
- `_mountXterm` flow (load assets → mount → open WS).
- `.embedded-terminal-panel` flex column pattern.
- Existing `_sendAcpInput` (keep `acpSending` lock + WS frame).

**Test scenarios:**
- Happy path. ACP session mounts the chat panel (visible) and not the xterm panel (hidden) — assert via `toBeVisible()` / `toBeHidden()`.
- Happy path. PTY session mounts the xterm panel and not the chat panel.
- Edge case. Switching from a finished ACP session to a new PTY session correctly tears down chat state and mounts xterm.
- Edge case. `_sendAcpInput` from the input row pushes a user-role message into `acpMessages`.

**Verification:**
- New chat panel visible for `transport=acp`, hidden for `transport=pty`.
- xterm panel visible for `transport=pty`, hidden for `transport=acp`.
- Existing PTY tests in `test_web_agent_matrix.py` still pass unchanged.

---

- U3. **`agent_chunk` → markdown bubble with code-block highlighting**

**Goal:** Render assistant text. Each `agent_chunk` either creates a new streaming bubble (if `streamingMessageId === null`) or appends text to the current one. On `turn_end`, finalise — re-render full bubble through marked → DOMPurify → highlight.js so a code block split across chunks renders correctly.

**Requirements:** R2, R9.

**Dependencies:** U1, U2.

**Files:**
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` (extend WS message handler, add `_appendAgentChunk`, `_finaliseStreamingBubble`, `_renderMarkdown` helper)
- Modify: `packages/studyloop/src/studyloop/web/static/style.css` (`.acp-message.assistant`, `.acp-message.user`, `.acp-message pre code`, role label column)
- Test: `packages/studyloop/tests/test_web_acp_chat_ui.py` (new file)

**Approach:**
- During streaming, append raw text to a `<pre>`-styled placeholder for snappy feedback.
- On `turn_end`, re-render the full accumulated text through marked → DOMPurify → highlight.js and replace the placeholder.
- DOMPurify config: forbid `script`, `style`, `iframe`, `object`, `embed`, `form`; allow `pre`, `code`, `a` (with `target="_blank" rel="noopener noreferrer"`); strip event-handler attributes.
- highlight.js: call `hljs.highlightAll()` on the message subtree after sanitisation.

**Patterns to follow:**
- `_extractChunkText(payload)` already in `index.html` for both content shapes.
- DOMPurify default safelist + targeted additions documented in the marked README.

**Test scenarios:**
- Happy path. Stub agent emits `agent_chunk` with `Hello, **world**`; bubble renders `<strong>world</strong>` after `turn_end`.
- Happy path. Multi-chunk fenced code block (` ```python\nprint(1)\n``` ` split across two chunks) renders one highlighted code block, not two raw fragments.
- Edge case. `agent_chunk` with `content` as object form (Gemini) and array form (Kiro) both render identically.
- Error path. Malicious chunk text `<script>alert(1)</script>` renders as escaped text, no script tag in DOM. `<a href="javascript:alert(1)">x</a>` renders as `<a>x</a>` with the unsafe href stripped.
- Integration. Streamed multi-chunk text accumulates correctly into a single bubble that is finalised on `turn_end`. (The `TestAgentChunkRendersInXterm` migration to chat-surface assertions is owned by U7, not this unit.)

**Verification:**
- Stub-driven Playwright run shows rendered markdown + syntax highlighting.
- DOMPurify config rejects `<script>`, `javascript:` href, `onerror=` attributes — verified by negative assertions.

---

- U4. **`tool_call` + `tool_call_update` cards (collapsible, with bash exec pane)**

**Goal:** Render `tool_call` events as cards keyed by `toolCallId`. `tool_call_update` mutates the matching card. When tool name matches `/^(bash|shell|exec|run)/i`, render output in a `<pre>`-styled exec pane styled like a terminal.

**Requirements:** R3, R4, R5.

**Dependencies:** U2, U3 (`_renderMarkdown` helper used for non-shell tool output), U9 (multi-turn stub scripting for tests).

**Files:**
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` (handle `tool_call` and `tool_call_update` kinds, render card template via `<template x-for>` over `acpMessages` filtered by `kind === 'tool_call'`, click handler for collapse toggle, helper `_isShellTool(name)`)
- Modify: `packages/studyloop/src/studyloop/web/static/style.css` (`.acp-tool-call`, `.acp-tool-call-header`, `.acp-tool-call-body`, `.acp-tool-call-status-{pending,running,done,failed}`, `.acp-tool-exec-pane` monospace + dark bg)
- Test: `packages/studyloop/tests/test_web_acp_chat_ui.py`

**Approach:**
- Each `tool_call` pushes `{kind: 'tool_call', id, name, args, status: 'pending', output: '', expanded: false}` to `acpMessages` and registers in `toolCallsById`.
- `tool_call_update` looks up by `id`, merges fields shallowly. Status transitions: `pending → running → done | failed`.
- Args render as JSON pretty-printed inside the body (`<pre><code class="language-json">`).
- Output rendering branches: if `_isShellTool(name)`, dump raw text into `.acp-tool-exec-pane` (monospace, scrollable, dark background); otherwise pass through markdown pipeline.
- Default collapsed; click header to expand. Body always shown when status is `failed` (so error is visible).

**Patterns to follow:**
- Alpine `<template x-for>` already used elsewhere in `index.html` for repeated lists.
- Hierarchical state objects in Alpine (mutate by id, then re-render).

**Test scenarios:**
- Happy path. Stub emits `tool_call(id="t1", name="search_docs", arguments={q:"x"})` → card appears with name "search_docs", status pending.
- Happy path. Subsequent `tool_call_update(id="t1", status="running")` flips status indicator without creating a duplicate card.
- Happy path. `tool_call_update(id="t1", status="done", output="result text")` sets status done and renders output.
- Happy path. Tool name "bash" → output renders in `.acp-tool-exec-pane` (monospace, dark).
- Edge case. Tool name "Bash" / "shell" / "exec" / "run" / "run_command" all match the shell heuristic.
- Edge case. Two concurrent tool_calls (different ids) render as two distinct cards; updates route to the correct one.
- Error path. `tool_call_update` with no matching `toolCallId` is dropped silently with a `console.warn` — does not throw.
- Error path. `tool_call_update` with `status="failed"` shows red status and auto-expands the card.
- Integration. Click on collapsed card header toggles `expanded`; body becomes visible.

**Verification:**
- Cards render distinctly for shell vs non-shell tools.
- Status transitions visible across stub-emitted updates.
- No duplicate cards under stress (10 updates to one id).

---

- U5. **`plan` / `plan_update` tree render**

**Goal:** Render `plan` and `plan_update` events as a live todo-list. Steps with `status === 'completed'` are struck through. Plan replaces in place when a new `plan_update` arrives.

**Requirements:** R6.

**Dependencies:** U2, U9 (multi-turn stub scripting for tests).

**Files:**
- Modify: `packages/studyloop/src/studyloop/session/transports/acp_normaliser.py` (add explicit `UPDATE_KIND_MAP` entries for `plan` and `plan_update` — verify wire-string discriminator names against the live ACP CLI before relying on passthrough)
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` (add `plan` + `plan_update` to the WS handler — both set `this.plan = payload`; render block via `<template x-if="plan">` showing `plan.steps`)
- Modify: `packages/studyloop/src/studyloop/web/static/style.css` (`.acp-plan`, `.acp-plan-step`, `.acp-plan-step-completed { text-decoration: line-through; opacity: 0.6 }`, status icons)
- Test: `packages/studyloop/tests/test_acp_normaliser.py` (add unit tests for the new map entries)

**Approach:**
- Plan renders as a sticky panel above the input row, OR inline as a chat message — pick inline for v1 (matches the "this is what the agent is going to do next" mental model). Re-evaluate after dogfooding.
- Step shapes: `{title, status}` where status ∈ `pending|in_progress|completed|failed`.
- Latest plan replaces previous (don't keep history). If user wants to scroll back, they'll use the messages.

**Patterns to follow:**
- Alpine `<template x-if="plan">` and `<template x-for="step in plan.steps">`.

**Test scenarios:**
- Happy path. Stub emits `plan` with three steps `[a, b, c]`, all pending → list shows three items.
- Happy path. `plan_update` with first step `completed` → first item struck through, others unchanged.
- Edge case. Empty `plan.steps` array → plan panel renders empty (no error).
- Edge case. `plan` with no payload (`{}`) → handled gracefully (no crash).
- Edge case. New `plan` after old plan replaces, doesn't append.

**Verification:**
- Plan panel updates in place across multiple `plan_update` events.

---

- U6. **`request_permission` inline allow/deny prompt**

**Goal:** When `request_permission` arrives, render an inline blocking bubble with allow + deny buttons. Holding `acpSending = true` until resolved. On click, send a new WS frame `{type: 'permission_response', toolCallId, optionId}`. Server-side route handler forwards to ACP transport.

**Requirements:** R7.

**Dependencies:** U2, U4 (for the matching tool-call card visual association), U9 (multi-turn stub scripting for tests).

**Files:**
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` (handle `request_permission` kind, render `.acp-permission-prompt` block with buttons, `_resolvePermission(optionId)` helper)
- Modify: `packages/studyloop/src/studyloop/web/static/style.css` (`.acp-permission-prompt` — distinct yellow/amber styling, allow/deny button colours)
- Modify: `packages/studyloop/src/studyloop/web/routes/session.py` (extend `ws_to_pty` handler in `live_session_socket`: accept `{type: 'permission_response', toolCallId, optionId}` and forward via duck-typed `hasattr(transport, 'send_permission')` guard — see Approach for rationale)
- Modify: `packages/studyloop/src/studyloop/session/transports/acp.py` (add `send_permission(toolCallId, optionId) -> None` method — sends the ACP JSON-RPC permission-response method with payload matching the spec)
- Modify: `packages/studyloop/src/studyloop/session/transports/acp_normaliser.py` (add explicit `UPDATE_KIND_MAP` entry for `request_permission` — do not rely on passthrough)
- Modify: `packages/studyloop/tests/_stub_acp_agent.py` (add JSON-RPC handler for the permission-response method so e2e verification can complete the round-trip)
- Test: `packages/studyloop/tests/test_web_acp_chat_ui.py` (UI), `packages/studyloop/tests/test_acp_transport.py` (transport), `packages/studyloop/tests/test_acp_normaliser.py` (normaliser)

**Approach:**
- ACP method name for permission response: pulled from spec docs at implementation time. If the live ACP CLI uses a different name, the implementation adjusts but the WS frame contract stays.
- `request_permission` payload: `{toolCallId, options: [{kind, name, optionId}]}`. Each option becomes a button.
- While `pendingPermission !== null`: hide input row, show permission prompt prominently. On resolve: clear `pendingPermission`, restore input row, release `acpSending`.
- **Server-side Protocol pattern**: do NOT add `send_permission` to the `AgentSessionTransport` Protocol — Python `Protocol` cannot have optional methods with default no-op bodies (concrete classes failing structural checks at runtime breaks PTY). Instead, in `ws_to_pty` use `hasattr(transport, 'send_permission')` as the duck-type guard and call only when present. PTYTransport gets no method added; ACPTransport adds the concrete method. Future transports opt-in by implementing the same method name. New unit test asserts the route forwards correctly via mock with the method present, and silently no-ops when absent.
- **Stub agent**: `_stub_acp_agent.py` must add a handler for the permission-response JSON-RPC method so the e2e Verification path can complete (otherwise the stub returns -32601 "Method not found" and the test surfaces as a `transport_error`).

**Execution note:** Test-first for the server-side route + transport method — the contract matters and the surface is small.

**Test scenarios:**
- Happy path. Stub emits `request_permission` with two options `[allow, deny]` → both buttons render; input row hidden.
- Happy path. Click allow → WS frame `{type: 'permission_response', toolCallId, optionId}` sent; prompt clears; input row restored.
- Edge case. Stub emits `request_permission` with one option only → single button renders.
- Edge case. Stub emits `request_permission` with three options (not just allow/deny) → all three render with `option.name` labels.
- Error path. Click during `acpSending = true` from a normal turn → permission flow takes precedence; no concurrent prompt sent.
- Integration. `request_permission` arrives mid-turn → input row already locked; permission prompt overlays; resolution clears both locks.
- Integration (server). WS frame `permission_response` reaches `ACPTransport.send_permission`; verified by spy mock.

**Verification:**
- End-to-end stub run: prompt → user clicks allow → stub sees the JSON-RPC respond message → conversation continues.

---

- U9. **Extend `_stub_acp_agent.py` for per-turn scripted notification flows**

**Goal:** Replace the static `STUB_ACP_PROMPT_UPDATES` (one notification sequence per subprocess) with a per-turn scripted mechanism so multi-turn test scenarios in U4 / U5 / U6 / U7 can drive different events on different prompts.

**Requirements:** R10 (test enablement).

**Dependencies:** None directly; **must land before U4, U5, U6, U7** because their multi-turn test scenarios depend on it.

**Files:**
- Modify: `packages/studyloop/tests/_stub_acp_agent.py`
- Modify: `packages/studyloop/tests/test_web_acp_agent_matrix.py` (existing fixture call sites — keep `STUB_ACP_PROMPT_UPDATES` working as the all-turns fallback)

**Approach:**
- Introduce `STUB_ACP_PROMPT_UPDATES_SEQ` — JSON array-of-arrays. Each inner array is the notification sequence emitted for the nth `session/prompt`. If the array is exhausted, last entry repeats (or fall back to `STUB_ACP_PROMPT_UPDATES` if set).
- Existing `STUB_ACP_PROMPT_UPDATES` env var keeps working as "every turn emits this sequence" for back-compat.
- Stub maintains a per-process `_prompt_count` counter; increments on each `session/prompt` request.

**Test scenarios:**
- Happy path. With `STUB_ACP_PROMPT_UPDATES_SEQ=[[chunk_a],[chunk_b]]`, two sequential prompts emit different chunk text.
- Happy path. Without `_SEQ` set but with the legacy `STUB_ACP_PROMPT_UPDATES` set, every prompt emits the same sequence (back-compat).
- Edge case. `_SEQ` array has 2 entries; third prompt repeats the last entry.

**Verification:**
- New unit test in `test_web_acp_chat_ui.py` (or a dedicated stub-test file) that drives two prompts and asserts different output streams.
- Existing per-agent matrix tests pass unchanged.

---

- U7. **Migrate / replace `TestAgentChunkRendersInXterm` and add `TestAcpChatSurface` matrix**

**Goal:** Update the per-ACP-agent matrix to assert on chat-surface DOM (not xterm buffer). Add new test class covering R1–R7 against both Kiro and Gemini stubs. PTY tests untouched.

**Requirements:** R10.

**Dependencies:** U2, U3, U4, U5, U6, U9.

**Files:**
- Modify: `packages/studyloop/tests/test_web_acp_agent_matrix.py` (replace `TestAgentChunkRendersInXterm` with `TestAcpChatChunkRenders` asserting on `.acp-message.assistant` content; remove `TestAcpInputRow` xterm-targeted tests; keep WS round-trip tests)
- Create: `packages/studyloop/tests/test_web_acp_chat_ui.py` (new file, parametrised over kiro+gemini, uses `stub_acp_server` fixture; covers tool-call cards, plan tree, permission prompt, markdown rendering)
- Update: `packages/studyloop/tests/_stub_acp_agent.py` if current scripted notification flow is too rigid (it accepts `STUB_ACP_PROMPT_UPDATES` JSON; extend to support multiple `tool_call` + `plan` + `request_permission` notifications per turn)

**Approach:**
- Reuse `stub_acp_server` and `acp_page` fixtures.
- Each test class drives a different stub script via `STUB_ACP_PROMPT_UPDATES`.
- All assertions on rendered DOM use `.acp-*` selectors and `toBeVisible()` / `textContent()` — not `term.buffer.active`.

**Patterns to follow:**
- Existing `TestAcpAgentMatrix` parametrisation (`@pytest.mark.parametrize("agent", ACP_AGENTS)`).
- Existing `_start_acp_session_in_dom` helper for the bypass-the-picker dance.

**Test scenarios:**
- (See per-unit test scenarios in U3, U4, U5, U6 — this unit aggregates them in the matrix file.)
- Smoke: every chat surface test passes for both kiro and gemini agents.

**Verification:**
- `uv run pytest packages/studyloop/tests/test_web_acp_chat_ui.py packages/studyloop/tests/test_web_acp_agent_matrix.py -m e2e -v` — all green.
- `uv run pytest packages/studyloop/tests/test_web_agent_matrix.py -m e2e -v` (PTY matrix) still passes unchanged.

---

- U8. **Cleanup: remove ACP usage of xterm + dead PR-D/PR-E code**

**Goal:** Once chat surface is the single ACP path, remove the xterm `agent_chunk → term.write` plumbing for ACP, the `acp-input-row` from inside the xterm panel (it's now inside the chat panel), and the `> {text}` echo writeln. PTY path keeps its xterm wiring.

**Requirements:** R8 (cleanly enforced by removing the path entirely rather than leaving dead branches).

**Dependencies:** U2, U3, U4, U5, U6.

**Files:**
- Modify: `packages/studyloop/src/studyloop/web/static/index.html` (in `_openWebSocket` message handler, remove the ACP branches inside the xterm-targeted `agent_message` block; remove the `term.writeln` lines that wrote `> {text}` echo and `[turn end_turn]` markers — those land in the chat panel now)
- Modify: `packages/studyloop/src/studyloop/web/static/style.css` (no `.acp-input-row` removal — class is reused inside chat panel; only verify CSS selectors don't accidentally apply to xterm panel)

**Approach:**
- Walk the WS message handler; the `frame.kind === 'agent_chunk'` and `frame.kind === 'turn_end'` blocks that write into `this._term` are removed (these branches are dead for ACP after U2, since `_term` is null in the chat path).
- Confirm `_sendAcpInput`'s `if (this._term) { writeln } else { push }` branching from U2 is correct and the `else` branch is taken in ACP sessions.
- Input-row relocation is owned by U2; this unit only verifies no orphaned duplicate input row remains in the xterm panel.

**Test scenarios:**
- Happy path. ACP session does not touch `_term` (does not exist for ACP — `terminalMode === 'acp-chat'`).
- Happy path. PTY session still receives raw bytes via `term.write` per existing flow.
- Edge case. Switching from PTY → ACP → PTY across three sessions does not leak xterm into the chat panel or vice versa.

**Verification:**
- Search the codebase: no `_term.write` calls inside ACP-only branches.
- PTY agent matrix tests pass; ACP chat tests pass.

---

## System-Wide Impact

- **Interaction graph:** WS message handler becomes the central event router; new branches added but existing branches (`started`, `stopped`, `transport_error`, PTY `OutputBytes`) untouched.
- **Error propagation:** `transport_error` frames already release `acpSending`; with the chat surface, also clear `pendingPermission` if any to avoid permanent lock.
- **State lifecycle risks:** `acpMessages` array can grow large in long sessions; bounded by 25-90min focus block. Tool-call cards held in a Map by id — gc'd when session ends and component is torn down. Reload clears state by design.
- **API surface parity:** New WS frame type `permission_response` is additive — existing clients ignore unknown frame types. Server-side `transport.send_permission` is an additive Protocol method with default no-op.
- **Integration coverage:** Stub agent must be extended to script multi-event flows (chunk → tool_call → tool_call_update → plan → request_permission → turn_end) so the chat UI matrix can assert on full conversation flows, not just isolated event types.
- **Unchanged invariants:** PTY transport path, xterm component, ttyd legacy fallback, REST `/session/start` shape, WS frame envelope (`{type, kind?, payload?}`), `AgentMessage` normaliser. All untouched.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| XSS via agent-emitted markdown / `<script>` / `javascript:` href | DOMPurify in pipeline; explicit negative tests in U3; `Content-Security-Policy` header recommended as separate hardening (out of scope here, noted) |
| `request_permission` ACP method name uncertainty (no live trace at plan time) | U6 implements the WS frame contract first, then adjusts the server-side ACP RPC method name when observed in a real Kiro session; if the JSON-RPC method differs across Kiro/Gemini, normalise in `acp.py` |
| Vendored library size growth (3 new files ~100KB combined) | One-off — files cache; future xterm removal for ACP-only repos could net out |
| Plan v1 `agent_thought` hidden — users may want to see reasoning | Defer toggle; add in follow-up PR if dogfooding shows demand |
| Markdown rendering flakiness (split fenced code across chunks) | Streaming bubble shows raw text; finalise re-renders full markdown on `turn_end`; test scenario in U3 covers this |
| Tool-call output extremely large (e.g. `bash: find /` dump) | Exec pane has `max-height` + scroll; future virtualisation if needed |
| Two ACP agents (Kiro, Gemini) emit slightly different `tool_call` argument shapes | U4 renders args via `JSON.stringify(args, null, 2)` inside `<pre><code class="language-json">` — handles any shape without per-agent branching |
| Permission prompt locks UI permanently if server WS dies mid-prompt | `transport_error` handler clears `pendingPermission`; WS `close` handler same; manual user "End session" still works because the timer status bar's End button is outside the chat panel |

---

## Phased Delivery

### Phase 1 — Foundation (U1, U2, U9)
Vendoring + branched mount + stub multi-turn extension. U9 lands first (or alongside U1) so test infrastructure is ready before U4/U5/U6 begin. After this lands, ACP sessions show an empty chat panel; xterm is no longer invoked for ACP sessions (old xterm-write branches remain in code as unreachable until Phase 4 cleanup). Smoke-test value: regressions in PTY caught early.

### Phase 2 — Core Rendering (U3, U4, U5)
Chat content lights up: markdown bubbles, tool-call cards, plan tree. After this lands, the user can actually use ACP sessions.

### Phase 3 — Permission Flow (U6)
`request_permission` inline prompt + server-side WS handler. Required for tool-gated agents (Kiro permission policy enabled).

### Phase 4 — Test Migration + Cleanup (U7, U8)
Per-agent matrix updated; dead xterm-for-ACP code removed; PTY untouched.

---

## Documentation Plan

- Update `docs/plans/2026-05-09-refactor-agent-session-transport-plan.md` with an Amendment #13 entry pointing to this plan.
- Add a one-pager `docs/explanations/acp-chat-ui.md` after U7 lands, covering: the event → render pipeline, the markdown sanitisation policy, and how to extend with new event kinds.
- Update `README.md` (if it mentions ACP transport limitations / structured event surfacing) to reflect the new UI.

---

## Operational / Rollout Notes

- No feature flag — chat UI replaces xterm for ACP at the seam in U2. Picker still surfaces both transports; user selects per session.
- Browser cache: vendored JS is fingerprint-versioned by filename; first request hits cold cache, subsequent are fresh-from-CDN-style.
- No server config changes; no environment variables added.
- No DB migrations.

---

## Sources & References

- **Origin / related plan:** [docs/plans/2026-05-09-refactor-agent-session-transport-plan.md](2026-05-09-refactor-agent-session-transport-plan.md)
- **ACP event shapes research:** [docs/research/2026-05-10-acp-event-shapes.md](../research/2026-05-10-acp-event-shapes.md)
- **xterm vendoring smoke test:** `packages/studyloop/tests/test_web_vendor_xterm.py`
- **ACP per-agent matrix (existing):** `packages/studyloop/tests/test_web_acp_agent_matrix.py`
- **Stub ACP agent driver:** `packages/studyloop/tests/_stub_acp_agent.py`
- **External:** marked (https://github.com/markedjs/marked), highlight.js (https://highlightjs.org/), DOMPurify (https://github.com/cure53/DOMPurify)
