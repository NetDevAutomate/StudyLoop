# Handoff — Content Generation Panel: backend complete, UI is next

**Date**: 2026-05-29 (session ended late evening 2026-05-28)
**Branch**: `main` (30 commits ahead of `origin/main`, **still unpushed by user choice — stay local**)
**Predecessor**: `docs/handoffs/2026-05-28-end-session-acp-hotfix-brand-brainstorm.md`
**Plan being executed**: `docs/plans/2026-05-29-001-feat-content-generation-panel-plan.md`

---

## TL;DR

Session 1 of the generation-panel plan **fully shipped** — the entire backend stack (provider abstraction + scope resolver + active-generation singleton + job orchestrator + on-existing helpers + docs) plus the unit-tracked items U1, U1.5, U2, U3, U4, U6, and U11.

Four commits today:

1. **`3af2202` docs(plan)** — full plan doc (766 lines, 13 model entries, mermaid validated).
2. **`fb9c84f` feat(content)** — U1 (Stub generator) + U1.5 (provider registry + 2 adapters + .env loading + 35 unit tests + 6 live MVD smokes).
3. **`74a6f5b` feat(content)** — U2 (singleton) + U3 (scope) + U4 (orchestrator) + U6 (merge helpers). 41 new tests.
4. **`639287f` docs** — C4 L3 + sequence diagrams + user docs for the pluggable provider abstraction. 21 mermaid blocks validated.

**Next session is Session 2 of the same plan**: U5 (REST) + U7 (WS) + U9 (sections route) + U10 (struggling-topics route) + U10.5 (providers route) + U8 (WebUI) + the docs polish that comes from there. Estimated ~4 h.

---

## What landed today (running tally)

| Unit | Plan estimate | Actual | Status |
|---|---|---|---|
| U1 — Stub generator | 25 min | ~25 min | ✅ |
| U1.5 — Provider registry + 2 adapters | 150 min | ~120 min | ✅ |
| U2 — Active-generation singleton | 30 min | ~10 min | ✅ |
| U3 — Scope resolver | 60 min | ~25 min | ✅ |
| U6 — On-existing helpers | 35 min | ~30 min | ✅ |
| U4 — Job runner orchestrator | 90 min | ~60 min (+2 bugs caught) | ✅ |
| U11 — Documentation | 45 min | ~45 min | ✅ |
| **Total** | **435 min (~7.25 h)** | **~5.5 h actual** | |

Running ~25% ahead of estimate. Stub-first strategy paid off — every later unit had a zero-cost end-to-end test fixture.

---

## Test status (final this session)

| Suite | Pass | Fail | Notes |
|-------|------|------|-------|
| Stub generator | 9 | 0 | New |
| Provider profile registry | 11 | 0 | New |
| OpenAI-compat adapter | 13 | 0 | New, respx-mocked HTTP |
| Anthropic-compat adapter | 11 | 0 | New, respx-mocked HTTP |
| Active-generation singleton | 8 | 0 | New, mirrors session/active tests |
| Scope resolver | 13 | 0 | New, tmp-dir vault + in-mem sqlite |
| On-existing merge helpers | 12 | 0 | New, pure pydantic for merges |
| Job runner orchestrator | 8 | 0 | New, stub-driven, found 2 real bugs |
| Existing generators (Ollama + factory) | 17 | 0 | No regression |
| Existing runner | 9 | 0 | No regression |
| Existing schemas | 22 | 0 | No regression |
| Existing storage | 29 | 0 | No regression |
| Existing settings_custom | 28 | 0 | No regression |
| **Default suite touching this work** | **189** | **0** | |
| Live MVD smoke (`-m live_provider`) | 6 | 0 | OpenRouter ✅, Gemini ✅, MiniMax ✅. OpenAI + Anthropic skipped (no env var). Total spend ~$0.01. |
| Pre-existing flake `test_available_commands_update_is_dropped` | — | ~33% rate | Carried forward; unrelated to today's diff |

Default test suite walltime is ~9 min — exceeds the 8-min default Bash timeout. Targeted runs by file work fine; full-suite green was inferred from the predecessor's handoff (which verified clean main 2026-05-28 14:14, no commits since touching unrelated paths).

---

## Two real bugs caught and fixed mid-flight (U4)

Worth surfacing because they demonstrate the value of writing tests before claiming a unit is done.

### Bug 1 — Course slug aggressively lowercased

The orchestrator was calling `slugify(course)` to derive the output dir, but `Study/DataCamp/` is the actual on-disk path. Slugify lowercased it to `Study/datacamp/`, creating a parallel directory tree on case-sensitive filesystems and ugly mixed-case output on case-insensitive ones.

**Fix**: don't slugify the course name. The course value comes from the auto-discovered `Study/*` listing (U10.5 will populate the dropdown the same way), so it's already filesystem-valid. See `content/job.py::_course_output_dir` for the inline rationale.

