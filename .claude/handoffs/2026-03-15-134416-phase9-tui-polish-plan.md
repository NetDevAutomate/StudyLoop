# Handoff: Phase 9 TUI Polish & Documentation — Plan Complete, Ready for Implementation

## Session Metadata
- Created: 2026-03-15 13:44:16
- Project: /Users/user/code/personal/tools/Socratic-Study-Mentor
- Branch: main
- Session duration: ~2 hours (planning, deepening, review, pre-commit fix)

### Recent Commits (for context)
  - 4841fd8 fix: add studyctl pyright to pre-commit and move pytest to pre-push
  - c27d7ac style: format studyctl package with ruff
  - 36c5cd4 docs: update artefact links

## Handoff Chain

- **Continues from**: None (this is a new planning session, not related to the pipeline restructure)
- **Supersedes**: None

## Current State Summary

Created, deepened, and reviewed an implementation plan for Phase 9 (TUI Polish & Documentation) plus remaining Phase 1 item 8c. The plan went through 3 iterations: initial draft, deepening with 6 research agents, and simplification after 6 review agents. The final plan has 9 items (~106 lines of new code) with no schema migrations needed. A pre-commit config fix was committed to achieve CI parity. The plan is at `docs/plans/2026-03-15-feat-tui-polish-documentation-plan.md` (gitignored as personal WIP). CI is green on main. Ready to implement via `/ce:work`.

## Codebase Understanding

### Architecture Overview

Monorepo with two workspace packages:
- `packages/studyctl` — CLI + TUI (Textual) for study sessions, flashcard review, spaced repetition
- `packages/agent-session-tools` — Session export, sync, migrations for sessions.db

Both share a SQLite database (`~/.config/studyctl/sessions.db`) but have no import-time dependencies on each other. Schema ownership: agent-session-tools owns `sessions`/`messages` tables, studyctl owns `card_reviews`/`review_sessions`/`study_progress`/`concepts`.

### Critical Files

| File | Purpose | Relevance |
|------|---------|-----------|
| `packages/agent-session-tools/src/agent_session_tools/export_sessions.py` | Session export with Rich progress bar | A1: fix progress bar bug (line 182) |
| `packages/studyctl/src/studyctl/history.py` | Study progress, concepts, teachbacks (~900 lines) | A2: add `list_concepts()` here |
| `packages/studyctl/src/studyctl/tui/study_cards.py` | Textual widget for flashcard/quiz review | A3: course picker, A4: retry mode |
| `packages/studyctl/src/studyctl/tui/app.py` | Textual App with tabbed layout | A3: picker logic in `_launch_study()` |
| `packages/studyctl/src/studyctl/review_db.py` | SM-2 spaced repetition DB operations | A4: `get_wrong_hashes()`, A5: `get_due_cards()` fix |
| `packages/studyctl/src/studyctl/review_loader.py` | JSON flashcard/quiz loader | A3: `discover_directories()` |
| `.pre-commit-config.yaml` | Pre-commit hooks | Already fixed this session |

### Key Patterns Discovered

1. **In-memory wrong_hashes for retry** — After session completion, `self._result.wrong_hashes` is already in memory. No DB round-trip needed for retry. This eliminated the entire `session_id` FK migration.
2. **SM-2 Step 7 canonical pattern** — Retry should NOT update SM-2 scheduling. The original incorrect already penalised the card (interval=1, ease-=0.2).
3. **ExportStats dual-type smell** — `source_stats` can be dict or object (`isinstance` check). Fix the display bug in 4 lines; defer normalisation.
4. **Textual pyright exclusion** — `packages/studyctl/pyproject.toml` excludes `src/studyctl/tui` from pyright because textual is optional. Pre-commit hook must `cd packages/studyctl` to pick this up.
5. **`get_due_cards()` correctness bug** — GROUP BY with `HAVING reviewed_at = MAX(reviewed_at)` makes `correct` non-deterministic. Needs `ROW_NUMBER()` window function.

## Work Completed

### Tasks Finished

- [x] Created implementation plan (docs/plans/2026-03-15-feat-tui-polish-documentation-plan.md)
- [x] Deepened plan with 6 research agents (SM-2 patterns, Textual docs, architecture)
- [x] Reviewed plan with 6 review agents (Python, architecture, simplicity, performance, security, learnings)
- [x] Applied simplifications (~50% scope reduction, ~106 lines vs ~200+)
- [x] Fixed pre-commit config: added studyctl pyright hook, moved pytest to pre-push
- [x] Verified CI green on main (commit c27d7ac)
- [x] Installed both pre-commit and pre-push git hooks
- [x] Ran `uv sync --all-packages` to fix workspace environment

### Files Modified

| File | Changes | Rationale |
|------|---------|-----------|
| `.pre-commit-config.yaml` | +9/-2: added studyctl pyright, moved pytest to pre-push | CI parity — studyctl typecheck was missing locally |

### Decisions Made

