# Remediation Log — Codebase Review 2026-04-08

Tracks each issue identified in the codebase review, its remediation, and proof of resolution.

**Source reviews:**
- `docs/codebase-review-2026-04-08.md` (comprehensive, 5 sub-agent deep analysis)
- `CODE_REVIEW_REPORT.md` (shallow review — mostly superseded; `components.js` finding was valid)

**Test baseline before remediation:** 1 failed, 1,312 passed, 6 skipped, 135 deselected, 3 warnings
**Test result after Wave 1:** 1,360 passed, 0 failed, 6 skipped, 135 deselected, 0 warnings

---

## Wave 1 — Fix Broken Things

### 1a. Missing `components.js` (Failing Test)

**Original issue:** `index.html:1136` and `sw.js:17` reference `/components.js` but the file doesn't exist. `test_web_app.py::TestStaticFiles::test_js_served` fails with 404.

**Source:** CODE_REVIEW_REPORT.md (confirmed by running test suite: 1 failed, 1,312 passed)

**Remediation:** Created `packages/studyctl/src/studyctl/web/static/components.js` — a complete Alpine.js `reviewApp()` component (~300 LOC) that drives the flashcard and quiz review UI. This wasn't just a missing file — the entire review engine JS implementation was absent. The component implements:
- Course listing with stats from `/api/courses`
- Card loading from `/api/cards/{course}` with source filtering and shuffle
- Flashcard flip/reveal with correct/incorrect tracking
- Quiz multiple-choice with auto-advance and rationale display
- SM-2 review recording via `POST /api/review`
- Session summary with score ring, retry-wrong, and restart
- Keyboard shortcuts (Space, Y/N, 1-4, T for TTS, Esc)
- Heatmap placeholder for study activity

**Why this approach:** The HTML templates (lines 125-365 of `index.html`) already defined the full UI with Alpine `x-data`, `x-show`, `x-text`, and `@click` bindings referencing ~30 properties and ~15 methods. The API routes (`cards.py`, `courses.py`) were also already implemented. Only the JavaScript bridge was missing.

**File created:** `packages/studyctl/src/studyctl/web/static/components.js`

**Test result:**
```
packages/studyctl/tests/test_web_app.py::TestStaticFiles::test_js_served PASSED
```

---

### 1b. Unregistered `e2e` Pytest Marker

**Original issue:** `pytest.mark.e2e` used in 3 test files (`test_harness_matrix.py`, `test_web_terminal.py`, `test_e2e_session_demo.py`) but not registered in `pyproject.toml`, producing `PytestUnknownMarkWarning` during collection.

