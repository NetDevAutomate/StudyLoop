# Socratic Study Mentor — Improvement Plan

## Phase 1: Fix Broken Code (bugs affecting correctness)
**Commit: `fix: correct bugs in spaced repetition, progress tracking, and config`**

- [x] 1. Fix `spaced_repetition_due()` interval logic in `history.py` — reviewed, logic is correct (ascending iteration keeps last match = deepest overdue review)
- [x] 2. Fix `record_progress()` case sensitivity in `history.py` — normalise topic/concept to lowercase before storing
- [x] 3. Fix `struggle_topics()` hardcoded keywords in `history.py` — already uses `_get_study_terms()` from config
- [x] 4. Fix `tutor_checkpoint.py` hardcoded "macmini" sync target — already uses `get_endpoints()` from config
- [x] 5. Fix `config.py` module-level `load_settings()` — already lazy-loaded inside functions
- [x] 6. Remove hardcoded legacy DB paths from `history.py` — removed fallback, uses config only
- [x] 7. Add "aider" and "bedrock" to `SOURCE_CHOICES` in `export_sessions.py` — already present
- [x] 8. Wire up orphaned `study_sessions` table — added `start_study_session()`, `end_study_session()`, `get_study_session_stats()`
- [x] 8b. Fix `shared.py` `init_config()` hardcoded personal machine names — uses `socket.gethostname()` + sensible defaults
- [ ] 8c. Fix `session-export` progress bar showing cumulative stats with last-source label — e.g. "Kiro: 48 added" is really the total across all sources, not Kiro-specific. Show per-source stats instead.

## Phase 2: Unify Agent Framework (single source of truth)
**Commit: `feat: unify agent framework across all platforms with shared AuDHD methodology`**

- [x] 9. Create `agents/shared/` reference docs — 8 files: audhd-framework, socratic-engine, session-protocol, network-bridges, knowledge-bridging, break-science, wind-down-protocol, teach-back-protocol
- [x] 10. Rewrite Claude Code agent to reference shared framework — replaced 476-line inline version with shared doc references
- [x] 11. Create Gemini CLI agent — replaced inline content with shared doc references
- [x] 12. Create OpenCode agent — replaced inline content with shared doc references
- [x] 13. Create Amp agent — `AGENTS.md` references shared docs
- [x] 14. Update `install-agents.sh` for all 5 platforms — supports kiro, claude, gemini, opencode, amp with shared symlinks
- [x] 15. Update Kiro agent to reference `agents/shared/` — persona references shared, skill references are symlinks to shared

## Phase 3: AuDHD Methodology Enhancements
**Commit: `feat: add emotional regulation, transition support, parking lot, and sensory patterns`**

- [x] 16. Add emotional regulation / pre-study state check — `session-protocol.md` §2 (State Check) + `audhd-framework.md` §Emotional Regulation
- [x] 17. Add transition support / grounding ritual — `audhd-framework.md` §Transition Support / Attention Residue
- [x] 18. Add parking lot pattern for tangential thoughts — `audhd-framework.md` §Parking Lot Pattern
- [x] 19. Add sensory environment check — `session-protocol.md` §Sensory Environment + `audhd-framework.md` §Sensory Environment Adaptation
- [x] 20. Add micro-celebrations / dopamine maintenance — `audhd-framework.md` §Micro-Celebrations / Dopamine Maintenance
- [x] 21. Add interleaving / varied practice to review system — `audhd-framework.md` §Interleaving / Varied Practice + `socratic-engine.md` §Interleaving Prompts
- [x] 22. Add async body doubling session type — `audhd-framework.md` §Async Body Doubling
- [x] 23. Update `docs/audhd-learning-philosophy.md` with all new patterns — comprehensive coverage of all 7 patterns

## Phase 4: AuDHD-Friendly Documentation Site
**Commit: `feat: add MkDocs Material documentation site with AuDHD-friendly design`**

- [x] 24. Set up MkDocs Material with offline + privacy plugins — `mkdocs.yml` configured
- [x] 25. Implement font toggle (Lexend Deca / OpenDyslexic / Atkinson Hyperlegible) — `stylesheets/fonts.css`
- [x] 26. Implement Nord-inspired colour scheme (light + dark) — `stylesheets/audhd.css` with warm paper/slate toggle
- [x] 27. Add reading preferences panel (font, size, theme) — `javascripts/preferences.js` with localStorage persistence
- [x] 28. Migrate existing docs to MkDocs structure with colour-coded admonitions — 7 custom admonition types (struggling, learning, confident, mastered, parking-lot, micro-celebration, energy-check)
- [x] 29. Add `studyctl docs` command — `docs serve`, `docs open`, `docs list`, `docs read` subcommands

## Phase 5: Documentation & Install Polish
**Commit: `docs: update README, agent-install, and roadmap for all platforms`**

- [x] 30. Update README agent support table — already covers all 5 platforms (Kiro, Claude Code, Gemini, OpenCode, Amp)
- [x] 31. Update `docs/agent-install.md` for all 5 platforms — already comprehensive with auto-install + manual install for each
- [x] 32. Update `docs/roadmap.md` with completed items — added v1.5 section with all recent work

## Phase 6: Centralised Artefact Store (Completed 2026-03-13)

