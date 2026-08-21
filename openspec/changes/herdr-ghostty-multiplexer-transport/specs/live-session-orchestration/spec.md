## MODIFIED Requirements

### Requirement: studyloop study composes a session via the Multiplexer protocol
The system SHALL call `get_backend()` to obtain the active multiplexer
implementation and use its protocol methods to compose the study session.
`session/orchestrator.py::create_tmux_environment()` becomes
`create_study_environment()` and calls `mux.create_session()`,
`mux.split_pane()`, `mux.configure_session_defaults()`, and
`mux.select_pane()`. `attach_if_needed()` calls `mux.is_inside_session()`
to choose between `mux.switch_client()` and `mux.attach()`.

The session naming convention (`study-{slug}-{id[:8]}`) and the layout
(main pane + 25% right sidebar) are preserved regardless of backend.

#### Scenario: Starting a session with TmuxBackend (regression)
- **WHEN** `studyloop study "Python decorators"` is run with the tmux
  backend active
- **THEN** behaviour is identical to the prior direct-call path: detached
  tmux session, agent in main pane, sidebar in 25% right split, attach or
  switch

#### Scenario: Starting a session with HerdrBackend
- **WHEN** `studyloop study "Python decorators"` is run with the herdr
  backend active (user has herdr installed, `STUDYLOOP_MULTIPLEXER=herdr`)
- **THEN** a herdr workspace is created with label `study-{slug}-{id[:8]}`,
  the agent runs in the initial pane, the sidebar runs in a right split,
  and the CLI either focuses the workspace (if already in herdr) or calls
  `os.execvp("herdr", ["herdr"])` to attach

### Requirement: Multiplexer pre-flight checks backend availability
`session/start.py::start_session()` SHALL call `get_backend().is_available()`
as the pre-flight gate instead of `tmux.is_tmux_available()`. If the backend
is unavailable, the error message SHALL name the specific backend that is
missing (e.g. "herdr binary not found" or "tmux not installed").

#### Scenario: herdr explicitly selected but not installed
- **WHEN** `STUDYLOOP_MULTIPLEXER=herdr` is set and `herdr` is not on PATH
- **THEN** `get_backend()` raises `MultiplexerError` with a message
  directing the user to install herdr or switch to tmux

### Requirement: Zombie detection uses backend-native introspection
`session/cleanup.py::auto_clean_zombies()` SHALL call
`get_backend().list_study_sessions()` and `get_backend().is_zombie_session()`
to identify and kill orphaned sessions. The herdr backend's zombie detection
uses `agent_status` from `herdr pane get` (a pane with `agent_status:
"unknown"` and no foreground children is zombie) combined with session age
from StudyLoop's DB (`started_at` field in `session-state.json`).

#### Scenario: Zombie detection with herdr backend
- **WHEN** a herdr workspace labelled `study-*` has no child process in its
  main pane and the DB records its creation time as >60 seconds ago
- **THEN** `is_zombie_session()` returns True and `auto_clean_zombies()`
  kills the workspace via `mux.kill_session()`

### Requirement: Session state keys are backend-agnostic
`session_state.py` SHALL write `mux_session`, `mux_main_pane`, and
`mux_sidebar_pane` to `session-state.json`. For backwards compatibility,
`read_session_state()` SHALL read `mux_session` first and fall back to
`tmux_session` (same for pane keys). The old keys are NOT deleted from
existing files.

#### Scenario: Reading a state file from before the migration
- **WHEN** `session-state.json` contains `tmux_session` but not
  `mux_session`
- **THEN** `read_session_state()` returns the value from `tmux_session`

### Requirement: Session end kills all study sessions via the protocol
`session/cleanup.py::end_session_common()` SHALL call
`get_backend().kill_all_study_sessions()` instead of importing
`tmux.kill_all_study_sessions()` directly. The backend implementation
handles the semantics: tmux kills `study-*` sessions; herdr closes
`study-*` workspaces.

#### Scenario: Q-quit with herdr backend
- **WHEN** the user presses Q in the sidebar and the backend is herdr
- **THEN** the sidebar sends Ctrl-C + /exit via `mux.send_keys()`, then
  `kill_all_study_sessions()` closes all `study-*` workspaces

### Requirement: Doctor tmux-resurrect check is conditional on backend
`cli/_doctor.py` SHALL only invoke `check_tmux_resurrect()` when the active
backend is `TmuxBackend`. When herdr is active, the resurrect check is
irrelevant and SHALL be skipped silently.

#### Scenario: Doctor with herdr backend
- **WHEN** `studyloop doctor` runs and `get_backend()` returns
  `HerdrBackend`
- **THEN** the tmux-resurrect check is skipped and no tmux-related warnings
  are emitted
