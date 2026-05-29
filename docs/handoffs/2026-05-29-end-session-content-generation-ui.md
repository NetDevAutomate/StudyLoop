# Handoff — Content Generation Panel: UI shipped, plan complete

**Date**: 2026-05-29 (session ran morning, ~11:00am → 12:30pm GMT+1)
**Branch**: `main` (36 commits ahead of `origin/main`, **still unpushed by user choice — stay local**)
**Predecessor**: `docs/handoffs/2026-05-29-end-session-content-generation-backend.md`
**Plan executed (now complete)**: `docs/plans/2026-05-29-001-feat-content-generation-panel-plan.md`

---

## TL;DR

Session 2 of the generation-panel plan **fully shipped** in roughly 1.5 h vs the 4 h plan estimate. All seven remaining units landed: U5 (REST), U7 (WS), U9 (sections), U10 (struggling-topics), U10.5 (providers), U8 (WebUI panel), U11 (docs polish). One real bug surfaced and fixed mid-session — `/api/courses` only enumerated already-decked courses, blocking fresh-course generation; new `/api/content/courses` route documents the producer-vs-reviewer split.

Three commits today:

1. **`f89ff53` feat(web)** — HTTP surface: REST + WS + sections + struggling-topics + providers routes. 23 new tests.
2. **`f53aa65` feat(web)** — Generate sidebar panel + Alpine factory + CSS + bug-fix `/api/content/courses` route. 4 Playwright e2e + 2 unit tests.
3. **`a361edf` docs** — flip status from "planned" to "shipped" in `web-ui-guide.md` and `architecture/current.md`. mmdc validated.

The whole content generation panel — backend, HTTP surface, browser side — is **functionally complete on `main`**. The Generate tab is now a first-class sidebar item alongside Flashcards / Quizzes / Body Double / Study Session.

---

## What landed today

| Unit | Plan estimate | Actual | Tests | Commit |
|---|---|---|---|---|
| U5 — REST endpoint + router wiring | 60 min | ~15 min | 7 ✓ | `f89ff53` |
| U7 — WS endpoint | 50 min | ~10 min | 5 ✓ | `f89ff53` |
| U9 — sections route | 20 min | ~10 min | 3 ✓ | `f89ff53` |
| U10 — struggling-topics route | 30 min | ~15 min | 4 ✓ | `f89ff53` |
| U10.5 — providers route | 30 min | ~15 min | 4 + 2 ✓ | `f89ff53` + `f53aa65` |
| U8 — WebUI panel + Playwright e2e | 120 min | ~50 min | 4 ✓ | `f53aa65` |
| U11 — docs polish | 30 min | ~15 min | mmdc-validated | `a361edf` |
| **Subtotal** | **340 min (~5.7 h)** | **~130 min (~2.2 h)** | **29 new** | **3 commits** |

Running ~60% under estimate. Stub-first strategy continued to pay off — every UI flow could be exercised against a deterministic, offline, free generator.

---

## Test status (final this session)

| Suite | Pass | Fail | Notes |
|-------|------|------|-------|
| REST endpoint (`test_web_content_gen_rest.py`) | 7 | 0 | New |
| WS endpoint (`test_web_content_gen_ws.py`) | 5 | 0 | New, real ASGI handshake |
| Sections route (`test_web_courses_sections.py`) | 3 | 0 | New |
| Struggling-topics (`test_web_history_struggling.py`) | 4 | 0 | New, monkeypatched DB connect |
| Providers + content/courses (`test_web_content_providers.py`) | 6 | 0 | New |
| Generate panel e2e (`test_web_content_gen_e2e.py`) | 4 | 0 | New, Playwright + real subprocess; 8s walltime |
| Existing `test_active_generation` | 8 | 0 | No regression |
| Existing `test_content_job_runner` | 8 | 0 | No regression |
| Existing `test_content_scope` | 13 | 0 | No regression |
| Existing `test_web_navigation` | 14 | 0 | No regression — adding `'generate'` to nav valid list didn't break anything |
| **Total touching this work** | **72** | **0** | |
| Pyright on `web/routes/content_gen.py` | — | 0 errors / 0 warnings / 0 informations | |

Composite test command (everything above) ran in **~16s walltime**. Default suite untouched.

---

## One real bug caught and fixed mid-flight (U8 e2e)

Worth surfacing because it's a **producer-vs-reviewer split** the existing API contract didn't make explicit.

### `/api/courses` doesn't list courses without decks

The Generate panel populates its course dropdown from a courses endpoint. The first U8 Playwright run hung in `select_option` — the `<select>` had only the placeholder `"— pick a course —"` after the lookup fired. Direct probe confirmed `/api/courses` returned `[]` even with the test vault populated.

The reviewer's `discover_directories()` calls `_has_review_content()`, which checks for **flashcards/quizzes JSON files**. A fresh `Study/<course>/` tree with markdown sources but zero decks is invisible to the reviewer — and was therefore invisible to the panel meant to *create* those decks.

