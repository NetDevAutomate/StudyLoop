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
