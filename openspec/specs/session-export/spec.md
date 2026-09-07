## Purpose

Import conversation history from AI coding tools (Claude, Codex, Grok,
Kiro, OpenCode, Pi) into a shared `sessions.db`, redact secrets on export
paths, and optionally write Obsidian vault notes. This is the
`agent-session-tools` package, distinct from the `studyloop` web/CLI
package.

## Requirements

### Requirement: One exporter module per supported tool, sharing a common base
The system SHALL implement each importer as a module under
`agent_session_tools/exporters/` — `claude.py`, `codex.py`, `grok.py`,
`kiro.py`, `opencode.py`, `pi.py` — sharing persistence helpers in
`exporters/base.py`, and SHALL expose each through a `session-export
--<tool>-only` flag. Grok is a capture-only source: `--grok-only` imports
local Grok transcripts, and Grok has no skill/hook installer support
(ADR-0011).

#### Scenario: Export only Grok transcripts
- **WHEN** the user runs `session-export --grok-only`
- **THEN** only the Grok exporter runs, writing to the same `sessions.db`
  with the same integrity rules as the other five exporters

#### Scenario: The exporter list is complete and honest
- **WHEN** documentation or installed-wheel verification enumerates
  supported sources
- **THEN** it names exactly Claude Code, Codex, Grok, Kiro CLI, OpenCode
  and pi, and documents automatic-hook support separately from export
  support

### Requirement: kiro exporter drops non-dict history entries
`exporters/kiro.py`'s `_extract_text` SHALL handle only dict-shaped
history entries as of `61a15fc`; string-shaped entries hit a `continue`
and their content is silently dropped from the export.

#### Scenario: Kiro session history containing string-shaped entries
- **WHEN** a real Kiro session's history array contains string entries
  (not the usual dict shape)
- **THEN** those entries are skipped without error or warning, and their
  content is absent from `sessions.db` (confirmed against live Kiro data
  shapes; ~19% content loss measured on one real session)

### Requirement: Secret scrubbing targets known key formats but misses unquoted assignment
`session_clean` (`scrubber.py`) SHALL match secrets via the
`SECRET_PATTERNS` regex table (AWS access/secret key, GitHub PAT,
OpenAI/Anthropic key, JWT, private key header, DB connection string, GCP
API key, and more). The `aws_secret_key` pattern SHALL require the value
to be quoted (`['\"][0-9a-zA-Z/+]{40}['\"]`), which does not match the
common unquoted shell/env-var assignment shape
`AWS_SECRET_ACCESS_KEY=...`.

#### Scenario: Unquoted AWS secret key in session text
- **WHEN** a session transcript contains
  `export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`
  with no surrounding quotes
- **THEN** `session_clean`'s `aws_secret_key` pattern does not match this
  occurrence and the value is not redacted (confirmed live miss; other
  quoted-value shapes are still caught)

### Requirement: Obsidian export is opt-in and idempotent
`obsidian_writer.py` SHALL write one note per session to the configured
vault only when `--obsidian` is passed to `session-export` or
`obsidian.export_enabled: true` is set. Writes SHALL be idempotent via
content-hash comparison, and paths SHALL be hardened against traversal.

#### Scenario: Running session-export twice with --obsidian
- **WHEN** `session-export --obsidian` runs twice against the same
  unchanged session
- **THEN** the second run detects the content hash is unchanged and does
  not rewrite the note