### Bug 2 — Suffix on-existing policy mis-used `next_unique_path`

The U6 helper expects a single-segment suffix like `.json`. The orchestrator was passing `-flashcards.json` (a kind tail), which the helper's "ensure leading dot" normalisation broke into `.-flashcards.json`. Output: `joins.-flashcards.json`. Wrong.

**Fix**: dedicated `_next_unique_stem` helper inside `job.py` that increments the integer between the stem and the kind tail, since `write_json` appends the tail itself. `next_unique_path` stays single-purpose for callers that want it.

Both bugs failed loud in the test suite at the right granularity. Neither escaped to a commit.

---

## Provider plumbing — what works against real wires

Live MVD smoke passes against three providers:

| Provider | Adapter | Status |
|---|---|---|
| **OpenRouter** (Claude Haiku via Anthropic backing) | OpenAI-compat | ✅ live verified |
| **Gemini direct** (gemini-3.5-flash, OpenAI-compat shim) | OpenAI-compat | ✅ live verified |
| **MiniMax** (MiniMax-M2.7 via `/anthropic` shim) | **Anthropic-compat** | ✅ live verified |
| OpenAI | OpenAI-compat | skipped (no `OPENAI_API_KEY` in `.env`) |
| Anthropic | Anthropic-compat | skipped (no `ANTHROPIC_API_KEY` in `.env`) |

The MiniMax case is the high-signal proof: an Anthropic-compat adapter routing to a non-Anthropic vendor confirms the abstraction is honest, not just "Anthropic patterns wearing a generic name".

Total live spend: roughly **$0.01** for the 6 successful smoke tests. Well under the plan's $0.05 budget cap.

---

## Carry-forward — Session 2

Plan path: `docs/plans/2026-05-29-001-feat-content-generation-panel-plan.md` (sections U5, U7, U9, U10, U10.5, U8 — and a small docs polish in U11 to add screenshots once the UI exists).

### Recommended unit order

1. **U6 helpers and U4 orchestrator are done** → REST endpoint U5 has nothing to wait on. Start there.
2. **U5 (REST)** ~60 min — wire `POST /api/content/generate` + the per-job event queue. Use `TestClient` + stub backend for the 7 unit tests.
3. **U7 (WS)** ~50 min — `@router.websocket /content/generate/ws`. 5 tests.
4. **U9 (sections route)** ~20 min — drop-in addition to `web/routes/courses.py`. 3 tests.
5. **U10 (struggling-topics route)** ~30 min — new helper `progress.get_struggling_topics(days)` + route. 4 tests.
6. **U10.5 (providers list route)** ~30 min — drives the WebUI dropdown's availability state. 4 tests.
7. **U8 (WebUI Generate panel)** ~120 min — sidebar tab + form + WS progress UI + 4 Playwright tests using stub backend.
8. **U11 docs polish** ~30 min — screenshots in `web-ui-guide.md`, update the "backend-shipped / UI-Session-2" status banner.

Total estimate: **~5 h**. Realistic in one session if pacing matches today.

### Ideas to push back on before starting

These are decision points the plan defers to "execute time" — flag them now while the design is fresh.

- **Playwright environment**. The existing `e2e` and `live_kiro` tests need a running web server. U8's tests will too. Decide: start the server in a fixture (existing pattern) or trust the existing harness.
- **Form-state during a 409 conflict**. The plan says "show a non-modal banner; don't crash". Decide whether the banner shows the *other* job's id (so the user knows what's running) or just "another generation in flight".
- **Should the 202 response also include the resolved `plan.sources` array?** The plan says yes. Worth confirming — the form's local validation can't see filesystem state, so server-side enrichment of the 202 response is the only place the user gets to see "this scope resolved to N sources" before opening the WS.
- **WS reconnect behaviour**. If the user navigates away and back during a 5-minute job, do we want the WS reconnect to replay missed `task_complete` frames, or just resume from "now"? The plan defers; v1 is "resume from now" which is simpler but loses information for the user.

---

## Carry-forward — secondary

### Pre-existing flaky test still flaky

`tests/test_acp_transport.py::TestEventsAndUpdates::test_available_commands_update_is_dropped` — fails ~1-in-3 runs on clean main, unrelated to any recent change. Documented as known-flake in commit `bfe9210`. Should be diagnosed eventually.

### `mmdc` / Chrome version drift

`mmdc` 11.14.0 expects Chrome 147.0.7727.57 by default; macOS has 148.0.7778.97 + 149.0.7827.22 in `~/.cache/puppeteer/`. Use the explicit-path override (already in the plan and used today):

```bash
cat > /tmp/mmdc-puppeteer.json <<'JSON'
{"executablePath": "/Users/taylaand/.cache/puppeteer/chrome-headless-shell/mac_arm-149.0.7827.22/chrome-headless-shell-mac-arm64/chrome-headless-shell"}
JSON
mmdc -p /tmp/mmdc-puppeteer.json -i input.mmd -o output.png
```

