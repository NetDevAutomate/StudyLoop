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
- Five MCP review-loop/lifecycle parity tools (`get_due_cards`,
  `log_review_outcome`, `get_next_action`, `get_active_topics`,
  `log_struggle`) — the desktop MCP server now exposes 18 tools; Claude
  Desktop + Codex registration snippets live in `docs/desktop-mcp/`.
- Three MCP Course Explorer read-parity tools (`get_lesson_tree`,
  `read_lesson`, `search_lessons`) wrapping the existing explorer route
  internals (shared `resolve_lesson_path` traversal guard, FTS5 search) —
  desktop MCP clients can now browse and read course material; 21 tools
  total.

### Fixed
- **Session-export data integrity (root cause):** `scrub_log` (v18) and
  `file_references` (v19) had `message_id`/`session_id` foreign keys with no
  `ON DELETE CASCADE` (every other FK in the schema has it). With
  `PRAGMA foreign_keys=ON` (set on the export path), an exporter's update-path
  `DELETE FROM messages` raised a FK violation once a message had a scrub_log
  row — which gemini's bare `except` swallowed, silently dropping the whole
  session. Migration 25 rebuilds both tables with cascading FKs; an
  end-to-end gemini re-import test proves the session survives.
- **Kiro exporter dropped >half of history:** real kiro entries are 2-element
  lists `[user_turn, assistant_turn]`, but the extractor only handled a dict
  shape and the loop skipped non-dict entries — losing 2759 of 4794 entries
  on the real vault. `_extract_text` now handles both shapes (extraction
  1369 → 3419 messages).
- **Aider exporter duplicated messages on re-export:** aider mints a fresh
  uuid per message each run and never deleted old messages on the updated
  path, so `INSERT OR REPLACE` (keyed on id) accumulated duplicates. Now
  deletes prior messages for the session before re-inserting (matches
  kiro/gemini).
- **Settings shape-hardening:** a bare `review:` key (YAML `None`) no longer
  crashes `resolve_study_dirs()` with `AttributeError`; a scalar
  `review.directories` or `content.study_paths` string is treated as a single
  path instead of being iterated per-character into bogus one-letter dirs.
- **MCP `get_chapter_text`:** a non-positive `chapter` (0 or negative) now
  errors instead of falling through to `all_pdfs[chapter-1]`, which Python's
  negative indexing silently resolved to a chapter counted from the end.
- **Secret scrubber:** the `aws_secret_key` pattern now also catches the
  common unquoted `.env`/CLI shape (`aws_secret_access_key = wJalr…`); it
  previously required surrounding quotes and let unquoted keys through.
- **Desktop MCP install:** documented `uv tool install` command corrected to
  require the `[mcp,web,content]` extras (a bare install produced a
  `studyloop-mcp` binary that crashed on launch or on any web-route-backed
  tool call), plus a warning that `which studyloop-mcp` may resolve to a
  mise/asdf shim shadowing the uv-tool binary.
- **Security (P0):** session-directory slug now strips path-traversal vectors
  (`/`, `\`, `..`) from the user-controlled topic across all four
  session-start paths (web PTY/ttyd, CLI). The directory is later `rmtree`'d on
  failure, so an unsanitised `../../x` was a real escape-and-delete vector.
- Course Vendor picker no longer lists configured topics (Python, DevOps, …)
  as vendors, and same-name vendors under multiple course roots render once
  (courses from all of them are still discovered).
- Ending a session now uses an in-page confirm dialog instead of native
  `confirm()`, which Chrome could auto-dismiss while the embedded ttyd
  terminal held focus — leaving agent sessions impossible to end.
- Flat dotted top-level config keys (e.g. a literal `tts.backend: openvox`
  line) are now expanded into the nested tree, so every consumer sees them;
  doctor repair hints phrase fixes as nested YAML.
- `get_next_action` MCP tool validates `energy`/`modality` against their
  Literal types instead of passing bad values through.
- Web session-start error handling: a 500 with a non-JSON body no longer
  masquerades as "Network error"; the real HTTP status is surfaced.

### Removed
- Dead no-op content-index warm check from the web-app startup lifespan.

---

Historical releases predate this changelog; see the git history and
`docs/roadmap.md` for prior milestones. The project is at version `2.5.0`.
