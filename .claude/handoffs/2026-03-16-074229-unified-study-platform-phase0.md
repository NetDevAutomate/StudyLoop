# Handoff: Unified Study Platform -- Ready for Phase 0 Implementation

## Session Metadata
- Created: 2026-03-16 07:42:29
- Project: /Users/user/code/personal/tools/Socratic-Study-Mentor
- Branch: main
- Session duration: ~3 hours (brainstorm + plan + deepen)

### Recent Commits (for context)
  - 389d7d1 Merge feat/phase9-tui-polish: Phase 9 TUI Polish + PWA Web App
  - d73f355 docs: comprehensive update for web PWA, voice, and accessibility features
  - eec3ffe fix: use parent directory name when course dir is 'downloads'
  - 945502b feat: add speak-once button on cards for on-demand voice
  - 6e83285 feat: add Pomodoro timer with audio chime and browser notifications

## Handoff Chain

- **Continues from**: [2026-03-15-180000-native-app-handoff.md](./2026-03-15-180000-native-app-handoff.md)
  - Previous title: Native macOS/iOS App -- Socratic Study Mentor
- **Supersedes**: The native Swift app direction is **deferred**. This handoff pivots to improving the existing Python codebase instead.

## Current State Summary

This session brainstormed, planned, and deepened a strategy to unify Socratic-Study-Mentor and notebooklm-pdf-by-chapters into a single installable tool (`studyctl`). We explored and rejected a native Swift app rewrite (research preserved in `docs/research/`), then pivoted to improving the existing Python codebase with: pdf-by-chapters absorption, FastAPI web UI, MCP agent integration, and PyPI packaging. The plan was deepened with 7 parallel research/review agents that cut 7 phases to 5 and eliminated 10 YAGNI features (~1,500 lines never written). **No code was written. All output is documentation (brainstorm, plan, research, reviews). Phase 0 implementation is the next step.**

## Codebase Understanding

### Architecture Overview

Monorepo with uv workspace (`packages/studyctl` + `packages/agent-session-tools`). studyctl is a Click CLI (1272-line cli.py) with a stdlib HTTP web server, Textual TUI, and spaced repetition engine. agent-session-tools provides session export/query/sync CLIs. A separate repo (`notebooklm-pdf-by-chapters`) has a Typer CLI for PDF splitting, NotebookLM upload/generation, and Obsidian markdown conversion -- this will be absorbed into studyctl.

### Critical Files

| File | Purpose | Relevance |
|------|---------|-----------|
| `packages/studyctl/src/studyctl/cli.py` | Click CLI, 1272 lines, all commands | **Phase 0: Must split into cli/ package** |
| `packages/studyctl/src/studyctl/settings.py` | Settings dataclass, config loading (L65) | **Phase 0: Must consolidate with config.py** |
| `packages/studyctl/src/studyctl/config.py` | Old config module (Topic namedtuple) | **Phase 0: Merge into settings.py, delete** |
| `packages/studyctl/src/studyctl/review_db.py` | SQLite SM-2 spaced repetition | **Phase 0: Add WAL mode + busy_timeout** |
| `packages/studyctl/src/studyctl/review_loader.py` | Flashcard/quiz JSON loader | **Phase 0: Formalize JSON contract** |
| `packages/studyctl/src/studyctl/web/server.py` | stdlib HTTP server, 11 API routes | Phase 2: Replace with FastAPI |
| `/Users/user/code/personal/tools/notebooklm_pdf_by_chapters/src/pdf_by_chapters/cli.py` | Typer CLI, 1300+ lines, 12 commands | Phase 1: Absorb into studyctl content/ |
| `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` | **THE PLAN** -- read this first | Implementation guide for all phases |
| `docs/brainstorms/2026-03-15-unified-study-platform-brainstorm.md` | All decisions with rationale | Reference for "why" behind decisions |

### Key Patterns Discovered

- Click groups pattern: `@cli.group("name")` for subcommands (state, config, schedule, docs)
- LazyGroup pattern from Click docs defers imports until command invoked -- essential for startup speed after adding 12+ content commands
- `review.directories` config list is how web UI and TUI discover flashcard/quiz JSON -- content pipeline output dirs must appear here
- Two separate migration domains share sessions.db: studyctl owns `card_reviews` + `review_sessions`, agent-session-tools owns `sessions` + 10 other tables. DO NOT mix migration systems.
- pdf-by-chapters `review.py` duplicates studyctl `review_loader.py` -- eliminate during absorption
- Typer-to-Click conversion is mechanical: `Annotated[str, typer.Option()]` becomes `@click.option()`

