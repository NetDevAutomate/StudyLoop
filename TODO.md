# Socratic Study Mentor -- Active Backlog

> Single source of truth for outstanding work.
> For Phase 1-4 implementation details, see `docs/plans/2026-03-15-feat-unified-study-platform-plan.md`.

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
| 8 | StudyCards TUI (review_loader, review_db, SM-2, voice toggle) | Done |
| 9 | TUI polish & PWA web app (Pomodoro, voice, accessibility) | Done |
| Phase 0 | Pre-work: config consolidation, CLI split, WAL mode, service layer | Done |
| Fixes | Export progress bar (A1), list_concepts (A2), course picker (A3), retry wrong (A4), SQL/connection leaks (A5), narrow exceptions (A6) | Done |

## Unified Platform Plan -- Next Phases

### Phase 1: Content Absorption (next)

Absorb all 12 pdf-by-chapters commands into `studyctl content` group. Course-centric storage, Typer-to-Click conversion, service layer population.

See: `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` -- Phase 1

### Phase 2: FastAPI Web UI

Replace stdlib HTTP server with FastAPI. HTMX + Alpine.js frontend, artefact viewer, progress dashboard. Migrate all 11 existing routes.

See: `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` -- Phase 2

### Phase 3: MCP Agent Integration

FastMCP v1 server with stdio transport. Flashcard/quiz generation tools, study context tools, onboarding agent skill.

See: `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` -- Phase 3

### Phase 4: Packaging & Documentation

PyPI as `studyctl`, Homebrew personal tap, `studyctl setup` wizard, user documentation rewrite.

See: `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` -- Phase 4

## Standalone Items (not blocked by phases)

- [ ] Obsidian export: convert flashcard JSON to Obsidian `#flashcard` format (Spaced Repetition plugin compatible)

## Deferred (add when real demand appears)

- LAN password auth (`--password` flag + HTTP Basic Auth)
- Config editor web UI
- GitHub Issues API feedback
- TUI artefact browser
- Native iOS/macOS app (research in `docs/research/swift-poc-feasibility.md`)
- AWS cloud sync (Cognito, DynamoDB, push notifications)

## Key File References

| Item | Location |
|------|----------|
| Unified Platform Plan | `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` |
| Brainstorm (decisions) | `docs/brainstorms/2026-03-15-unified-study-platform-brainstorm.md` |
| Code Review Items | `code-review-plan-items.md` |
| CLI Package | `packages/studyctl/src/studyctl/cli/` |
| Services Layer | `packages/studyctl/src/studyctl/services/` |
| Settings (config) | `packages/studyctl/src/studyctl/settings.py` |
| Review DB (SM-2) | `packages/studyctl/src/studyctl/review_db.py` |
| TUI Source | `packages/studyctl/src/studyctl/tui/` |
| Web PWA | `packages/studyctl/src/studyctl/web/` |
| Hosts Config | `~/.config/studyctl/config.yaml` |
