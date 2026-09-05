# harness-session-memory Specification

## Purpose

Guarantee that every supported coding harness can retrieve relevant prior
StudyLoop sessions and automatically persist its own transcript, with installer
and doctor enforcing the same fail-closed contract.

## Requirements

### Requirement: Every release harness receives the canonical query skill

`studyloop install agents` SHALL install one canonical
`studyloop-session-memory` skill into `~/.agents/skills/`. Harnesses that
discover that hub directly SHALL use it there; Kiro and Claude SHALL receive
links from their documented native skill directories. The skill SHALL prefer
`session_search` when connected and SHALL specify `session-query` as the
fallback, so MCP absence cannot silently disable retrieval.

#### Scenario: A release harness is added
- **WHEN** a harness is added to `RELEASE_HARNESSES`
- **THEN** installer contract tests fail until the harness has either a verified
  hub-discovery path or a native-directory skill link

#### Scenario: Session DB MCP is unavailable
- **WHEN** an agent follows the skill without a `session_search` tool
- **THEN** it uses `session-query` scoped by project and topic instead of
  skipping prior-session retrieval

### Requirement: Every release harness has a native automatic export hook

The installer SHALL provide a real lifecycle hook for Kiro, Codex, Claude Code,
OpenCode and pi. The hooks SHALL run the matching `session-export
--<harness>-only` command best-effort and SHALL NOT block session close. Prompt
or steering mandates MAY reinforce export but SHALL NOT count as automatic
hooks.

#### Scenario: Installer wires all detected harnesses
- **WHEN** `studyloop install agents` detects any release harness
- **THEN** that harness receives its verified hook strategy: Kiro custom-agent
  `stop`, Codex global `SessionEnd`, Claude Code global `Stop`, OpenCode global
  plugin `session.idle`, or pi global extension `session_shutdown`

#### Scenario: Existing user hook configuration is present
- **WHEN** Claude or Codex already has unrelated hook groups
- **THEN** StudyLoop merges its owned hook idempotently without replacing those
  groups

### Requirement: Doctor verifies query and export end to end

`studyloop doctor --category harness` SHALL check the shared executables, each
detected harness's reachable session-memory skill, its steering mandate where
used, and its native export hook as separate results. `--fix` SHALL invoke the
same top-level tool and agent installers used by normal installation.

#### Scenario: Skill exists but hook is missing
- **WHEN** doctor finds a valid session-memory skill but no native hook
- **THEN** it reports the hook as a distinct auto-fixable warning

#### Scenario: Query executable is missing
- **WHEN** `session-query` is not on PATH
- **THEN** doctor reports an auto-fixable executable warning and `--fix`
  reinstalls workspace tools before refreshing harness wiring

### Requirement: Desktop support is evidence-gated

StudyLoop SHALL reuse global Codex hook configuration for Codex app sessions
that load `~/.codex/hooks.json`. It SHALL NOT claim that consumer Claude
Desktop supports Claude Code hooks or shares Claude Code's session store
without verified product documentation and tests. Desktop variants SHALL be
modeled separately when their lifecycle and storage contracts are known.

#### Scenario: Documentation describes desktop support
- **WHEN** installation documentation names a desktop application
- **THEN** it distinguishes evidence-backed Codex global-hook support from the
  unverified consumer Claude Desktop product rather than conflating either
  with its CLI harness