**Source:** Both reports identified this (though CODE_REVIEW_REPORT.md got the description backwards — it said the marker was "defined in pyproject.toml but not registered in tests", when it's the opposite).

**Remediation:** Added `e2e` marker to `pyproject.toml`:
```toml
markers = [
    "integration: requires external infrastructure (tmux, real DB, network)",
    "e2e: end-to-end tests requiring full stack (tmux, ttyd, web server)",
]
```

**File changed:** `pyproject.toml`

**Learning point:** Pytest markers must be registered in `pyproject.toml` (or `pytest.ini` / `conftest.py`) to suppress `PytestUnknownMarkWarning`. Unregistered markers still work but the warnings clutter output and can mask real issues.

**Test result:** Full suite runs with 0 warnings (previously 3 warnings).

---

### 1c. `list_artefacts` Path Traversal Gap

**Original issue:** `web/routes/artefacts.py:38` — the `list_artefacts` endpoint constructs `base / course` and calls `iterdir()` without checking `is_relative_to()`. A `../` in the `course` parameter could read directory listings outside the content base. The adjacent `_validate_artefact_path` function (line 22-24) shows the correct pattern but it wasn't applied here.

**Source:** `docs/codebase-review-2026-04-08.md` (security agent finding)

**Remediation:** Added `resolve()` + `is_relative_to()` check before the `is_dir()` check:
```python
course_dir = (base / course).resolve()
if not course_dir.is_relative_to(base.resolve()):
    raise HTTPException(status_code=404)
```

**File changed:** `packages/studyctl/src/studyctl/web/routes/artefacts.py`

**Learning point:** Path traversal is the #1 file-serving vulnerability. The pattern is always: (1) `resolve()` to collapse `../`, (2) `is_relative_to()` to verify the result is still within the allowed base directory. FastAPI does NOT automatically sanitise path parameters — the application must validate them. Having one function in the same file do it correctly (`_validate_artefact_path`) while another doesn't (`list_artefacts`) shows why consistency checks matter.

**Test result:** Full suite passes. Note: no dedicated traversal test existed — would be valuable to add in Wave 5.

---

### 1d. `docs/artefacts.md` Missing (Breaks mkdocs)

**Original issue:** `mkdocs.yml` nav (line 70) references `artefacts.md` but the file didn't exist in `docs/`. Running `mkdocs build` or the `docs.yml` CI workflow would fail.

**Source:** `docs/codebase-review-2026-04-08.md` (packaging agent finding)

**Remediation:** Created `docs/artefacts.md` with content drawn from the README's artefacts section. Includes links to all 4 artefact types (audio, video, infographic, slides) on the artefact store, plus a description of the generation pipeline.

**File created:** `docs/artefacts.md`

**Learning point:** MkDocs nav entries must correspond to actual files. If a nav entry references a file that doesn't exist, `mkdocs build` fails hard rather than producing a broken page. Always run `mkdocs build` locally after changing the nav.

**Test result:** File exists and is referenced correctly in `mkdocs.yml` nav.

---

### 1e. `install.sh` Python Version Check Too Lenient

**Original issue:** `scripts/install.sh` checks for Python >= 3.10 but all `pyproject.toml` files specify `requires-python = ">=3.12"`. Users on 3.10 or 3.11 get a misleading "prerequisites met" message, then fail later during `uv sync` with a confusing resolution error.

**Source:** `docs/codebase-review-2026-04-08.md` (packaging agent finding)

**Remediation:** Changed all 3 occurrences of `3.10` to `3.12` in the version check:
```bash
# Before
if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
    info "Python ${PY_VER} found"
  else
    err "Python >= 3.10 required (found ${PY_VER})"

# After
if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 12 ]; then
    info "Python ${PY_VER} found"
  else
    err "Python >= 3.12 required (found ${PY_VER})"
```

**File changed:** `scripts/install.sh`

**Learning point:** Install scripts must match the actual `requires-python` in `pyproject.toml`. When the minimum version changes, all downstream scripts must be updated too. This is a good candidate for a CI check that validates `install.sh` against `pyproject.toml`.

**Test result:** Manual verification — the check now reads 3.12 in all positions.

---

### 1f. Tracked Build Artifacts in Git

**Original issue:** `.coverage` (76 KB), `socratic_study_mentor.egg-info/`, and `uv-3372627849829312.lock` (0 bytes) are tracked by git despite matching `.gitignore` patterns. This happened because they were added before the gitignore rules existed.

**Source:** `docs/codebase-review-2026-04-08.md`

**Remediation:** Resolved — the original diagnosis was **incorrect**. The files were never tracked by git. The corrupt HEAD (`fatal: bad object HEAD`) caused `git ls-files` to return unreliable results during the initial review. After fixing the corruption (`git fetch origin main` restored the missing commit object), `git ls-files --error-unmatch` confirmed none of these files were tracked. All three are properly covered by `.gitignore` rules.

**Root cause of corruption:** Commit `a120ae6` existed on the remote but the local pack files didn't contain it. This likely happened during a worktree operation (`.claude/worktrees/` exists) or a partial garbage collection. `git fetch origin main` resolved it.

**Learning point:** Don't trust `git ls-files` output when `git status` reports `fatal: bad object HEAD`. The index may appear populated but object lookups fail silently. Fix the corruption first, then diagnose. Also: `git fetch` can restore missing local objects from the remote — no need for a full re-clone.

**Test result:** `git fsck` clean. `git log`, `git status`, `git diff` all functional.

---

## Wave 1 — Report Corrections

### BM25 False Positive in codebase-review-2026-04-08.md

**Original claim:** "BM25 search returns worst-match-first" — listed as Priority 1 bug in all 3 locations (`mcp_server.py:107`, `query_logic.py:94`, `semantic_search.py:196`).

**Why it's wrong:** SQLite FTS5 `bm25()` returns **negative** values where more-negative = better match. The default `ORDER BY` direction is ASC, which sorts -10, -5, -1 — correctly putting the **best** matches first. Verified by reading:
- `query_logic.py:78`: `bm25(messages_fts) as rank`
- `semantic_search.py:157`: `bm25(messages_fts) as score`
- `mcp_server.py:107`: `ORDER BY bm25(messages_fts), m.timestamp DESC`

**Learning point:** FTS5 `bm25()` is a distance metric (lower = better), not a score metric (higher = better). This is opposite to what most people expect from a "ranking function". The SQLite docs state: "a lower value indicates a better match." So ASC ordering (the default) is correct. Always check the polarity convention of ranking functions before assuming `DESC` is needed.

**Action:** Remove from Priority 1 in the review document. The search ordering is correct.

---

### CODE_REVIEW_REPORT.md — Factual Errors Documented

For the project record, these findings in CODE_REVIEW_REPORT.md were verified as **incorrect**:

| Claim | Reality |
|-------|---------|
| "Git Repository in Detached HEAD State" | HEAD points to main. The issue is corrupt object references, not a detached HEAD. |
| "No migration system detected" | `agent-session-tools/migrations.py` has 745 LOC with 21 versioned migrations using `PRAGMA user_version` |
| "e2e marker defined in pyproject.toml but not registered" | Backwards — it's used in tests but NOT registered in pyproject.toml |
| "Duplicate `__init__.py` files" | Every Python package requires `__init__.py` — this is not duplication |
| "web/app.py 0% coverage" | `test_web_app.py` has 14+ test methods; the 0% was from running coverage without optional extras |
| "Consider Plugin Architecture for Agents" | A registry pattern already exists (`AgentAdapter` dataclass + `AGENTS` dict) — see brainstorm below |
| "Async First for Web Layer" | `proxy_terminal_ws` is already async; sync routes do quick DB reads |
| "Consider Alembic for studyctl" | studyctl uses agent-session-tools migrations; adding Alembic would create two migration systems |

**Recommendation:** Delete `CODE_REVIEW_REPORT.md` to avoid misleading future contributors.

---

## Wave 2 — Architecture & Data Integrity

### 2a. Layer Violation: `session/resume.py` → `cli/_study._handle_start`

**Original issue:** `session/resume.py:93` imported `_handle_start` directly from `cli/_study.py` — a lower-level module reaching up into the presentation layer.

**Remediation:** Inverted the dependency. `handle_resume()` now accepts an optional `start_fn: Callable` parameter. The CLI layer passes `_handle_start` as the callback. No direct import from `cli/` remains.

**Files changed:** `session/resume.py`, `cli/_study.py`

**Learning point:** When a lower layer needs behaviour from a higher layer, inject it as a callback rather than importing directly. This keeps the dependency graph flowing downward. The higher layer "knows" the lower layer, not the reverse.

**Test result:** 681 studyctl tests passed, 0 failed.

---

### 2b. Layer Violation: `web/routes/session.py` → `cli/_study._auto_clean_zombies`

**Original issue:** `web/routes/session.py:415` imported a private function from the CLI layer to clean up zombie tmux sessions.

**Remediation:** Moved `_auto_clean_zombies` to `session/cleanup.py` as `auto_clean_zombies` (public name). Both `cli/_study.py` and `web/routes/session.py` now import from the session layer.

**Files changed:** `session/cleanup.py`, `cli/_study.py`, `web/routes/session.py`

**Learning point:** If two presentation layers (CLI and web) both need the same function, that function belongs in a shared lower layer (services or session), not in one of the presentation layers.

**Test result:** Passes as part of full suite.

---

### 2c. Layer Violation: `session/orchestrator.py` → `cli/_shared.console`

**Original issue:** `session/orchestrator.py:236` imported `console` from `cli._shared` when `output.py` already existed as the intended replacement.

**Remediation:** Changed import to `from studyctl.output import console`.

**File changed:** `session/orchestrator.py`

**Test result:** Passes. Verified with `grep -rn "from studyctl.cli._" packages/studyctl/src/studyctl/session/ packages/studyctl/src/studyctl/web/` — zero results.

---

### 2d. Mixed UTC/local Timestamps

**Original issue:** `parking.py:235` and `history/medication.py:20` used naive `datetime.now()` while the rest of the codebase uses `datetime.now(UTC)`, creating mixed timezone data in the same database.

**Remediation:**
- `parking.py`: Added `UTC` import, changed `datetime.now().isoformat()` → `datetime.now(UTC).isoformat()`
- `medication.py`: Added `UTC` import, changed `datetime.now()` → `datetime.now(UTC)`

**Files changed:** `parking.py`, `history/medication.py`

**Learning point:** `datetime.now()` returns a naive (timezone-unaware) datetime in the local timezone. `datetime.now(UTC)` returns a timezone-aware datetime in UTC. Mixing these in the same database means timestamps are inconsistent — some are UTC, some are local time, and there's no way to tell which is which after the fact. Always use `datetime.now(UTC)` for persistence.

**Test result:** 1,360 passed.

---

### 2e. Dead Code: `web/server.py` (259 LOC)

**Original issue:** The stdlib-based `StudyHandler` HTTP server was entirely superseded by `web/app.py` (FastAPI). No callers existed.

**Remediation:** Deleted `packages/studyctl/src/studyctl/web/server.py` (259 lines removed).

**Verification:** `grep -rn "web.server\|StudyHandler" packages/studyctl/src/ packages/studyctl/tests/` returned no results before deletion.

**Test result:** Full suite passes.

---

### 2f. Dead Code: VSCode Integration Stubs

**Original issue:** Two commands in `query_sessions.py` (`snippet`, `setup`) always printed an error and raised `typer.Exit(1)` due to an unresolved circular import with `integrations/vscode.py`.

**Remediation:** Removed the commented-out import, the `vscode_app` Typer sub-app registration, and both stub commands. `integrations/vscode.py` itself was NOT deleted (may be re-enabled later).

**File changed:** `agent_session_tools/query_sessions.py`

**Test result:** Full suite passes.

---

### 2g. Module-Level `logging.basicConfig()` Side Effects

**Original issue:** Three modules (`query_logic.py`, `maintenance.py`, `sync.py`) called `logging.basicConfig()` at import time, configuring the root logger for the entire process. This affected tests and any code that imported these modules.

**Remediation:** Moved `logging.basicConfig()` into Typer `@app.callback()` functions (`_setup_logging()`) so logging is only configured when the module is run as a CLI tool, not when imported as a library. Also moved module-level `config = load_config()` and `DB_PATH = ...` into lazy `_get_config()` / `_get_db_path()` helpers.

**Files changed:** `query_logic.py`, `maintenance.py`, `sync.py`

**Learning point:** Module-level side effects (logging config, file I/O, network calls) are a code smell. They run on every import, which means tests, MCP servers, and other consumers all get hit. The fix pattern is:
1. Keep `logger = logging.getLogger(__name__)` at module level (creates a logger without configuring it)
2. Move `logging.basicConfig()` into the CLI entry point
3. Use lazy initialization for config/DB paths that are only needed at runtime

**Test result:** 1,360 passed, 0 failed. `grep -n "logging.basicConfig" *.py` confirms it's only inside `_setup_logging()` callbacks.

---

## Wave 2 — Summary

**Before:** 3 layer violations, 2 naive timestamps, 279 LOC dead code, 3 module-level side effects
**After:** 0 violations, 0 naive timestamps, 0 dead code, 0 module-level side effects
**Test result:** 1,360 passed, 0 failed, 6 skipped, 0 warnings

---

## Wave 3 — Dead Code Removal

Completed as part of Wave 2 (items 2e and 2f above).

---

## Wave 4 — Data Integrity & Exporter Fixes

### 4a. Archive Schema Drift (Data Loss on Archive)

**Original issue:** `maintenance._archive()` creates archive databases with a hardcoded schema missing 5 columns added in later migrations: `content_hash`, `import_fingerprint`, `session_type` (sessions), `content_hash`, `seq` (messages). The INSERT statements used `SELECT *` with positional `?` placeholders that didn't match the live table's column count. Archiving sessions silently lost data.

**Remediation:**
- Added all 5 missing columns to the archive CREATE TABLE statements
- Changed all INSERTs from positional `VALUES (?, ?, ...)` to explicit column-named INSERTs
- Changed all SELECTs from `SELECT *` to explicit column lists
- Fixed archive FTS5 table to match the v5 migration schema (porter tokenizer, unindexed metadata columns)
- Added test `test_archive_preserves_all_columns` that verifies all column values survive archiving

**Files changed:** `maintenance.py`, `test_maintenance.py`

**Learning point:** Hardcoded schemas in non-migration code are a maintenance trap. Every time a migration adds a column, every other place that creates tables (archive, backup, test helpers) must be updated too. The fix is either: (a) share the schema source between migrations and archive code, or (b) use `SELECT sql FROM sqlite_master` to clone the live schema. Option (a) is simpler; option (b) is self-healing.

**Test result:** 41/41 maintenance tests passed.

---

### 4b. Exporter Protocol Consistency

**Original issue:** Multiple exporters diverged from the `BaseExporter` Protocol:
- `aider.py` and `litellm.py` missing `batch_size` parameter
- `litellm.py` had 3 silent `except Exception: pass` blocks with no logging
- `bedrock.py` duplicated the `commit_batch` function instead of using the shared one
- `base.py` and `bedrock.py` used `raise e` instead of bare `raise` (loses traceback)

**Remediation:**
- `base.py`: `raise e` → bare `raise`
- `aider.py`: Added `batch_size: int = 50` parameter, replaced module constant
- `litellm.py`: Added `batch_size` parameter + `logger.warning(exc_info=True)` to all 3 silent exception blocks
- `bedrock.py`: Removed duplicated `_commit_batch` method, replaced with `from .base import commit_batch`

**Files changed:** `base.py`, `aider.py`, `litellm.py`, `bedrock.py`

**Learning point:** `raise e` vs bare `raise` — `raise e` creates a new traceback starting at the raise statement, losing the original exception context. Bare `raise` preserves the full traceback chain. Always use bare `raise` in except blocks unless you intentionally want to hide the original call stack.

**Test result:** 682/682 agent-session-tools tests passed.

---

### 4c. Gemini/OpenCode Incremental Re-import

**Original issue:** Both exporters used existence-only incremental checks (`SELECT 1 FROM sessions WHERE id = ?`). Once a session was imported, it was never re-imported even if the source file was updated with new messages. Claude and Kiro exporters handled this correctly.

**Remediation:** Replaced existence checks with `updated_at` comparison (following the Kiro pattern):
1. Query `SELECT updated_at FROM sessions WHERE id = ?`
2. If timestamps match → skip (unchanged)
3. If timestamps differ → delete old messages, re-import, set status = "updated"
4. If no existing row → import fresh, set status = "added"

Added 3-phase tests (add → skip → update) to both `test_exporter_gemini.py` and `test_exporter_opencode.py`.

**Files changed:** `gemini.py`, `opencode.py`, `test_exporter_gemini.py`, `test_exporter_opencode.py`

**Learning point:** Incremental import checks must account for updates, not just existence. The existence-only pattern (`SELECT 1`) is a one-way door — once imported, always skipped. The `updated_at` comparison pattern is O(1) per session and correctly handles the three states: new (add), unchanged (skip), modified (re-import).

**Test result:** 31/31 Gemini + OpenCode exporter tests passed. 1,469 total.

---

## Plugin Architecture for Agents

**Brainstorm:** [`docs/brainstorms/2026-04-08-agent-plugin-architecture-brainstorm.md`](brainstorms/2026-04-08-agent-plugin-architecture-brainstorm.md)
**Plan:** [`docs/plans/2026-04-08-agent-plugin-architecture.md`](plans/2026-04-08-agent-plugin-architecture.md)

**Remediation:** Implemented the full plugin architecture in 9 TDD tasks using parallel subagents:

| Task | What | Result |
|------|------|--------|
| 1. Protocol + AgentAdapter | `adapters/_protocol.py` | 4/4 tests |
| 2. Strategy helpers | `adapters/_strategies.py` — cli_flag, cwd_file, MCP writer | 10/10 tests |
| 3. Registry | `adapters/registry.py` — auto-discovery + detect_agents | 5/5 tests |
| 4. Migrate built-ins | 6 adapter files + `_local_llm.py` | 22/22 tests |
| 5. Custom agents | `adapters/_custom.py` — config-driven factory | 10/10 tests |
| 6. Settings update | `custom` field on `AgentsConfig` | 2/2 tests |
| 7. Thin facade | `agent_launcher.py` → re-exports from adapters | 65/65 existing tests |
| 8. Public API | `adapters/__init__.py` clean exports | Pass |
| 9. Verification | Full suite + ruff | 1,413 passed, ruff clean |

**Architecture delivered:**

```
adapters/
├── __init__.py          # Public API (28 LOC)
├── _protocol.py         # AdapterProtocol + AgentAdapter (53 LOC)
├── _strategies.py       # cli_flag_setup, cwd_file_setup, write_mcp_config (164 LOC)
├── _custom.py           # Config-driven adapter factory (157 LOC)
├── _local_llm.py        # Shared Ollama/LM Studio helpers (46 LOC)
├── registry.py          # Auto-discovery + registration (174 LOC)
├── claude.py            # 36 LOC
├── gemini.py            # 46 LOC
├── kiro.py              # 113 LOC
├── opencode.py          # 67 LOC
├── ollama.py            # 36 LOC
└── lmstudio.py          # 36 LOC
                           Total: 956 LOC (12 files)
agent_launcher.py        # Thin facade: 396 LOC (down from 585)
```

**Key learning points:**

1. **Protocol vs ABC:** Python's `runtime_checkable` Protocol doesn't work with dataclass `Callable` fields (they're data attributes, not methods). Protocol is still valuable for documentation and static type checking, but `isinstance` checks require structural verification.

2. **Strategy pattern for extensibility:** Three strategies (cli-flag, cwd-file, config-file) cover all 6 existing agents and most future ones. Users add agents via YAML config without writing Python. The `functools.partial` trick lets cwd-file bind its filename while keeping the same callable signature.

3. **Auto-discovery with `pkgutil.iter_modules`:** Scanning the package for modules that export an `ADAPTER` constant means adding a new built-in adapter is one file — no registry edits needed.

4. **Facade pattern for backwards compatibility:** Existing callers (`cli/_study.py`, `web/routes/session.py`, `session/cleanup.py`) continue to `from studyctl.agent_launcher import AGENTS` without changes. The facade re-exports from the new package.

5. **Parallel subagents work well when files don't overlap:** Tasks 2+3+6 ran simultaneously (zero shared files), as did Tasks 4+5. Total wall-clock time was about half what sequential would have been.

**Test result:** 1,413 passed, 0 failed, 6 skipped, 0 warnings. Ruff clean.
