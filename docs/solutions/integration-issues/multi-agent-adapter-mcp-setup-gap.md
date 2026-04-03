---
title: Multi-Agent Adapter — mcp_setup() Not Called in Session Start Flow
category: integration-issues
tags: [adapters, mcp, multi-agent, orchestration, integration-testing]
module: cli/_study.py
symptom: MCP config files absent from session directory; Gemini and OpenCode agents start without persona
root_cause: _handle_start() called adapter.setup() but omitted adapter.mcp_setup(session_dir)
---

# Multi-Agent Adapter: mcp_setup() Gap in Session Start Flow

## Problem Summary

The `AgentAdapter` dataclass carries four callables: `setup`, `launch_cmd`, `teardown`, and `mcp_setup`.
The orchestrator (`_handle_start()` in `cli/_study.py`) wired `setup()` but never called `mcp_setup()`.
Result: MCP config files were never written to the session directory, so agents started without persona context.

## Symptom

```
studyctl study --agent gemini   # starts, but Gemini has no system prompt
studyctl study --agent opencode # starts, but OpenCode ignores agent persona
```

Expected files that were absent:

| Agent     | Expected file                          |
|-----------|----------------------------------------|
| Gemini    | `<session_dir>/.gemini/settings.json`  |
| OpenCode  | `<session_dir>/.opencode/opencode.json`|

Unit tests: 45/45 passed.
Integration tests: 5/7 passed — the two failures were persona-verification checks.

## Agent Persona Injection Mechanisms

Each tool uses a fundamentally different mechanism — no universal standard exists.

| Agent     | Mechanism                                          | Written by         |
|-----------|----------------------------------------------------|--------------------|
| Claude    | `--system-prompt` CLI flag on launch               | `launch_cmd`       |
| Gemini    | `GEMINI.md` file in the working directory          | `mcp_setup()`      |
| Kiro      | Atomic JSON written to `~/.kiro/agents/<name>.json`| `mcp_setup()`      |
| OpenCode  | `<session_dir>/.opencode/agents/<name>.md` with YAML frontmatter | `mcp_setup()` |

Claude's persona is injected at launch time via a flag, so it worked even without `mcp_setup()`.
Gemini, Kiro, and OpenCode all depend on files written by `mcp_setup()` — which was never called.

## Root Cause

```python
# cli/_study.py — _handle_start() BEFORE fix
def _handle_start(session_dir: Path, adapter: AgentAdapter, ...) -> None:
    adapter.setup(session_dir)          # ✓ called
    # adapter.mcp_setup(session_dir)   # ✗ forgotten — not called
    cmd = adapter.launch_cmd(session_dir)
    _launch_tmux(cmd, ...)
```

The `AgentAdapter` dataclass is frozen; all callables are optional (`Callable | None`).
`mcp_setup` was defined on the adapter objects but simply never invoked in the orchestrator.

## Fix

```python
# cli/_study.py — _handle_start() AFTER fix
def _handle_start(session_dir: Path, adapter: AgentAdapter, ...) -> None:
    adapter.setup(session_dir)
    if adapter.mcp_setup:                    # guard for adapters that don't need it
        adapter.mcp_setup(session_dir)       # ← added
    cmd = adapter.launch_cmd(session_dir)
    _launch_tmux(cmd, ...)
```

One line. The guard handles adapters (e.g. Claude) where `mcp_setup` is `None`.

## Why Unit Tests Passed

Unit tests exercised each adapter function in isolation:

```python
def test_gemini_mcp_setup_writes_settings(tmp_path):
    adapter = gemini_adapter()
    adapter.mcp_setup(tmp_path)             # called directly
    assert (tmp_path / ".gemini/settings.json").exists()
```

This confirmed `mcp_setup()` worked correctly. It did not test whether `_handle_start()` *called* it.
The orchestration gap is invisible to unit tests — only integration tests that run a full session lifecycle can catch it.

## Prevention Strategies

1. **Checklist on adapter contracts** — when an adapter/strategy carries multiple callables, the orchestrator review checklist must include "all callables invoked".

2. **Integration smoke test per adapter** — a test that calls `_handle_start()` end-to-end (not the adapter directly) and asserts all expected side-effects (files written, tmux pane alive).

3. **Dataclass field ordering as a hint** — group "must-call" fields at the top of the dataclass so code review catches omissions by visual inspection.

4. **Post-setup assertion in `_handle_start()`** — after setup, assert that required paths exist before launching:

   ```python
   missing = adapter.required_paths(session_dir) - {p for p in ... if p.exists()}
   if missing:
       raise SetupError(f"Adapter setup incomplete: {missing}")
   ```

## Related Files

- `src/studyctl/adapters/` — one module per agent adapter
- `src/studyctl/cli/_study.py` — `_handle_start()` orchestrator
- `tests/unit/test_adapters.py` — per-function unit tests
- `tests/integration/test_session_lifecycle.py` — end-to-end tests that caught this
