---
title: "GitHub Actions Triple Workflow Failure: Schema Init, Pytest Markers, and Environment Assumptions"
description: "All three CI workflows failed every run due to missing base schema on fresh DBs, unmarked integration tests, missing --agent flags, and stale module references."
category: test-failures
tags:
  - github-actions
  - pytest-markers
  - sqlite-migrations
  - tmux
  - ci-cd
  - studyctl-doctor
  - lazy-loading
severity: high
components:
  - packages/studyctl/src/studyctl/history/_connection.py
  - packages/studyctl/src/studyctl/doctor/core.py
  - packages/studyctl/src/studyctl/cli/__init__.py
  - packages/studyctl/tests/test_harness_matrix.py
  - packages/studyctl/tests/test_study_integration.py
  - packages/studyctl/tests/test_uat_terminal.py
  - .github/workflows/nightly-uat.yml
  - .github/workflows/nightly-install.yml
  - pyproject.toml
symptoms:
  - "Nightly Install: studyctl doctor exiting non-zero — Config not found"
  - "CI: 42 test errors — TimeoutError waiting for session-state.json after 20s"
  - "UAT: Failed to start session. Run 'studyctl doctor'."
  - "UAT: No AI agent found."
  - "UAT: exit code 5 — no tests collected (all deselected)"
  - "Local: ModuleNotFoundError: No module named 'studyctl.cli._eval'"
  - "PytestUnknownMarkWarning: Unknown pytest.mark.e2e"
date_resolved: "2026-04-06"
---

# CI Workflow Failures: Schema Init, Pytest Markers, and Environment Assumptions

## Problem

All three GitHub Actions workflows (CI, Nightly Install Check, Nightly UAT) were failing on every run. The failures had been accumulating over several days with 7 distinct root causes that interacted and masked each other.

## Root Causes and Fixes

### 1. Missing Base Schema on Fresh DB (Critical)

**File**: `packages/studyctl/src/studyctl/history/_connection.py`

`_connect()` called `migrate(conn)` on new databases but never applied `schema.sql` first. Migration v1 does `ALTER TABLE sessions ADD COLUMN`, which fails if the `sessions` table doesn't exist. On any fresh CI runner, every test that started a study session failed with "Failed to start session."

**Fix**: Apply the base schema before running migrations, matching the pattern in `agent_session_tools.export_sessions.init_db()`.

```python
# Before
if is_new:
    try:
        from agent_session_tools.migrations import migrate
        migrate(conn)

# After
if is_new:
    try:
        from agent_session_tools.export_sessions import SCHEMA_FILE
        from agent_session_tools.migrations import migrate
        with open(SCHEMA_FILE) as f:
            conn.executescript(f.read())
        migrate(conn)
```

### 2. Doctor Check Too Strict for CI

**File**: `packages/studyctl/src/studyctl/doctor/core.py`

`check_config_file()` returned `"fail"` for a missing `config.yaml`. On fresh CI runners, no config exists — this is expected. The Nightly Install workflow treated `core` category failures as CI-blocking.

**Fix**: Changed from `"fail"` to `"warn"`. The check already had `fix_auto=True`, signalling it's auto-recoverable. Invalid YAML in an existing config remains `"fail"`.

### 3. Integration Tests Not Marked

**File**: `packages/studyctl/tests/test_harness_matrix.py`

`TestAgentMatrix` (42 tests across 6 agents) requires tmux + mock agent spawning but wasn't marked `@pytest.mark.integration`. CI runs with `-m "not integration"`, so these ran and timed out.

**Fix**: Added `pytest.mark.integration` to the module-level `pytestmark`.

### 4. Missing `--agent` Flag in Integration Tests

**Files**: `test_study_integration.py`, `test_study_integration.py::test_double_start_blocked`

`_start_session()` didn't pass `--agent`, so `detect_agents()` ran on CI where no AI agents are installed. This produced "No AI agent found" and the command exited before writing `session-state.json`.

**Fix**: Added `"--agent", "claude"` to default args. `STUDYCTL_TEST_AGENT_CMD` bypasses the actual agent binary.

### 5. Deleted Eval Module Still Referenced

**File**: `packages/studyctl/src/studyctl/cli/__init__.py`

