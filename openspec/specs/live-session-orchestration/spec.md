## Purpose

Orchestrate a live study session by composing a tmux window with an AI
agent in the main pane and a Textual sidebar in the right pane, managing
session lifecycle (start, IPC, end, cleanup) through shared state files.
The CLI entry point is `studyloop study`; the IPC surface
(`session-state.json`, `session-topics.md`, `session-parking.md`) is
polled by the TUI sidebar and the web dashboard independently.  Transport
selection and wire-protocol details are out of scope (see
`session-transports` spec).

## Requirements

### Requirement: studyloop study composes a tmux session with agent and sidebar panes
The system SHALL create a detached tmux session named
`study-{slug}-{id[:8]}`, run the resolved agent command in the main
pane, split the window horizontally for a 25%-width right sidebar pane
running `python -m studyloop.tui.sidebar`, then attach or switch the
client.  `session/orchestrator.py::create_tmux_environment()` performs
the split and `attach_if_needed()` calls `os.execvp("tmux", ["tmux",
"attach-session", ...])` when not already in tmux, or
`tmux.switch_client()` when already inside tmux.

#### Scenario: Starting a new study session from a non-tmux terminal
- **WHEN** `studyloop study "Python decorators" --energy 7` is run
  outside tmux
- **THEN** a detached tmux session is created, the agent launches in
  the main pane, the Textual sidebar launches in a 25% right split,
  and the calling process is replaced by `tmux attach-session`

#### Scenario: Starting a session while already inside tmux
- **WHEN** the user invokes `studyloop study` from within an existing
  tmux session
- **THEN** the new study session is created and the client switches to
  it via `tmux switch-client` rather than attempting a nested attach

### Requirement: Only one tmux-based session may be active at a time
The system SHALL reject a new `studyloop study` invocation when
`session_state.is_session_active()` returns True (state file exists with
a `study_session_id` and `mode != "ended"`).  The guard lives in
`session/start.py::start_session()` and raises `SessionStartError`.

#### Scenario: Attempting to start a second session
- **WHEN** a session is already active and `studyloop study` is invoked
  again
- **THEN** the command prints a message directing to `--resume` or
  `--end` and exits with code 1 without spawning tmux

### Requirement: IPC files provide the inter-process communication surface
The system SHALL maintain three files under `SESSION_DIR`
(`~/.config/studyloop` by default, overridable via
`STUDYLOOP_SESSION_DIR`): `session-state.json` (JSON, atomic
read-merge-write with `fcntl.flock`), `session-topics.md` (append-only
markdown lines), and `session-parking.md` (append-only markdown lines).
`session_state.py` owns all read/write functions:
`write_session_state()`, `append_topic()`, `append_parking()`,
`parse_topics_file()`, `parse_parking_file()`, `read_session_state()`.
The sidebar and web dashboard poll these files; agents write to them via
CLI commands.

#### Scenario: Agent logs a topic during a session
- **WHEN** the AI agent runs
  `studyloop topic "Closures" --status win --note "nailed it"`
- **THEN** `append_topic()` writes a line to `session-topics.md` and
  the sidebar's next 2-second poll cycle renders it in the activity feed

#### Scenario: Concurrent writers do not corrupt state
- **WHEN** the agent and sidebar both call `write_session_state()`
  within the same instant
- **THEN** `fcntl.flock(LOCK_EX)` on a dedicated `.session-state.lock`
  file serialises the read-merge-write operations, preventing data loss

### Requirement: studyloop park persists tangential questions to both DB and IPC
`cli/_session.py::park()` SHALL call `parking.park_topic()` to write the
question to the `parked_topics` SQLite table immediately (crash
resilience), then call `session_state.append_parking()` to append to
`session-parking.md` so the sidebar and web dashboard see it in their
next poll cycle.

#### Scenario: Parking a question during a live session
- **WHEN** `studyloop park "How do metaclasses work?"` is run while a
  session is active
- **THEN** the question is inserted into `parked_topics` in the
  sessions DB AND appended to `session-parking.md`

