# Handoff — Course Explorer panel (worktree `course-explorer-panel`)

**Date:** 2026-06-01
**Branch:** `worktree-course-explorer-panel` (rebased onto local `main` incl. the course-list rework + the async-fixture de-flake `86d2579`)
**Design docs:** `docs/course-explorer/{VIABILITY,PLAN,MILESTONES}.md`

## What shipped (Phases 0–3, the read-only MVP)

A new **Course Explorer** side panel + reading view, independent of the Flashcards/Quizzes review panels.

- **M1 backend** — `web/routes/explorer.py`, 3 read-only endpoints (all path-traversal guarded + suffix allowlist):
  - `GET /api/explorer/tree` — nested Provider→Course tree, cached on `app.state`, `[]` on empty base.
  - `GET /api/explorer/courses/{course_id:path}/lessons` — lesson list for a course.
  - `GET /api/explorer/lesson/{lesson_id:path}/content` — `{content, lesson_id}` JSON.
- **M2 frontend** — `course-explorer-panel` `<aside>` (3rd grid column, toggled via `$store.explorer`), `courseExplorer()` Alpine factory, CSS scroll-snap carousels per provider, per-provider filter. All CSS self-scoped `.explorer-*`.
- **M3 reading view** — extracted top-level `renderMarkdown()` (shared with live-agent console), `_stripFrontmatter()`, vendored **mermaid v11.4.1**, two-pass mermaid render (`_renderMermaidPlaceholders`). Renders into `.acp-message-final` prose.
- **M4 review fixes** — addressed a 3-lens adversarial review: deterministic suffix priority (F1), non-utf8 `errors='replace'` (F6), symlink-listing guard (SEC-001), `openLesson` generation-guard for fast A→B clicks (F3/F7), CRLF frontmatter (F5), explicit mermaid `securityLevel:'strict'` (SEC-002), and **8 new geometry assertions** closing the CONTRIBUTING.md visibility≠layout gap (#9).

**Gate at MVP:** 1484 non-e2e passed + 24 e2e (16 layout incl. 8 new explorer + 8 settings/key) green; ruff clean. Verified live (Playwright) against the real `~/Obsidian/Personal/Study` vault: tree→lessons→content, 9 mermaid SVGs rendered on a real lesson, traversal 404.

**Contract conformance:** uses only `.explorer-*`-scoped selectors (zero dead `.course-card`/`.mode-btn`); reworked `reviewApp` getters intact; coexists with all 6 existing nav items as an additive toggle panel.

## In progress this session (Phases 4–6)

Building on the MVP per `PLAN.md`:
- **P4** global fuzzy search — Fuse.js (client, titles) + SQLite FTS5 (server, bodies).
- **P5** mark-section-as-struggle — migration v22 (`source_course/section/publisher/created_by` on `study_progress`) + `POST /api/history/struggling-topics` + reading-view button. Feeds the existing struggle-surfacing + deck-gen pipeline unchanged.
- **P6** TTS read-aloud — **GATED**: `window.ttsEngine` lives only on the `browser-neural-tts` worktree. Wired defensively (feature-detect, no-op when absent); pure md→plaintext logic unit-tested here, live playback verifiable only after that worktree merges.

## Deferred / known limitations
See `docs/course-explorer/PLAN.md` → "Known limitations / deferred" (F2 cache mtime, F4/F8 sub-ms races, F9 single-level vault; SEC-003/004 assessed non-exploitable).

## To resume / operational notes
- **Worktree venv gotcha:** this worktree has its own `.venv`. Run tests as `VIRTUAL_ENV=.venv uv run --active pytest …`. Install deps: `studyloop` + sibling `agent-session-tools` + `respx`/`playwright` (else tests die at *collection*). **Never** `uv tool install` from here — it clobbers the user's live `:8567`. Use a private port (8601+).
- **Not pushed / no PR yet** — 5 (now more) delivery commits are local only.