| Decision | Options Considered | Rationale |
|----------|-------------------|-----------|
| No `session_id` FK migration | Migration vs in-memory hashes | Retry has wrong_hashes in memory already; migration solves non-existent problem for v1 |
| Keep `list_concepts()` in history.py | New `concepts.py` vs history.py | Only 3 concept functions; extraction not justified |
| 3-field NamedTuple for concepts | Dataclass with 5 fields vs NamedTuple with 3 | No consumer needs `id` or `relation_count` today |
| 2 states + boolean for retry | 4-state enum vs 2 states + `_is_retry` bool | retry_summary is just summary with r key disabled |
| 4-line A1 fix | Fix display vs normalise all exporters | Don't couple cross-exporter refactor to a display bug |
| Skip SM-2 during retry | Record retry to SM-2 vs skip | Wozniak 1990 + FSRS research: retry correct would create false confidence |

## Pending Work

## Immediate Next Steps

1. **Run `/ce:work docs/plans/2026-03-15-feat-tui-polish-documentation-plan.md`** — this is the primary action
2. **Execution order:** A1 (export fix) → A2 (list_concepts) → A3 (course picker) → A4 (retry wrong answers) → A5 (get_due_cards fix) → A6 (suppress narrowing) → B1-B4 (docs)
3. **A1 and A2 are independent** — can be parallelised if using subagents

### Blockers/Open Questions

- [ ] GitHub CLI auth expired — source credentials from `~/tmp/.env` before any `gh` commands: `export GH_TOKEN=$(grep '^GITHUB_TOKEN=' ~/tmp/.env | cut -d= -f2)`
- [ ] B1 (screenshot) requires manual capture — do last after all code changes

### Deferred Items

| Item | Why Deferred |
|------|-------------|
| ExportStats normalisation across exporters | Good cleanup but separate PR; don't couple to display bug |
| `session_id` FK on card_reviews | Not needed for in-process retry; add when cross-session analytics require it |
| `concepts.py` module extraction | Only 3 functions; extract at 5+ |
| Connection management (context managers in review_db.py) | Correctness improvement, not blocking |
| Schema ownership documentation | Process artifact, separate PR |
| Pre-existing bugs: `ensure_tables()` silent return, `_get_db()` bare except | Preparatory cleanup, separate commit |
| Node.js 20 deprecation in GitHub Actions | `actions/checkout@v4` and `astral-sh/setup-uv@v4` warn about forced Node.js 24 from June 2nd, 2026 |

## Important Context

1. **The plan is gitignored** — `docs/plans/` is in `.gitignore` as personal WIP. The plan file exists on disk at `docs/plans/2026-03-15-feat-tui-polish-documentation-plan.md` but won't show in git.
2. **Research artifacts also untracked** — `docs/analysis/`, `docs/research/`, `docs/reviews/` contain agent research from the deepening pass. Useful reference, not for git.
3. **`uv sync --all-packages` is required** — workspace packages won't be importable without it. This was already run this session.
4. **Pre-commit + pre-push hooks both installed** — Linting/pyright on commit, pytest on push.
5. **Test baseline: 696 passed, 0 failures** (from MEMORY.md). Run `uv sync --all-packages && pytest` to verify before starting.
6. **Course name normalisation is critical** — the string used in the course picker (A3) must match what `record_card_review()` stores in `card_reviews.course`. Use directory basename consistently.

## Assumptions Made

- The `concepts` table already exists (confirmed via migration tests during research)
- Textual's `OptionList.OptionSelected` message pattern works for course picker
- `check_action` + `refresh_bindings` pattern handles dynamic footer bindings for retry key
- The `_result.wrong_hashes` attribute is available on the widget after session completion

## Potential Gotchas

- **Don't extract concepts.py** — the simplicity review killed this. Put `list_concepts()` in `history.py`.
- **Don't add a migration** — retry uses in-memory hashes. The session_id FK is deferred.
- **A1 is in agent-session-tools package**, not studyctl — different package, different pyright scope.
- **studyctl TUI excluded from pyright** — `packages/studyctl/pyproject.toml` has `exclude = ["src/studyctl/tui"]`. Pyright won't catch type errors in TUI code.
- **`suppress(Exception)` is at two call sites** (~lines 218 and 263 in study_cards.py) — narrow both.

## Environment State

### Tools/Services Used

- uv (package manager, workspace sync)
- pre-commit (hooks: ruff, pyright x2, pytest on pre-push)
- GitHub CLI (`gh`) — requires `export GH_TOKEN=$(grep '^GITHUB_TOKEN=' ~/tmp/.env | cut -d= -f2)`
- Textual (TUI framework, optional dep for studyctl)

### Active Processes

- None — clean state, no servers running

### Environment Variables

- `GH_TOKEN` — needed for `gh` CLI (source from `~/tmp/.env`)
- Standard uv/python env via `.venv` at workspace root

## Related Resources

- **Plan file:** `docs/plans/2026-03-15-feat-tui-polish-documentation-plan.md`
- **SM-2 retry research:** `docs/research/2026-03-15-retry-wrong-answers-best-practices.md`
- **SpecFlow analysis:** `docs/analysis/phase9-spec-analysis.md`
- **Python review:** `docs/reviews/2026-03-15-tui-polish-plan-review.md`
- **Architecture review:** `.claude/handoffs/2026-03-15-architecture-review-implementation-plan.md`
- **Repo research:** `.claude/research/2026-03-15-repo-research.md`
- **TODO.md:** Tracks all phases; Phase 9 items are the target
- **MEMORY.md:** Key project patterns, test baseline, workspace gotchas

---

**Security Reminder**: No secrets in this document. GH_TOKEN referenced by name only.
