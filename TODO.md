# Socratic Study Mentor — Active Backlog

> Single source of truth for outstanding work.
> For compaction rationale, see `docs/plans/compaction-plan.md`.

## Core Features (maintained)

| Feature | Status |
|---------|--------|
| Socratic AI sessions (Claude, Kiro, Gemini, OpenCode) | ✅ Active |
| Content pipeline → NotebookLM (split, process, autopilot) | ✅ Active |
| Flashcard/quiz review (PWA web app, SM-2) | ✅ Active |
| Session intelligence (export, search, sync) | ✅ Active |

## Completed (summary)

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Fix broken code (spaced repetition, progress, config) | Done |
| 2 | Unify agent framework (5 platforms, shared docs) | Done |
| 3 | AuDHD methodology (emotional regulation, parking lot, etc.) | Done |
| 4 | Documentation site (MkDocs Material, font toggle, custom admonitions) | Done |
| 5 | Documentation & install polish (README, agent-install, roadmap) | Done |
| 6 | Centralised artefact store (GitHub Pages, config, store module) | Done |
| 7 | Unified config & cross-machine sync (hosts, SSH, install scripts) | Done |
| 8 | StudyCards TUI (review_loader, review_db, SM-2, voice toggle) | Done (archived in compaction) |
| 9 | TUI polish & PWA web app (Pomodoro, voice, accessibility) | Done (TUI archived, PWA kept) |
| Phase 0 | Pre-work: config consolidation, CLI split, WAL mode, service layer | Done |
| Phase 1 | Content absorption: 7 modules, 10 CLI commands, 76 tests | Done |
| Phase 4 | PyPI + Homebrew tap live, OIDC trusted publishing | Done |
| Phase 5 | Doctor/upgrade/install-mentor: 3 CLI commands, 7 checker modules | Done |
| Compaction | Strip to 4 core features, 13 CLI commands, fix doctor tests | Done |

## Next

### Phase 6: CI/CD Pipeline

Nightly drift detection, pre-release gate, Docker image pipeline. Spec at `docs/ci-cd-pipeline.md`.

### Phase 7: Docker Web + Server-Side TTS

Docker image running `studyctl web` with kokoro-onnx server-side TTS.

## Standalone Items (not blocked by phases)

- [ ] Obsidian export: convert flashcard JSON to Obsidian `#flashcard` format (Spaced Repetition plugin compatible)

## Archived Features (in git history, restore on demand)

- TUI dashboard (`studyctl tui`)
- Scheduler (launchd/cron management)
- Calendar .ics generation (`schedule-blocks`)
- Win tracking / streaks / progress-map CLI commands
- Knowledge bridges DB + CLI commands
- Teach-back scoring DB + CLI commands
- State push/pull CLI (merged into `session-sync`)
- Crush + Amp agent definitions
- 5 extra Claude agent files (consolidated to `socratic-mentor.md`)

## Deferred (add when real demand appears)

- LAN password auth (`--password` flag + HTTP Basic Auth)
- Config editor web UI
- GitHub Issues API feedback
- Native iOS/macOS app (research in `docs/research/swift-poc-feasibility.md`)
- AWS cloud sync (Cognito, DynamoDB, push notifications)

## Key File References

| Item | Location |
|------|----------|
| Compaction Plan | `docs/plans/compaction-plan.md` |
| Unified Platform Plan | `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` |
| CLI Package | `packages/studyctl/src/studyctl/cli/` |
| Services Layer | `packages/studyctl/src/studyctl/services/` |
| Settings (config) | `packages/studyctl/src/studyctl/settings.py` |
| Review DB (SM-2) | `packages/studyctl/src/studyctl/review_db.py` |
| Web PWA | `packages/studyctl/src/studyctl/web/` |
| Hosts Config | `~/.config/studyctl/config.yaml` |
