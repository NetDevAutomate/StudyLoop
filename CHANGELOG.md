# Changelog

All notable changes to StudyLoop are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Fast incremental `ContentIndex` (SQLite mtime-fingerprint index over
  providers → courses → lessons + quiz/flashcard artefacts) and a
  `studyloop content index [--provider] [--force] [--artefacts]` CLI command.
- `GET /api/backlog` — surfaces the 3-topic rule by splitting pending topics
  into `active` (first `MAX_ACTIVE_TOPICS`) and `parking_lot` (the rest).
- Representative end-to-end user-journey harness (`tests/e2e/`) driving the
  real web UI via Playwright, marked `e2e` (deselected by default).
- Server-side ACP capability guard: a PTY-only agent (Claude Code, Codex)
  requesting `transport=acp` now fails fast with a 400 (cause + repair) before
  any spawn attempt. `ACP_CAPABLE_AGENTS` is the single source of truth.

### Fixed
- **Security (P0):** session-directory slug now strips path-traversal vectors
  (`/`, `\`, `..`) from the user-controlled topic across all four
  session-start paths (web PTY/ttyd, CLI). The directory is later `rmtree`'d on
  failure, so an unsanitised `../../x` was a real escape-and-delete vector.
- Web session-start error handling: a 500 with a non-JSON body no longer
  masquerades as "Network error"; the real HTTP status is surfaced.

### Removed
- Dead no-op content-index warm check from the web-app startup lifespan.

---

Historical releases predate this changelog; see the git history and
`docs/roadmap.md` for prior milestones. The project is at version `2.5.0`.