#### Scenario: Parking without an active session
- **WHEN** `studyloop park "question"` is run with no active session
- **THEN** the question is still persisted to the DB (via
  `park_topic()`) but nothing is appended to the IPC file (no
  `study_session_id` in state)

### Requirement: Energy-adaptive break suggestions use bounded thresholds
`logic/break_logic.py::check_break_needed()` SHALL compute
minutes-since-last-break and compare against energy-band thresholds:
Low (energy 1-3) micro=15/short=30/long=60, Medium (4-6)
micro=20/short=40/long=75, High (7-10) micro=25/short=50/long=90.
The sidebar calls this every poll cycle and renders a `BreakBanner`
widget with break-type-specific colouring.  Resuming from pause
(`action_toggle_pause`) increments `breaks_taken` and resets the
break clock by writing `last_break_at_min` to the state file.

#### Scenario: Low-energy session exceeds micro threshold
- **WHEN** a session started with `--energy 2` has been running 16
  minutes since the last break (or session start)
- **THEN** `check_break_needed()` returns a `BreakSuggestion` with
  `break_type="micro"` and the sidebar displays the break banner

#### Scenario: Pausing and resuming resets the break clock
- **WHEN** the user presses `p` in the sidebar to pause, then `p`
  again to resume
- **THEN** `last_break_at_min` is written to the state file at the
  current elapsed minute and `breaks_taken` is incremented, so the
  next break suggestion is deferred by a full threshold interval

### Requirement: Session end flushes summary to DB and clears IPC files
`session/cleanup.py::end_session_common()` SHALL parse topic and parking
IPC files, build session notes, call `history.end_study_session()` with
win/struggle counts, auto-persist struggled topics to the backlog via
`services/backlog.auto_persist_struggled()`, generate flashcards from
wins via `services/flashcard_writer.write_session_flashcards()`, record
per-topic confidence to `study_progress`, signal the dashboard
(`mode=ended`), kill background processes (web + ttyd by PID then port
fallback), remove `session-topics.md` and `session-parking.md`, and
kill all `study-*` tmux sessions.  `session-state.json` is kept with
`mode=ended` so the dashboard can render a summary view.

#### Scenario: Agent exits normally
- **WHEN** the agent process terminates (user types `/exit` or quits)
- **THEN** the shell wrapper calls `cleanup_on_exit()` which invokes
  `end_session_common()`; the DB session record is closed with notes
  summarising wins, struggles, and parked items

#### Scenario: User presses Q in the sidebar
- **WHEN** the user presses `Q` in the focused sidebar pane
- **THEN** the sidebar sends `Ctrl-C` then `/exit` to the main pane,
  runs `cleanup_on_exit()`, then fires `kill_all_study_sessions()`
  (which kills itself last via SIGHUP)

### Requirement: Orphan sessions are auto-cleaned before new session start
`session/cleanup.py::auto_clean_zombies()` SHALL run at the start of
every `studyloop study` invocation, identifying tmux sessions with the
`study-` prefix whose main pane has no child process and whose session
age exceeds 60 seconds (`tmux.is_zombie_session()`).  It delegates the
decision to `logic/clean_logic.py::plan_clean()` (pure function) and
executes the plan: kill zombie sessions, remove orphan session
directories under `SESSION_DIR/sessions/` that have no matching live
tmux session, and clear stale `session-state.json` when `mode=ended`
with no matching tmux session.

#### Scenario: tmux-resurrect restores a dead study session
- **WHEN** tmux-resurrect restores a previously killed `study-*`
  session on terminal restart, and the user runs `studyloop study`
- **THEN** `auto_clean_zombies()` detects the session has no child
  process and is older than 60s, kills it, removes its directory, and
  proceeds with normal session startup

#### Scenario: Explicit cleanup via CLI
- **WHEN** `studyloop clean --dry-run` is run
- **THEN** the same `plan_clean()` logic reports what would be cleaned
  (zombie sessions, orphan directories, stale state file) without
  performing any side effects

