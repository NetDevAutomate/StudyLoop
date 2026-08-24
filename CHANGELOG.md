# Changelog

All notable changes to StudyLoop are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Body Double now switches to a terminal-first live layout: the explanatory
  heading disappears, the duplicate focus list folds without overwriting the
  learner's saved preference, and the timer/focus/session controls become
  compact strips above a viewport-sized terminal. Its parent workspace now
  restores the same live session after refresh alongside the terminal's PTY
  reattachment, including at tablet-sized viewports.
- The v1 web-session contract is PTY/xterm.js across all supported harnesses.
  ACP remains implemented but is exposed only by `studyloop web --dev`; a
  release-mode direct ACP start is rejected server-side. Kiro's ACP launch now
  names the `study-mentor` agent explicitly.
- Added deterministic all-harness Playwright coverage for terminal paint,
  shrink/grow resize, refresh, session reattachment, and post-refresh input,
  plus an opt-in credentialled real-TUI lane. The live lane uncovered and fixed
  `TERM=dumb` leaking into browser PTYs, which prevented Codex from painting.

## [0.1.0] - Unreleased

Planned first public release. Versioned `0.1.0` deliberately: under semantic versioning
`0.y.z` signals that the public API is not yet stable, which is accurate. Internal
versions up to `2.5.0` existed during development but were never published — no
tag, no PyPI release, no installable artefact — so the first version anyone can
install will be this one. Everything below was developed under those internal versions
and is targeted for the first release. See `releases/v0.1.0.md` for the draft release note
and its list of known limitations.

### Added
- **Agentic study plans in the browser** — open **Study Plans → Create with
  Architect** and type or dictate one unstructured brain dump; there is no
  structured intake form. The server-owned Architect preserves that capture,
  can use optional course or notes context without treating it as progress,
  asks focused follow-up questions, and presents the exact Markdown proposal
  with a rendered Mermaid learning map. Nothing is written until the learner
  approves that digest-bound proposal; revise and reject remain explicit
  choices. Existing plans use the same conversation for proposed changes, at
  most three plans stay current, and a same-tab reload restores the active
  conversation. CLI plan commands remain manual document-management adapters,
  not a second agentic intake path.
- **Origin-aware session recovery in both start pickers** — `sessionActive`
  previously meant only "a session exists", so a picker would hide on a session
  it did not own, and the surface that *did* render its picker offered a Start
  button that could only ever return 409. It complained without offering a way
  out. `sessionActive` now means "a session exists **and this view owns it**".
  Both pickers name the owning surface and offer the two levers that work: open
  that surface, or end its session. Reattach is offered only for a session the
  view owns, which is what the origin guard exists to enforce.