**Fix**: new `GET /api/content/courses` route in `web/routes/content_gen.py` that enumerates subdirs of `settings.content.base_path` directly (skipping dot-dirs and the `flashcards`/`quizzes` output dirs). The panel JS uses this in place of `/api/courses`. Two unit tests pin the contract; the e2e tests then passed.

This is a real user bug — without the fix, anyone with a Study tree of pure source markdown could never trigger generation through the UI. The reviewer-vs-producer endpoint split is now documented in `web-ui-guide.md` (the form-fields table has a sub-note explaining why).

---

## Carry-forward — secondary tooling issues

These are NOT blocking and are unchanged from the predecessor handoff. Captured here for the next session.

### `test_web_app.py` port-bind hang

Hangs reproducibly at test #7 (`TestWebCommandConfig::test_web_reads_review_dirs_from_studyloop_config_env`). Tests 1–6 pass. Both `uvicorn.run` and `create_app` are monkeypatched in the test, but something runs *before* the mock and blocks. Most plausible mechanism: the `_web.py` watchdog or asyncio loop setup runs even when the call is mocked.

**Estimated cost when picked up**: 45–60 min.

**Investigation status**: I dispatched a `bug-analyzer` sub-agent for this today. Its trace was corrupted — claimed every file in the project was a 0-byte iCloud stub (verifiably false; I'd been reading files all session). The agent produced no usable findings. Treat the agent-tooling reliability as a known issue when picking this up: prefer inline investigation, or verify `bug-analyzer` is actually using its `Read` tool before re-dispatching.

### `test_available_commands_update_is_dropped` flake

Unchanged from yesterday. Fails ~1-in-3 on clean main. Documented as known-flake in commit `bfe9210`. Test exists at `packages/studyloop/tests/test_acp_transport.py::TestEventsAndUpdates::test_available_commands_update_is_dropped` (21.7 KB file — the second sub-agent today that claimed the file didn't exist was also hallucinating; verified by `ls` directly).

**Estimated cost when picked up**: 60–90 min. Run the test 10× to baseline the flake rate, then trace the ACP normaliser path.

**Investigation status**: same `bug-analyzer` agent failure as above. Tooling re-verification needed before next attempt.

### `mmdc` / Chrome version drift

Same workaround as predecessor; still works today. The `/tmp/mmdc-puppeteer.json` override file persists across sessions:

```bash
cat > /tmp/mmdc-puppeteer.json <<'JSON'
{"executablePath": "/Users/taylaand/.cache/puppeteer/chrome-headless-shell/mac_arm-149.0.7827.22/chrome-headless-shell-mac-arm64/chrome-headless-shell"}
JSON
mmdc -p /tmp/mmdc-puppeteer.json -i input.mmd -o output.png
```

If Chrome bumps again, update the path. Not blocking.

### Stale `.git/index.lock` — recurred once today

Happened once during the U5 commit. 0-byte lock, no live git process when checked. Removed manually. Same pattern as predecessor handoff documented; no new diagnosis, no escalation needed.

### wterm exploration thread (parked in memory)

User raised: replace xterm.js with [Vercel Labs's wterm](https://github.com/vercel-labs/wterm) for the body-double terminal embed. Saved as project memory at `.claude/projects/-Users-taylaand-code-personal-tools-StudyLoop/memory/wterm-migration-exploration.md`. **NOT part of the generation panel plan** — separate workstream. Pick it up when ready; the prior xterm integration surface map (memory observation S8730) is a good starting point.

---

## Conventions confirmed this session

- **Real-subprocess Playwright over headless mocks** — when the user wanted "real interactions and validation against the agent response", the e2e suite used `studyloop web` as a real subprocess + a tmp config + `STUDYLOOP_CONFIG` env var, mirroring `test_web_navigation.py`'s pattern. Worth roughly 8s of walltime; surfaced one real bug the unit tests couldn't have. Keep this as the default for new UI surfaces.
- **Two-commit shape continued** — backend (`f89ff53`) shipped first as a coherent committable unit, UI (`f53aa65`) followed. Per-commit conventional message style, em-dash, body with "what's new" + tests footer. Matches recent history.
- **Pyright noise on imports** still venv-resolution and not real. Today honoured the predecessor's convention; ran `uv run pyright` once on the new route module (0 errors) to confirm.
- **mmdc validation before architecture-doc commit** — kept the convention; all 6 diagrams in `architecture/current.md` re-validated green.
- **Live tests still opt-in via marker.** No live providers exercised today (UI tests use stub backend). Live spend this session: $0.00.
- CLAUDE.md per-tool rules continue to hold: no `git push` without explicit approval, no `--amend`, conventional commits, no emojis in files.

---

## Plan status — closed

`docs/plans/2026-05-29-001-feat-content-generation-panel-plan.md` was 766 lines, 11 unit specs, all units shipped:

| Unit | Status |
|---|---|
| U1 Stub generator | ✅ (Session 1) |
| U1.5 Provider registry + 2 adapters | ✅ (Session 1) |
| U2 Active-generation singleton | ✅ (Session 1) |
| U3 Scope resolver | ✅ (Session 1) |
| U4 Job runner orchestrator | ✅ (Session 1) |
| U5 REST endpoint | ✅ (Session 2) |
| U6 On-existing helpers | ✅ (Session 1) |
| U7 WS endpoint | ✅ (Session 2) |
| U8 WebUI panel | ✅ (Session 2) |
| U9 Sections route | ✅ (Session 2) |
| U10 Struggling-topics route | ✅ (Session 2) |
| U10.5 Providers route | ✅ (Session 2) |
| U11 Documentation | ✅ (both sessions) |

Plan totals: ~7.25 h estimated → ~7.7 h actual across both sessions (5.5 h Session 1 + 2.2 h Session 2). Roughly on plan once both sessions are summed; Session 2 itself ran well ahead because Session 1's stub-first investment compounded.

---

## What's next (post-plan)

The generation panel is a finished feature. Next session has options:

1. **Push to origin.** 36 local commits represent ~7 sessions. User must give explicit go-ahead — no autonomous push.
2. **Diagnose the two carry-forward bugs** (`test_web_app.py` hang + ACP flake). Inline if `bug-analyzer` tooling still flaky; ~2 h total.
3. **Live MVD smoke** to confirm the new HTTP surface works against real wires. Already verified yesterday for the orchestrator; running it again through the REST endpoint is a small belt-and-braces lap.
4. **wterm exploration** (separate thread, memory-pinned).
5. **Generation panel v2 — agent-marked struggles** (carry-forward from the original plan's "scope B"). Adds mid-session "agent flags this concept as struggling → click Generate → one-shot deck targeting that concept" flow. Additive; doesn't touch v1.

No urgency on any of them.

---

## Resume steps for next session

```bash
cd /Users/taylaand/code/personal/tools/StudyLoop
git -P status                    # working tree clean
git -P log --oneline -8          # 36 ahead of origin/main, top is a361edf
ls .env                          # confirm 3 keys present (OPENROUTER, GEMINI, MINIMAX)

# 1. Read this handoff.
# 2. Read whichever next-session option matters:
#    - origin push: needs user go-ahead, then a single `git push`.
#    - bug investigation: read this handoff's Carry-forward section.
#    - v2 scope (agent-marked struggles): read the original plan's
#      "v2 (carry-forward, separate plan)" note at line ~224.
# 3. Live REST smoke (optional belt-and-braces):
#    uv run uvicorn studyloop.web.app:create_app --port 8567 &
#    curl -X POST http://127.0.0.1:8567/api/content/generate \
#      -H 'Content-Type: application/json' \
#      -d '{"course":"DataCamp","scope":{"kind":"course","course":"DataCamp"},
#           "kinds":["flashcards"],"count_per_source":5,
#           "on_existing":"merge","backend":"openai_compat","provider":"openrouter"}'
#    # expect 202 + job_id; subscribe to WS for streamed progress.
```

---

## Key files for next-session work

| Purpose | Path |
|---|---|
| **NEW** REST + WS routes | `packages/studyloop/src/studyloop/web/routes/content_gen.py` |
| **NEW** Playwright e2e suite (UI smoke template) | `packages/studyloop/tests/test_web_content_gen_e2e.py` |
| **NEW** `/api/content/courses` (producer-side discovery) | same `content_gen.py`, line ~210 |
| **NEW** Sections route | `packages/studyloop/src/studyloop/web/routes/courses.py` (extended) |
| **NEW** Struggling-topics route + helper | `packages/studyloop/src/studyloop/web/routes/history.py` + `history/progress.py::get_struggling_topics` |
| **NEW** Generate sidebar tab + Alpine `generatePanel()` | `packages/studyloop/src/studyloop/web/static/index.html` (~line 169 sidebar, ~line 681 view, ~line 1259 factory) |
| **NEW** Generate panel CSS | `packages/studyloop/src/studyloop/web/static/style.css` (appended at EOF) |
| Updated user docs | `docs/web-ui-guide.md` (section "Generate Panel") |
| Updated C4 component diagram | `docs/architecture/current.md` (section "C4 Level 3 — Component (zoomed into the Generate panel)") |
| Plan doc (now closed) | `docs/plans/2026-05-29-001-feat-content-generation-panel-plan.md` |

---

## Headline number

**3 commits, ~2072 lines added across code + tests + docs.**
**29 new tests passing, 0 regressions, 4 Playwright e2e tests verifying the full REST → WS → DOM round-trip.**
**Generation panel plan: 100% complete across two sessions.**

Strong session. The producer-vs-reviewer split surfaced by the e2e tests is the kind of bug only a real-subprocess Playwright run could catch; the fixture cost paid for itself in one test cycle.