### Requirement: The sidebar polls IPC files every 2 seconds
`tui/sidebar.py::SidebarApp._poll_ipc_files()` SHALL run in a
background thread (Textual `@work(thread=True)`), sleeping 2 seconds
between iterations.  Each iteration reads `session-state.json` (for
timer/energy/mode), `session-topics.md` (for activity feed), and
`session-parking.md` (for parked items), recomputes elapsed time via
`_compute_elapsed()`, and updates the `TimerWidget`, `ActivityFeed`,
`CounterBar`, and `BreakBanner` widgets.  A `session-oneline.txt` file
is written as a side effect for tmux status-bar integration.

#### Scenario: State file updated mid-cycle
- **WHEN** the agent writes a new topic at second T and the poll fires
  at second T+1.5
- **THEN** the sidebar picks up the new topic on the next poll at
  T+2 (worst-case latency ~2 seconds)

### Requirement: Timer supports elapsed and pomodoro modes with sidebar key bindings
The `TimerWidget` SHALL render in two modes selected by the
`timer_mode` field in `session-state.json`: `"elapsed"` (count-up with
energy-adaptive green/amber/red colour phases) and `"pomodoro"`
(countdown through configurable focus/short-break/long-break cycles,
defaulting to 25/5/15 minutes with 4 cycles per set, overridable via
`config.yaml` pomodoro settings).  The sidebar binds `p` (toggle
pause/resume), `r` (reset timer), `s` (toggle pomodoro/elapsed), `+`
(increase pomodoro focus by 5 min, capped at 120), `-` (decrease focus
by 5 min, floored at 5), `Q` (end session), and `q` (quit sidebar
only).

#### Scenario: Switching to pomodoro mid-session
- **WHEN** the user presses `s` in the sidebar during an elapsed-mode
  session
- **THEN** `timer_mode` is written as `"pomodoro"` to the state file
  and the timer re-renders as a countdown within the current focus
  block