- **Fake harness agent (`studyloop-fake-agent`)** — a deterministic console
  script that speaks just enough "agent" (banner, echo replies, clean
  EOF/SIGTERM exit) to walk the real spawn → PTY → WebSocket → terminal path
  in CI without an LLM or vendor CLI. Registers as the `fake` adapter ONLY
  under `STUDYLOOP_TEST_AGENT=1` (never in a real user's picker); the journey
  asserts bytes flow both ways over the live WS, the browser terminal
  connects, and the ended session leaves a `study_sessions` row.
- **Journey phases 2–4** (`tests/e2e/test_journey_generate_review.py`) — an
  isolated tmp-vault world drives the REAL Generate panel with the stub
  backend (deck files asserted on disk), walks the flashcards review UI over
  the generated deck to the summary, and asserts durable `card_reviews` /
  `review_sessions` rows landed in the tmp DB.
- **"Today" landing view** — the app now opens on a one-next-action card
  driven by the shared decision engine (`GET /api/now`): concept, time
  estimate, reason, one Start button, collapsible alternates, and a
  context-aware resume shortcut (rejoin live session > resume last study
  topic > resume last review deck). Parked-topic chips offer one-tap pickup.
- **Quick-park brain-dump** — a global "＋ Park a thought" button (and `p`
  shortcut) captures a tangent to the parking lot via the new
  `POST /api/backlog/park` without leaving the current view; confirmation
  via a new minimal toast primitive.
- **Park-first friction modal** — starting a 4th topic while
  `MAX_ACTIVE_TOPICS` are live opens an in-page overlay that requires
  parking one first (`POST /api/backlog/demote` makes it the oldest pending
  row — re-parking the same question would be an INSERT OR IGNORE no-op).
- `GET /api/session/last` — most recent study session (topic/energy), powers
  the Resume shortcut; fixes "no way to resume a stopped session" in the web
  UI (start-again-same-topic; tmux reattach remains CLI-only).
- Fast incremental `ContentIndex` (SQLite mtime-fingerprint index over
  providers → courses → lessons + quiz/flashcard artefacts) and a
  `studyloop content index [--provider] [--force] [--artefacts]` CLI command.
- `GET /api/backlog` — surfaces the 3-topic rule by splitting pending topics
  into `active` (first `MAX_ACTIVE_TOPICS`) and `parking_lot` (the rest).
- Representative end-to-end user-journey harness (`tests/e2e/`) driving the
  real web UI via Playwright, marked `e2e` (deselected by default).
- Server-side ACP capability guard: release mode rejects every
  `transport=acp` request with a 403 and an explicit `studyloop web --dev`
  repair. In dev mode, a PTY-only agent (Claude Code, Codex) requesting ACP
  fails fast with a 400 before any spawn attempt. `ACP_CAPABLE_AGENTS` remains
  the single source of truth for that experimental path.
- Five MCP review-loop/lifecycle parity tools (`get_due_cards`,
  `log_review_outcome`, `get_next_action`, `get_active_topics`,
  `log_struggle`) — the desktop MCP server now exposes 18 tools; Claude
  Desktop + Codex registration snippets live in `docs/desktop-mcp/`.
- Three MCP Course Explorer read-parity tools (`get_lesson_tree`,
  `read_lesson`, `search_lessons`) wrapping the existing explorer route
  internals (shared `resolve_lesson_path` traversal guard, FTS5 search) —
  desktop MCP clients can now browse and read course material; 21 tools
  total.

### Changed
- **Frontend modularised out of `index.html`** — the seven Alpine component
  factories (`generatePanel`, `settingsPanel`, `sessionTimer`, `terminalPanel`,
  `splitLayout`, `liveAgentConsole`, `plansPanel`) moved from the inline
  `<script>` into one ES module each under
  `static/js/components/`, with shared helpers in `static/js/lib/` and
  `static/js/main.js` as the entry point. `main.js` assigns each factory to
  `window` — Alpine resolves `x-data` names off the global scope, so a factory
  that is only a module export is invisible to it — and registers the `plans`
  store on `alpine:init`. `index.html` drops from 4,403 lines to 2,702. Each
  factory body was moved verbatim, the only edit being the added `export`
  keyword. No user-visible behaviour change, but it is the reason frontend
  assertions no longer all cost a browser launch: JS unit tests went 5 → 87,
  running in seconds against a ~24-minute e2e suite. `courseExplorer`,
  `reviewApp` and the rest still live in `static/components.js`, which loads as
  a classic script.
- **Install now installs everything:** `studyloop install tools` (and thus
  `./scripts/install.sh`) installs both workspace packages with their `[all]`
  aggregate extras — `studyloop[all]` (content, bedrock, web, notebooklm, tui,
  mcp, sessions) and `agent-session-tools[all]` (tokens, tui, watch, semantic,
  tts). Previously the installer used partial extras (`[tui,web,content]` /
  `[tts]`), so a fresh install could die at runtime with
  `ModuleNotFoundError` for `boto3` or `mcp`. The `agent-session-tools` `all`
  extra is now a self-referential aggregate that includes `tts`, so new
  extras can't drift out of it.

### Fixed

- The live-session message in the sidebar is now contained by its scrollable
  activity rail instead of overlapping Study Plans and Courses when the window
  becomes short or the text wraps.
- Web voice now falls back from the configured OpenVox-compatible endpoint to
  VoiceMode's local Kokoro endpoint, then to Web Speech if every server fails.
  A server that passed health-check and subsequently returns 503 no longer
  leaves the browser silent with a cached stale tier.
- **Live console came back empty after a page refresh:** `init()` only ever
  reacted to a `study-session-start` event, and for an already-running session
  that event had been dispatched before the page existed — so a reload mounted
  no terminal at all. (`sessionTimer()` dispatches only on a fresh start, never
  on restore, so waiting to be told was never going to work.) `init()` now calls
  `_adoptLiveSession()`, which reads `GET /api/session/state` and mounts only
  when this view owns the session, comparing the endpoint's `origin` against the
  console's own — the same ownership test the recovery banner uses. Listeners are
  still registered before that await, so an event arriving mid-fetch is not lost,
  and an `_adoptEpoch` counter bumped by every real start/stop is re-checked
  afterwards so a slow adopt cannot mount over newer user action. A reattach
  reports `Reattached · <agent>` rather than `Starting`, because claiming to
  start something that has been running for an hour is a lie the learner has to
  decode.
- **TTS voice ignored + overlapping playback:** the engine never restored the
  saved `neuralVoiceId`, so every page load spoke as the `am_michael` default
  regardless of the Settings selection (the dropdown showed the right voice;
  the engine used the wrong one). And rapid speak() calls overlapped: the
  shared `_stopped` flag was reset by the newer call while the older chunk
  loop was suspended in an await, so both fed the AudioContext at once ("two
  voices talking nonsense"). Voice now restored in init(); a monotonic
  generation counter kills superseded chunk loops, re-checked at the moment
  audio would start.
- **False "No courses found" flash:** switching to Flashcards/Quizzes showed
  the empty state instantly, then swapped in content when the fetch landed.
  A `coursesLoading` tri-state now shows "Checking your content…" until the
  fetch resolves.
- **Security (LAN auth divergence):** `studyloop web --lan --password X` (with
  X not persisted to config) protected the FastAPI app but left the ttyd
  terminal side-channel unauthenticated — the ttyd start path re-read
  `lan_password` from config.yaml (empty) instead of the CLI-resolved value.
  `create_app` now stores the resolved `(lan_username, lan_password)` on
  `app.state` as the single source of truth, and the ttyd start path reads
  from there via `_ttyd_credentials`, failing closed (500) if app.state is
  unreadable rather than spawning an unauthenticated PTY on the LAN.
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
- **The ttyd browser terminal is no longer offered in the UI.** Both transport
  selects lose their `Legacy terminal (ttyd iframe)` option and both legacy
  `<iframe>` panels are gone. ttyd is an external binary (`brew install ttyd`);
  without it the iframe rendered an *empty frame*, indistinguishable from a hang
  — and it was the path the pickers offered as a fallback. The dispatcher's
  `else` branch now reports an explicit `unavailable` state naming the transport
  it cannot render and what to do about it, rather than a blank frame.
  Installing ttyd no longer enables anything user-visible.
  **The server transport is retained:** `POST /api/session/start` still honours
  `transport: "ttyd"` and `STUDYLOOP_TRANSPORT=ttyd`, and `/terminal/` plus
  `terminal_proxy.py` are untouched — a session started that way simply has no
  browser renderer. See `docs/adr/0005-retire-ttyd-browser-surface.md`.
- **The `wterm` dev renderer** — its registry entry, the inline-injection branch,
  the `--dev-renderer wterm` choice, three vendored assets, and its 342-line
  test module. The project's own evaluation had ghostty-web ahead on 9 of 12
  dimensions, and wterm's registry entry carried its own indictment ("No
  onScroll, no custom key handler, no clipboard"; "known to disconnect
  mid-session"). It also required a 200-line adapter shim and an esbuild step
  that ghostty's UMD build removes. `--dev-renderer` now accepts only `ghostty`;
  xterm.js remains the production default.
- Dead no-op content-index warm check from the web-app startup lifespan.

---

There are no historical *releases* — `0.1.0` is the first published version. The
entries above were developed under internal versions up to `2.5.0` that were never
tagged or distributed; see the git history and `docs/roadmap.md` for the
development milestones behind them, and `releases/archive/` for the release notes
drafted against those internal versions.