## Work Completed

### Tasks Finished

- [x] Brainstorm: Explored native Swift app, rejected it, pivoted to Python improvement
- [x] Brainstorm: Resolved all open questions (package name, NotebookLM auth, artefact storage, absorption scope)
- [x] Plan: Created comprehensive 5-phase implementation plan
- [x] Deepen: 4 research agents (FastAPI+HTMX, MCP Python, Click CLI, PyPI+Homebrew)
- [x] Deepen: 3 review agents (Security, Architecture, Simplicity)
- [x] Deepen: Cut 7 phases to 5, eliminated 10 YAGNI features
- [x] Memory updated with key decisions

### Files Created (all untracked -- commit before starting Phase 0)

| File | Purpose |
|------|---------|
| `docs/brainstorms/2026-03-15-unified-study-platform-brainstorm.md` | Final brainstorm with all decisions |
| `docs/brainstorms/2026-03-15-native-app-repackaging-brainstorm.md` | Deferred native app brainstorm |
| `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` | **THE PLAN -- implementation guide** |
| `docs/research/repo-research-summary.md` | Socratic-Study-Mentor codebase analysis |
| `docs/research/notebooklm-pdf-by-chapters-analysis.md` | pdf-by-chapters codebase analysis |
| `docs/research/unified-platform-repo-research.md` | Integration points (line numbers, schemas) |
| `docs/research/unified-platform-specflow.md` | Edge case analysis, 16 clarifying questions |
| `docs/research/mcp-native-app-research.md` | MCP in native apps (deferred) |
| `docs/research/2026-03-15-acp-research.md` | ACP protocol (deferred) |
| `docs/research/swift-poc-feasibility.md` | Swift PoC assessment (deferred) |
| `docs/research/monetisation-research.md` | Education app monetisation (deferred) |
| `docs/research/fastapi-htmx-best-practices.md` | FastAPI + HTMX patterns (Phase 2) |
| `docs/research/mcp-python-server-patterns.md` | MCP server patterns (Phase 3) |
| `docs/research/click-cli-patterns.md` | Click CLI large apps (Phase 0-1) |
| `docs/research/pypi-homebrew-packaging.md` | PyPI + Homebrew (Phase 4) |
| `docs/reviews/2026-03-15-plan-simplicity-review.md` | YAGNI analysis, cut 10 features |
| `docs/reviews/2026-03-15-architecture-review.md` | 3 blocking issues, Phase 0 needed |
| `docs/reviews/2026-03-15-security-review-unified-study-platform.md` | 13 security findings |

### Decisions Made

| Decision | Options Considered | Rationale |
|----------|-------------------|-----------|
| Improve existing Python, not rewrite in Swift | Swift native app, hybrid, Python improvement | 696+ tests, working PWA, 3-6 months to reach parity in Swift. Ship now. |
| Absorb pdf-by-chapters fully (all 12 commands) | Merge as package, dependency, absorb logic | Single repo, single install, single CLI. Kill fragmentation. |
| FastAPI + HTMX (no build step) | Svelte, React, keep stdlib | FastAPI gives auth middleware, async, templates. HTMX avoids node_modules. |
| AI coding assistants remain the AI brain | Direct LLM API in web UI, MCP bridge, both | Users already pay for agent subscriptions. No extra API cost. |
| Agent-generated flashcards (core), NotebookLM optional | NotebookLM core, all native, fork notebooklm-py | LLM structured output is better than unofficial API for flashcards/quizzes |
| Course-centric artefact storage | Type-centric, flat | Self-contained per course, browsable |
| Package name: `studyctl` | socratic-study-mentor, socratic-mentor | Short, matches CLI command |
| Cut 7 phases to 5, add Phase 0 | Keep original 7 phases | Simplicity review: 10 features are YAGNI. Architecture review: pre-work needed. |
| Default localhost, `--lan` flag for network | Default 0.0.0.0 with auth | Security: no password auth over cleartext HTTP by default |
| FastMCP v1, stdio transport | MCP v2, HTTP transport | v2 is pre-alpha. stdio is universal (all agent CLIs support it) |

