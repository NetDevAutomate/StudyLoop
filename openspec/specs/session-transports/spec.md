## Purpose

Run a live study session by spawning an AI agent CLI (Kiro, Claude Code,
Gemini, Codex, OpenCode) as a child process and streaming its output to the
web UI in real time. StudyLoop supports two wire protocols to the agent
(ACP JSON-RPC over stdio, and a raw PTY), selected per-agent, plus a legacy
tmux+ttyd fallback. Exactly one session may be active at a time.

## Requirements

### Requirement: Transport selection is per-agent, not user-chosen
The system SHALL route each agent to the transport it actually supports:
Kiro, Gemini, and Grok via ACP (`ACP_CAPABLE_AGENTS` in
`web/services/session_start.py`); Claude Code, Codex, and OpenCode via PTY.
The request body field `transport` (`"pty" | "acp" | "ttyd"`) selects the
code path but does not itself grant ACP capability to a PTY-only agent — a
server-side guard rejects `transport: "acp"` for any agent outside
`ACP_CAPABLE_AGENTS` with a 400 before spawning.

#### Scenario: ACP request for a PTY-only agent
- **WHEN** `POST /api/session/start` is called with `transport: "acp"` and
  `agent: "Claude Code"`
- **THEN** the ACP transport attempts to speak JSON-RPC to a process that
  does not implement the ACP protocol, and the session fails to establish
  (no server-side capability gate exists as of `9f033fa`; this is tracked
  as open hardening work, not implemented behavior)

### Requirement: Only one session may be active
The system SHALL enforce a single live session at a time via an
`asyncio.Lock`-guarded singleton (`session/active.py:46`). A second
`POST /api/session/start` while a session is active SHALL return HTTP 409.

#### Scenario: Second start attempt while a session is running
- **WHEN** a session is already active and the client posts another
  `/api/session/start`
- **THEN** the server responds with status 409 and does not spawn a second
  agent process

### Requirement: PTY transport owns the child process lifecycle
The system SHALL fork a PTY child (`pty.fork()`), `execvpe` the agent
binary, register a `SIGCHLD` handler on the event loop to detect process
exit, and stream raw bytes bidirectionally with `WINSZ` resize support
(`session/transports/pty.py:192`).

#### Scenario: Agent process exits
- **WHEN** the forked child process terminates (normally or via signal)
- **THEN** the registered `SIGCHLD` handler decodes the exit status, emits
  exactly one `Stopped(returncode, reason)` event, then a sentinel `None`
  that ends the transport's `events()` async generator

#### Scenario: SIGCHLD handler installed from a non-main thread
- **WHEN** `PTYTransport.start()` runs on an event loop that is not owned by
  the process's main thread (for example, uvicorn hosted in a background
  thread rather than as its own process)
- **THEN** `loop.add_signal_handler(SIGCHLD, ...)` raises `ValueError`
  because Python only permits installing signal handlers from the main
  thread, and the session-start request fails with an unhandled exception
  (verified root cause of the `POST /api/session/start` "Network error"
  regression seen under thread-hosted test servers; the frontend further
  masks this as a network error because `res.json()` throws on the
  resulting non-JSON 500 body before the `!res.ok` branch is reached)

### Requirement: ACP transport speaks JSON-RPC over stdio
The system SHALL spawn the agent via
`asyncio.create_subprocess_exec`, perform ACP `initialize` and
`session/new`, then translate `session/update` frames
(`agent_chunk`, `tool_call`, `tool_call_update`, `plan`, `plan_update`,
`request_permission`, `turn_end`) into `AgentMessage` events forwarded
over the session WebSocket (`session/transports/acp.py:120`,
`web/routes/session/_ws.py`).

#### Scenario: Persona delivered via invisible first prompt
- **WHEN** an ACP session's WebSocket first opens
- **THEN** the browser sends the `persona_text` (returned inline in the
  `/api/session/start` response body) as the first `session/prompt`, with a
  `_suppressStreamingBubble` flag set so the persona turn's `agent_chunk`,
  `tool_call*`, and `plan*` frames render nothing in the chat UI, and
  `request_permission` frames are auto-allowed, until that turn's
  `turn_end`

### Requirement: PTY persona delivery never touches the wire
The system SHALL write the persona text to a temp file and embed its path
in the agent's launch command argv for PTY-transported agents; persona
content SHALL NOT be sent as a runtime message on the PTY path.

#### Scenario: PTY session start
- **WHEN** a PTY-transported session starts
- **THEN** `build_canonical_persona()` output is written to a session-scoped
  temp file before the agent process is forked, and the launch command
  references that file path as an argument

### Requirement: Session directory naming is not path-traversal-safe
The system's `session_dir_name()` helper (`web/services/session_start.py:13`)
SHALL derive a directory name from `topic.lower().replace(" ", "-")[:20]`.
This transform does not strip `/`, `\`, or `..` sequences, and the same
unsafe transform is duplicated at `web/routes/session/_start.py:562`.

#### Scenario: Topic containing path-traversal sequences
- **WHEN** `POST /api/session/start` is called with
  `topic: "../../../etc"`
- **THEN** the computed session directory name contains the un-sanitized
  `../` sequence and the session directory may be created outside
  `SESSION_DIR` (confirmed defect; not yet fixed as of `61a15fc` — the
  `content.storage.slugify()` helper exists and strips unsafe characters
  but is not reused here)

### Requirement: Legacy ttyd fallback remains available
The system SHALL support a `transport: "ttyd"` path that starts a tmux
session plus a ttyd process, proxied same-origin through FastAPI at
`/terminal/` (HTTP and WebSocket), with the operator env var
`STUDYLOOP_TRANSPORT` able to force `pty`/`ttyd` (ACP is body-only and
cannot be forced via env var).

#### Scenario: Operator forces ttyd via environment
- **WHEN** `STUDYLOOP_TRANSPORT=ttyd` is set in the server environment
- **THEN** session starts use the ttyd transport regardless of the
  request body's `transport` field