`LazyGroup` still had `"eval": "studyctl.cli._eval:eval_group"` but `_eval.py` had been deleted. The lazy import deferred the `ModuleNotFoundError` to runtime, so static analysis missed it.

**Fix**: Removed the stale entry from `lazy_subcommands`.

### 6. `e2e` Marker Not Registered at Workspace Root

**File**: `pyproject.toml` (root)

The `e2e` pytest marker was only in `packages/studyctl/pyproject.toml`. When pytest runs from the workspace root, it uses the root config — so `e2e` was unregistered, producing warnings.

**Fix**: Added `e2e` marker to root `pyproject.toml`.

### 7. UAT Workflow Per-File Steps Missing Marker Override

**File**: `.github/workflows/nightly-uat.yml`

The package `pyproject.toml` has `addopts = "-m 'not integration'"`. Per-file UAT steps ran without `-m integration`, so pytest deselected all integration tests (exit code 5 = no tests collected).

**Fix**: Added `-m integration` to the per-file UAT workflow steps.

## Key Diagnostic: Surfacing Silent Failures

The breakthrough was adding subprocess output to timeout error messages. Previously, failures were completely silent:

```python
# Before
raise TimeoutError(f"Timed out waiting for {desc} after {timeout}s")

# After — reveals the actual error
raise TimeoutError(
    f"Timed out waiting for {desc}"
    f" (exit={result.returncode},"
    f" stdout={result.stdout[-200:]!r},"
    f" stderr={result.stderr[-200:]!r})"
)
```

This revealed `"Failed to start session"` (Root Cause 1) and `"No AI agent found"` (Root Cause 4) — both had been invisible.

## Fix Dependency Chain

```
RC5 (import error) ──────────────────────► fix LazyGroup
RC1 (no schema) ──► diagnostics ──────────► fix _connect()
RC4 (no agent)  ──► diagnostics ──────────► fix _start_session()
RC3 (no marker) ──────────────────────────► fix pytestmark
RC2 (strict doctor) ──────────────────────► fix warn vs fail
RC6 (marker config) ──────────────────────► fix root pyproject
RC7 (UAT addopts) ────────────────────────► fix -m integration
```

## Related Documentation

- [tmux session management and CI issues](../../../docs/internal/solutions/tmux-session-management-and-ci-issues.md) — prior CI fixes for ruff, tmux timeouts, zombie sessions
- [SQLite schema drift self-healing](../../../docs/internal/solutions/sqlite-schema-drift-self-healing.md) — prior migration ordering issue with `parked_topics`
- [CI/CD pipeline spec](../../../docs/local_repo_docs/specs/ci-cd-pipeline.md) — workflow design and matrix strategy
- [Test harness framework brainstorm](../../../docs/local_repo_docs/brainstorms/2026-04-02-test-harness-framework-brainstorm.md) — harness architecture decisions

## Prevention Strategies

### For Fresh Database Initialization
- The migration runner must be idempotent from zero — base schema belongs inside the init path, not as a caller precondition
- Write `test_migrate_from_empty_db` that creates a fresh in-memory DB, runs the full migration stack, and asserts the final schema

### For Test Marker Management
- Run `--strict-markers` in CI to surface missing registrations immediately
- Treat the workspace root `pyproject.toml` as the single source of truth for all marker declarations
- When adding a marker in a package, the PR must also add it to the root config

### For Agent/Binary Assumptions
- Any test touching external binaries is integration by definition — mark it at the point of writing
- Tests should use `--agent claude` when `STUDYCTL_TEST_AGENT_CMD` is set, never relying on `detect_agents()`

### For Module Deletion
- Search for the module's dotted path as a string literal (lazy loaders store paths as strings, not imports)
- Add a `test_lazy_loader_imports` that iterates every `LazyGroup` entry and does `importlib.import_module()`

### Checklist for Future CI Changes
- [ ] Every `pytest` invocation includes the correct marker filter
- [ ] Every `pytest` invocation includes `--strict-markers`
- [ ] New markers registered at workspace root, not just package level
- [ ] DB tests start from empty (not pre-populated) state
- [ ] Optional binary presence is printed before test steps
- [ ] Deleted modules searched for as string literals, not just imports
