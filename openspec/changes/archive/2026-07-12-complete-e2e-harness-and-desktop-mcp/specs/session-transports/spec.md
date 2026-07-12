## MODIFIED Requirements

### Requirement: Session directory naming is path-traversal-safe
The system SHALL derive session directory names via a shared
`session_dir_slug()` helper built on `content.storage.slugify()`, applied
identically across the PTY, ACP, and ttyd start paths in
`web/services/session_start.py` and `web/routes/session/_start.py`. The
helper SHALL reject or strip `/`, `\`, `..`, empty, and overlong inputs
before any directory is created.

#### Scenario: Topic containing path-traversal sequences
- **WHEN** `POST /api/session/start` is called with
  `topic: "../../../etc"` on any of the three transports
- **THEN** the resulting session directory name contains no `../`
  sequence and the session directory is created inside `SESSION_DIR`

#### Scenario: Regression test posts a hostile topic to each transport
- **WHEN** the added regression test posts `topic="../../../etc"` to
  `/api/session/start` for `transport: "pty"`, `"acp"`, and `"ttyd"` in
  turn
- **THEN** all three requests either reject the topic or produce a
  contained, non-traversing session directory — the same guarantee holds
  for every transport, not just one
