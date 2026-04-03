---
title: "SQLite Schema Drift: PRAGMA user_version vs Actual Table State"
date: 2026-04-03
category: database-issues
tags: [sqlite, migrations, schema-drift, self-healing, testing, mock-targeting]
module: studyctl
symptoms:
  - "test_parking_logged timed out waiting for IPC parking file after 15s"
  - "test_wrapper_agent_can_park_topics timed out waiting for IPC parking file after 15s"
  - "park_topic() silently returned None with no visible error"
  - "parked_topics table missing from sessions.db despite PRAGMA user_version = 14"
  - "Migration v15 failed: no such table: main.parked_topics"
  - "test_cli_session.py CI failures: assert 1 == 0 on session start"
root_cause: "PRAGMA user_version advanced to 14 without parked_topics table being created (partial migration). Migration system couldn't self-heal — thought v14 already ran, tried v15 which needed the missing table."
---

# SQLite Schema Drift: Self-Healing Database Connections

## Problem

Two integration tests (`test_parking_logged`, `test_wrapper_agent_can_park_topics`) consistently timed out after 15 seconds waiting for the IPC parking file to contain data.

The tests were NOT flaky — they failed deterministically on every run.

## Investigation

### Step 1: Timing analysis (wrong hypothesis)

Initial assumption: `uv run` startup overhead was causing the mock agent's `park` command to execute after the 15s timeout. Measured `uv run` overhead at **0.3s** — total agent execution time was ~5s. Timeout was not the issue.

### Step 2: Trace the code path

The `park` CLI command has two gates before writing the IPC file:

```python
# cli/_session.py — park command
row_id = park_topic(question=question, study_session_id=study_session_id)
if row_id:                    # gate 1: DB insert must succeed
    if study_session_id:       # gate 2: session state must have ID
        append_parking(question)  # only THEN write IPC file
```

### Step 3: Diagnostic script

Created a script to call `park_topic()` directly during a running session:

```
Migration v15 failed: no such table: main.parked_topics
park_topic returned: None (truthy=False)
```

### Step 4: Root cause identified

```
DB path: ~/.config/studyctl/sessions.db
PRAGMA user_version: 14
Tables: [sessions, messages, study_sessions, ...] — NO parked_topics
```

**Version/schema drift**: `user_version` was 14 (the migration that creates `parked_topics`), but the table didn't exist. The migration system saw version=14, skipped v14, tried v15 (creates an index ON `parked_topics`), and failed because the table was missing.

The original `_connect()` code tried to handle this:

```python
try:
    conn.execute("SELECT 1 FROM parked_topics LIMIT 0")
except sqlite3.OperationalError:
    try:
        from agent_session_tools.migrations import migrate
        migrate(conn)  # fails — tries v15, which needs the table
    except Exception:
        logger.warning("Could not run migrations")  # swallowed silently
```

## Solution

Two-tier fallback in `parking.py:_connect()`:

```python
# Tier 1: Try migrations (proper path)
try:
    from agent_session_tools.migrations import migrate
    migrate(conn)
except Exception:
    pass

# Tier 2: Verify + fallback (self-healing path)
try:
    conn.execute("SELECT 1 FROM parked_topics LIMIT 0")
except sqlite3.OperationalError:
    logger.info("Creating parked_topics table directly (migration drift recovery)")
    _create_parked_topics_table(conn)
```

The `_create_parked_topics_table()` creates the table with the **full current schema** (v14-v17 columns: source, tech_area, priority), not just the v14 schema. This is critical — `park_topic()` inserts v16 columns, so the fallback table must match current code.

Both `CREATE TABLE IF NOT EXISTS` and `CREATE UNIQUE INDEX IF NOT EXISTS` ensure idempotency.

## Secondary Issue: CI Test Failures

Three tests in `test_cli_session.py` failed on CI with:
```
assert 1 == 0  # session start exit code
```

**Root cause**: The test fixture patched `studyctl.settings.get_db_path()`, but `history.py:start_study_session()` resolves its DB via `_find_db()` → `load_settings().session_db` — a completely different code path. On CI (no real `sessions.db`), `_find_db()` returned `None`.

**Fix**: Patch the actual lookup function:
```python
monkeypatch.setattr("studyctl.history._find_db", lambda: db_path)
```

**Why it passed locally**: Your machine has a real `~/.config/studyctl/sessions.db`, so `_find_db()` succeeded against the real DB, masking the missing patch.

## Prevention

### Pattern: Check-Try-Verify-Fallback

For any managed system (migrations, provisioning, deployment) that can get into inconsistent state:

1. **Check**: does the resource exist?
2. **Try**: use the proper mechanism to create it
3. **Verify**: did the proper mechanism work?
4. **Fallback**: create it directly if still missing

### Pattern: Mock Where the Name Is Looked Up

When patching for tests, trace the actual code path:
- `get_db_path()` is defined in `settings.py` — but `history.py` never calls it
- `_find_db()` calls `load_settings().session_db` — that's where the lookup happens
- Patch `history._find_db`, not `settings.get_db_path`

### Test locally without real DB

To catch these issues before CI:
```bash
# Temporarily rename your real DB
mv ~/.config/studyctl/sessions.db ~/.config/studyctl/sessions.db.bak
uv run pytest packages/studyctl/tests/test_cli_session.py -v
mv ~/.config/studyctl/sessions.db.bak ~/.config/studyctl/sessions.db
```

## Related

- `docs/solutions/tmux-session-management-and-ci-issues.md` — previous CI/test environment issues
- Teaching moment: "Self-Healing Database Connections" (Obsidian Teaching-Moments.md, 2026-04-03)
- Teaching moment: "Lazy Imports and Mock Targeting" (Obsidian Teaching-Moments.md, 2026-03-27)

## Files Changed

| File | Change |
|------|--------|
| `packages/studyctl/src/studyctl/parking.py` | Two-tier `_connect()` with `_create_parked_topics_table()` fallback |
| `packages/studyctl/tests/test_cli_session.py` | Added `monkeypatch.setattr("studyctl.history._find_db", ...)` |
