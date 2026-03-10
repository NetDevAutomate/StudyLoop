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
