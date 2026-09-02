# Changelog

All notable public changes to StudyLoop are recorded here.

StudyLoop is preparing its first pre-release. The public API and installation
experience may change before `1.0.0`.

## [Unreleased]

### Added

- A learner-focused Web UI for starting Study Sessions, Body Double sessions,
  reviews, and study-plan work.
- First-party harness support for Kiro CLI, Codex, and Claude Code.
- Preview harness support for OpenCode and pi.
- Session-history import for each supported harness.
- Study-plan creation in the Web UI (**Study Plans → New plan**) and the CLI. The
  Web UI form is manual, with seed suggestions drawn from your own history; an
  agent-led planning interview is not integrated there yet.
- AuDHD-aware session scaffolding, spaced review, teach-back, parking-lot, and
  wind-down workflows.
- A strict public-documentation build and a separate internal audit/archive
  area.

### Changed

- Reworked the README and public guide around learner outcomes and approachable
  setup, with a real Kiro CLI walkthrough captured from the Web UI.
- Made the supported harness contract explicit across setup, diagnostics,
  launching, session export, and documentation.
- Made struggle extraction require an explicitly selected live model and a real
  exported harness session.
- Added source-session provenance and transaction-safe writes to struggle
  extraction.

### Removed

- Product-selectable fake agent and deterministic content backends. Test
  fixtures now live only in the test suite and are excluded from distributed
  packages.
- First-party session-harness claims for Gemini CLI, Antigravity, Grok, and
  local-model launchers.
- Session exporters outside the five-harness pre-release contract.
- Public pages that exposed implementation notes, internal architecture detail,
  or release-planning material.

### Security

- Closed a gap in the agent-child credential scrub: a bare `_KEY` suffix
  (`ENCRYPTION_KEY`, `SIGNING_KEY`, `MASTER_KEY`, ...) and bare
  `AUTHORIZATION`/`JWT`/`COOKIE`-shaped variables now get stripped from an
  agent child's environment, matching the compounds (`api_key`,
  `secret_key`, ...) already covered.

### Known pre-release boundaries

- Kiro CLI is the documented demonstration harness.
- OpenCode and pi are preview integrations while their release evidence is
  completed on supported local installations.
- Grok may be used as an independent review model through the development
  gateway; that does not make Grok a StudyLoop code harness.
- Live extraction does not silently fall back to sample output. If a model,
  credentials, session, or harness binary is unavailable, the command stops
  with an actionable error.

See [the `0.1.0` release note](releases/v0.1.0.md) for the current acceptance
boundary. Earlier private development history remains available in Git rather
than being presented as shipped product history.