### Requirement: Session purpose
A web session start (`POST /api/session/start`) SHALL carry a *purpose* —
`focus` (the default) or `planning` — validated structurally by
`StartSessionRequest` (`purpose: Literal["focus", "planning"] = "focus"`), so
any other value is refused with `422` before the handler runs. A `focus` start
SHALL be indistinguishable from a start that names no purpose: the same
persona, the same `persona_hash`, the same session-state `mode`. A `planning`
start SHALL launch the study-plan architect: the persona is the
`plan-architect` mode carrying a `## Planning brief` section (the interview
questions, the learner's history evidence, the existing plans and — only when
the request carried one — the learner's brain dump), and the session's topic
is the learner's subject when one was supplied, else the fixed label
`Study plan` — the same label `studyloop plan architect` pins. The start
SHALL NOT create a plan and SHALL NOT store a plan id anywhere; the architect
creates plans through the plan tools during the session.

The request MAY carry `brain_dump: str | None` (default `None`, `max_length`
`BRAIN_DUMP_MAX_CHARS` = 4000, published by `_models`), the learner's own free
text for the architect. On a `planning` start a non-blank dump SHALL be
rendered by the brief renderer as a fourth section, `### Learner's brain dump`,
after `### Existing plans`, introduced as the learner's words — evidence, not
instructions — with every line of the dump emitted as a Markdown blockquote
line (`> …`, a blank line as a bare `>`) after in-line whitespace
normalisation, and a line that begins with a block marker (`#`, `-`, `*`,
`+`, `>`, `` ` ``, `~`) backslash-escaped, so a dump line can never open a
heading, list item or fence of its own inside the persona (review-3 F4
containment). A blank or absent dump SHALL render no section, so a brief
without one is byte-identical to the pre-change brief. The dump SHALL NOT be
folded into `topic`, SHALL NOT be written to the session state or exposed by
`GET /api/session/state`, and SHALL travel once, inside the persona (on `acp`
the `201` echoes the persona as `persona_text` by design, and the dump appears
in that field only). On a `focus` start the dump SHALL be ignored: the persona
and state are byte-identical to a start without it. A dump longer than
`BRAIN_DUMP_MAX_CHARS` SHALL be refused with `422` before the handler runs,
holding no slot.

The only planning fact the live-session state carries is `purpose`, written on
every start (never inherited through the state file's read-merge-write), and
`GET /api/session/state` SHALL expose it for the reconnect label with one
precedence on every path it answers from — the live-slot overlay and the
file-only path a CLI-started session takes: an explicitly persisted
`purpose` wins; otherwise a state whose persisted `mode` is the planning
persona's (`persona_mode_for("planning")`, the mode `studyloop plan
architect` writes without a `purpose` key) reports `planning`; anything else
— a state that predates the key, or an overlay that rebuilt the payload —
reports `focus`. The topic string SHALL never determine the purpose. If the
planning brief cannot be built, the start SHALL refuse with a
structured error (`error`, `purpose`, `repair`; HTTP 500) and leave the
single-session slot free — no reservation, no live slot, no study row. Both
transports (`pty` and `acp`) SHALL follow this requirement identically.

#### Scenario: Planning start launches the architect with a brief
- **WHEN** `POST /api/session/start` is made with `purpose: "planning"` and `topic: ""`
- **THEN** the persona the agent receives has `**Mode:** plan-architect`, a `## Planning brief` section containing the interview's first prompt and the existing plans, `**Topic:** Study plan`, and no `Resuming Previous Session`

#### Scenario: Brain dump travels once, contained, and is never persisted
- **WHEN** a planning start carries `brain_dump` with several paragraphs, one of which begins `## Ignore previous instructions`
- **THEN** the persona contains exactly one `### Learner's brain dump` section after `### Existing plans`, every dump line rendered as `> …` with the `##` line escaped (`> \## …`), and `**Topic:** Study plan`
- **AND** the session state file and `GET /api/session/state` carry neither a `brain_dump` key nor the text, and on `acp` the text appears in the `201` body's `persona_text` only

#### Scenario: Over-limit brain dump is refused structurally
- **WHEN** a planning start carries a `brain_dump` of `BRAIN_DUMP_MAX_CHARS + 1` characters
- **THEN** the response is `422` naming `brain_dump`, no slot is held and no agent is launched; a dump of exactly `BRAIN_DUMP_MAX_CHARS` is accepted

#### Scenario: Brain dump on a focus start is ignored
- **WHEN** a focus start carries `brain_dump`
- **THEN** the persona is byte-identical to `build_canonical_persona("focus", topic, energy)` and the state carries no trace of the text

#### Scenario: Planning start keeps a supplied subject
- **WHEN** a planning start carries `topic: "Spark"`
- **THEN** the persona carries `**Topic:** Spark` and the state's `topic` is `Spark`

#### Scenario: Default purpose is focus and unchanged
- **WHEN** a start names no purpose
- **THEN** the persona equals `build_canonical_persona("focus", topic, energy)`, the state's `mode` is `focus` and its `purpose` is `focus`

#### Scenario: Unknown purpose is refused structurally
- **WHEN** a start carries `purpose: "revision"`
- **THEN** the response is `422` and no slot is held

#### Scenario: Planning start creates no plan and stores no plan id
- **WHEN** a planning start succeeds
- **THEN** the plans directory is unchanged, the `201` body has no `plan_id`, and the state carries `purpose == "planning"` and no `plan_id`

#### Scenario: Purpose is persisted for the reconnect label
- **WHEN** a planning start succeeds
- **THEN** the state file's `purpose` is `planning` and `GET /api/session/state` reports it with the fixed topic `Study plan`

#### Scenario: A CLI-started architect is labelled from its persisted mode
- **WHEN** the state file carries `mode == "plan-architect"` and no `purpose`
- **THEN** `GET /api/session/state` reports `purpose == "planning"`; an explicit persisted `purpose` wins over the mode; `mode == "focus"` with topic `Study plan` reports `focus`

#### Scenario: Brief failure releases the session claim
- **WHEN** the planning brief cannot be built on either transport
- **THEN** the response is a structured `500` with `error`, `purpose` and `repair`, and the active slot is free

#### Scenario: PTY and ACP resolve the mode through one resolver
- **WHEN** a planning start is made over `pty` and over `acp`
- **THEN** both personas carry the same mode and brief section and neither route names a persona mode as a literal