## Pending Work

### Immediate Next Steps

1. **Commit all docs** -- 18 new files (brainstorms, plans, research, reviews) are untracked. Commit before any code changes.
2. **Start Phase 0** -- read the plan (`docs/plans/2026-03-15-feat-unified-study-platform-plan.md`), Phase 0 section
3. **Phase 0 tasks in order:**
   a. Consolidate `config.py` into `settings.py` (merge, update imports, delete old)
   b. Split `cli.py` (1272 lines) into `cli/` package with LazyGroup
   c. Enable WAL mode + `busy_timeout=5000` on all SQLite connections in `review_db.py`
   d. Formalize flashcard/quiz JSON contract (docstring + shape validation in `review_loader.py`)
   e. Fix known SQL bug in `get_due_cards()` (flagged in `code-review-plan-items.md`)
   f. Extract service layer stubs (`services/review.py`)

### Blockers/Open Questions

- None. All questions resolved in brainstorm.

### Deferred Items

- Native Swift app (research in `docs/research/swift-poc-feasibility.md`, `mcp-native-app-research.md`, `monetisation-research.md`)
- LAN password auth, config editor UI, GitHub Issues API, TUI enhancements (see "Deferred Features" in plan)
- ACP (Agent Client Protocol) support -- MCP is sufficient for now

## Context for Resuming Agent

### Important Context

1. **Read the plan first**: `docs/plans/2026-03-15-feat-unified-study-platform-plan.md` -- this is the implementation guide. It has been deepened with research insights and review feedback.
2. **Phase 0 is pre-work before features**: Consolidate config, split CLI, enable WAL, formalize schemas. ~2-3 days. All 696+ tests must pass after each change.
3. **The pdf-by-chapters repo is at**: `/Users/user/code/personal/tools/notebooklm_pdf_by_chapters/` -- this is the code to absorb in Phase 1.
4. **Two config modules exist** (`config.py` and `settings.py`) -- this is the first thing to fix. `settings.py` is the newer, correct one. `config.py` is legacy.
5. **cli.py is 1272 lines** -- must be split into `cli/` package BEFORE adding 12 more content commands.
6. **Test count**: 696 passed, 0 failures, 8 skipped. `uv sync --all-packages` required before running tests.
7. **Never auto-commit** -- user controls all git operations.

### Assumptions Made

- `studyctl` is available on PyPI (not yet verified)
- pdf-by-chapters repo will be archived after absorption (not deleted immediately)
- Single user, multiple devices (not multi-user). No user_id column needed.
- NotebookLM cookie auth fragility is accepted and documented

### Potential Gotchas

- `uv sync` alone only installs ROOT deps. `uv sync --all-packages` required for workspace members.
- `config.py` provides `Topic` namedtuple used in several places -- grep all imports before deleting
- `review_db.py` and agent-session-tools share the same `sessions.db` but have separate migration domains -- DO NOT touch agent-session-tools tables
- cli.py uses `raise SystemExit(1)` in ~8 places -- replace with `click.ClickException` during split
- The web server currently uses `localhost` default -- Phase 2 changes this, but Phase 0 should not

## Environment State

### Tools/Services Used

- uv (package manager) -- `uv sync --all-packages --extra dev --extra test`
- pytest -- `uv run pytest`
- ruff -- linting/formatting (pre-commit hook)
- pyright -- type checking (basic mode)

### Active Processes

- None. No servers or processes running.

### Environment Variables

- None required for Phase 0.

## Related Resources

- **Implementation plan**: `docs/plans/2026-03-15-feat-unified-study-platform-plan.md`
- **Brainstorm**: `docs/brainstorms/2026-03-15-unified-study-platform-brainstorm.md`
- **Click CLI patterns**: `docs/research/click-cli-patterns.md` (LazyGroup, cli/ package structure)
- **Architecture review**: `docs/reviews/2026-03-15-architecture-review.md` (Phase 0 justification)
- **Code review items**: `code-review-plan-items.md` (SQL bug in get_due_cards)
- **Memory file**: `/Users/user/.claude/projects/-Users-user-code-personal-tools-Socratic-Study-Mentor/memory/MEMORY.md`

---

**Security Reminder**: No secrets in this document. Validated clean.