- [x] Create `NetDevAutomate/artefact-store` repo with landing page + GitHub Pages
- [x] Cloudflare DNS CNAME: `artefacts.netdevautomate.dev`
- [x] `repo-artefacts` — config system (`config.py`, TOML, `default_store`)
- [x] `repo-artefacts` — store module (`store.py`, clone/publish/manifest/push)
- [x] `repo-artefacts` — `--store` flag on `pipeline` and `publish` commands
- [x] `repo-artefacts` — `validate`, `clean`, `migrate` commands
- [x] Migrate 3 repos (Socratic-Study-Mentor, pdf-by-chapters, Agent-Speaker)
- [x] Git history cleaned (`git filter-repo`) on all 3 repos
- [x] Bug fixes: enum comparison, completed artefact deletion, infographic params, source dedup

## Phase 7: Unified Config & Cross-Machine Sync (Completed 2026-03-13)

- [x] Unified `hosts` config with hostname-based auto-detection
- [x] Primary/secondary IP support for wired/wifi fallback
- [x] `session-sync` reads hosts from studyctl config
- [x] Remote DB seeding on first push (`_seed_remote_db`)
- [x] Tilde path expansion fix for SSH commands
- [x] SSH prerequisite docs with platform caveats
- [x] Consolidated install scripts (`install.sh` with `--non-interactive`)

## Phase 8: StudyCards TUI (Completed 2026-03-13)

- [x] `review_loader.py` — self-contained flashcard/quiz JSON loader
- [x] `review_db.py` — SM-2 spaced repetition tracking (card_reviews table)
- [x] `tui/study_cards.py` — Textual widget with keyboard-driven review
- [x] Voice toggle (v key) via study-speak/kokoro
- [x] `studyctl tui` command registered in CLI
- [x] 27 unit tests for loader + DB
- [x] Agent configs updated for quiz/flashcard generation from Obsidian

## Phase 9: TUI Polish & Documentation (Next Session)

- [ ] Update README.md with TUI section + screenshot (`images/soctractic_mentor_tui.png`)
- [ ] Fix screenshot filename typo: `soctractic` → `socratic`
- [ ] Update `docs/setup-guide.md` with TUI installation and `review.directories` config
- [ ] Update `docs/cli-reference.md` with `studyctl tui` command
- [ ] Add course picker for multiple directories (currently uses first course)
- [ ] Add `--retry-wrong` flag to `pdf-by-chapters review` command
- [ ] Add "Review Wrong Answers" mode (r key) in TUI after session completion
- [ ] Fix 29 pre-existing test failures (classifier, TUI import, vscode, dedup, etc.)
- [ ] Implement `list_concepts()` in `history.py` (referenced but missing)

## Phase 10: Local Web App (PWA)

**Plan:** `~/code/personal/tools/notebooklm_pdf_by_chapters/docs/plans/2026-03-13-feat-study-review-interfaces-plan.md`

- [ ] `studyctl serve` command (FastAPI + Jinja2 + HTMX + Pico CSS)
- [ ] Dashboard: courses, progress, due reviews, recent sessions
- [ ] Flashcard page: tap to flip, score buttons, progress bar
- [ ] Quiz page: multiple choice with rationale reveal
- [ ] Audio page: play/pause episodes from downloads/audio/
- [ ] Wrong answers review mode
- [ ] Voice: `POST /api/speak` endpoint + browser SpeechSynthesis fallback
- [ ] PWA: manifest.json, service worker, offline caching
- [ ] Per-card scoring to card_reviews table via API
- [ ] Spaced repetition dashboard (due/overdue/mastered)
- [ ] Mobile responsive (test on iPhone Safari)
- [ ] `studyctl[serve]` optional dependency group

## Phase 11: Obsidian Export

- [ ] `pdf-by-chapters export-obsidian` command
- [ ] Convert flashcard JSON → Obsidian `#flashcard` format
- [ ] Compatible with Obsidian Spaced Repetition plugin

## Phase 12: Native iOS/macOS Apps (Future)

- [ ] SwiftUI universal app (iPhone + iPad + Mac Catalyst)
- [ ] Core Data / Swift Data for local storage
- [ ] Push notifications for due reviews
- [ ] Apple Watch complication (due count)
- [ ] Siri Shortcuts integration

## Phase 13: AWS Cloud Sync (Future)

- [ ] Cognito user pools + social login (Apple ID, Google)
- [ ] API Gateway + Lambda REST API
- [ ] DynamoDB with per-user partition key
- [ ] Offline-first sync with conflict resolution
- [ ] SNS + APNS push notifications

## Key File References

| Item | Location |
|------|----------|
| Study Review Plan | `~/code/personal/tools/notebooklm_pdf_by_chapters/docs/plans/2026-03-13-feat-study-review-interfaces-plan.md` |
| Artefact Store Plan | `~/code/personal/tools/notebooklm_repo_artefacts/docs/plans/2026-03-11-feat-centralised-artefact-store-plan.md` |
| TUI Source | `packages/studyctl/src/studyctl/tui/` |
| Review Loader | `packages/studyctl/src/studyctl/review_loader.py` |
| Review DB (SM-2) | `packages/studyctl/src/studyctl/review_db.py` |
| TUI Screenshot | `images/soctractic_mentor_tui.png` |
| Hosts Config | `~/.config/studyctl/config.yaml` |
| Store Config | `~/.config/repo-artefacts/config.toml` |
