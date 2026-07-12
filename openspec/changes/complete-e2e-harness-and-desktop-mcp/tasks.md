## 1. Unblock session start (Lane A)

- [ ] 1.1 Reproduce the thread-hosted-uvicorn `SIGCHLD` `ValueError` with a
      failing test, confirming §3.2 of the handoff doc against the live
      checkout before changing anything.
- [ ] 1.2 Replace `_playwright_helpers.py`'s thread-hosted uvicorn with a
      subprocess runner (`tests/e2e/support/run_server.py` calling
      `create_app()` + `uvicorn.run()` directly via `subprocess.Popen`).
- [ ] 1.3 Fix `startSession()` in `index.html` to parse non-JSON error
      bodies defensively instead of surfacing "Network error" for any
      `res.json()` failure.
- [ ] 1.4 Add a fake-agent PTY binary (reads persona + echoes Socratic-ish
      output) so the PTY path has something real to spawn in CI/headless
      runs.

## 2. Close the path-traversal defect

- [ ] 2.1 Add `session_dir_slug()` built on `content.storage.slugify` with
      an allowlist; add a regression test posting
      `topic="../../../etc"` to `/api/session/start` for PTY, ACP, and
      ttyd transports.
- [ ] 2.2 Route `web/services/session_start.py` and
      `web/routes/session/_start.py:562` through the shared helper.

## 3. Harvest or discard grok worktree lanes

- [ ] 3.1 Diff `~/.grok/worktrees/tools-studyloop/subagent-019f55c3-…`
      (Task 1 hardening) against main; commit salvageable pieces with
      tests, discard the rest.
- [ ] 3.2 Diff `subagent-019f55c4-f9a2…` (MCP parity) against main; same
      treatment.
- [ ] 3.3 Diff `subagent-019f55c4-f9a8…` (learner surface) against main;
      same treatment.
- [ ] 3.4 Delete all three worktrees once harvested.

## 4. Complete the representative journey (Phase B)

- [ ] 4.1 Extend `tests/e2e/test_representative_user_journey.py` through
      real generation (Stub provider), study blocks, break, flashcard/quiz
      review, session end.
- [ ] 4.2 Add the Socratic-steering LLM-judge assertion (judge model ≠
      mentor model, via the LiteLLM gateway) asserting the mentor asks
      guiding questions rather than giving full answers.
- [ ] 4.3 Add one `live_provider`-marked variant using real questions.
- [ ] 4.4 Assert session-end export behavior (progress recorded, session
      exported to `sessions.db`).

## 5. Desktop MCP parity (Phase C)

- [ ] 5.1 Add `get_lesson_tree`, `read_lesson`, `search_lessons` to
      `mcp/tools.py`, reusing `_safe_course_dir` / explorer internals.
- [ ] 5.2 Add `get_due_cards` and `submit_card_answer`, extracting the
      due-card join into a shared service if not already exposed.
- [ ] 5.3 Smoke-test the new tools against MCP Inspector.
- [ ] 5.4 Draft Claude Desktop (`claude_desktop_config.json`) and Codex
      (`~/.codex/config.toml`) registration snippets; verify Codex
      tool-calling works against the real app (prompts/resources remain
      unverified — do not build on them yet).
- [ ] 5.5 Update `docs/mcp.md` with the studyloop-mcp section, the full
      tool list, desktop-app install snippets, and the honest
      capability matrix (what works via MCP vs. browser-only).

## 6. Verification

- [ ] 6.1 Full suite green (`pytest -m 'not integration and not e2e and
      not live_kiro and not live_provider'`).
- [ ] 6.2 `-m e2e` suite green locally.
- [ ] 6.3 `ruff check .` and `pyright` clean.
- [ ] 6.4 `openspec validate --all` clean; archive this change once merged.
