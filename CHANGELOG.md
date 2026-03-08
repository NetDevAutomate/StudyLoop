# Changelog

All notable changes to the Socratic Study Mentor will be documented in this file.

Generated with [git-cliff](https://git-cliff.org/). To regenerate: `git cliff --output CHANGELOG.md`

## [Unreleased]

### Features

- **resume:** "Where Was I?" auto-resume — last session context, topics, concepts in progress
- **streaks:** Study consistency tracking with current/longest streak, weekly count, 90-day %
- **progress-map:** Visual map of tracked concepts with Mermaid diagram output
- **medication:** Optional stimulant medication timing awareness (onset/peak/tapering/worn off)
- **pda:** Demand-light mode for PDA-profile learners (observations instead of questions)
- **express-start:** Skip session protocol with "let's go" — sensible defaults, adapt as you go

### Bug Fixes

- Harden sync.py against SQL injection via session ID validation
- Apply shlex.quote() to all SSH command string interpolation
- Move SSH control socket from /tmp to user-private XDG_RUNTIME_DIR
- Align Python version to >=3.12 across all workspace packages
- Defer config loading from import-time to CLI entry points
- Replace __getattr__ module magic with explicit functions
- Narrow bare `except Exception` to `sqlite3.OperationalError`
- Fix ICS datetime missing UTC timezone suffix
- Fix opencode exporter falsy check for ms=0 timestamps
- Set 0o600 permissions on database and state files

### Refactoring

- Consolidate 4 divergent commit_batch copies into single canonical version
- Create utils.py with shared stable_id, content_hash, file_fingerprint
- Remove shared mutable Lock from ExportStats dataclass
- Consolidate ruff lint config to workspace root
- Symlink kiro agent references to agents/shared/ (single source of truth)

### Documentation

- Replace all placeholder URLs with github.com/NetDevAutomate/Socratic-Study-Mentor
- Update architecture diagrams to show all 5 agent platforms
- Document studyctl docs, resume, streaks, progress-map commands
- Add artefacts page to MkDocs nav
- Replace docs/contributing.md with symlink to root CONTRIBUTING.md
- Add custom admonition style guide for contributors
- Suppress interleaving on low-energy days in session protocol
- Expand RSD coverage: Socratic questions as judgment, anticipatory avoidance
- Update roadmap with v1.3 AuDHD features

### CI/CD

- Add Python 3.12/3.13 version matrix to test job
- Add GitHub Pages deployment workflow for MkDocs
- Add release workflow with git-cliff changelog generation

## [1.0.0] - 2026-03-07

### Features

- Monorepo with studyctl + agent-session-tools
- Kiro CLI, Claude Code, Gemini CLI, OpenCode, Amp agent definitions
- Spaced repetition scheduling (1/3/7/14/30 days)
- Session export from 8 AI tools (Claude, Kiro, Gemini, Aider, OpenCode, LiteLLM, RepoPrompt, Bedrock)
- FTS5 + hybrid semantic search
- Cross-machine sync via SSH
- Obsidian to NotebookLM sync
- Win tracking and struggle detection
- Energy-adaptive sessions (low/medium/high)
- Emotional regulation check (calm/anxious/frustrated/flat/overwhelmed/shutdown)
- Calendar time-blocking with .ics generation
- TTS voice output via kokoro-onnx
- MkDocs documentation site with AuDHD-friendly design
