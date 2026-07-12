## Purpose

Import conversation history from AI coding tools (Claude, Kiro, Codex,
Gemini, Aider, Grok, OpenCode, Bedrock, LiteLLM, RepoPrompt, Pi) into a
shared `sessions.db`, redact secrets on export paths, and optionally write
Obsidian vault notes. This is the `agent-session-tools` package, distinct
from the `studyloop` web/CLI package.

## Requirements

### Requirement: One exporter module per supported tool, sharing a common base
The system SHALL implement each importer as a module under
`agent_session_tools/exporters/` (`claude.py`, `kiro.py`, `codex.py`,
`gemini.py`, `aider.py`, `grok.py`, `opencode.py`, `bedrock.py`,
`litellm.py`, `repoprompt.py`, `pi.py`) sharing common persistence helpers
in `exporters/base.py`.

#### Scenario: A new agent CLI is added
- **WHEN** support for a new agent CLI's session format is added
- **THEN** it is implemented as a new module in `exporters/` reusing
  `base.py`'s shared persistence helpers, not a parallel storage path

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

### Requirement: gemini/aider incremental re-import has divergent failure modes
`exporters/gemini.py` (and three sibling exporters) SHALL delete existing
messages for a session before re-inserting on incremental re-export. If
`session_clean` has already scrubbed that session, the DELETE raises an
`IntegrityError` (FK from `scrub_log`) that is currently swallowed,
silently halting further updates to that session. `exporters/aider.py`
instead assigns a fresh `uuid4()` message ID on every parse with no
delete-before-reinsert step, so every incremental re-export duplicates all
prior messages for that session.

#### Scenario: Re-exporting a scrubbed Gemini session
- **WHEN** `session-export` runs again on a Gemini session that
  `session_clean` previously scrubbed
- **THEN** the delete-before-reinsert step raises an FK `IntegrityError`
  that is swallowed, and that session stops receiving updates from future
  exports

#### Scenario: Re-exporting the same Aider session twice
- **WHEN** `session-export` runs twice against an unchanged Aider log
- **THEN** every message from that session appears twice in `sessions.db`
  (message IDs are freshly generated per parse, not stable)

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