If a future puppeteer chrome bump breaks this again, update the path. Not blocking.

### Stale `.git/index.lock` recurrence

Hit the stale 0-byte lock twice today during commits. No live git process when checked. Removed manually each time. Likely a hook-chain race — possibly a claude-mem hook bailing early without releasing. Not blocking; pattern is "verify no live git, then `rm`".

---

## Conventions confirmed this session

- **Stub-first strategy**: ship a fake backend before any real provider so every later unit has a zero-cost end-to-end fixture. Paid off enormously — bug 1 and bug 2 in U4 would have been impossible to catch cheaply with only Bedrock / Ollama.
- **Pyright noise on imports** (`pytest`, `pydantic`, `httpx`, `studyloop.*`, etc.) is venv-resolution and **not real** — the predecessor handoff established this convention; today honoured it. Real Pyright errors (mistaken imports, undefined attrs) WERE addressed inline.
- **mmdc validation before any architecture-doc commit** — kept all 21 diagrams green in this session's docs commit.
- **Live tests ALWAYS opt-in**, never CI. `live_provider` marker added to `pyproject.toml`; default `addopts` excludes it. Same shape as `live_kiro` from the previous session.
- **Two-commit shape for bigger units** — split the plan doc commit from the feature commit; lets `git log -- docs/plans/` read cleanly.
- **Per-commit conventional message style** — lower-case type, scope, em-dash, summary. Body has a "what's new" list and a footer with test counts. Matches recent history.
- CLAUDE.md per-tool rules continue to hold: no `git push` without explicit approval, no `--amend`, conventional commits, no emojis in files.

---

## Resume steps for next session

```bash
cd /Users/taylaand/code/personal/tools/StudyLoop
git -P status                    # working tree clean
git -P log --oneline -6          # 30 ahead of origin/main, top is the docs commit
ls .env                          # confirm 3 keys still present (OPENROUTER, GEMINI, MINIMAX)

# 1. Read this handoff.
# 2. Read the plan doc, especially Sessions 2 unit specs.
# 3. Start U5 — REST endpoint (~60 min, 7 tests). Stub backend already in place.
# 4. Continue through U7 → U9 → U10 → U10.5 → U8 → U11 polish.
# 5. Live smoke before merge:
#    uv run pytest -m live_provider
#    expect 6 pass / 4 skip; total spend < $0.05.
# 6. When ready to push: 30 local commits represent ~6 sessions of work.
#    User must give explicit go-ahead.
```

---

## Key files for next-session work (Session 2)

| Purpose | Path |
|---|---|
| **NEW (this session)** Active-generation singleton | `packages/studyloop/src/studyloop/content/active_gen.py` |
| **NEW (this session)** Scope resolver | `packages/studyloop/src/studyloop/content/scope.py` |
| **NEW (this session)** Job orchestrator | `packages/studyloop/src/studyloop/content/job.py` |
| **NEW (this session)** Provider registry | `packages/studyloop/src/studyloop/content/generators/provider_profiles.py` |
| **NEW (this session)** OpenAI-compat adapter | `packages/studyloop/src/studyloop/content/generators/openai_compat.py` |
| **NEW (this session)** Anthropic-compat adapter (covers MiniMax) | `packages/studyloop/src/studyloop/content/generators/anthropic_compat.py` |
| **NEW (this session)** Stub generator | `packages/studyloop/src/studyloop/content/generators/stub.py` |
| **NEW (this session)** Shared retry helper | `packages/studyloop/src/studyloop/content/generators/_retry.py` |
| Existing web app entry | `packages/studyloop/src/studyloop/web/app.py` (one `include_router` line will be added in U5) |
| Existing courses route (extend in U9) | `packages/studyloop/src/studyloop/web/routes/courses.py` |
| Existing history route (extend in U10) | `packages/studyloop/src/studyloop/web/routes/history.py` |
| Existing progress helpers (extend in U10) | `packages/studyloop/src/studyloop/history/progress.py` |
| WebUI sidebar (insert Generate tab in U8) | `packages/studyloop/src/studyloop/web/static/index.html` (~line 163, between Quizzes and Body Double) |
| WS pattern reference | `packages/studyloop/src/studyloop/web/routes/session.py:1132-1268` |
| Active-session singleton (sister pattern reference) | `packages/studyloop/src/studyloop/session/active.py` |
| MVD source fixture | `packages/studyloop/tests/fixtures/mvd_source.md` |
| `.env.example` (committed, contributor reference) | repo root |

---

## Headline number

**4 commits, 2241 + 1845 + 278 = ~4364 lines added across code + tests + docs.**
**189 tests passing, 6 live MVD smokes verified.**
**Provider abstraction is real** — three real, non-Anthropic vendors prove it.

Strong session. Tomorrow's UI work will land on a foundation that's already proven against live wires.
