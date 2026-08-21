## MODIFIED Requirements

### Requirement: Legacy ttyd fallback routes through the Multiplexer protocol
The ttyd transport path (`web/routes/session/_start.py::_start_ttyd_session()`)
SHALL call `get_backend().create_session()`, `get_backend().session_exists()`,
and `get_backend().kill_session()` instead of importing functions directly from
`studyloop.tmux`. The transport path's behaviour is unchanged — tmux session
creation, ttyd spawning, and same-origin proxy — but the indirection through
the protocol allows the ttyd path to function with any backend that can spawn a
named session with a pane running a command.

#### Scenario: ttyd start path uses the multiplexer protocol
- **WHEN** `POST /api/session/start` is called with `transport: "ttyd"` and
  the active backend is `TmuxBackend`
- **THEN** the session is created identically to the prior direct-call path
  (detached tmux session, ttyd process proxied at `/terminal/`)

#### Scenario: ttyd start path with herdr backend
- **WHEN** `POST /api/session/start` is called with `transport: "ttyd"` and
  the active backend is `HerdrBackend`
- **THEN** the herdr backend creates a workspace, runs ttyd in the pane, and
  the proxy path operates identically (ttyd speaks its own WebSocket
  regardless of which multiplexer hosts it)

### Requirement: Session aliveness check routes through the protocol
`web/routes/session/_ipc.py::_is_tmux_session_alive()` SHALL be replaced by
`get_backend().session_exists(session_name)` rather than calling
`subprocess.run(["tmux", "has-session", ...])` directly. This removes the
only raw subprocess call to tmux that bypasses `tmux.py`.

#### Scenario: IPC aliveness check with herdr backend
- **WHEN** the web dashboard polls session state and the backend is herdr
- **THEN** `session_exists()` queries `herdr workspace list` for the label
  match, without attempting a tmux subprocess call
